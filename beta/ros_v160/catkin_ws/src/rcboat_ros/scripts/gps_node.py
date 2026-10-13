#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import rospy
import serial
from sensor_msgs.msg import NavSatFix, NavSatStatus

from rcboat_ros.gps_health import GpsHealthThresholds, evaluate_gps_health
from rcboat_ros.gps_parser import MixedGpsParser
from rcboat_ros.msg import GpsStatus, Rtcm
from rcboat_ros.ros_utils import finite_or_nan
from rcboat_ros.srv import SetGpsSettings, SetGpsSettingsResponse


UBX_NAV_PVT_POLL = bytes.fromhex("B5 62 01 07 00 00 08 19")


class GpsNode:
    def __init__(self) -> None:
        self.device = rospy.get_param(
            "/rcboat/hardware/gps_device",
            "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00",
        )
        self.baudrate = int(rospy.get_param("/rcboat/hardware/gps_baudrate", 115200))
        self.reconnect_s = float(rospy.get_param("/rcboat/hardware/reconnect_interval_s", 1.0))
        self.frame_id = rospy.get_param("/rcboat/gps/frame_id", "gps")
        runtime = Path(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime"))
        self.settings_path = runtime / "gps_settings.json"
        self._load_saved_settings()
        self.stale_s = float(rospy.get_param("/rcboat/gps/health_stale_s", 2.0))
        self.poll_s = float(rospy.get_param("/rcboat/gps/nav_pvt_poll_interval_s", 1.0))
        self.parser = MixedGpsParser()
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._port = None
        self._connected = False
        self._error = "waiting for ZED-F9R"
        self._last_poll = 0.0
        self._stop = threading.Event()
        self.status_pub = rospy.Publisher("/rcboat/gps/status", GpsStatus, queue_size=10)
        self.fix_pub = rospy.Publisher("/fix", NavSatFix, queue_size=10)
        self.rtcm_sub = rospy.Subscriber("/rtcm", Rtcm, self._on_rtcm, queue_size=50)
        rospy.Service("/rcboat/gps/set_settings", SetGpsSettings, self._set_settings)
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        rospy.on_shutdown(self.close)

    def _load_saved_settings(self) -> None:
        try:
            values = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        allowed = {
            "health_stale_s", "navigation_max_hdop", "rtk_required_for_navigation",
            "rtk_fallback_to_gps", "rtk_correction_max_age_s",
        }
        for key in allowed:
            if key in values:
                rospy.set_param(f"/rcboat/gps/{key}", values[key])

    def _set_settings(self, req: SetGpsSettings.Request) -> SetGpsSettingsResponse:
        values = {
            "health_stale_s": float(req.health_stale_s),
            "navigation_max_hdop": float(req.navigation_max_hdop),
            "rtk_required_for_navigation": bool(req.rtk_required_for_navigation),
            "rtk_fallback_to_gps": bool(req.rtk_fallback_to_gps),
            "rtk_correction_max_age_s": float(req.rtk_correction_max_age_s),
        }
        try:
            if not 0.5 <= values["health_stale_s"] <= 30.0:
                raise ValueError("health_stale_s must be 0.5..30")
            if not 0.5 <= values["navigation_max_hdop"] <= 20.0:
                raise ValueError("navigation_max_hdop must be 0.5..20")
            if not 1.0 <= values["rtk_correction_max_age_s"] <= 120.0:
                raise ValueError("rtk_correction_max_age_s must be 1..120")
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_name(f".{self.settings_path.name}.tmp")
            temporary.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.settings_path)
            for key, value in values.items():
                rospy.set_param(f"/rcboat/gps/{key}", value)
            self.stale_s = values["health_stale_s"]
            return SetGpsSettingsResponse(True, "GPS settings saved")
        except Exception as exc:
            return SetGpsSettingsResponse(False, str(exc))

    def _disconnect(self, error: str) -> None:
        with self._io_lock:
            port, self._port = self._port, None
            if port is not None:
                try:
                    port.close()
                except Exception:
                    pass
        with self._lock:
            self._connected = False
            self._error = error

    def _read_loop(self) -> None:
        last_bytes = time.monotonic()
        while not self._stop.is_set() and not rospy.is_shutdown():
            if self._port is None:
                try:
                    candidate = serial.Serial(self.device, self.baudrate, timeout=0.2)
                    with self._io_lock:
                        self._port = candidate
                    with self._lock:
                        self._connected = True
                        self._error = ""
                    last_bytes = time.monotonic()
                except Exception as exc:
                    self._disconnect(f"GPS connect: {exc}")
                    self._stop.wait(self.reconnect_s)
                    continue
            try:
                with self._io_lock:
                    if self._port is None:
                        continue
                    chunk = self._port.read(512)
                    now = time.monotonic()
                    if now - self._last_poll >= self.poll_s:
                        self._port.write(UBX_NAV_PVT_POLL)
                        self._port.flush()
                        self._last_poll = now
                if not chunk:
                    if time.monotonic() - last_bytes > self.stale_s:
                        raise TimeoutError("GPS byte stream became stale")
                    continue
                last_bytes = time.monotonic()
                with self._lock:
                    self.parser.feed(chunk, last_bytes)
                    self._connected = True
                    self._error = ""
            except Exception as exc:
                self._disconnect(f"GPS read: {exc}")
                self._stop.wait(self.reconnect_s)

    def _on_rtcm(self, msg: Rtcm) -> None:
        data = bytes(msg.data)
        if not data:
            return
        try:
            with self._io_lock:
                if self._port is None:
                    raise ConnectionError("GPS serial port unavailable")
                self._port.write(data)
                self._port.flush()
        except Exception as exc:
            with self._lock:
                self._error = f"RTCM write: {exc}"

    def _messages(self) -> tuple[GpsStatus, NavSatFix | None]:
        with self._lock:
            data = self.parser.data.public()
            connected = self._connected
            error = self._error
        thresholds = GpsHealthThresholds(stale_s=self.stale_s)
        health = evaluate_gps_health(data, connected=connected, thresholds=thresholds)
        stamp = rospy.Time.now()
        status = GpsStatus()
        status.header.stamp = stamp
        status.header.frame_id = self.frame_id
        status.connected = connected
        status.fix = bool(data.get("fix"))
        status.fix_quality = int(data.get("fix_quality") or 0)
        status.fix_label = str(data.get("fix_label") or {
            0: "NO FIX", 1: "GPS", 2: "DGPS", 4: "RTK FIXED", 5: "RTK FLOAT",
        }.get(status.fix_quality, f"FIX {status.fix_quality}"))
        status.latitude = finite_or_nan(data.get("latitude"))
        status.longitude = finite_or_nan(data.get("longitude"))
        status.altitude_m = finite_or_nan(data.get("altitude_m"))
        status.satellites = int(data.get("satellites") or 0)
        for field in ("hdop", "pdop", "vdop", "cno_avg_dbhz", "hacc_m", "speed_mps", "course_deg"):
            setattr(status, field, finite_or_nan(data.get(field)))
        status.utc_time = str(data.get("utc_time") or "")
        status.age_s = float(health.get("age_s")) if health.get("age_s") is not None else float("inf")
        status.position_age_s = float(health.get("position_age_s")) if health.get("position_age_s") is not None else float("inf")
        status.health_status = str(health.get("status", "BAD"))
        status.navigation_status = str(health.get("navigation_status", "BAD"))
        reasons = list(health.get("reasons") or [])
        if error:
            reasons.append(error)
        status.health_reason = "; ".join(reasons)
        status.rtk_state = str(data.get("rtk_state") or "NO_RTK")
        status.rtk_fallback_active = bool(status.fix and status.rtk_state != "RTK_FIXED")
        status.navigation_fix_mode = status.rtk_state if status.rtk_state in {"RTK_FIXED", "RTK_FLOAT"} else "GPS"
        for field in ("parser_error_count", "nmea_sentence_count", "ubx_message_count", "nav_pvt_message_count"):
            setattr(status, field, int(data.get(field) or 0))
        status.utm_easting = finite_or_nan(data.get("utm_easting"))
        status.utm_northing = finite_or_nan(data.get("utm_northing"))
        status.utm_zone = str(data.get("utm_zone") or "")

        fix = None
        if status.fix and math.isfinite(status.latitude) and math.isfinite(status.longitude):
            fix = NavSatFix()
            fix.header = status.header
            fix.status.status = NavSatStatus.STATUS_FIX
            fix.status.service = NavSatStatus.SERVICE_GPS
            fix.latitude = status.latitude
            fix.longitude = status.longitude
            fix.altitude = status.altitude_m
            if math.isfinite(status.hacc_m):
                variance = status.hacc_m * status.hacc_m
                fix.position_covariance = [variance, 0.0, 0.0, 0.0, variance, 0.0, 0.0, 0.0, variance * 4.0]
                fix.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
        return status, fix

    def spin(self) -> None:
        rate = rospy.Rate(10)
        while not rospy.is_shutdown():
            status, fix = self._messages()
            self.status_pub.publish(status)
            if fix is not None:
                self.fix_pub.publish(fix)
            rate.sleep()

    def close(self) -> None:
        self._stop.set()
        self._disconnect("shutdown")
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)


if __name__ == "__main__":
    rospy.init_node("gps_node")
    GpsNode().spin()
