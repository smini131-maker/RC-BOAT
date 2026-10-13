#!/usr/bin/env python3
from __future__ import annotations

import math
import time

import rospy
from rcboat_msgs.msg import GpsStatus, NtripStatus
from sensor_msgs.msg import NavSatFix, NavSatStatus
from ublox_msgs.msg import NavDOP, NavPVT


class GpsHealthNode:
    def __init__(self) -> None:
        self.stale_s = float(rospy.get_param("~stale_s", 2.0))
        self.fix_message = None
        self.pvt_message = None
        self.dop_message = None
        self.ntrip_message = None
        self.fix_received_at = 0.0
        self.publisher = rospy.Publisher("/rcboat/gps_status", GpsStatus, queue_size=10)
        rospy.Subscriber("/ublox_gps/fix", NavSatFix, self.fix_callback, queue_size=10)
        rospy.Subscriber("/ublox_gps/navpvt", NavPVT, self.pvt_callback, queue_size=10)
        rospy.Subscriber("/ublox_gps/navdop", NavDOP, self.dop_callback, queue_size=10)
        rospy.Subscriber("/rcboat/ntrip_status", NtripStatus, self.ntrip_callback, queue_size=10)
        rospy.Timer(rospy.Duration(0.1), self.publish)

    def fix_callback(self, message: NavSatFix) -> None:
        self.fix_message = message
        self.fix_received_at = time.monotonic()

    def pvt_callback(self, message: NavPVT) -> None:
        self.pvt_message = message

    def dop_callback(self, message: NavDOP) -> None:
        self.dop_message = message

    def ntrip_callback(self, message: NtripStatus) -> None:
        self.ntrip_message = message

    def publish(self, _event) -> None:
        now = time.monotonic()
        message = GpsStatus()
        message.header.stamp = rospy.Time.now()
        age = now - self.fix_received_at if self.fix_received_at else math.inf
        message.age_s = age
        message.connected = self.fix_message is not None and age <= self.stale_s * 2
        if self.fix_message is not None:
            message.latitude = self.fix_message.latitude
            message.longitude = self.fix_message.longitude
            message.altitude_m = self.fix_message.altitude
            if self.fix_message.position_covariance_type != NavSatFix.COVARIANCE_TYPE_UNKNOWN:
                message.hacc_m = math.sqrt(max(0.0, self.fix_message.position_covariance[0]))
            else:
                message.hacc_m = math.nan
        else:
            message.latitude = math.nan
            message.longitude = math.nan
            message.altitude_m = math.nan
            message.hacc_m = math.nan

        pvt = self.pvt_message
        fix_ok = bool(pvt is not None and pvt.flags & NavPVT.FLAGS_GNSS_FIX_OK)
        navsat_ok = bool(
            self.fix_message is not None
            and self.fix_message.status.status >= NavSatStatus.STATUS_FIX
        )
        message.fix = fix_ok or navsat_ok
        carrier = pvt.flags & NavPVT.FLAGS_CARRIER_PHASE_MASK if pvt is not None else 0
        if carrier == NavPVT.CARRIER_PHASE_FIXED:
            message.quality = 4
            message.fix_label = "RTK FIXED"
            message.rtk_state = "RTK_FIXED"
        elif carrier == NavPVT.CARRIER_PHASE_FLOAT:
            message.quality = 5
            message.fix_label = "RTK FLOAT"
            message.rtk_state = "RTK_FLOAT"
        elif pvt is not None and pvt.flags & NavPVT.FLAGS_DIFF_SOLN:
            message.quality = 2
            message.fix_label = "DGPS"
            message.rtk_state = "DGPS"
        elif message.fix:
            message.quality = 1
            message.fix_label = "GPS"
            message.rtk_state = "NO_RTK"
        else:
            message.quality = 0
            message.fix_label = "NO FIX"
            message.rtk_state = "NO_RTK"

        if pvt is not None:
            message.satellites = int(pvt.numSV)
            message.speed_mps = float(pvt.gSpeed) / 1000.0
            message.course_deg = float(pvt.heading) * 1e-5
            if not message.hacc_m or math.isnan(message.hacc_m):
                message.hacc_m = float(pvt.hAcc) / 1000.0
            message.pdop = float(pvt.pDOP) * 0.01
        else:
            message.satellites = 0
            message.speed_mps = 0.0
            message.course_deg = math.nan
            message.pdop = math.nan
        if self.dop_message is not None:
            message.hdop = float(self.dop_message.hDOP) * 0.01
            message.pdop = float(self.dop_message.pDOP) * 0.01
            message.vdop = float(self.dop_message.vDOP) * 0.01
        else:
            message.hdop = math.nan
            message.vdop = math.nan

        if self.ntrip_message is not None:
            message.correction_age_s = self.ntrip_message.correction_age_s
        else:
            message.correction_age_s = math.nan
        message.rtk_fallback_active = message.fix and message.rtk_state != "RTK_FIXED"
        message.health, message.health_reason = self._evaluate(message)
        self.publisher.publish(message)

    def _evaluate(self, message: GpsStatus) -> tuple[str, str]:
        if not message.connected:
            return "STALE", "GPS topic not updating"
        if not message.fix:
            return "NO_FIX", "GNSS fix unavailable"
        if message.age_s > self.stale_s:
            return "STALE", "GPS data stale"
        if message.satellites and message.satellites <= 5:
            return "BAD", "satellites <= 5"
        if math.isfinite(message.hdop) and message.hdop > 3.0:
            return "BAD", "HDOP > 3.0"
        if math.isfinite(message.hacc_m) and message.hacc_m > 3.0:
            return "BAD", "hAcc > 3 m"
        if message.satellites and message.satellites <= 7:
            return "WARNING", "satellites 6-7"
        if math.isfinite(message.hdop) and message.hdop > 2.0:
            return "WARNING", "HDOP > 2.0"
        return "GOOD", ""


if __name__ == "__main__":
    rospy.init_node("rcboat_gps_health")
    GpsHealthNode()
    rospy.spin()
