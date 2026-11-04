#!/usr/bin/env python3
"""Only Arduino Serial owner. No other node opens this port."""
import json
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack
from rcboat_ros.control_config import load_rc,rc_valid

def main():
    rospy.init_node('rc_input_node')
    pub=rospy.Publisher('/rcboat/rc/input',String,queue_size=10)
    calibration=load_rc(rospy.get_param)
    import serial
    path=rospy.get_param('/rcboat/arduino_port')
    s=serial.Serial(path,int(rospy.get_param('/rcboat/arduino_baudrate',9600)),timeout=0.2,exclusive=True)
    try:
        while not rospy.is_shutdown():
            raw=s.readline().decode('ascii','ignore').strip().split(',')
            if raw==['']:continue  # Serial timeout: existing 0.75 s lease decides staleness.
            try:
                if len(raw)!=2:raise ValueError('missing RC channels')
                steer,throttle=map(int,raw)
                data=dict(steering_us=steer,throttle_us=throttle,monotonic=time.monotonic(),
                          input_source='arduino_serial_rc_input',input_unit='us')
                data['valid']=rc_valid(data,calibration,time.monotonic())
                pub.publish(pack(**data))
            except ValueError:
                pub.publish(pack(valid=False,monotonic=time.monotonic(),
                                 input_source='arduino_serial_rc_input',input_unit='us'))
    finally:s.close()
if __name__=='__main__':main()
