#!/usr/bin/env python3
"""Single GPS read/write owner; RTCM is forwarded into this process."""
import threading
import time
import rospy
from std_msgs.msg import String, UInt8MultiArray
from rcboat_ros.gps_mix import MixedGpsParser
from rcboat_ros.common import pack,gps_is_healthy,cno_quality

def main():
    rospy.init_node('gps_node')
    import serial
    dev=rospy.get_param('/rcboat/gps_port')
    serial_port=serial.Serial(dev,int(rospy.get_param('/rcboat/gps_baudrate',115200)),timeout=.08,exclusive=True)
    io_lock=threading.Lock()
    parser=MixedGpsParser()
    def rtcm(msg):
        try:
            with io_lock:serial_port.write(bytes(msg.data))
        except (OSError,ValueError) as exc:rospy.logerr('RTCM forwarding failed: %s',exc)
    rospy.Subscriber('/rcboat/gps/rtcm',UInt8MultiArray,rtcm,queue_size=20)
    pub=rospy.Publisher('/rcboat/gps/status',String,queue_size=5)
    last_publish=0
    last_poll=0
    try:
        while not rospy.is_shutdown():
            try:
                with io_lock:data=serial_port.read(max(1,min(serial_port.in_waiting,4096)))
                parser.feed(data)
            except Exception as exc:
                rospy.logerr('GPS read fault %s',exc)
                parser.state['fix']=False
                rospy.sleep(0.25)
            now=time.monotonic()
            if now-last_poll>=1.0:
                try:
                    with io_lock:serial_port.write(b'\xb5\x62\x01\x07\x00\x00\x08\x19')
                except Exception as exc:rospy.logwarn('NAV-PVT polling failed %s',exc)
                last_poll=now
            if now-last_publish>=.25:
                result=dict(parser.state)
                result['healthy']=gps_is_healthy(result,now,rospy.get_param('/rcboat/gps_stale_s',2.0),rospy.get_param('/rcboat/max_hdop',3.0))
                result['cno_quality']=cno_quality(result.get('cno_dbhz'))
                # stale FIX explicitly cleared; old coordinates remain for diagnostic display only.
                if not result['healthy']:result['fix']=False
                pub.publish(pack(**result));last_publish=now
    finally:serial_port.close()
if __name__=='__main__':main()
