#!/usr/bin/env python3
from __future__ import annotations

import csv
import time
from pathlib import Path

import rospy
from rcboat_msgs.msg import GpsLogStatus, GpsStatus
from std_srvs.srv import Trigger, TriggerResponse


class GpsLoggerNode:
    def __init__(self) -> None:
        self.log_dir = Path(rospy.get_param("~log_dir"))
        self.handle = None
        self.writer = None
        self.path = ""
        self.samples = 0
        self.status_pub = rospy.Publisher(
            "/rcboat/gps_log_status", GpsLogStatus, queue_size=1, latch=True
        )
        rospy.Subscriber("/rcboat/gps_status", GpsStatus, self.callback, queue_size=100)
        rospy.Service("/rcboat/start_gps_logging", Trigger, self.start)
        rospy.Service("/rcboat/stop_gps_logging", Trigger, self.stop)
        rospy.on_shutdown(self.close)
        self.publish_status()

    def publish_status(self) -> None:
        message = GpsLogStatus()
        message.header.stamp = rospy.Time.now()
        message.active = self.handle is not None
        message.samples = self.samples
        message.file_path = self.path
        self.status_pub.publish(message)

    def start(self, _request) -> TriggerResponse:
        if self.handle is not None:
            return TriggerResponse(False, "GPS logging already active")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = str(self.log_dir / time.strftime("gps_%Y%m%d_%H%M%S.csv"))
        self.samples = 0
        self.handle = open(self.path, "w", encoding="utf-8-sig", newline="")
        fields = [
            "ros_time", "latitude", "longitude", "altitude_m", "fix_quality",
            "fix_label", "satellites", "hdop", "pdop", "vdop", "hacc_m",
            "speed_mps", "course_deg", "health", "rtk_state",
            "correction_age_s",
        ]
        self.writer = csv.DictWriter(self.handle, fieldnames=fields)
        self.writer.writeheader()
        self.handle.flush()
        self.publish_status()
        return TriggerResponse(True, self.path)

    def stop(self, _request) -> TriggerResponse:
        if self.handle is None:
            return TriggerResponse(False, "GPS logging is not active")
        path = self.path
        self.close()
        self.publish_status()
        return TriggerResponse(True, path)

    def close(self) -> None:
        if self.handle is not None:
            self.handle.flush()
            self.handle.close()
        self.handle = None
        self.writer = None

    def callback(self, message: GpsStatus) -> None:
        if self.writer is None or self.handle is None:
            return
        self.writer.writerow(
            {
                "ros_time": message.header.stamp.to_sec(),
                "latitude": message.latitude,
                "longitude": message.longitude,
                "altitude_m": message.altitude_m,
                "fix_quality": message.quality,
                "fix_label": message.fix_label,
                "satellites": message.satellites,
                "hdop": message.hdop,
                "pdop": message.pdop,
                "vdop": message.vdop,
                "hacc_m": message.hacc_m,
                "speed_mps": message.speed_mps,
                "course_deg": message.course_deg,
                "health": message.health,
                "rtk_state": message.rtk_state,
                "correction_age_s": message.correction_age_s,
            }
        )
        self.samples += 1
        self.handle.flush()
        self.publish_status()


if __name__ == "__main__":
    rospy.init_node("rcboat_gps_logger")
    GpsLoggerNode()
    rospy.spin()