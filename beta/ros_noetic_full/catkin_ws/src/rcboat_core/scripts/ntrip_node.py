#!/usr/bin/env python3
from __future__ import annotations

import base64
import math
import socket
import ssl
import threading
import time

import rospy
from rcboat_core.ntrip_protocol import build_gga, load_env, pop_rtcm_frames
from rcboat_msgs.msg import GpsStatus, NtripStatus
from rtcm_msgs.msg import Message


class NtripNode:
    def __init__(self) -> None:
        self.env_path = rospy.get_param("~env_file")
        config = load_env(self.env_path)
        self.enabled = config.get("NTRIP_ENABLED", "false").lower() == "true"
        self.host = config.get("NTRIP_HOST", "")
        self.port = int(config.get("NTRIP_PORT", "2101"))
        self.mountpoint = config.get("NTRIP_MOUNTPOINT", "").lstrip("/")
        self.username = config.get("NTRIP_USERNAME", "")
        self.password = config.get("NTRIP_PASSWORD", "")
        self.use_tls = config.get("NTRIP_TLS", "false").lower() == "true"
        self.latest_gps = None
        self.bytes_received = 0
        self.reconnect_count = 0
        self.last_correction_at = 0.0
        self.last_error = ""
        self.connected = False
        self.stop_event = threading.Event()
        self.rtcm_pub = rospy.Publisher("/rtcm", Message, queue_size=100)
        self.status_pub = rospy.Publisher("/rcboat/ntrip_status", NtripStatus, queue_size=10)
        rospy.Subscriber("/rcboat/gps_status", GpsStatus, self.gps_callback, queue_size=10)
        rospy.Timer(rospy.Duration(0.5), self.publish_status)
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()
        rospy.on_shutdown(self.close)

    def gps_callback(self, message: GpsStatus) -> None:
        self.latest_gps = message

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.0)

    def publish_status(self, _event) -> None:
        message = NtripStatus()
        message.header.stamp = rospy.Time.now()
        message.enabled = self.enabled
        message.connected = self.connected
        message.bytes_received = self.bytes_received
        message.reconnect_count = self.reconnect_count
        message.correction_age_s = (
            time.monotonic() - self.last_correction_at
            if self.last_correction_at
            else math.inf
        )
        message.last_error = self.last_error
        self.status_pub.publish(message)

    def worker(self) -> None:
        if not self.enabled:
            return
        while not self.stop_event.is_set() and not rospy.is_shutdown():
            try:
                self.run_connection()
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                self.reconnect_count += 1
                rospy.logwarn("NTRIP reconnect: %s", exc)
            self.stop_event.wait(2.0)

    def run_connection(self) -> None:
        if not self.host or not self.mountpoint:
            raise RuntimeError("NTRIP host and mountpoint are required")
        sock = socket.create_connection((self.host, self.port), timeout=10.0)
        if self.use_tls:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        sock.settimeout(1.0)
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        request = (
            f"GET /{self.mountpoint} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Ntrip-Version: Ntrip/2.0\r\n"
            "User-Agent: NTRIP rcboat_ros_noetic/1.0\r\n"
            f"Authorization: Basic {token}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        header = self.read_response_header(sock)
        if b"200" not in header.split(b"\r\n", 1)[0]:
            raise RuntimeError(header.decode("ascii", errors="replace"))
        self.connected = True
        self.last_error = ""
        buffer = bytearray()
        last_gga = 0.0
        try:
            while not self.stop_event.is_set() and not rospy.is_shutdown():
                now = time.monotonic()
                gps = self.latest_gps
                if (
                    gps is not None
                    and gps.fix
                    and math.isfinite(gps.latitude)
                    and math.isfinite(gps.longitude)
                    and now - last_gga >= 5.0
                ):
                    sock.sendall(build_gga(gps.latitude, gps.longitude))
                    last_gga = now
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    raise ConnectionError("NTRIP caster closed connection")
                buffer.extend(chunk)
                self.bytes_received += len(chunk)
                self.publish_frames(buffer)
        finally:
            self.connected = False
            sock.close()

    def publish_frames(self, buffer: bytearray) -> None:
        for frame in pop_rtcm_frames(buffer):
            message = Message()
            message.header.stamp = rospy.Time.now()
            message.message = list(frame)
            self.rtcm_pub.publish(message)
            self.last_correction_at = time.monotonic()

    @staticmethod
    def read_response_header(sock) -> bytes:
        """Read both HTTP/NTRIP2 and legacy ICY/NTRIP1 response headers."""
        response = bytearray()
        while True:
            byte = sock.recv(1)
            if not byte:
                raise ConnectionError("NTRIP caster closed during response header")
            response.extend(byte)
            if response.startswith(b"ICY ") and response.endswith(b"\r\n"):
                return bytes(response[:-2])
            if b"\r\n\r\n" in response:
                return bytes(response).split(b"\r\n\r\n", 1)[0]
            if len(response) > 8192:
                raise RuntimeError("NTRIP response header too large")


if __name__ == "__main__":
    rospy.init_node("rcboat_ntrip")
    NtripNode()
    rospy.spin()
