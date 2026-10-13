#!/usr/bin/env python3
from __future__ import annotations

import math
import threading
import time

import rospy

from rcboat_ros.msg import ActuatorStatus, ControlCommand, GpsStatus, NtripStatus, RcInput
from rcboat_ros.srv import InjectHilFault, InjectHilFaultResponse


class MockHardwareNode:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.lat = 35.078
        self.lon = 129.086
        self.course = 45.0
        self.last_step = time.monotonic()
        self.command = (6000, 6450)
        self.faults = set()
        self.rc_pub = rospy.Publisher("/rcboat/rc/input", RcInput, queue_size=10)
        self.gps_pub = rospy.Publisher("/rcboat/gps/status", GpsStatus, queue_size=10)
        self.actuator_pub = rospy.Publisher("/rcboat/actuator/status", ActuatorStatus, queue_size=10, latch=True)
        self.ntrip_pub = rospy.Publisher("/rcboat/ntrip/status", NtripStatus, queue_size=2, latch=True)
        rospy.Subscriber("/rcboat/safety/actuator_command", ControlCommand, self._command_cb, queue_size=1)
        rospy.Service("/rcboat/hil/inject_fault", InjectHilFault, self._fault)

    def _command_cb(self, msg):
        with self._lock:
            self.command = (msg.steering_pwm, msg.throttle_pwm) if msg.valid else (6000, 6450)

    def _fault(self, req):
        allowed = {
            "gps_disconnect", "gps_no_fix", "gps_stale", "gps_hdop_bad",
            "rtk_loss", "rc_disconnect", "actuator_fault", "multipath_switch",
        }
        if req.fault not in allowed:
            return InjectHilFaultResponse(False, f"unknown fault: {req.fault}")
        with self._lock:
            if req.fault == "multipath_switch" and req.enabled:
                # One-shot lateral jump used to exercise the route manager's
                # off-route / alternate-path logic without touching hardware.
                self.lon += 12.0 / (111_320.0 * max(0.1, math.cos(math.radians(self.lat))))
                self.faults.discard(req.fault)
                return InjectHilFaultResponse(True, "synthetic 12 m lateral jump applied")
            if req.enabled:
                self.faults.add(req.fault)
            else:
                self.faults.discard(req.fault)
        return InjectHilFaultResponse(True, f"{req.fault}={req.enabled}")

    def _step_motion(self, now: float) -> None:
        dt = min(0.1, max(0.0, now - self.last_step))
        self.last_step = now
        steering, throttle = self.command
        turn = (steering - 6000) / 1300.0 * 35.0
        self.course = (self.course + turn * dt) % 360.0
        speed = max(0.0, throttle - 6450) / 550.0 * 1.5
        distance = speed * dt
        radians = math.radians(self.course)
        self.lat += math.cos(radians) * distance / 111_320.0
        self.lon += math.sin(radians) * distance / (111_320.0 * max(0.1, math.cos(math.radians(self.lat))))

    def spin(self) -> None:
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            now = time.monotonic()
            with self._lock:
                self._step_motion(now)
                faults = set(self.faults)
                steering, throttle = self.command
                lat, lon, course = self.lat, self.lon, self.course
            stamp = rospy.Time.now()
            rc = RcInput()
            rc.header.stamp = stamp
            rc.connected = "rc_disconnect" not in faults
            rc.steering_us = 1640
            rc.throttle_us = 1500
            rc.age_s = 0.0 if rc.connected else float("inf")
            rc.error = "HIL injected RC disconnect" if not rc.connected else ""
            self.rc_pub.publish(rc)
            gps = GpsStatus()
            gps.header.stamp = stamp
            gps.header.frame_id = "gps"
            gps.connected = "gps_disconnect" not in faults
            gps.fix = gps.connected and "gps_no_fix" not in faults
            rtk_fixed = gps.fix and "rtk_loss" not in faults
            gps.fix_quality = 4 if rtk_fixed else 1 if gps.fix else 0
            gps.fix_label = "RTK FIXED" if rtk_fixed else "GPS" if gps.fix else "NO FIX"
            gps.latitude = lat if gps.fix else float("nan")
            gps.longitude = lon if gps.fix else float("nan")
            gps.altitude_m = 4.2
            gps.satellites = 18 if gps.fix else 0
            gps.hdop = 5.0 if "gps_hdop_bad" in faults else 0.8
            gps.pdop = 1.1
            gps.vdop = 1.4
            gps.cno_avg_dbhz = 38.0
            gps.hacc_m = 0.05
            gps.speed_mps = max(0.0, throttle - 6450) / 550.0 * 1.5
            gps.course_deg = course
            gps.age_s = 99.0 if "gps_stale" in faults else 0.0 if gps.connected else float("inf")
            gps.position_age_s = 0.0 if gps.fix else float("inf")
            gps.health_status = "GOOD" if gps.fix and gps.hdop <= 3.0 else "BAD"
            gps.navigation_status = gps.health_status
            gps.health_reason = "HIL synthetic GPS"
            gps.rtk_state = "RTK_FIXED" if rtk_fixed else "NO_RTK"
            gps.rtk_fallback_active = bool(gps.fix and not rtk_fixed)
            gps.navigation_fix_mode = gps.rtk_state if rtk_fixed else "GPS" if gps.fix else "NO_FIX"
            self.gps_pub.publish(gps)
            actuator = ActuatorStatus()
            actuator.header.stamp = stamp
            actuator.connected = "actuator_fault" not in faults
            actuator.mock = True
            actuator.steering_pwm = steering
            actuator.throttle_pwm = throttle
            actuator.command_age_s = 0.0
            actuator.watchdog_safe = False
            actuator.error = "HIL injected actuator fault" if not actuator.connected else ""
            self.actuator_pub.publish(actuator)
            ntrip = NtripStatus()
            ntrip.header.stamp = stamp
            ntrip.enabled = False
            ntrip.connected = False
            ntrip.port = 2101
            ntrip.last_correction_age_s = float("inf")
            self.ntrip_pub.publish(ntrip)
            rate.sleep()


if __name__ == "__main__":
    rospy.init_node("mock_hardware_node")
    MockHardwareNode().spin()
