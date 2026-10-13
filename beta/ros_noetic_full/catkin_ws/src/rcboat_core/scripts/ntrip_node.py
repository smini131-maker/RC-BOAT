#!/usr/bin/env python3
from __future__ import annotations

import base64
import math
import os
import socket
import ssl
import threading
import time
from pathlib import Path

import rospy
from rcboat_core.ntrip_protocol import build_gga, load_env, pop_rtcm_frames
from rcboat_msgs.msg import GpsStatus, NtripStatus
from rcboat_msgs.srv import ConfigureNtrip, ConfigureNtripResponse
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
        self.wake_event = threading.Event()
        self.config_lock = threading.RLock()
        self.active_socket = None
        self.rtcm_pub = rospy.Publisher("/rtcm", Message, queue_size=100)
        self.status_pub = rospy.Publisher("/rcboat/ntrip_status", NtripStatus, queue_size=10)
        rospy.Subscriber("/rcboat/gps_status", GpsStatus, self.gps_callback, queue_size=10)
        rospy.Service("/rcboat/configure_ntrip", ConfigureNtrip, self.configure)
        rospy.Timer(rospy.Duration(0.5), self.publish_status)
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()
        rospy.on_shutdown(self.close)

    def gps_callback(self, message: GpsStatus) -> None:
        self.latest_gps = message

    def close(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        self._close_active_socket()
        self.thread.join(timeout=3.0)

    def publish_status(self, _event=None) -> None:
        message = NtripStatus()
        message.header.stamp = rospy.Time.now()
        message.enabled = self.enabled
        message.connected = self.connected
        message.host = self.host
        message.port = self.port
        message.mountpoint = self.mountpoint
        message.tls = self.use_tls
        message.bytes_received = self.bytes_received
        message.reconnect_count = self.reconnect_count
        message.correction_age_s = (
            time.monotonic() - self.last_correction_at
            if self.last_correction_at
            else math.inf
        )
        message.last_error = self.last_error
        self.status_pub.publish(message)

    @staticmethod
    def _clean(value: str, name: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{name} contains a line break")
        return value.strip()

    def configure(self, request) -> ConfigureNtripResponse:
        try:
            host = self._clean(request.host, "host")
            mountpoint = self._clean(request.mountpoint, "mountpoint").lstrip("/")
            username = self._clean(request.username, "username")
            password = request.password
            if "\n" in password or "\r" in password:
                raise ValueError("password contains a line break")
            port = int(request.port or self.port)
            if not 1 <= port <= 65535:
                raise ValueError("port must be 1..65535")
            if request.enabled and (not host or not mountpoint):
                raise ValueError("enabled NTRIP requires host and mountpoint")
            with self.config_lock:
                self.enabled = bool(request.enabled)
                if host:
                    self.host = host
                if mountpoint:
                    self.mountpoint = mountpoint
                if username:
                    self.username = username
                if password:
                    self.password = password
                self.port = port
                self.use_tls = bool(request.tls)
                self._save_config()
                self.last_error = ""
            self._close_active_socket()
            self.wake_event.set()
            self.publish_status()
            return ConfigureNtripResponse(True, "saved")
        except (OSError, ValueError) as exc:
            return ConfigureNtripResponse(False, str(exc))

    def _save_config(self) -> None:
        path = Path(self.env_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            "\n".join(
                [
                    f"NTRIP_ENABLED={'true' if self.enabled else 'false'}",
                    f"NTRIP_HOST={self.host}",
                    f"NTRIP_PORT={self.port}",
                    f"NTRIP_MOUNTPOINT={self.mountpoint}",
                    f"NTRIP_USERNAME={self.username}",
                    f"NTRIP_PASSWORD={self.password}",
                    f"NTRIP_TLS={'true' if self.use_tls else 'false'}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    def _close_active_socket(self) -> None:
        with self.config_lock:
            sock = self.active_socket
            self.active_socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def worker(self) -> None:
        while not self.stop_event.is_set() and not rospy.is_shutdown():
            if not self.enabled:
                self.connected = False
                self.wake_event.wait(1.0)
                self.wake_event.clear()
                continue
            try:
                self.run_connection()
            except Exception as exc:
                self.connected = False
                if self.enabled and not self.stop_event.is_set():
                    self.last_error = str(exc)
                    self.reconnect_count += 1
                    rospy.logwarn("NTRIP reconnect: %s", exc)
            self.wake_event.wait(2.0)
            self.wake_event.clear()

    def run_connection(self) -> None:
        with self.config_lock:
            host = self.host
            port = self.port
            mountpoint = self.mountpoint
            username = self.username
            password = self.password
            use_tls = self.use_tls
        if not host or not mountpoint:
            raise RuntimeError("NTRIP host and mountpoint are required")
        sock = socket.create_connection((host, port), timeout=10.0)
        if use_tls:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        with self.config_lock:
            self.active_socket = sock
        sock.settimeout(1.0)
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        request = (
            f"GET /{mountpoint} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
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
            with self.config_lock:
                if self.active_socket is sock:
                    self.active_socket = None
            try:
                sock.close()
            except OSError:
                pass

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