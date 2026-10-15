#!/usr/bin/env python3
"""All commands arbitrate here; ground-test actuation requires explicit opt-in."""
import json
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.msg import ControlCommand
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.common import unpack,pack,clamp,lerp,fresh,SAFE_STEERING,SAFE_THROTTLE

MODES={'AUTO_SAFE','AUTO','MANUAL','REMOTE','NAVIGATION','GROUND_TEST'}

class Supervisor:
    def __init__(self):
        self.mode='AUTO_SAFE';self.armed=False;self.estop=False
        self.ground_test_actuation_enabled=False
        self.gps={};self.rc={};self.nav={};self.remote={};self.remote_stamp=0
        self.auto_gesture_since=None;self.manual_gesture_since=None;self.manual_rearm_since=None;self.manual_rearm_pending=False
        self.cmd=rospy.Publisher('/rcboat/safety/final_command',ControlCommand,queue_size=4)
        self.state=rospy.Publisher('/rcboat/safety/state',String,queue_size=4,latch=True)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
        rospy.Subscriber('/rcboat/rc/input',String,lambda m:setattr(self,'rc',unpack(m)))
        rospy.Subscriber('/rcboat/navigation/desired',String,lambda m:setattr(self,'nav',unpack(m)))
        rospy.Service('/rcboat/safety/execute',Execute,self.execute)
    def execute(self,req):
        try:
            args=json.loads(req.arguments_json or '{}')
            if not isinstance(args,dict):raise ValueError('request must be JSON object')
            if req.action=='estop':
                self.estop=True;self.mode='AUTO_SAFE';self.armed=False
                self.ground_test_actuation_enabled=False
                self.events.publish(pack(type='ESTOP',at=time.time()))
            elif req.action=='reset_estop':
                # Requires physical-safe mode; reset never restores navigation automatically.
                if self.mode!='AUTO_SAFE':raise ValueError('must first select AUTO_SAFE')
                self.estop=False;self.armed=False
            elif req.action=='set_mode':
                mode=str(args['mode'])
                if mode not in MODES:raise ValueError('unknown mode')
                if self.estop and mode!='AUTO_SAFE':raise ValueError('E-STOP latched')
                self.mode=mode
                self.ground_test_actuation_enabled=(
                    mode=='GROUND_TEST' and bool(args.get('ground_test_actuation_enabled',False))
                )
                self.auto_gesture_since=None;self.manual_gesture_since=None
                self.manual_rearm_pending=False
                self.armed=bool(args.get('armed',False)) if mode=='NAVIGATION' else False
                if mode=='REMOTE':self.remote_stamp=0
                self.events.publish(pack(type='MODE_CHANGED',mode=mode,at=time.time()))
            elif req.action=='set_remote_pwm':
                if self.mode!='REMOTE':raise ValueError('not in REMOTE mode')
                steer=int(args['steering_pwm']);throttle=int(args['throttle_pwm'])
                if not 4900<=steer<=7300 or not 5800<=throttle<=7000:raise ValueError('PWM outside calibration')
                self.remote={'steering_pwm':steer,'throttle_pwm':throttle}
                self.remote_stamp=time.monotonic()
            elif req.action=='heartbeat':
                if self.mode!='REMOTE':raise ValueError('not in REMOTE')
                self.remote_stamp=time.monotonic()
            elif req.action=='status':pass
            else:raise ValueError('unknown safety command')
            return ExecuteResponse(True,pack(mode=self.mode,estop=self.estop,armed=self.armed))
        except Exception as e:return ExecuteResponse(False,pack(error=str(e)))
    def _gestures(self,now):
        if self.estop or not fresh(float(self.rc.get('monotonic',0)),.75,now):
            self.auto_gesture_since=self.manual_gesture_since=self.manual_rearm_since=None
            return
        steer=int(self.rc['steering_us']);throttle=int(self.rc['throttle_us'])
        if self.mode=='MANUAL' and steer>=1950 and abs(throttle-1500)<=30:
            if self.auto_gesture_since is None:self.auto_gesture_since=now
            elif now-self.auto_gesture_since>=3.0:
                self.mode='AUTO_SAFE';self.armed=False;self.auto_gesture_since=None
                self.events.publish(pack(type='RC_GESTURE_AUTO_SAFE',at=time.time()))
        else:self.auto_gesture_since=None
        if self.mode in ('AUTO_SAFE','AUTO','NAVIGATION','REMOTE') and throttle>=1850:
            if self.manual_gesture_since is None:self.manual_gesture_since=now
            elif now-self.manual_gesture_since>=.5:
                self.mode='MANUAL';self.armed=False;self.manual_rearm_pending=True
                self.manual_rearm_since=None;self.manual_gesture_since=None
                self.events.publish(pack(type='RC_GESTURE_MANUAL_PENDING_NEUTRAL',at=time.time()))
        else:self.manual_gesture_since=None
        if self.manual_rearm_pending:
            if abs(throttle-1500)<=30:
                if self.manual_rearm_since is None:self.manual_rearm_since=now
                elif now-self.manual_rearm_since>=.3:
                    self.manual_rearm_pending=False;self.manual_rearm_since=None
                    self.events.publish(pack(type='RC_MANUAL_ARMED',at=time.time()))
            else:self.manual_rearm_since=None
    def _command(self):
        now=time.monotonic();source='AUTO_SAFE';s=SAFE_STEERING;t=SAFE_THROTTLE;lock=True
        self._gestures(now)
        # GPS hard faults must lock autonomous navigation, not physically safe manual takeover.
        if self.estop:return 'ESTOP',s,t,True
        if self.mode=='GROUND_TEST':
            # Full navigation-equivalent output is allowed only for the explicit,
            # non-persistent ground-test opt-in. E-STOP, GPS and freshness gates still win.
            if (self.ground_test_actuation_enabled and self.gps.get('healthy') and
                    self.nav.get('valid') and fresh(float(self.nav.get('monotonic',0)),.75,now)):
                s=int(clamp(int(self.nav['desired_steering_pwm']),4900,7300))
                t=int(clamp(int(self.nav['desired_throttle_pwm']),5800,7000))
                return 'GROUND_TEST_NAVIGATION',s,t,False
            return 'GROUND_TEST',s,SAFE_THROTTLE,True
        if self.mode=='AUTO':
            return 'AUTO',s,int(rospy.get_param('/rcboat/cruise_pwm',6650)),False
        if self.mode=='MANUAL' and not self.manual_rearm_pending:
            if fresh(float(self.rc.get('monotonic',0)),.75,now):
                us_s=float(self.rc['steering_us']);us_t=float(self.rc['throttle_us'])
                s=round(lerp(us_s,1214,1640,4900,6000)) if us_s<=1640 else round(lerp(us_s,1640,2000,6000,7300))
                if 1470<=us_t<=1530:t=6450
                elif us_t<1470:t=round(lerp(us_t,1106,1500,5800,6450))
                else:t=round(lerp(us_t,1500,1888,6450,7000))
                source='MANUAL';lock=False
        elif self.mode=='REMOTE':
            if fresh(self.remote_stamp,float(rospy.get_param('/rcboat/remote_heartbeat_s',.7)),now):
                s=self.remote['steering_pwm'];t=self.remote['throttle_pwm'];source='REMOTE';lock=False
            else:self.mode='AUTO_SAFE';self.events.publish(pack(type='REMOTE_TIMEOUT',at=time.time()))
        elif self.mode=='NAVIGATION' and self.armed:
            if self.gps.get('healthy') and self.nav.get('valid') and fresh(float(self.nav.get('monotonic',0)),.75,now):
                s=int(self.nav['desired_steering_pwm']);t=int(self.nav['desired_throttle_pwm']);source='NAVIGATION';lock=False
        return source,s,t,lock
    def run(self):
        rate=rospy.Rate(10)
        while not rospy.is_shutdown():
            source,s,t,lock=self._command()
            msg=ControlCommand()
            msg.header.stamp=rospy.Time.now();msg.mode=self.mode;msg.source=source
            msg.steering_pwm=int(s);msg.throttle_pwm=int(t);msg.actuator_locked=lock
            self.cmd.publish(msg)
            self.state.publish(pack(mode=self.mode,armed=self.armed,estop=self.estop,actuator_locked=lock,
                                    ground_test_actuation_enabled=self.ground_test_actuation_enabled,
                                    throttle_locked=lock,
                                    steering_test_enabled=self.mode=='GROUND_TEST' and source=='GROUND_TEST_NAVIGATION',
                                    effective_source=source,steering_pwm=s,throttle_pwm=t))
            rate.sleep()
if __name__=='__main__':rospy.init_node('safety_supervisor_node');Supervisor().run()
