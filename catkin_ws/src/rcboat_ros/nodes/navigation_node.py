#!/usr/bin/env python3
import time
import json
import threading
import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack,unpack,fresh
from rcboat_ros.path_tracking import (HeadingShockProtection, moving_course_sample,
    navigation_command, navigation_throttle_limit, TRACKING_MODES)
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.control_config import validate_cruise,load_output,NavigationThrottleRamp,NAV_RAMP_RATE

class Navigation:
    def __init__(self):
        self.lock=threading.RLock()
        self.throttle_ramp=NavigationThrottleRamp();self.ramp_session=None;self.safety_received_at=0
        self.heading_shock=HeadingShockProtection()
        self.output_calibration=load_output(rospy.get_param)
        self.gps={};self.route={};self.safety={};self.paused_until=0;self.large_turn_seen=False
        self.config={k:rospy.get_param('/rcboat/'+k,v) for k,v in {
            'steering_low':4900,'steering_center':6000,'steering_high':7300,'throttle_stop':6450,'cruise_pwm':6650,'nav_invert_steering':True}.items()}
        self.config.update(self.output_calibration)
        self.config['tracking_mode']=str(rospy.get_param('/rcboat/tracking_mode','HEADING')).upper()
        self.config['cruise_pwm']=validate_cruise(self.config['cruise_pwm'])
        self.cruise_applied_monotonic=time.monotonic()
        self.config['curve_slowdown_enabled']=rospy.get_param('/rcboat/curve_slowdown_enabled',True) is not False
        self.curve_slowdown_applied_monotonic=self.cruise_applied_monotonic
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
                    state.get('estop') or session!=self.ramp_session):
                self.heading_shock.reset()
                self.throttle_ramp.reset()
            elif state.get('gps_grace_active') and not self.heading_shock.holding:
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
            elif self.heading_shock.holding:
                # GPS grace cannot replace the neutral baseline during a direction shock.
                self.throttle_ramp.update(self.output_calibration['throttle_stop'],now)
            else:
                self.throttle_ramp.reset()
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
            elif request.action=='nav_curve_slowdown':
                enabled=args.get('enabled')
                if type(enabled) is not bool:
                    raise ValueError('enabled must be a boolean')
                before=self.config['curve_slowdown_enabled']
                rospy.set_param('/rcboat/curve_slowdown_enabled',enabled)
                self.config['curve_slowdown_enabled']=enabled
                self.curve_slowdown_applied_monotonic=time.monotonic()
                result=dict(curve_slowdown_enabled=enabled,
                            curve_slowdown_applied_monotonic=self.curve_slowdown_applied_monotonic)
                self.events.publish(pack(type='CONFIG_CHANGE',change_type='curve_slowdown',
                                         before={'curve_slowdown_enabled':before},after=result))
            else:raise ValueError('unknown navigation action')
            return ExecuteResponse(True,pack(**result))
        except (ValueError,TypeError) as exc:
            return ExecuteResponse(False,pack(error=str(exc)))

    def _apply_navigation_protection(self, out, gps, route, now):
        # Called under the same lock as the session and ramp updates.
        if (self.safety.get('mode') != 'NAVIGATION' or not self.safety.get('armed')
                or self.safety.get('estop') or out.get('route_complete')
                or not fresh(self.safety_received_at, .75, now)):
            return out
        was_holding = self.heading_shock.holding
        if out['valid'] and not self.safety.get('gps_grace_active'):
            course = moving_course_sample(gps, now)
            leg = (route.get('active_route_id'), route.get('target_waypoint_index'),
                   route.get('target_lat'), route.get('target_lon'), out['controller_mode'])
            self.heading_shock.update(leg, course, out['heading_error_deg'], now)
            out['navigation_protection'] = navigation_throttle_limit(
                out, course, out['desired_throttle_pwm'], self.config['curve_slowdown_enabled'],
                self.output_calibration['throttle_stop'])
            out['desired_throttle_pwm'] = out['navigation_protection']['throttle_limit_pwm']
        else:
            self.heading_shock.update(self.heading_shock.leg, None, None, now)
        if self.heading_shock.holding:
            out['desired_throttle_pwm'] = self.output_calibration['throttle_stop']
            out['navigation_protection'] = {
                'reason': 'HEADING_SHOCK', 'throttle_limit_pwm': out['desired_throttle_pwm']}
        if was_holding != self.heading_shock.holding:
            self.events.publish(pack(type='NAVIGATION_HEADING_SHOCK_HELD' if self.heading_shock.holding
                                     else 'NAVIGATION_HEADING_SHOCK_RECOVERED',
                                     monotonic=now, route_id=out.get('route_id'),
                                     heading_error_deg=out.get('heading_error_deg'),
                                     course_sample_id=gps.get('course_sample_id')))
        return out

    def run(self):
        rate=rospy.Rate(4)
        while not rospy.is_shutdown():
            # Subscriber callbacks replace these dictionaries. Keep one pair
            # throughout this calculation so its FIX provenance is accurate.
            gps=self.gps;route=self.route
            with self.lock:
                config=dict(self.config)
                applied_at=getattr(self,'cruise_applied_monotonic',0.0)
                session=self.ramp_session
                protect=(self.safety.get('mode')=='NAVIGATION' and self.safety.get('armed')
                         and not self.safety.get('estop'))
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
                    calc=navigation_command(gps,route,config,self.large_turn_seen,protect=protect)
                    abs_error=abs(calc['heading_error_deg'])
                    if abs_error<125:self.large_turn_seen=False
                    if calc['initial_turn_pause_requested']:
                        self.large_turn_seen=True;self.paused_until=time.monotonic()+0.4
                    if time.monotonic()<self.paused_until:calc['desired_throttle_pwm']=6450
                    out.update(calc,valid=True,gps_solution_monotonic=gps.get('last_valid_monotonic'))
                except (TypeError,ValueError,KeyError) as e:rospy.logwarn('Navigation waiting: %s',e)
            with self.lock:
                now=time.monotonic()
                if session != self.ramp_session:
                    # A calculation from the old session cannot arm the new one.
                    out.update(valid=False, desired_throttle_pwm=self.output_calibration['throttle_stop'])
                else:
                    self._apply_navigation_protection(out,gps,route,now)
                out['curve_slowdown_enabled']=self.config.get('curve_slowdown_enabled',True)
                out['curve_slowdown_applied_monotonic']=getattr(self,'curve_slowdown_applied_monotonic',0.0)
                self.apply_throttle_ramp(out,now)
            self.pub.publish(pack(**out));rate.sleep()
if __name__=='__main__':rospy.init_node('navigation_node');Navigation().run()
