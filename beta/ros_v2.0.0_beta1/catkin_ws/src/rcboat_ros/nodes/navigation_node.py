#!/usr/bin/env python3
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack,unpack
from rcboat_ros.path_tracking import navigation_command

class Navigation:
    def __init__(self):
        self.gps={};self.route={};self.paused_until=0;self.large_turn_seen=False
        self.config={k:rospy.get_param('/rcboat/'+k,v) for k,v in {
            'steering_low':4900,'steering_center':6000,'steering_high':7300,'throttle_stop':6450,'cruise_pwm':6650,'nav_invert_steering':True}.items()}
        self.pub=rospy.Publisher('/rcboat/navigation/desired',String,queue_size=5)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
        rospy.Subscriber('/rcboat/route/state',String,lambda m:setattr(self,'route',unpack(m)))
    def run(self):
        rate=rospy.Rate(4)
        while not rospy.is_shutdown():
            out={'valid':False,'desired_steering_pwm':6000,'desired_throttle_pwm':6450,
                 'desired_rudder_angle_deg':0,'monotonic':time.monotonic()}
            if self.gps.get('healthy') and 'target_lat' in self.route and self.gps.get('heading_deg') is not None:
                try:
                    abs_error=None
                    calc=navigation_command(self.gps,self.route,self.config,self.large_turn_seen)
                    abs_error=abs(calc['heading_error_deg'])
                    if abs_error<125:self.large_turn_seen=False
                    if calc['initial_turn_pause_requested']:
                        self.large_turn_seen=True;self.paused_until=time.monotonic()+0.4
                    if time.monotonic()<self.paused_until:calc['desired_throttle_pwm']=6450
                    out.update(calc,valid=True)
                except (TypeError,ValueError,KeyError) as e:rospy.logwarn('Navigation waiting: %s',e)
            self.pub.publish(pack(**out));rate.sleep()
if __name__=='__main__':rospy.init_node('navigation_node');Navigation().run()
