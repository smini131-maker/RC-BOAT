#!/usr/bin/env python3
"""Only Arduino Serial owner. No other node opens this port."""
import json
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack

def main():
    rospy.init_node('rc_input_node')
    pub=rospy.Publisher('/rcboat/rc/input',String,queue_size=10)
    import serial
    path=rospy.get_param('/rcboat/arduino_port')
    s=serial.Serial(path,int(rospy.get_param('/rcboat/arduino_baudrate',9600)),timeout=0.2,exclusive=True)
    try:
        while not rospy.is_shutdown():
            raw=s.readline().decode('ascii','ignore').strip().split(',')
            if len(raw)!=2: continue
            try:
                steer,throttle=map(int,raw)
                if not 700<=steer<=2300 or not 700<=throttle<=2300:continue
            except ValueError:continue
            pub.publish(pack(steering_us=steer,throttle_us=throttle,monotonic=time.monotonic()))
    finally:s.close()
if __name__=='__main__':main()
