#!/usr/bin/env python3
from __future__ import annotations

import math
import threading
import time

import rospy

from rcboat_ros.msg import BoatState, ControlCommand, GpsStatus, NavigationStatus, NtripStatus, RouteState
from rcboat_ros.navigation import angle_error_deg, bearing_deg
from rcboat_ros.ros_utils import clamp_int


class NavigationNode:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.gps = None
        self.route = None
        self.boat = None
        self.ntrip = None
        self.center = int(rospy.get_param("/rcboat/hardware/steering_center_pwm", 6000))
        self.steer_low = int(rospy.get_param("/rcboat/hardware/steering_low_pwm", 4900))
        self.steer_high = int(rospy.get_param("/rcboat/hardware/steering_high_pwm", 7300))
        self.stop_pwm = int(rospy.get_param("/rcboat/hardware/throttle_stop_pwm", 6450))
        self.inverted = bool(rospy.get_param("/rcboat/navigation/steering_inverted", True))
        self.full_error = float(rospy.get_param("/rcboat/navigation/full_speed_error_deg", 35.0))
        self.slow_error = float(rospy.get_param("/rcboat/navigation/slow_error_deg", 100.0))
        self.min_fraction = float(rospy.get_param("/rcboat/navigation/minimum_speed_fraction", 0.65))
        self.severe_error = float(rospy.get_param("/rcboat/navigation/severe_turn_error_deg", 150.0))
        self.severe_release = float(rospy.get_param("/rcboat/navigation/severe_turn_release_deg", 100.0))
        self.severe_pause_s = float(rospy.get_param("/rcboat/navigation/severe_turn_pause_s", 0.4))
        self.gps_stale_s = float(rospy.get_param("/rcboat/gps/health_stale_s", 2.0))
        self.max_hdop = float(rospy.get_param("/rcboat/gps/navigation_max_hdop", 3.0))
        self.rtk_required = bool(rospy.get_param("/rcboat/gps/rtk_required_for_navigation", False))
        self.rtk_fallback = bool(rospy.get_param("/rcboat/gps/rtk_fallback_to_gps", True))
        self.correction_max_s = float(rospy.get_param("/rcboat/gps/rtk_correction_max_age_s", 10.0))
        self.severe_active = False
        self.pause_until = 0.0
        self.command_pub = rospy.Publisher("/rcboat/navigation/command", ControlCommand, queue_size=10)
        self.status_pub = rospy.Publisher("/rcboat/navigation/status", NavigationStatus, queue_size=10)
        rospy.Subscriber("/rcboat/gps/status", GpsStatus, self._gps_cb, queue_size=10)
        rospy.Subscriber("/rcboat/route/state", RouteState, self._route_cb, queue_size=10)
        rospy.Subscriber("/rcboat/safety/state", BoatState, self._boat_cb, queue_size=10)
        rospy.Subscriber("/rcboat/ntrip/status", NtripStatus, self._ntrip_cb, queue_size=10)

    def _gps_cb(self, msg):
        with self._lock: self.gps = msg

    def _route_cb(self, msg):
        with self._lock: self.route = msg

    def _boat_cb(self, msg):
        with self._lock: self.boat = msg

    def _ntrip_cb(self, msg):
        with self._lock: self.ntrip = msg

    def _gate(self, gps: GpsStatus | None) -> str:
        self.gps_stale_s = float(rospy.get_param("/rcboat/gps/health_stale_s", self.gps_stale_s))
        self.max_hdop = float(rospy.get_param("/rcboat/gps/navigation_max_hdop", self.max_hdop))
        self.rtk_required = bool(rospy.get_param("/rcboat/gps/rtk_required_for_navigation", self.rtk_required))
        self.rtk_fallback = bool(rospy.get_param("/rcboat/gps/rtk_fallback_to_gps", self.rtk_fallback))
        self.correction_max_s = float(rospy.get_param("/rcboat/gps/rtk_correction_max_age_s", self.correction_max_s))
        if gps is None or not gps.connected:
            return "GPS_DISCONNECTED"
        if gps.age_s > self.gps_stale_s:
            return "GPS_STALE"
        if not gps.fix:
            return "GPS_NO_FIX"
        if not math.isfinite(gps.latitude) or not math.isfinite(gps.longitude):
            return "GPS_DATA_INVALID"
        if math.isfinite(gps.hdop) and gps.hdop > self.max_hdop:
            return "GPS_HDOP_BAD"
        if self.rtk_required and not self.rtk_fallback:
            if gps.rtk_state != "RTK_FIXED":
                return "RTK_REQUIRED"
            if self.ntrip is None or self.ntrip.last_correction_age_s > self.correction_max_s:
                return "RTK_CORRECTION_STALE"
        return ""

    def _calculate(self) -> tuple[ControlCommand, NavigationStatus]:
        with self._lock:
            gps, route, boat = self.gps, self.route, self.boat
        cmd = ControlCommand()
        cmd.header.stamp = rospy.Time.now()
        cmd.source = "NAVIGATION"
        cmd.steering_pwm = self.center
        cmd.throttle_pwm = self.stop_pwm
        cmd.valid = False
        status = NavigationStatus()
        status.header = cmd.header
        status.state = "NAVIGATION_IDLE"
        status.target_latitude = float("nan")
        status.target_longitude = float("nan")
        status.target_bearing_deg = float("nan")
        status.heading_error_deg = float("nan")
        status.distance_to_waypoint_m = float("nan")
        mode_active = bool(boat and boat.mode == "NAVIGATION")
        status.active = mode_active
        if not mode_active:
            self.severe_active = False
            return cmd, status
        gate = self._gate(gps)
        if gate:
            status.state = "NAVIGATION_WAITING_GPS"
            status.gate_reason = gate
            return cmd, status
        if route is None or not route.available or route.route_complete:
            status.state = "NAVIGATION_ROUTE_COMPLETE" if route and route.route_complete else "NAVIGATION_WAITING_ROUTE"
            status.gate_reason = "ROUTE_COMPLETE" if route and route.route_complete else "ROUTE_UNAVAILABLE"
            status.route_complete = bool(route and route.route_complete)
            return cmd, status
        target = (route.target_latitude, route.target_longitude)
        status.target_latitude, status.target_longitude = target
        status.distance_to_waypoint_m = route.distance_to_waypoint_m
        status.waypoint_index = route.waypoint_index
        status.waypoint_count = route.waypoint_count
        status.route_complete = route.route_complete
        cruise = int(boat.auto_cruise_pwm)
        if not math.isfinite(gps.course_deg):
            cmd.valid = True
            cmd.throttle_pwm = cruise
            status.active = True
            status.command_valid = True
            status.state = "NAVIGATION_ACTIVE"
            status.speed_fraction = 1.0
            return cmd, status
        target_bearing = bearing_deg((gps.latitude, gps.longitude), target)
        error = angle_error_deg(target_bearing, gps.course_deg)
        steering_error = -error if self.inverted else error
        if steering_error >= 0:
            steering = self.center + min(steering_error / 90.0, 1.0) * (self.steer_high - self.center)
        else:
            steering = self.center + max(steering_error / 90.0, -1.0) * (self.center - self.steer_low)
        now = time.monotonic()
        abs_error = abs(error)
        if abs_error >= self.severe_error and not self.severe_active:
            self.severe_active = True
            self.pause_until = now + self.severe_pause_s
        elif self.severe_active and abs_error <= self.severe_release:
            self.severe_active = False
            self.pause_until = 0.0
        if self.severe_active and now < self.pause_until:
            fraction = 0.0
            throttle = self.stop_pwm
            status.state = "NAVIGATION_TURN_PAUSE"
        else:
            if abs_error <= self.full_error:
                fraction = 1.0
            elif abs_error >= self.slow_error:
                fraction = self.min_fraction
            else:
                progress = (abs_error - self.full_error) / max(0.001, self.slow_error - self.full_error)
                fraction = 1.0 - progress * (1.0 - self.min_fraction)
            throttle = int(round(self.stop_pwm + (cruise - self.stop_pwm) * fraction))
            status.state = "NAVIGATION_ACTIVE"
        cmd.steering_pwm = clamp_int(steering, self.steer_low, self.steer_high)
        cmd.throttle_pwm = throttle
        cmd.valid = True
        status.active = True
        status.command_valid = True
        status.target_bearing_deg = target_bearing
        status.heading_error_deg = error
        status.speed_fraction = fraction
        status.severe_turn_recovery = self.severe_active
        return cmd, status

    def spin(self) -> None:
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            cmd, status = self._calculate()
            self.command_pub.publish(cmd)
            self.status_pub.publish(status)
            rate.sleep()


if __name__ == "__main__":
    rospy.init_node("navigation_node")
    NavigationNode().spin()
