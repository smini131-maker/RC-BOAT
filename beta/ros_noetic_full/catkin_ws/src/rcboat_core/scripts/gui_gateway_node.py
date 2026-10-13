#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import socket
import threading
import time
from pathlib import Path
from typing import Any

import rospy
import yaml
from rcboat_msgs.msg import (
    BoatState,
    GpsLogStatus,
    GpsStatus,
    NtripStatus,
    PwmCommand,
)
from rcboat_msgs.srv import (
    ConfigureNtrip,
    SelectRoute,
    SetAutoCruise,
    SetGpsSettings,
    SetMode,
    SetMultipath,
    StartHil,
    StartRouteRecording,
)
from std_msgs.msg import Empty
from std_srvs.srv import Trigger


MAX_MESSAGE_BYTES = 1_048_576


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


class GuiGatewayNode:
    """SSH-tunnel-only JSON control surface backed exclusively by ROS APIs."""

    def __init__(self) -> None:
        self.bind_host = str(rospy.get_param("~bind_host", "127.0.0.1"))
        if self.bind_host not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("GUI gateway must bind to loopback only")
        self.port = int(rospy.get_param("~port", 8876))
        self.config_path = Path(rospy.get_param("~config_file"))
        self.routes_path = Path(rospy.get_param("~routes_file"))
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.started_at = time.monotonic()
        self.state: BoatState | None = None
        self.gps: GpsStatus | None = None
        self.ntrip: NtripStatus | None = None
        self.gps_log: GpsLogStatus | None = None
        family = socket.AF_INET6 if self.bind_host == "::1" else socket.AF_INET
        self.server = socket.socket(family, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.bind_host, self.port))
        self.server.listen(4)
        self.server.settimeout(0.5)
        self.clients: set[socket.socket] = set()
        self.remote_pub = rospy.Publisher("/rcboat/remote_pwm", PwmCommand, queue_size=1)
        self.heartbeat_pub = rospy.Publisher(
            "/rcboat/remote_heartbeat", Empty, queue_size=10
        )
        rospy.Subscriber("/rcboat/state", BoatState, self._state_callback, queue_size=10)
        rospy.Subscriber(
            "/rcboat/gps_status", GpsStatus, self._gps_callback, queue_size=10
        )
        rospy.Subscriber(
            "/rcboat/ntrip_status", NtripStatus, self._ntrip_callback, queue_size=10
        )
        rospy.Subscriber(
            "/rcboat/gps_log_status",
            GpsLogStatus,
            self._gps_log_callback,
            queue_size=10,
        )
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        rospy.on_shutdown(self.close)

    def _state_callback(self, message: BoatState) -> None:
        with self.lock:
            self.state = message

    def _gps_callback(self, message: GpsStatus) -> None:
        with self.lock:
            self.gps = message

    def _ntrip_callback(self, message: NtripStatus) -> None:
        with self.lock:
            self.ntrip = message

    def _gps_log_callback(self, message: GpsLogStatus) -> None:
        with self.lock:
            self.gps_log = message

    def close(self) -> None:
        self.stop_event.set()
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.close()
            except OSError:
                pass
        self.thread.join(timeout=2.0)

    def _serve(self) -> None:
        server = self.server
        rospy.loginfo("ROS GUI gateway listening on %s:%d", self.bind_host, self.port)
        while not self.stop_event.is_set() and not rospy.is_shutdown():
            try:
                client, _address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(0.1)
            with self.lock:
                self.clients.add(client)
            threading.Thread(
                target=self._client_loop, args=(client,), daemon=True
            ).start()

    def _client_loop(self, client: socket.socket) -> None:
        buffer = bytearray()
        next_telemetry = 0.0
        try:
            while not self.stop_event.is_set() and not rospy.is_shutdown():
                now = time.monotonic()
                if now >= next_telemetry:
                    self._send(client, self.telemetry())
                    next_telemetry = now + 0.1
                try:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                except socket.timeout:
                    pass
                if len(buffer) > MAX_MESSAGE_BYTES:
                    raise ValueError("message exceeded safety limit")
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if not raw:
                        continue
                    try:
                        request = json.loads(raw.decode("utf-8"))
                        response = self.execute(request)
                    except Exception as exc:
                        response = {
                            "type": "ack",
                            "request_id": "",
                            "command": "UNKNOWN",
                            "ok": False,
                            "error": str(exc),
                        }
                    self._send(client, response)
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                self.clients.discard(client)
            try:
                client.close()
            except OSError:
                pass

    @staticmethod
    def _send(client: socket.socket, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(json_safe(payload), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        client.sendall(encoded)

    @staticmethod
    def _service(name: str, service_type, *args):
        rospy.wait_for_service(name, timeout=2.0)
        return rospy.ServiceProxy(name, service_type)(*args)

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise ValueError("command must be an object")
        command = str(request.get("command", "")).upper()
        request_id = str(request.get("request_id", ""))
        try:
            message = self._execute_command(command, request)
            return {
                "type": "ack",
                "request_id": request_id,
                "command": command,
                "ok": True,
                "message": message,
            }
        except Exception as exc:
            return {
                "type": "ack",
                "request_id": request_id,
                "command": command,
                "ok": False,
                "error": str(exc),
            }

    @staticmethod
    def _checked(response) -> str:
        success = bool(getattr(response, "success", False))
        message = str(getattr(response, "message", ""))
        if not success:
            raise RuntimeError(message or "ROS service rejected the request")
        return message

    def _execute_command(self, command: str, request: dict[str, Any]) -> str:
        if command == "SET_MODE":
            return self._checked(
                self._service("/rcboat/set_mode", SetMode, str(request["mode"]))
            )
        if command == "EMERGENCY_STOP":
            return self._checked(
                self._service("/rcboat/emergency_stop", Trigger)
            )
        if command == "CLEAR_ESTOP":
            return self._checked(self._service("/rcboat/clear_estop", Trigger))
        if command == "HEARTBEAT":
            self.heartbeat_pub.publish(Empty())
            return "heartbeat"
        if command == "REMOTE_CONTROL":
            message = PwmCommand()
            message.header.stamp = rospy.Time.now()
            message.steering_pwm = int(request["steering_pwm"])
            message.throttle_pwm = int(request["throttle_pwm"])
            message.source = "windows_gui"
            self.remote_pub.publish(message)
            return "remote PWM published"
        if command == "SELECT_ROUTE":
            return self._checked(
                self._service(
                    "/rcboat/select_route", SelectRoute, str(request["route_id"])
                )
            )
        if command == "SET_AUTO_CRUISE_PWM":
            return self._checked(
                self._service(
                    "/rcboat/set_auto_cruise",
                    SetAutoCruise,
                    int(request["value"]),
                )
            )
        if command == "SET_MULTIPATH":
            return self._checked(
                self._service(
                    "/rcboat/set_multipath",
                    SetMultipath,
                    bool(request["enabled"]),
                    float(request["endpoint_tolerance_m"]),
                    float(request["off_route_distance_m"]),
                    float(request["off_route_hold_s"]),
                    float(request["closer_advantage_m"]),
                    float(request["switch_cooldown_s"]),
                )
            )
        if command == "START_GPS_RECORDING":
            return self._checked(
                self._service(
                    "/rcboat/start_route_recording",
                    StartRouteRecording,
                    str(request["name"]),
                    float(request["minimum_distance_m"]),
                    float(request["minimum_interval_s"]),
                    float(request["arrival_radius_m"]),
                )
            )
        if command == "STOP_GPS_RECORDING":
            return self._checked(
                self._service("/rcboat/stop_route_recording", Trigger)
            )
        if command == "CANCEL_GPS_RECORDING":
            return self._checked(
                self._service("/rcboat/cancel_route_recording", Trigger)
            )
        if command == "RELOAD_ROUTES":
            return self._checked(self._service("/rcboat/reload_routes", Trigger))
        if command == "START_GPS_LOGGING":
            return self._checked(
                self._service("/rcboat/start_gps_logging", Trigger)
            )
        if command == "STOP_GPS_LOGGING":
            return self._checked(self._service("/rcboat/stop_gps_logging", Trigger))
        if command == "START_HIL":
            return self._checked(
                self._service(
                    "/rcboat/start_hil", StartHil, str(request.get("route_id", ""))
                )
            )
        if command == "STOP_HIL":
            return self._checked(self._service("/rcboat/stop_hil", Trigger))
        if command == "SET_GPS_SETTINGS":
            return self._checked(
                self._service(
                    "/rcboat/set_gps_settings",
                    SetGpsSettings,
                    float(request["navigation_max_hdop"]),
                    bool(request["rtk_required_for_navigation"]),
                    bool(request["rtk_fallback_to_gps"]),
                    float(request.get("rtk_correction_max_age_s", 10.0)),
                )
            )
        if command in {"CONFIGURE_NTRIP", "DISABLE_NTRIP"}:
            enabled = bool(request.get("enabled", False)) and command != "DISABLE_NTRIP"
            return self._checked(
                self._service(
                    "/rcboat/configure_ntrip",
                    ConfigureNtrip,
                    enabled,
                    str(request.get("host", "")),
                    int(request.get("port", 2101)),
                    str(request.get("mountpoint", "")),
                    str(request.get("username", "")),
                    str(request.get("password", "")),
                    bool(request.get("tls", False)),
                )
            )
        if command == "REFRESH_NTRIP":
            return "status refresh requested"
        raise ValueError(f"unsupported ROS GUI command: {command}")

    def _read_files(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, TypeError):
            config = {}
        try:
            routes = json.loads(self.routes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            routes = {"routes": [], "selected_route_id": ""}
        return config, routes

    def telemetry(self) -> dict[str, Any]:
        with self.lock:
            state, gps, ntrip, gps_log = self.state, self.gps, self.ntrip, self.gps_log
        config, route_file = self._read_files()
        routes = route_file.get("routes", [])
        names = {str(item.get("id")): str(item.get("name", item.get("id", ""))) for item in routes}
        if state is None:
            return {
                "type": "telemetry",
                "timestamp": time.time(),
                "mode": "MANUAL",
                "operation_state": "ROS_WAITING_STATE",
                "failsafe_reason": "ROS_STATE_UNAVAILABLE",
                "devices": {"arduino": False, "gps": False, "pca9685": False},
                "gps": {"fix": False},
                "rc": {},
                "pca": {"steering_pwm": 6000, "throttle_pwm": 6450},
                "routes": routes,
            }
        gps_health = gps.health if gps is not None else "UNKNOWN"
        gps_reason = gps.health_reason if gps is not None else ""
        active_id = state.active_route_id
        selected_id = state.selected_route_id
        gps_values = {
            "connected": bool(gps.connected) if gps else False,
            "fix": bool(gps.fix) if gps else False,
            "quality": int(gps.quality) if gps else 0,
            "fix_label": gps.fix_label if gps else "NO FIX",
            "lat": gps.latitude if gps else None,
            "lon": gps.longitude if gps else None,
            "altitude_m": gps.altitude_m if gps else None,
            "satellites": int(gps.satellites) if gps else 0,
            "hdop": gps.hdop if gps else None,
            "pdop": gps.pdop if gps else None,
            "vdop": gps.vdop if gps else None,
            "hacc_m": gps.hacc_m if gps else None,
            "speed_mps": gps.speed_mps if gps else None,
            "course_deg": gps.course_deg if gps else None,
            "age_s": gps.age_s if gps else None,
            "last_fix_age_s": gps.age_s if gps else None,
            "rtk_state": gps.rtk_state if gps else "NO_RTK",
            "rtk_fallback_active": bool(gps.rtk_fallback_active) if gps else False,
            "health": {
                "status": gps_health,
                "navigation_status": gps_health,
                "reasons": [gps_reason] if gps_reason else [],
            },
        }
        ntrip_values = {
            "enabled": bool(ntrip.enabled) if ntrip else False,
            "connected": bool(ntrip.connected) if ntrip else False,
            "host": ntrip.host if ntrip else "",
            "port": int(ntrip.port) if ntrip else 2101,
            "mountpoint": ntrip.mountpoint if ntrip else "",
            "tls": bool(ntrip.tls) if ntrip else False,
            "bytes_received": int(ntrip.bytes_received) if ntrip else 0,
            "reconnect_count": int(ntrip.reconnect_count) if ntrip else 0,
            "last_correction_age_s": ntrip.correction_age_s if ntrip else None,
            "last_error": ntrip.last_error if ntrip else "",
        }
        multipath = dict(config.get("multipath", {}))
        gps_config = dict(config.get("gps", {}))
        return {
            "type": "telemetry",
            "timestamp": time.time(),
            "uptime_s": round(time.monotonic() - self.started_at, 1),
            "mode": state.mode,
            "operation_state": "HIL_ACTIVE" if state.hil_active else state.operation_state,
            "navigation_active": bool(state.navigation_active),
            "estop": bool(state.estop),
            "failsafe_reason": state.failsafe_reason,
            "manual_waiting_for_neutral": bool(state.manual_waiting_for_neutral),
            "auto_cruise_pwm": int(state.auto_cruise_pwm),
            "mock": bool(state.mock),
            "devices": {
                "arduino": bool(state.arduino_connected),
                "gps": bool(state.gps_connected),
                "pca9685": bool(state.pca_connected),
            },
            "rc": {
                "steering_us": int(state.rc_steering_us),
                "throttle_us": int(state.rc_throttle_us),
            },
            "pca": {
                "frequency_hz": 60,
                "steering_channel": 0,
                "throttle_channel": 6,
                "steering_pwm": int(state.steering_pwm),
                "throttle_pwm": int(state.throttle_pwm),
            },
            "gps": gps_values,
            "ntrip": ntrip_values,
            "gps_settings": gps_config,
            "gps_logging": {
                "active": bool(gps_log.active) if gps_log else False,
                "samples": int(gps_log.samples) if gps_log else 0,
                "file_path": gps_log.file_path if gps_log else "",
            },
            "gps_recording": {
                "active": bool(state.route_recording),
                "name": state.recording_name,
                "point_count": int(state.recorded_point_count),
            },
            "hil": {
                "active": bool(state.hil_active),
                "lat": state.hil_latitude,
                "lon": state.hil_longitude,
                "course_deg": state.hil_course_deg,
            },
            "route": {
                "selected_route_id": selected_id,
                "selected_route_name": names.get(selected_id, selected_id),
                "active_route_id": active_id,
                "active_route_name": names.get(active_id, active_id),
                "persisted_selected_route_id": route_file.get("selected_route_id", ""),
                "selected_route_persisted": selected_id
                == route_file.get("selected_route_id", ""),
                "storage_path": str(self.routes_path),
                "multipath_config_path": str(self.config_path),
                "waypoint_index": int(state.waypoint_index),
                "waypoint_count": int(state.waypoint_count),
                "distance_to_waypoint_m": state.distance_to_waypoint_m,
                "distance_to_route_m": state.distance_to_route_m,
                "route_complete": bool(state.route_complete),
                "load_error": "",
                "multipath": multipath,
                "multipath_group_route_ids": [],
                "off_route_duration_s": 0.0,
            },
            "routes": routes,
            "hardware_errors": [],
            "events": [],
        }


if __name__ == "__main__":
    rospy.init_node("rcboat_gui_gateway")
    GuiGatewayNode()
    rospy.spin()