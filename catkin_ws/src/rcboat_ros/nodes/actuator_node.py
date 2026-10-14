#!/usr/bin/env python3
"""Only PCA owner. Failsafe neutral on timeouts, ros_shutdown and bad command."""
import fcntl
import os
import time
import datetime as dt
import rospy
from std_msgs.msg import String
from rcboat_ros.msg import ControlCommand
from rcboat_ros.common import SAFE_STEERING,SAFE_THROTTLE,pack
from rcboat_ros.direct_pca import DirectLinuxPCA9685

class Actuator:
    def __init__(self):
        self.lockfd=open('/tmp/rcboat_ros_pca_owner.lock','w')
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
    def run(self):
        rate=rospy.Rate(15)
        while not rospy.is_shutdown():
            state='TIMEOUT';s=SAFE_STEERING;t=SAFE_THROTTLE
            msg=self.last_message
            timeout=float(rospy.get_param('/rcboat/command_timeout_s',.75))
            if msg and 0<=time.monotonic()-self.last_at<=timeout:
                if msg.actuator_locked or msg.mode=='GROUND_TEST':state='LOCKED'
                elif msg.source in ('AUTO','MANUAL','REMOTE','NAVIGATION'):
                    if 4900<=msg.steering_pwm<=7300 and 5800<=msg.throttle_pwm<=7000:
                        s=msg.steering_pwm;t=msg.throttle_pwm;state=msg.source
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
