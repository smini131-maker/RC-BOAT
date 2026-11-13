#!/usr/bin/env python3
"""All commands arbitrate here; ground-test actuation requires explicit opt-in."""
import json
import time
import threading
import math
import datetime as dt
import rospy
from std_msgs.msg import String
from rcboat_ros.msg import ControlCommand
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.common import unpack,pack,clamp,lerp,fresh,SAFE_STEERING,SAFE_THROTTLE,gps_is_healthy,finite_coordinate
from rcboat_ros.failsafe import ProgressMonitor
from rcboat_ros.control_config import load_rc,load_output,rc_valid,neutral,normalized,map_axis,validate_cruise,output_in_range,navigation_output_in_range

MODES={'AUTO_SAFE','AUTO','MANUAL','REMOTE','NAVIGATION','GROUND_TEST','BALLOON'}

from rcboat_ros.balloon_tracking import balloon_camera_ready,safe_balloon_output

BALLOON_CAMERA_RECOVERY_S = 5.0
NAVIGATION_SHOCK_GPS_GRACE = 'NAVIGATION_HEADING_SHOCK_GPS_GRACE'

class Supervisor:
    def __init__(self):
        self.rc_calibration=load_rc(rospy.get_param)
        self.output_calibration=load_output(rospy.get_param)
        self.mode='AUTO_SAFE';self.armed=False;self.estop=False;self.estop_reason=None;self.estop_time_utc=None;self.estop_origin=None
        self.vision={};self.vision_desired={};self.balloon_gps_gap_since=None
        self.lock=threading.RLock();self.reason='';self.link={};self.actuator={};self.propulsion={};self.decision_snapshot={}
        self.progress=ProgressMonitor();self.mode_since=time.monotonic()
        self.ground_test_actuation_enabled=False
        grace=float(rospy.get_param('/rcboat/ground_test_gps_grace_s',5.0))
        if not math.isfinite(grace) or not 0<=grace<=30:
            raise ValueError('ground_test_gps_grace_s must be between 0 and 30 seconds')
        self.ground_gps_grace_s=grace
        self.navigation_gps_grace_s=float(rospy.get_param('/rcboat/navigation_gps_grace_s',5.0))
        if not math.isfinite(self.navigation_gps_grace_s) or not 0<=self.navigation_gps_grace_s<=30:
            raise ValueError('navigation_gps_grace_s must be between 0 and 30 seconds')
        self.navigation_gps_grace_pwm=validate_cruise(rospy.get_param('/rcboat/navigation_gps_grace_pwm',6650))
        if self.navigation_gps_grace_pwm>self.output_calibration['throttle_forward_max']:
            raise ValueError('navigation_gps_grace_pwm exceeds the existing grace ceiling')
        self.gps_grace_mode=None
        self.ground_gps_gap_since=None;self.ground_gps_recovery_stamp=None
        self.ground_gps_grace_remaining_s=0.0
        self.gps={};self.rc={};self.nav={};self.remote={};self.remote_stamp=0
        self.auto_gesture_since=None;self.manual_gesture_since=None;self.manual_rearm_since=None;self.manual_rearm_pending=False
        self.cmd=rospy.Publisher('/rcboat/safety/final_command',ControlCommand,queue_size=4)
        self.state=rospy.Publisher('/rcboat/safety/state',String,queue_size=4,latch=True)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        # The clock and all inputs used by one decision must describe the same
        # snapshot. A callback arriving after that clock sample must wait until
        # the decision finishes, rather than becoming a false "future" timeout.
        for topic,name in [('/rcboat/gps/status','gps'),('/rcboat/rc/input','rc'),
                ('/rcboat/navigation/desired','nav'),('/rcboat/gui/link','link'),
                ('/rcboat/actuator/status','actuator'),('/rcboat/propulsion/status','propulsion'),
                ('/rcboat/vision/status','vision'),('/rcboat/vision/desired','vision_desired')]:
            rospy.Subscriber(topic,String,lambda m,name=name:self._receive(name,m),queue_size=1)
        rospy.Service('/rcboat/safety/execute',Execute,self.execute)
    def _receive(self,name,message):
        value=unpack(message)
        with self.lock:setattr(self,name,value)

    def _input_ages(self,now):
        def age(value):
            try:
                stamp=float(value)
                return round(now-stamp,6) if stamp>0 and math.isfinite(stamp) else None
            except (ValueError,TypeError):return None
        return dict(decision_monotonic=now,actuator_age_s=age(self.actuator.get('monotonic')),
                    rc_age_s=age(self.rc.get('monotonic')),link_age_s=age(self.link.get('monotonic')),
                    gps_age_s=age(self.gps.get('last_valid_monotonic')),
                    vision_command_age_s=age(self.vision_desired.get('monotonic')))
    def execute(self,req):
        with self.lock:return self._execute(req)

    def _execute(self,req):
        try:
            args=json.loads(req.arguments_json or '{}')
            if not isinstance(args,dict):raise ValueError('request must be JSON object')
            if req.action=='estop':
                self.estop_reason=args.get('reason') if args.get('reason') in ('OPERATOR_ESTOP','MAINTENANCE_CHECK') else 'OPERATOR_ESTOP'
                self.estop_origin=args.get('origin') if args.get('origin') in ('desktop','mobile','maintenance') else 'gateway'
                self.estop_time_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
                self.estop=True;self._manual('EMERGENCY_STOP')
                self.events.publish(pack(type='ESTOP',at=time.time(),reason=self.estop_reason,origin=self.estop_origin,utc=self.estop_time_utc))
            elif req.action=='reset_estop':
                # Requires physical-safe mode; reset never restores navigation automatically.
                if self.mode not in ('MANUAL','AUTO_SAFE'):raise ValueError('select MANUAL first')
                self.estop=False;self.armed=False
                self._manual('ESTOP_CLEARED_NEUTRAL_REQUIRED')
            elif req.action=='set_mode':
                mode=str(args['mode'])
                if mode not in MODES:raise ValueError('unknown mode')
                if self.estop and mode not in ('AUTO_SAFE','MANUAL'):raise ValueError('E-STOP latched')
                if mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST','BALLOON'):
                    reason=self._link_fault(time.monotonic(),mode)
                    if reason:raise ValueError(reason)
                if mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST','BALLOON'):
                    if not self.gps.get('healthy') or not gps_is_healthy(self.gps,time.monotonic(),2.0):
                        raise ValueError('GPS_INVALID_OR_STALE')
                if mode in ('NAVIGATION','GROUND_TEST'):
                    reason=self._navigation_fault(time.monotonic())
                    if reason:raise ValueError(reason)
                if mode==self.mode=='NAVIGATION' and self.armed and bool(args.get('armed',False)):
                    # Route selection is independent of arming. Keep the running
                    # session and its PWM ramp when applying another route.
                    return ExecuteResponse(True,pack(mode=self.mode,estop=self.estop,armed=self.armed))
                if mode=='BALLOON':
                    if args.get('expected_mode_since_monotonic', self.mode_since) != self.mode_since:
                        raise ValueError('BALLOON_NOT_READY: operation mode changed')
                    if not balloon_camera_ready(self.vision,time.monotonic()):
                        raise ValueError('BALLOON_NOT_READY: live camera required')
                self.balloon_gps_gap_since=None
                self._clear_gps_grace('ABORTED','MODE_CHANGED')
                self.mode=mode;self.mode_since=time.monotonic();self.reason='';self.progress.reset()
                self.ground_test_actuation_enabled=(
                    mode=='GROUND_TEST' and bool(args.get('ground_test_actuation_enabled',False))
                )
                self.auto_gesture_since=None;self.manual_gesture_since=None
                self.manual_rearm_pending=mode=='MANUAL'
                self.manual_rearm_since=None
                self.armed=bool(args.get('armed',False)) if mode in ('NAVIGATION','BALLOON') else False
                if mode=='REMOTE':self.remote_stamp=0
                self.events.publish(pack(type='MODE_CHANGED',mode=mode,at=time.time()))
            elif req.action=='set_remote_pwm':
                if self.mode!='REMOTE':raise ValueError('not in REMOTE mode')
                steer=args['steering_pwm'];throttle=args['throttle_pwm']
                if not output_in_range(steer,throttle,self.output_calibration):raise ValueError('PWM outside calibration')
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
        if self.estop or not rc_valid(self.rc,self.rc_calibration,now):
            self.auto_gesture_since=self.manual_gesture_since=self.manual_rearm_since=None
            if self.mode=='MANUAL':self.manual_rearm_pending=True
            return
        steer=self.rc['steering_us'];throttle=self.rc['throttle_us']
        throttle_neutral=neutral(throttle,self.rc_calibration['throttle'])
        # Numeric high-end gestures; manual direction is not nav_invert_steering.
        if self.mode=='MANUAL' and normalized(steer,self.rc_calibration['steering'])>=.85 and throttle_neutral:
            if self.auto_gesture_since is None:self.auto_gesture_since=now
            elif now-self.auto_gesture_since>=3.0:
                self.mode='AUTO_SAFE';self.armed=False;self.auto_gesture_since=None
                self.events.publish(pack(type='RC_GESTURE_AUTO_SAFE',at=time.time()))
        else:self.auto_gesture_since=None
        if self.mode in ('AUTO_SAFE','AUTO','NAVIGATION','REMOTE','GROUND_TEST','BALLOON') and normalized(throttle,self.rc_calibration['throttle'])>=.90:
            if self.manual_gesture_since is None:self.manual_gesture_since=now
            elif now-self.manual_gesture_since>=.5:
                self.mode='MANUAL';self.armed=False;self.manual_rearm_pending=True
                self.manual_rearm_since=None;self.manual_gesture_since=None
                self.events.publish(pack(type='RC_GESTURE_MANUAL_PENDING_NEUTRAL',at=time.time()))
        else:self.manual_gesture_since=None
        if self.manual_rearm_pending:
            if throttle_neutral:
                if self.manual_rearm_since is None:self.manual_rearm_since=now
                elif now-self.manual_rearm_since>=.3:
                    self.manual_rearm_pending=False;self.manual_rearm_since=None
                    self.events.publish(pack(type='RC_MANUAL_ARMED',at=time.time()))
            else:self.manual_rearm_since=None
    def _manual(self,reason):
        previous=self.mode
        self.balloon_gps_gap_since=None
        self._clear_gps_grace('ABORTED',reason)
        self.mode='MANUAL';self.armed=False;self.reason=reason
        self.ground_test_actuation_enabled=False
        self.manual_rearm_pending=True;self.manual_rearm_since=None
        self.auto_gesture_since=self.manual_gesture_since=None
        self.progress.reset()
        self.events.publish(pack(type='FAILSAFE_MANUAL',reason=reason,previous_mode=previous,
                                 mode='MANUAL',at=time.time(),monotonic=time.monotonic(),
                                 gps_snapshot=dict(self.gps),navigation_snapshot=dict(self.nav),
                                 link_snapshot=dict(self.link),actuator_snapshot=dict(self.actuator),
                                 decision_snapshot=dict(self.decision_snapshot),
                                 vision_command_snapshot=dict(self.vision_desired)))

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
        if self.nav.get('valid') and not navigation_output_in_range(self.nav.get('desired_steering_pwm'),
                self.nav.get('desired_throttle_pwm'),self.output_calibration):return 'NAVIGATION_PWM_OUT_OF_RANGE'
        return ''

    def _clear_gps_grace(self,outcome,reason=''):
        if self.ground_gps_gap_since is not None:
            self.events.publish(pack(type=(self.gps_grace_mode or 'GROUND_TEST')+'_GPS_GRACE_'+outcome,
                at=time.time(),monotonic=time.monotonic(),reason=reason,
                elapsed_s=max(0,time.monotonic()-self.ground_gps_gap_since)))
        self.ground_gps_gap_since=None;self.ground_gps_recovery_stamp=None
        self.ground_gps_grace_remaining_s=0.0
        self.gps_grace_mode=None
        if self.reason in ('GROUND_TEST_GPS_GRACE','NAVIGATION_GPS_GRACE',NAVIGATION_SHOCK_GPS_GRACE):self.reason=''

    def _ground_gps_grace(self,now):
        gps_ok=bool(self.gps.get('healthy')) and gps_is_healthy(self.gps,now,2.0)
        grace=self.ground_gps_grace_s if self.mode=='GROUND_TEST' else self.navigation_gps_grace_s
        if self.ground_gps_gap_since is None:
            self.ground_gps_gap_since=now
            self.gps_grace_mode=self.mode
            self.events.publish(pack(type=self.mode+'_GPS_GRACE_STARTED',at=time.time(),
                monotonic=now,grace_s=grace,gps_snapshot=dict(self.gps)))
        elapsed=max(0,now-self.ground_gps_gap_since)
        self.ground_gps_grace_remaining_s=max(0,grace-elapsed)
        if elapsed>=grace:
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
        self.reason=self.mode+'_GPS_GRACE'
        return ''

    def _fault(self,now):
        reason=self._link_fault(now)
        if reason:return reason
        if not rc_valid(self.rc,self.rc_calibration,now):return 'RC_INPUT_LOST'
        try:validate_cruise(rospy.get_param('/rcboat/cruise_pwm',6650))
        except ValueError:return 'CRUISE_PWM_INVALID'
        if self.mode in ('NAVIGATION','GROUND_TEST'):
            # Cruise setting is distinct from reduced turn/feedback output PWM.
            if 'auto_cruise_pwm' in self.nav:
                try:validate_cruise(self.nav['auto_cruise_pwm'])
                except ValueError:return 'CRUISE_PWM_INVALID'
        if self.propulsion.get('fault') or self.propulsion.get('blocked'):
            return 'PROPULSION_FAULT'
        if self.actuator.get('command_applied') is False:return 'ACTUATOR_ERROR'
        if now-self.mode_since>1.5 and not fresh(float(self.actuator.get('monotonic') or 0),1.0,now):
            return 'ACTUATOR_TIMEOUT'
        gps_ok=bool(self.gps.get('healthy')) and gps_is_healthy(self.gps,now,2.0)
        if self.gps.get('transport_connected') is False or self.gps.get('error'):
            return 'GPS_DISCONNECTED'
        nav_delay=(finite_coordinate(self.gps.get('latitude'),self.gps.get('longitude')) and
                   (self.gps.get('data_validity')=='stale' or
                    (bool(self.gps.get('fix')) and not fresh(float(self.gps.get('last_valid_monotonic') or 0),2.0,now))))
        # Invalid/missing FIX is not a mere delay. Only NAVIGATION stale data is
        # eligible; Ground Test retains its established broader recovery policy.
        if self.mode=='BALLOON':
            reason=self._balloon_fault(now,gps_ok,nav_delay)
            if reason:return reason
            gps_ok=True  # The separate balloon GPS lease has already been checked.
        if self.mode=='NAVIGATION' and not gps_ok and not nav_delay:
            return 'GPS_INVALID_OR_STALE'
        gps_gap=(self.mode=='GROUND_TEST' or (self.mode=='NAVIGATION' and (nav_delay or self.ground_gps_gap_since is not None))) and (not gps_ok or self.ground_gps_gap_since is not None)
        if not gps_ok and not gps_gap:return 'GPS_INVALID_OR_STALE'
        if self.mode in ('NAVIGATION','GROUND_TEST'):
            reason=self._navigation_fault(now,allow_gps_gap=gps_gap)
            if reason:return reason
        if gps_gap:
            reason=self._ground_gps_grace(now)
            if reason:return reason
        throttle=(int(rospy.get_param('/rcboat/cruise_pwm',6650)) if self.mode=='AUTO'
                  else int((self.vision_desired if self.mode=='BALLOON' else self.nav).get('desired_throttle_pwm') or 6450))
        if self.progress.update(now,self.gps,throttle,
                enabled=self.mode in ('AUTO','NAVIGATION','BALLOON') and not gps_gap and bool(self.gps.get('healthy')) and
                       bool(rospy.get_param('/rcboat/no_progress_enabled',True)),
                timeout=float(rospy.get_param('/rcboat/no_progress_timeout_s',15.0))):
            return 'PROPULSION_NO_PROGRESS_SUSPECTED'
        return ''

    def _balloon_fault(self,now,gps_ok,delay):
        if not gps_ok:
            if not delay:return 'GPS_INVALID_OR_STALE'
            if self.balloon_gps_gap_since is None:
                self.balloon_gps_gap_since=now
                self.events.publish(pack(type='BALLOON_GPS_GRACE_STARTED',at=time.time(),monotonic=now))
            if now-self.balloon_gps_gap_since>=self.navigation_gps_grace_s:return 'GPS_INVALID_OR_STALE'
            self.reason='BALLOON_GPS_GRACE'
        else:
            if self.balloon_gps_gap_since is not None:self.events.publish(pack(type='BALLOON_GPS_GRACE_RECOVERED',at=time.time(),monotonic=now))
            self.balloon_gps_gap_since=None
            if self.reason=='BALLOON_GPS_GRACE':self.reason=''
        vision, desired = self.vision, self.vision_desired
        lost = 'BALLOON_TARGET_OR_CAMERA_LOST'
        if not (vision.get('enabled') and vision.get('model_ready') and vision.get('live_source')):
            return lost
        if safe_balloon_output(vision, desired, now, self.mode_since) is not None:
            if self.reason in ('BALLOON_CAMERA_DELAY', 'BALLOON_WAITING_TARGET'):
                self.reason = 'BALLOON_GPS_GRACE' if self.balloon_gps_gap_since is not None else ''
            return ''

        current_session = desired.get('tracking_session') == self.mode_since
        last_frame = desired.get('monotonic', 0) if current_session else self.mode_since
        if not isinstance(last_frame, (int, float)) or not fresh(last_frame, BALLOON_CAMERA_RECOVERY_S, now):
            return lost
        camera_ready = balloon_camera_ready(vision, now)
        recent_frame = camera_ready and fresh(last_frame, float(vision.get('max_frame_age_s', 1.5)), now)
        if camera_ready and (not current_session or
                             (desired.get('phase') in ('NO_TARGET', 'ACQUIRING') and recent_frame)):
            self.reason = 'BALLOON_WAITING_TARGET'
            return ''
        if not recent_frame:
            # Keep the session and target history. _command_locked holds neutral
            # until the same session has a fresh, usable command again.
            self.reason = 'BALLOON_CAMERA_DELAY'
            return ''
        return lost

    def _command(self):
        with self.lock:return self._command_locked()

    def _command_locked(self):
        now=time.monotonic();source='AUTO_SAFE';s=SAFE_STEERING;t=SAFE_THROTTLE;lock=True
        self.decision_snapshot=self._input_ages(now)
        if self.mode in ('AUTO','NAVIGATION','REMOTE','GROUND_TEST','BALLOON'):
            reason=self._fault(now)
            if reason:
                self._manual(reason)
                return 'FAILSAFE_MANUAL',s,t,True
        self._gestures(now)
        if self.mode not in ('GROUND_TEST','NAVIGATION'):self._clear_gps_grace('ABORTED','MODE_CHANGED')
        # GPS hard faults must lock autonomous navigation, not physically safe manual takeover.
        if self.estop:return 'ESTOP',s,t,True
        if self.mode=='NAVIGATION' and self.armed and self.ground_gps_gap_since is not None:
            protection=self.nav.get('navigation_protection')
            if (self.nav.get('ramp_session_monotonic')==self.mode_since and
                    isinstance(protection,dict) and protection.get('reason')=='HEADING_SHOCK'):
                self.reason=NAVIGATION_SHOCK_GPS_GRACE
                return 'NAVIGATION_GPS_GRACE',s,t,True
            return 'NAVIGATION_GPS_GRACE',SAFE_STEERING,self.navigation_gps_grace_pwm,False
        if self.mode=='GROUND_TEST':
            if self.ground_gps_gap_since is not None:
                return 'GROUND_TEST_GPS_GRACE',SAFE_STEERING,SAFE_THROTTLE,True
            # Full navigation-equivalent output is allowed only for the explicit,
            # non-persistent ground-test opt-in. E-STOP, GPS and freshness gates still win.
            if (self.ground_test_actuation_enabled and self.gps.get('healthy') and
                    self.nav.get('valid') and fresh(float(self.nav.get('monotonic',0)),.75,now)):
                s=self.nav['desired_steering_pwm']
                t=min(self.nav['desired_throttle_pwm'],self.output_calibration['throttle_forward_max'])
                return 'GROUND_TEST_NAVIGATION',s,t,False
            return 'GROUND_TEST',s,SAFE_THROTTLE,True
        if self.mode=='BALLOON' and self.armed:
            pair=safe_balloon_output(self.vision,self.vision_desired,now,self.mode_since)
            if pair is not None:return 'BALLOON',pair[0],pair[1],False
        if self.mode=='AUTO':
            t=min(int(rospy.get_param('/rcboat/cruise_pwm',6650)),self.output_calibration['throttle_forward_max'])
            return 'AUTO',s,t,False
        if self.mode=='MANUAL' and not self.manual_rearm_pending:
            if rc_valid(self.rc,self.rc_calibration,now):
                us_s=float(self.rc['steering_us']);us_t=float(self.rc['throttle_us'])
                out=self.output_calibration
                s=map_axis(us_s,self.rc_calibration['steering'],out['steering_low'],out['steering_center'],out['steering_high'])
                t=map_axis(us_t,self.rc_calibration['throttle'],out['throttle_reverse_max'],out['throttle_stop'],out['throttle_forward_max'])
                source='MANUAL';lock=False
        elif self.mode=='REMOTE':
            if fresh(self.remote_stamp,float(rospy.get_param('/rcboat/remote_heartbeat_s',.7)),now):
                s=self.remote['steering_pwm'];t=self.remote['throttle_pwm'];source='REMOTE';lock=False
            else:self._manual('REMOTE_TIMEOUT')
        elif self.mode=='NAVIGATION' and self.armed:
            # A cached pre-start command must not bypass the new-session ramp.
            ramp_ready=(self.nav.get('ramp_active') is True and
                        self.nav.get('ramp_session_monotonic')==self.mode_since)
            if ramp_ready and self.gps.get('healthy') and self.nav.get('valid') and fresh(float(self.nav.get('monotonic',0)),.75,now):
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
                if self.mode=='NAVIGATION':
                    msg.navigation_session_monotonic=self.mode_since
                self.cmd.publish(msg)
                self.state.publish(pack(software_version="2.4.23",mode=self.mode,armed=self.armed,estop=self.estop,actuator_locked=lock,
                                        estop_reason=self.estop_reason,estop_time_utc=self.estop_time_utc,estop_origin=self.estop_origin,
                                        mode_since_monotonic=self.mode_since,
                                        ground_test_actuation_enabled=self.ground_test_actuation_enabled,
                                        gps_grace_active=self.ground_gps_gap_since is not None or self.balloon_gps_gap_since is not None,
                                        balloon_armed=self.mode=='BALLOON' and self.armed,
                                        gps_grace_remaining_s=round(max(0,self.navigation_gps_grace_s-(time.monotonic()-self.balloon_gps_gap_since)),2) if self.balloon_gps_gap_since is not None else round(self.ground_gps_grace_remaining_s,2),
                                        gps_grace_s=self.navigation_gps_grace_s if self.mode=='NAVIGATION' else self.ground_gps_grace_s,
                                        gps_grace_mode='BALLOON' if self.balloon_gps_gap_since is not None else self.gps_grace_mode,
                                        reason=self.reason,manual_rearm_pending=self.manual_rearm_pending,
                                        decision_snapshot=dict(self.decision_snapshot),
                                        rc_fresh=rc_valid(self.rc,self.rc_calibration,time.monotonic()),
                                        rc_input_calibration=self.rc_calibration,pca_output_calibration=self.output_calibration,
                                        propulsion_feedback_status='fault' if self.propulsion.get('fault') or self.propulsion.get('blocked') else 'available' if self.propulsion else 'unsupported',
                                        throttle_locked=lock,
                                        steering_test_enabled=self.mode=='GROUND_TEST' and source=='GROUND_TEST_NAVIGATION',
                                        effective_source=source,steering_pwm=s,throttle_pwm=t))
            rate.sleep()
if __name__=='__main__':rospy.init_node('safety_supervisor_node');Supervisor().run()
