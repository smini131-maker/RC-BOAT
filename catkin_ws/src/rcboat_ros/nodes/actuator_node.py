#!/usr/bin/env python3
"""Only PCA owner. Failsafe neutral on timeouts, ros_shutdown and bad command."""
import fcntl
import os
import time
import datetime as dt
import rospy
from std_msgs.msg import String
from rcboat_ros.msg import ControlCommand
from rcboat_ros.common import SAFE_STEERING,SAFE_THROTTLE,pack,PCA_OWNER_LOCK
from rcboat_ros.direct_pca import DirectLinuxPCA9685
from rcboat_ros.control_config import load_output,validate_cruise,output_in_range

class Actuator:
    def __init__(self):
        self.output_calibration=load_output(rospy.get_param)
        self.lockfd=open(PCA_OWNER_LOCK,'w')
        fcntl.flock(self.lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.pca=DirectLinuxPCA9685(rospy.get_param('/rcboat/pca_bus',1),rospy.get_param('/rcboat/pca_address',64),rospy.get_param('/rcboat/pca_frequency',60))
        self.steer_ch=int(rospy.get_param('/rcboat/steering_channel',0))
        self.throttle_ch=int(rospy.get_param('/rcboat/throttle_channel',6))
        self.last_message=None;self.last_at=0;self.last_good=(SAFE_STEERING,SAFE_THROTTLE)
        self.status=rospy.Publisher('/rcboat/actuator/status',String,queue_size=5)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        self.shutdown_done=False
        self.safe_write()
        rospy.Subscriber('/rcboat/safety/final_command',ControlCommand,self.command,queue_size=1)
        rospy.on_shutdown(self.shutdown)
    def write(self,s,t):
        # No partial PWM writes are considered successful. ESC command is neutralized first.
        self.pca.set_duty_cycle(self.throttle_ch,int(t))
        self.pca.set_duty_cycle(self.steer_ch,int(s))
        self.last_good=(s,t)
    def safe_write(self):self.write(SAFE_STEERING,SAFE_THROTTLE)
    def command(self,msg):
        self.last_message=msg;self.last_at=time.monotonic()
    def resolve(self,now):
        """Resolve a received safety command without performing hardware I/O."""
        state='TIMEOUT';s=SAFE_STEERING;t=SAFE_THROTTLE
        msg=self.last_message
        timeout=float(rospy.get_param('/rcboat/command_timeout_s',.75))
        if msg and 0<=now-self.last_at<=timeout:
            if msg.mode=='GROUND_TEST':
                if msg.actuator_locked:
                    state='GROUND_TEST_LOCKED'
                elif (msg.source=='GROUND_TEST_NAVIGATION' and
                      output_in_range(msg.steering_pwm,msg.throttle_pwm,self.output_calibration)):
                    s=msg.steering_pwm;t=msg.throttle_pwm;state='GROUND_TEST_NAVIGATION'
                else:state='GROUND_TEST_REJECTED'
            elif msg.actuator_locked:state='LOCKED'
            elif msg.mode=='NAVIGATION' and msg.source=='NAVIGATION_GPS_GRACE':
                try:
                    grace_pwm=validate_cruise(rospy.get_param('/rcboat/navigation_gps_grace_pwm',6650))
                    if msg.steering_pwm==SAFE_STEERING and msg.throttle_pwm==grace_pwm:
                        s=SAFE_STEERING;t=grace_pwm;state=msg.source
                except ValueError:state='CRUISE_REJECTED'
            elif msg.source in ('AUTO','MANUAL','REMOTE','NAVIGATION','BALLOON'):
                if output_in_range(msg.steering_pwm,msg.throttle_pwm,self.output_calibration):
                    s=msg.steering_pwm;t=msg.throttle_pwm;state=msg.source
        if msg and msg.mode in ('AUTO','NAVIGATION','GROUND_TEST','BALLOON') and state in ('AUTO','NAVIGATION','NAVIGATION_GPS_GRACE','GROUND_TEST_NAVIGATION','BALLOON'):
            try:
                validate_cruise(rospy.get_param('/rcboat/cruise_pwm',6650))
                if state=='AUTO':validate_cruise(t)
            except ValueError:
                s=SAFE_STEERING;t=SAFE_THROTTLE;state='CRUISE_REJECTED'
        return s,t,state

    def run(self):
        rate=rospy.Rate(15)
        while not rospy.is_shutdown():
            s,t,state=self.resolve(time.monotonic())
            try:
                self.write(s,t)
                self.status.publish(pack(actual_steering_pwm=s,actual_throttle_pwm=t,
                                         command_applied=True,readback_available=False,status=state,
                                         output_time_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
                                         monotonic=time.monotonic()))
            except (OSError,RuntimeError) as exc:
                rospy.logfatal('PCA I2C fault %s',exc)
                self.events.publish(pack(type='ACTUATOR_ERROR',error=str(exc)))
                # Real hardware state unknown after I2C fault; never report commanded as actual.
                self.status.publish(pack(actual_steering_pwm=None,actual_throttle_pwm=None,
                                         command_applied=False,readback_available=False,status='HARDWARE_FAULT'))
                raise
            rate.sleep()
    def shutdown(self):
        if self.shutdown_done:return
        self.shutdown_done=True
        try:
            self.safe_write()
        except Exception as e:rospy.logerr('shutdown safe write not confirmed: %s',e)
        finally:
            self.pca.close()
            fcntl.flock(self.lockfd,fcntl.LOCK_UN);self.lockfd.close()
if __name__=='__main__':rospy.init_node('actuator_node');Actuator().run()
