#!/usr/bin/env python3
from __future__ import annotations

import math

import rospy
from rcboat_msgs.msg import GpsStatus, PwmCommand, RcInput
from std_msgs.msg import Bool


class MockIoNode:
    def __init__(self) -> None:
        self.started = rospy.Time.now()
        self.rc_pub = rospy.Publisher("/rcboat/rc_input", RcInput, queue_size=10)
        self.gps_pub = rospy.Publisher("/rcboat/gps_status", GpsStatus, queue_size=10)
        self.pca_pub = rospy.Publisher("/rcboat/pca_connected", Bool, queue_size=1, latch=True)
        self.last_pwm = None
        rospy.Subscriber("/rcboat/pwm_command", PwmCommand, self.pwm_callback, queue_size=10)
        rospy.Timer(rospy.Duration(0.1), self.publish)
        self.pca_pub.publish(Bool(data=True))

    def pwm_callback(self, message: PwmCommand) -> None:
        self.last_pwm = message

    def publish(self, _event) -> None:
        now = rospy.Time.now()
        elapsed = (now - self.started).to_sec()
        rc = RcInput()
        rc.header.stamp = now
        rc.connected = True
        rc.steering_us = 1640
        rc.throttle_us = 1500
        self.rc_pub.publish(rc)

        gps = GpsStatus()
        gps.header.stamp = now
        gps.connected = True
        gps.fix = True
        gps.quality = 4
        gps.fix_label = "RTK FIXED"
        gps.latitude = 35.078 + elapsed * 0.000001
        gps.longitude = 129.086 + elapsed * 0.000001
        gps.altitude_m = 4.2
        gps.satellites = 18
        gps.hdop = 0.8
        gps.pdop = 1.2
        gps.vdop = 0.9
        gps.hacc_m = 0.02
        gps.speed_mps = 0.7
        gps.course_deg = 42.0
        gps.age_s = 0.0
        gps.health = "GOOD"
        gps.rtk_state = "RTK_FIXED"
        gps.rtk_fallback_active = False
        gps.correction_age_s = 0.1
        self.gps_pub.publish(gps)


if __name__ == "__main__":
    rospy.init_node("rcboat_mock_io")
    MockIoNode()
    rospy.spin()
