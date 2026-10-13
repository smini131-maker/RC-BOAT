#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import rospy
from std_msgs.msg import String
from std_srvs.srv import Trigger, TriggerResponse

from rcboat_ros.gps_logger import GpsCsvLogger
from rcboat_ros.msg import BoatState, GpsStatus, NavigationStatus, NtripStatus, RouteState


class GpsLoggerNode:
    def __init__(self) -> None:
        runtime = Path(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime"))
        self.logger = GpsCsvLogger(runtime / "logs" / "gps")
        self._lock = threading.Lock()
        self.gps = None
        self.ntrip = None
        self.nav = None
        self.route = None
        self.boat = None
        self.last_stamp = None
        self.state_pub = rospy.Publisher("/rcboat/gps/logging_state", String, queue_size=2, latch=True)
        rospy.Subscriber("/rcboat/gps/status", GpsStatus, self._gps_cb, queue_size=10)
        rospy.Subscriber("/rcboat/ntrip/status", NtripStatus, self._ntrip_cb, queue_size=10)
        rospy.Subscriber("/rcboat/navigation/status", NavigationStatus, self._nav_cb, queue_size=10)
        rospy.Subscriber("/rcboat/route/state", RouteState, self._route_cb, queue_size=10)
        rospy.Subscriber("/rcboat/safety/state", BoatState, self._boat_cb, queue_size=10)
        rospy.Service("/rcboat/gps/start_logging", Trigger, self._start)
        rospy.Service("/rcboat/gps/stop_logging", Trigger, self._stop)
        rospy.Timer(rospy.Duration(0.1), self._tick)
        rospy.on_shutdown(self.logger.close)

    def _gps_cb(self, msg):
        with self._lock: self.gps = msg

    def _ntrip_cb(self, msg):
        with self._lock: self.ntrip = msg

    def _nav_cb(self, msg):
        with self._lock: self.nav = msg

    def _route_cb(self, msg):
        with self._lock: self.route = msg

    def _boat_cb(self, msg):
        with self._lock: self.boat = msg

    def _publish_state(self) -> None:
        self.state_pub.publish(String(data=json.dumps(self.logger.state(), ensure_ascii=False)))

    def _start(self, _req):
        try:
            path = self.logger.start()
            self.last_stamp = None
            self._publish_state()
            return TriggerResponse(True, path)
        except Exception as exc:
            return TriggerResponse(False, str(exc))

    def _stop(self, _req):
        try:
            path = self.logger.stop()
            self._publish_state()
            return TriggerResponse(True, path)
        except Exception as exc:
            return TriggerResponse(False, str(exc))

    @staticmethod
    def _clean(value):
        return None if isinstance(value, float) and not math.isfinite(value) else value

    def _tick(self, _event) -> None:
        self._publish_state()
        if not self.logger.active:
            return
        with self._lock:
            gps, ntrip, nav, route, boat = self.gps, self.ntrip, self.nav, self.route, self.boat
        if gps is None:
            return
        stamp = gps.header.stamp.to_nsec()
        if stamp == self.last_stamp:
            return
        self.last_stamp = stamp
        self.logger.write({
            "utc_time": gps.utc_time,
            "latitude": self._clean(gps.latitude), "longitude": self._clean(gps.longitude),
            "altitude_m": self._clean(gps.altitude_m), "fix_quality": gps.fix_quality,
            "fix_label": gps.fix_label, "satellites": gps.satellites,
            "hdop": self._clean(gps.hdop), "pdop": self._clean(gps.pdop), "vdop": self._clean(gps.vdop),
            "speed_mps": self._clean(gps.speed_mps), "course_deg": self._clean(gps.course_deg),
            "cno_avg_dbhz": self._clean(gps.cno_avg_dbhz), "hacc_m": self._clean(gps.hacc_m),
            "rtk_state": gps.rtk_state,
            "rtk_correction_age_s": None if ntrip is None else self._clean(ntrip.last_correction_age_s),
            "gps_health": gps.health_status,
            "active_route_id": "" if route is None else route.active_route_id,
            "navigation_state": "" if boat is None else boat.operation_state,
            "utm_easting": self._clean(gps.utm_easting), "utm_northing": self._clean(gps.utm_northing),
            "utm_zone": gps.utm_zone,
        })


if __name__ == "__main__":
    rospy.init_node("gps_logger_node")
    GpsLoggerNode()
    rospy.spin()
