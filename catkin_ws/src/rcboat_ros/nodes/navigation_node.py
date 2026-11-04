#!/usr/bin/env python3
import time
import json
import threading
import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack,unpack,fresh
from rcboat_ros.path_tracking import navigation_command,TRACKING_MODES
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.control_config import validate_cruise,load_output,NavigationThrottleRamp,NAV_RAMP_RATE

class Navigation:
    def __init__(self):
        self.lock=threading.RLock()
        self.throttle_ramp=NavigationThrottleRamp();self.ramp_session=None;self.safety_received_at=0
        self.output_calibration=load_output(rospy.get_param)
        self.gps={};self.route={};self.safety={};self.paused_until=0;self.large_turn_seen=False
        self.config={k:rospy.get_param('/rcboat/'+k,v) for k,v in {
            'steering_low':4900,'steering_center':6000,'steering_high':7300,'throttle_stop':6450,'cruise_pwm':6650,'nav_invert_steering':True}.items()}
        self.config.update(self.output_calibration)
        self.config['tracking_mode']=str(rospy.get_param('/rcboat/tracking_mode','HEADING')).upper()
        self.config['cruise_pwm']=validate_cruise(self.config['cruise_pwm'])
        self.cruise_applied_monotonic=time.monotonic()
        for key,value in {'lookahead_base_m':2.0,'lookahead_speed_gain_s':2.5,
                          'lookahead_min_m':2.0,'lookahead_max_m':10.0,
                          'speed_feedback_enabled':False,'target_speed_mps':0.6}.items():
            self.config[key]=rospy.get_param('/rcboat/'+key,value)
        rospy.Service('/rcboat/navigation/execute',Execute,self.execute)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        rospy.Subscriber('/rcboat/safety/state',String,self.update_safety)
        self.pub=rospy.Publisher('/rcboat/navigation/desired',String,queue_size=5)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
        rospy.Subscriber('/rcboat/route/state',String,lambda m:setattr(self,'route',unpack(m)))
    def update_safety(self,message):
        with self.lock:
            state=unpack(message)
            session=state.get('mode_since_monotonic')
            if (state.get('mode')!='NAVIGATION' or not state.get('armed') or
                    state.get('estop') or state.get('gps_grace_active') or session!=self.ramp_session):
                self.throttle_ramp.reset()
            self.ramp_session=session
            self.safety=state;self.safety_received_at=time.monotonic()

    def apply_throttle_ramp(self,out,now):
        with self.lock:
            state=self.safety
            active=(out.get('valid') and not out.get('route_complete') and
                    fresh(self.safety_received_at,.75,now) and state.get('mode')=='NAVIGATION' and
                    state.get('armed') and not state.get('estop') and not state.get('gps_grace_active') and
                    isinstance(self.ramp_session,(float,int)) and self.ramp_session>0)
            if active:
                out['desired_throttle_pwm']=self.throttle_ramp.update(out['desired_throttle_pwm'],now)
            else:self.throttle_ramp.reset()
            out.update(ramp_active=bool(active),ramp_session_monotonic=self.ramp_session,
                       ramp_throttle_pwm=out['desired_throttle_pwm'] if active else None,
                       ramp_rate_pwm_s=NAV_RAMP_RATE)
        return out
    def execute(self,request):
        with self.lock:return self._execute(request)

    def _execute(self,request):
        try:
            args=json.loads(request.arguments_json or '{}')
            if not isinstance(args,dict):raise ValueError('arguments must be a JSON object')
            if request.action=='set_tracking_mode':
                mode=str(args.get('tracking_mode','')).upper()
                if mode not in TRACKING_MODES:raise ValueError('unsupported tracking mode')
                self.config['tracking_mode']=mode
                self.large_turn_seen=False;self.paused_until=0
                result={'tracking_mode':mode}
                self.events.publish(pack(type='CONFIG_CHANGE',change_type='tracking_mode',after=result))
            elif request.action=='set_auto_cruise_pwm':
                value=validate_cruise(args.get('value'))
                before=self.config['cruise_pwm']
                rospy.set_param('/rcboat/cruise_pwm',value)
                self.config['cruise_pwm']=value
                self.cruise_applied_monotonic=time.monotonic()
                result={'value':value,'cruise_applied_monotonic':self.cruise_applied_monotonic}
                self.events.publish(pack(type='CONFIG_CHANGE',change_type='auto_cruise_pwm',
                                         before={'value':before},after=result))
            else:raise ValueError('unknown navigation action')
            return ExecuteResponse(True,pack(**result))
        except (ValueError,TypeError) as exc:
            return ExecuteResponse(False,pack(error=str(exc)))

    def run(self):
        rate=rospy.Rate(4)
        while not rospy.is_shutdown():
            # Subscriber callbacks replace these dictionaries. Keep one pair
            # throughout this calculation so its FIX provenance is accurate.
            gps=self.gps;route=self.route
            with self.lock:
                config=dict(self.config)
                applied_at=getattr(self,'cruise_applied_monotonic',0.0)
            out={'valid':False,'desired_steering_pwm':6000,'desired_throttle_pwm':6450,
                 'desired_rudder_angle_deg':0,'controller_mode':self.config['tracking_mode'],
                 'target_speed_mps':float(config['target_speed_mps']),
                 'auto_cruise_pwm':validate_cruise(config['cruise_pwm']),
                 'cruise_applied_monotonic':applied_at,
                 'route_id':route.get('active_route_id'),
                 'route_monotonic':route.get('monotonic'),
                 'route_complete':bool(route.get('route_complete')),
                 'gps_solution_monotonic':None,
                 'monotonic':time.monotonic()}
            if (fresh(float(route.get('monotonic') or 0),1.0) and
                    gps.get('healthy')) and 'target_lat' in route and gps.get('heading_deg') is not None:
                try:
                    abs_error=None
                    calc=navigation_command(gps,route,config,self.large_turn_seen)
                    abs_error=abs(calc['heading_error_deg'])
                    if abs_error<125:self.large_turn_seen=False
                    if calc['initial_turn_pause_requested']:
                        self.large_turn_seen=True;self.paused_until=time.monotonic()+0.4
                    if time.monotonic()<self.paused_until:calc['desired_throttle_pwm']=6450
                    out.update(calc,valid=True,gps_solution_monotonic=gps.get('last_valid_monotonic'))
                except (TypeError,ValueError,KeyError) as e:rospy.logwarn('Navigation waiting: %s',e)
            self.apply_throttle_ramp(out,time.monotonic())
            self.pub.publish(pack(**out));rate.sleep()
if __name__=='__main__':rospy.init_node('navigation_node');Navigation().run()
