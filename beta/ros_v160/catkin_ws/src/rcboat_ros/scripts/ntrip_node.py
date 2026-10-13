#!/usr/bin/env python3
from __future__ import annotations

import math
import threading
from pathlib import Path

import rospy

from rcboat_ros.msg import GpsStatus, NtripStatus, Rtcm
from rcboat_ros.ntrip import NtripClient, NtripConfig, build_gga, load_ntrip_env, save_ntrip_env
from rcboat_ros.srv import ConfigureNtrip, ConfigureNtripResponse
from std_srvs.srv import Trigger, TriggerResponse


class NtripNode:
    def __init__(self) -> None:
        runtime = Path(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime"))
        self.env_path = runtime / ".ntrip.env"
        self._lock = threading.Lock()
        self._gps = None
        self.rtcm_pub = rospy.Publisher("/rtcm", Rtcm, queue_size=100)
        self.status_pub = rospy.Publisher("/rcboat/ntrip/status", NtripStatus, queue_size=10, latch=True)
        rospy.Subscriber("/rcboat/gps/status", GpsStatus, self._on_gps, queue_size=10)
        self.client = self._new_client(load_ntrip_env(self.env_path))
        if self.client.config.enabled:
            try:
                self.client.start()
            except Exception as exc:
                rospy.logerr("NTRIP start failed: %s", exc)
        rospy.Service("/rcboat/ntrip/configure", ConfigureNtrip, self._configure)
        rospy.Service("/rcboat/ntrip/disable", Trigger, self._disable)
        rospy.Timer(rospy.Duration(0.5), self._publish_status)
        rospy.on_shutdown(self.close)

    def _on_gps(self, msg: GpsStatus) -> None:
        with self._lock:
            self._gps = msg

    def _write_rtcm(self, data: bytes) -> None:
        msg = Rtcm()
        msg.header.stamp = rospy.Time.now()
        msg.data = list(data)
        self.rtcm_pub.publish(msg)

    def _gga(self) -> bytes | None:
        with self._lock:
            gps = self._gps
        if gps is None or not gps.fix or not math.isfinite(gps.latitude) or not math.isfinite(gps.longitude):
            return None
        return build_gga(gps.latitude, gps.longitude, satellites=gps.satellites, hdop=gps.hdop if math.isfinite(gps.hdop) else 1.0)

    def _new_client(self, config: NtripConfig) -> NtripClient:
        return NtripClient(config, self._write_rtcm, self._gga)

    def _replace(self, config: NtripConfig) -> None:
        config.validate()
        self.client.stop()
        save_ntrip_env(self.env_path, config)
        self.client = self._new_client(config)
        if config.enabled:
            self.client.start()

    def _configure(self, req: ConfigureNtrip.Request) -> ConfigureNtripResponse:
        try:
            previous = self.client.config
            config = NtripConfig(
                enabled=req.enabled,
                host=req.host.strip() or previous.host,
                port=req.port or previous.port,
                mountpoint=req.mountpoint.strip().lstrip("/") or previous.mountpoint,
                username=req.username.strip() or previous.username,
                password=req.password or previous.password,
                tls=req.tls,
                timeout_s=req.timeout_s or previous.timeout_s,
                gga_interval_s=req.gga_interval_s or previous.gga_interval_s,
            )
            self._replace(config)
            rospy.loginfo("NTRIP configuration updated (password redacted)")
            return ConfigureNtripResponse(True, "NTRIP configuration updated")
        except Exception as exc:
            return ConfigureNtripResponse(False, str(exc))

    def _disable(self, _req: Trigger.Request) -> TriggerResponse:
        try:
            previous = self.client.config
            self._replace(NtripConfig(
                enabled=False, host=previous.host, port=previous.port,
                mountpoint=previous.mountpoint, username=previous.username,
                password=previous.password, tls=previous.tls,
                timeout_s=previous.timeout_s, gga_interval_s=previous.gga_interval_s,
            ))
            return TriggerResponse(True, "NTRIP disabled")
        except Exception as exc:
            return TriggerResponse(False, str(exc))

    def _publish_status(self, _event) -> None:
        data = self.client.status()
        msg = NtripStatus()
        msg.header.stamp = rospy.Time.now()
        msg.enabled = bool(data["enabled"])
        msg.connected = bool(data["connected"])
        msg.host = str(data["host"])
        msg.port = int(data["port"])
        msg.mountpoint = str(data["mountpoint"])
        msg.tls = bool(data["tls"])
        age = data["last_correction_age_s"]
        msg.last_correction_age_s = float(age) if age is not None else float("inf")
        msg.bytes_received = int(data["bytes_received"])
        msg.reconnect_count = int(data["reconnect_count"])
        msg.last_error = str(data["last_error"])
        self.status_pub.publish(msg)

    def close(self) -> None:
        self.client.stop()


if __name__ == "__main__":
    rospy.init_node("ntrip_node")
    NtripNode()
    rospy.spin()
