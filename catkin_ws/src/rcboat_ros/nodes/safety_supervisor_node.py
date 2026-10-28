#!/usr/bin/env python3
"""All commands arbitrate here; ground-test actuation requires explicit opt-in."""
import json
import time
import threading
import math
import rospy
from std_msgs.msg import String
from rcboat_ros.msg import ControlCommand
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.common import unpack,pack,clamp,lerp,fresh,SAFE_STEERING,SAFE_THROTTLE,gps_is_healthy
from rcboat_ros.failsafe import ProgressMonitor

MODES={'AUTO_SAFE','AUTO','MANUAL','REMOTE','NAVIGATION','GROUND_TEST'}

class Supervisor:
    def __init__(self):
        self.mode='AUTO_SAFE';self.armed=False;self.estop=False
        self.lock=threading.RLock();self.reason='';self.link={};self.actuator={};self.propulsion={}
        self.progress=ProgressMonitor();self.mode_since=time.monotonic()
        self.ground_test_actuation_enabled=False
        grace=float(rospy.get_param('/rcboat/ground_test_gps_grace_s',5.0))
        if not math.isfinite(grace) or not 0<=grace<=30:
            raise ValueError('ground_test_gps_grace_s must be between 0 and 30 seconds')
        self.ground_gps_grace_s=grace
        self.ground_gps_gap_since=None;self.ground_gps_recovery_stamp=None
        self.ground_gps_grace_remaining_s=0.0
        self.gps={};self.rc={};self.nav={};self.remote={};self.remote_stamp=0
        self.auto_gesture_since=None;self.manual_gesture_since=None;self.manual_rearm_since=None;self.manual_rearm_pending=False
        self.cmd=rospy.Publisher('/rcboat/safety/final_command',ControlCommand,queue_size=4)
        self.state=rospy.Publisher('/rcboat/safety/state',String,queue_size=4,latch=True)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
        rospy.Subscriber('/rcboat/rc/input',String,lambda m:setattr(self,'rc',unpack(m)))
        rospy.Subscriber('/rcboat/navigation/desired',String,lambda m:setattr(self,'nav',unpack(m)))
        rospy.Subscriber('/rcboat/gui/link',String,lambda m:setattr(self,'link',unpack(m)))
        rospy.Subscriber('/rcboat/actuator/status',String,lambda m:setattr(self,'actuator',unpack(m)))
        rospy.Subscriber('/rcboat/propulsion/status',String,lambda m:setattr(self,'propulsion',unpack(m)))
        rospy.Service('/rcboat/safety/execute',Execute,self.execute)
    def execute(self,req):
        with self.lock:return self._execute(req)

    def _execute(self,req):
        try:
            args=json.loads(req.arguments_json or '{}')
            if not isinstance(args,dict):raise ValueError('request must be JSON object')
            if req.action=='estop':
                self.estop=True;self._manual('EMERGENCY_STOP')
                self.events.publish(pack(type='ESTOP',at=time.time()))
            elif req.action=='reset_estop':
                # Requires physical-safe mode; reset never restores navigation automatically.
                if self.mode not in ('MANUAL','AUTO_SAFE'):raise ValueError('select MANUAL first')
                self.estop=False;self.armed=False
                self._manual('ESTOP_CLEARED_NEUTRAL_REQUIRED')
            elif req.action=='set_mode':
                mode=str(args['mode'])
                if mode not in MODES:raise ValueError('unknown mode')
                if self.estop and mode not in ('AUTO_SAFE','MANUAL'):raise ValueError('E-STOP latched')
                if mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST'):
                    reason=self._link_fault(time.monotonic(),mode)
                    if reason:raise ValueError(reason)
                if mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST'):
                    if not self.gps.get('healthy') or not gps_is_healthy(self.gps,time.monotonic(),2.0):
                        raise ValueError('GPS_INVALID_OR_STALE')
                if mode in ('NAVIGATION','GROUND_TEST'):
                    reason=self._navigation_fault(time.monotonic())
                    if reason:raise ValueError(reason)
                self._clear_gps_grace('ABORTED','MODE_CHANGED')
                self.mode=mode;self.mode_since=time.monotonic();self.reason='';self.progress.reset()
                self.ground_test_actuation_enabled=(
                    mode=='GROUND_TEST' and bool(args.get('ground_test_actuation_enabled',False))
                )
                self.auto_gesture_since=None;self.manual_gesture_since=None
                self.manual_rearm_pending=mode=='MANUAL'
                self.manual_rearm_since=None
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
            if self.mode=='MANUAL':self.manual_rearm_pending=True
            return
        steer=int(self.rc['steering_us']);throttle=int(self.rc['throttle_us'])
        if self.mode=='MANUAL' and steer>=1950 and abs(throttle-1500)<=30:
            if self.auto_gesture_since is None:self.auto_gesture_since=now
            elif now-self.auto_gesture_since>=3.0:
                self.mode='AUTO_SAFE';self.armed=False;self.auto_gesture_since=None
                self.events.publish(pack(type='RC_GESTURE_AUTO_SAFE',at=time.time()))
        else:self.auto_gesture_since=None
        if self.mode in ('AUTO_SAFE','AUTO','NAVIGATION','REMOTE','GROUND_TEST') and throttle>=1850:
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
    def _manual(self,reason):
        previous=self.mode
        self._clear_gps_grace('ABORTED',reason)
        self.mode='MANUAL';self.armed=False;self.reason=reason
        self.ground_test_actuation_enabled=False
        self.manual_rearm_pending=True;self.manual_rearm_since=None
        self.auto_gesture_since=self.manual_gesture_since=None
        self.progress.reset()
        self.events.publish(pack(type='FAILSAFE_MANUAL',reason=reason,previous_mode=previous,
                                 mode='MANUAL',at=time.time(),monotonic=time.monotonic(),
                                 gps_snapshot=dict(self.gps),navigation_snapshot=dict(self.nav),
                                 link_snapshot=dict(self.link)))

    def _link_fault(self,now,mode=None):
        if not fresh(float(self.link.get('monotonic') or 0),5.0,now):return 'GUI_LINK_TIMEOUT'
        # Walking tests use the ROS gateway lease. SSH is only a management
        # channel; its loss must not interrupt an otherwise reachable test.
        if (mode or self.mode)!='GROUND_TEST' and not self.link.get('ssh_connected'):
            return 'SSH_DISCONNECTED'
        return ''

    def _navigation_fault(self,now,allow_gps_gap=False):
        if not allow_gps_gap and (not self.gps.get('healthy') or not gps_is_healthy(self.gps,now,2.0)):
            return 'GPS_INVALID_OR_STALE'
        if not fresh(float(self.nav.get('monotonic') or 0),.75,now):return 'NAVIGATION_TIMEOUT'
        if not fresh(float(self.nav.get('route_monotonic') or 0),1.0,now):return 'ROUTE_TIMEOUT'
        if self.nav.get('route_complete'):return 'TARGET_ARRIVED'
        if not allow_gps_gap and not self.nav.get('valid'):return 'NAVIGATION_INVALID'
        return ''

    def _clear_gps_grace(self,outcome,reason=''):
        if self.ground_gps_gap_since is not None:
            self.events.publish(pack(type='GROUND_TEST_GPS_GRACE_'+outcome,
                at=time.time(),monotonic=time.monotonic(),reason=reason,
                elapsed_s=max(0,time.monotonic()-self.ground_gps_gap_since)))
        self.ground_gps_gap_since=None;self.ground_gps_recovery_stamp=None
        self.ground_gps_grace_remaining_s=0.0
        if self.reason=='GROUND_TEST_GPS_GRACE':self.reason=''

    def _ground_gps_grace(self,now):
        gps_ok=bool(self.gps.get('healthy')) and gps_is_healthy(self.gps,now,2.0)
        if self.ground_gps_gap_since is None:
            self.ground_gps_gap_since=now
            self.events.publish(pack(type='GROUND_TEST_GPS_GRACE_STARTED',at=time.time(),
                monotonic=now,grace_s=self.ground_gps_grace_s,gps_snapshot=dict(self.gps)))
        elapsed=max(0,now-self.ground_gps_gap_since)
        self.ground_gps_grace_remaining_s=max(0,self.ground_gps_grace_s-elapsed)
        if elapsed>=self.ground_gps_grace_s:
            reason='NAVIGATION_INVALID' if gps_ok else 'GPS_INVALID_OR_STALE'
            self._clear_gps_grace('EXPIRED',reason)
            return reason
        if gps_ok:
            if self.ground_gps_recovery_stamp is None:
                self.ground_gps_recovery_stamp=float(self.gps.get('last_valid_monotonic') or 0)
            # Wait for a navigation result calculated from the recovered FIX,
            # never apply the cached command from before the GPS interruption.
            if (self.nav.get('valid') and
                    float(self.nav.get('gps_solution_monotonic') or 0)>=self.ground_gps_recovery_stamp):
                self._clear_gps_grace('RECOVERED')
                return ''
        else:
            self.ground_gps_recovery_stamp=None
        self.reason='GROUND_TEST_GPS_GRACE'
        return ''

    def _fault(self,now):
        reason=self._link_fault(now)
        if reason:return reason
        if not fresh(float(self.rc.get('monotonic') or 0),.75,now):return 'RC_INPUT_LOST'
        if self.propulsion.get('fault') or self.propulsion.get('blocked'):
            return 'PROPULSION_FAULT'
        if self.actuator.get('command_applied') is False:return 'ACTUATOR_ERROR'
        if now-self.mode_since>1.5 and not fresh(float(self.actuator.get('monotonic') or 0),1.0,now):
            return 'ACTUATOR_TIMEOUT'
        gps_ok=bool(self.gps.get('healthy')) and gps_is_healthy(self.gps,now,2.0)
        gps_gap=self.mode=='GROUND_TEST' and (not gps_ok or self.ground_gps_gap_since is not None)
        if not gps_ok and not gps_gap:return 'GPS_INVALID_OR_STALE'
        if self.mode in ('NAVIGATION','GROUND_TEST'):
            reason=self._navigation_fault(now,allow_gps_gap=gps_gap)
            if reason:return reason
        if gps_gap:
            reason=self._ground_gps_grace(now)
            if reason:return reason
        throttle=(int(rospy.get_param('/rcboat/cruise_pwm',6650)) if self.mode=='AUTO'
                  else int(self.nav.get('desired_throttle_pwm') or 6450))
        if self.progress.update(now,self.gps,throttle,
                enabled=self.mode in ('AUTO','NAVIGATION') and bool(self.gps.get('healthy')) and
                       bool(rospy.get_param('/rcboat/no_progress_enabled',True)),
                timeout=float(rospy.get_param('/rcboat/no_progress_timeout_s',15.0))):
            return 'PROPULSION_NO_PROGRESS_SUSPECTED'
        return ''

    def _command(self):
        with self.lock:return self._command_locked()

    def _command_locked(self):
        now=time.monotonic();source='AUTO_SAFE';s=SAFE_STEERING;t=SAFE_THROTTLE;lock=True
        if self.mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST'):
            reason=self._fault(now)
            if reason:
                self._manual(reason)
                return 'FAILSAFE_MANUAL',s,t,True
        self._gestures(now)
        if self.mode!='GROUND_TEST':self._clear_gps_grace('ABORTED','MODE_CHANGED')
        # GPS hard faults must lock autonomous navigation, not physically safe manual takeover.
        if self.estop:return 'ESTOP',s,t,True
        if self.mode=='GROUND_TEST':
            if self.ground_gps_gap_since is not None:
                return 'GROUND_TEST_GPS_GRACE',SAFE_STEERING,SAFE_THROTTLE,True
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
            else:self._manual('REMOTE_TIMEOUT')
        elif self.mode=='NAVIGATION' and self.armed:
            if self.gps.get('healthy') and self.nav.get('valid') and fresh(float(self.nav.get('monotonic',0)),.75,now):
                s=int(self.nav['desired_steering_pwm']);t=int(self.nav['desired_throttle_pwm']);source='NAVIGATION';lock=False
        return source,s,t,lock
    def run(self):
        rate=rospy.Rate(10)
        while not rospy.is_shutdown():
            with self.lock:
                source,s,t,lock=self._command()
                msg=ControlCommand()
                msg.header.stamp=rospy.Time.now();msg.mode=self.mode;msg.source=source
                msg.steering_pwm=int(s);msg.throttle_pwm=int(t);msg.actuator_locked=lock
                self.cmd.publish(msg)
                self.state.publish(pack(software_version="2.1.12",mode=self.mode,armed=self.armed,estop=self.estop,actuator_locked=lock,
                                        ground_test_actuation_enabled=self.ground_test_actuation_enabled,
                                        gps_grace_active=self.ground_gps_gap_since is not None,
                                        gps_grace_remaining_s=round(self.ground_gps_grace_remaining_s,2),
                                        gps_grace_s=self.ground_gps_grace_s,
                                        reason=self.reason,manual_rearm_pending=self.manual_rearm_pending,
                                        rc_fresh=fresh(float(self.rc.get('monotonic') or 0),.75),
                                        propulsion_feedback_status='fault' if self.propulsion.get('fault') or self.propulsion.get('blocked') else 'available' if self.propulsion else 'unsupported',
                                        throttle_locked=lock,
                                        steering_test_enabled=self.mode=='GROUND_TEST' and source=='GROUND_TEST_NAVIGATION',
                                        effective_source=source,steering_pwm=s,throttle_pwm=t))
            rate.sleep()
if __name__=='__main__':rospy.init_node('safety_supervisor_node');Supervisor().run()
