from __future__ import annotations

import base64
import codecs
import hashlib
import json
import queue
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import paramiko
from PySide6.QtCore import QThread, Signal


REMOTE_BRIDGE = r'''p=/home/jetson/rcboat_ros_ws/deployment/jetson/bridge_client.py
[ -f "$p" ] && exec python3 "$p"
printf '{"success":false,"error":"ROS bridge_client.py not found"}\n'
exit 1'''

def host_key_fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def clean_terminal_output(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, worker: "SSHWorker"):
        self.worker = worker

    def missing_host_key(self, client, hostname, key) -> None:
        if not self.worker.confirm_unknown_host_key(hostname, key):
            raise paramiko.SSHException("알 수 없는 SSH 호스트 키를 승인하지 않았습니다")
        client.get_host_keys().add(hostname, key.get_name(), key)
        self.worker.save_host_keys(client)


class SSHWorker(QThread):
    """ROS gateway worker with an independent, optional SSH management channel."""

    connected = Signal()
    disconnected = Signal(str)
    telemetry = Signal(dict)
    acknowledgement = Signal(dict)
    log = Signal(str)
    host_key_confirmation = Signal(str, str, str)
    terminal_output = Signal(str)
    terminal_state = Signal(bool, str)

    def __init__(self, host: str, port: int, username: str, password: str, known_hosts_path=None,
                 gateway_port: int = 8765, gateway_token: str = ""):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.gateway_port = int(gateway_port)
        self.gateway_token = gateway_token
        self.known_hosts_path = Path(known_hosts_path or Path.home() / ".ssh" / "known_hosts")
        self._commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self._terminal_commands: queue.Queue[bytes] = queue.Queue()
        self._stop_requested = False
        self._client: paramiko.SSHClient | None = None
        self._shell_channel = None
        self._host_key_event = threading.Event()
        self._host_key_accepted = False
        self._backend_error = ""
        self._backend_error_at = 0.0

    def send_command(self, command: str, **kwargs: Any) -> str:
        request_id = uuid.uuid4().hex[:12]
        self._commands.put({"command": command, "request_id": request_id, **kwargs})
        return request_id

    def send_terminal_input(self, text: str) -> None:
        self._terminal_commands.put((text if text.endswith("\n") else text + "\n").encode())

    def interrupt_terminal(self) -> None:
        self._terminal_commands.put(b"\x03")

    def stop(self) -> None:
        self._stop_requested = True
        self._host_key_event.set()
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def respond_to_host_key(self, accepted: bool) -> None:
        self._host_key_accepted = bool(accepted)
        self._host_key_event.set()

    def confirm_unknown_host_key(self, hostname: str, key: paramiko.PKey) -> bool:
        self._host_key_accepted = False
        self._host_key_event.clear()
        self.host_key_confirmation.emit(hostname, key.get_name(), host_key_fingerprint(key))
        return self._host_key_event.wait(60.0) and self._host_key_accepted

    def save_host_keys(self, client: paramiko.SSHClient) -> None:
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        client.save_host_keys(str(self.known_hosts_path))

    @staticmethod
    def _translate(request: dict[str, Any]) -> dict[str, Any]:
        command = str(request["command"]).upper()
        kwargs = {k: v for k, v in request.items() if k not in {"command", "request_id"}}
        direct = {
            "REMOTE_CONTROL": "set_remote_pwm", "HEARTBEAT": "heartbeat",
            "EMERGENCY_STOP": "estop", "CLEAR_ESTOP": "reset_estop",
            "SELECT_ROUTE": "select_route", "DELETE_ROUTE": "delete_route",
            "UPSERT_ROUTE": "upsert_route",
            "SELECT_MULTIPATH": "select_multipath", "UPSERT_MULTIPATH": "upsert_multipath",
            "DELETE_MULTIPATH": "delete_multipath", "COMPATIBLE_ROUTES": "compatible_routes",
            "RELOAD_ROUTES": "list_routes", "STOP_GPS_RECORDING": "record_stop",
            "CANCEL_GPS_RECORDING": "record_cancel", "CONFIGURE_NTRIP": "configure",
            "SET_GPS_SETTINGS": "set_gps_settings", "START_GPS_LOGGING": "gps_log_start",
            "STOP_GPS_LOGGING": "gps_log_stop", "GROUND_TEST_START": "ground_start",
            "GROUND_TEST_STOP": "ground_stop",
        }
        if command == "SET_MODE":
            mode = str(kwargs.get("mode", "AUTO")).upper()
            return {"action": "set_mode", "arguments": {
                "mode": mode,
                "armed": mode == "NAVIGATION",
            }}
        if command == "START_GPS_RECORDING":
            return {"action": "record_start", "arguments": kwargs}
        if command == "SET_MULTIPATH":
            return {"action": "set_multipath", "arguments": {
                "enabled": kwargs.get("enabled", True),
                "endpoint_tolerance_m": kwargs.get("endpoint_tolerance_m", 0.75),
                "switch_threshold_m": kwargs.get("switch_threshold_m", 2.0),
            }}
        if command == "SET_AUTO_CRUISE_PWM":
            return {"action": "set_auto_cruise_pwm", "arguments": {"value": kwargs.get("value")}}
        if command == "DISABLE_NTRIP":
            return {"action": "configure", "arguments": {"enabled": False}}
        if command == "REFRESH_NTRIP":
            return {"action": "status", "arguments": {}}
        if command in direct:
            return {"action": direct[command], "arguments": kwargs}
        raise ValueError(f"ROS에서 지원하지 않는 명령: {command}")

    def _ssh_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise ConnectionError("SSH fallback unavailable")
        stdin, stdout, stderr = self._client.exec_command(REMOTE_BRIDGE, timeout=9)
        stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        raw = stdout.read(250_000_000).decode("utf-8", errors="replace").strip()
        error = stderr.read(16_000).decode("utf-8", errors="replace").strip()
        if not raw:
            raise RuntimeError(error or "ROS bridge 응답이 없습니다")
        try:
            return json.loads(raw.splitlines()[-1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(raw[-500:]) from exc

    def _bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Talk directly to the ROS gateway; this path never depends on SSH."""
        request = dict(payload)
        if self.gateway_token:
            request["token"] = self.gateway_token
        try:
            with socket.create_connection((self.host, self.gateway_port), timeout=3.0) as connection:
                connection.settimeout(15.0)
                connection.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
                data = b""
                while not data.endswith(b"\n"):
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > 250_000_000:
                        raise RuntimeError("ROS gateway response exceeds 250 MB")
            if not data:
                raise RuntimeError("ROS gateway returned no data")
            return json.loads(data.decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as direct_error:
            # Compatibility fallback for installations not yet exposing the LAN gateway.
            if self._client is not None:
                try:
                    return self._ssh_bridge(payload)
                except Exception:
                    pass
            raise ConnectionError(f"ROS gateway offline: {direct_error}") from direct_error

    @staticmethod
    def _normalize(response: dict[str, Any], ssh_connected: bool = False) -> dict[str, Any]:
        cache = response.get("telemetry") or {}
        gps = cache.get("gps") or {}
        rc = cache.get("rc") or {}
        route = cache.get("route") or {}
        nav = cache.get("navigation") or {}
        safety = cache.get("safety") or {}
        actuator = cache.get("actuator") or {}
        ntrip = cache.get("ntrip") or {}
        ground = cache.get("ground_test") or {}
        nodes = set(response.get("nodes") or [])
        routes = route.get("routes") or []
        multipaths = route.get("multipaths") or []
        by_id = {str(item.get("id")): item for item in routes}
        selected_id = str(route.get("selected_route_id") or "")
        active_id = str(route.get("active_route_id") or selected_id)
        selected = by_id.get(selected_id, {})
        active = by_id.get(active_id, selected)
        ros_mode = str(safety.get("mode") or "AUTO_SAFE")
        mode = "AUTO" if ros_mode == "AUTO_SAFE" else ros_mode
        fix = bool(gps.get("fix"))
        healthy = bool(gps.get("healthy", fix))
        rtk_state = str(gps.get("rtk_state") or ("NO_RTK" if gps else "no_data"))
        gps_health = "GOOD" if healthy and fix else "NO_FIX" if not fix else "WARNING"
        group_ids = list(route.get("group_routes") or [])
        multipath = route.get("multipath") or {
            "enabled": True, "endpoint_tolerance_m": route.get("endpoint_tolerance_m", 0.75),
            "switch_threshold_m": 2.0,
            "switch_rule": "active_target_distance_gt_threshold_then_nearest",
            "off_route_gate": False, "priority_gate": False, "cooldown_gate": False,
        }
        logger_state = str(ground.get("state") or ("recording" if ground.get("active") else "idle"))
        return {
            "type": "telemetry", "software_version": response.get("version", "2.1.4"),
            "backend": {"name": str(response.get("backend") or "ROS Noetic"),
                        "ready": bool(response.get("gateway_online", True)), "node_count": len(nodes),
                        "master_online": bool(response.get("master_online")),
                        "gateway_online": bool(response.get("gateway_online", True)),
                        "ssh_connected": bool(ssh_connected), "logger_state": logger_state},
            "timestamp": time.time(), "mode": mode, "operation_state": ros_mode,
            "navigation_active": ros_mode == "NAVIGATION" and bool(safety.get("armed")),
            "estop": bool(safety.get("estop")), "failsafe_reason": safety.get("reason") or "",
            "manual_waiting_for_neutral": False,
            "auto_cruise_pwm": int(nav.get("auto_cruise_pwm") or 6650), "mock": False,
            "devices": {"arduino": bool(rc) or "/rc_input_node" in nodes,
                        "gps": bool(gps) or "/gps_node" in nodes,
                        "pca9685": bool(actuator) or "/actuator_node" in nodes},
            "rc": {"steering_us": rc.get("steering_us"), "throttle_us": rc.get("throttle_us"), "age_s": rc.get("age_s")},
            "pca": {"frequency_hz": 60, "steering_channel": 0, "throttle_channel": 6,
                    "steering_pwm": actuator.get("actual_steering_pwm"),
                    "throttle_pwm": actuator.get("actual_throttle_pwm")},
            "gps": {"fix": fix, "quality": gps.get("quality"),
                    "fix_label": gps.get("fix_label") or (rtk_state if fix else "NO FIX"),
                    "lat": gps.get("latitude"), "lon": gps.get("longitude"),
                    "altitude_m": gps.get("altitude_m"), "satellites": gps.get("satellites"),
                    "hdop": gps.get("hdop"), "pdop": gps.get("pdop"), "vdop": gps.get("vdop"),
                    "cno_avg_dbhz": gps.get("cno_dbhz"), "hacc_m": gps.get("hacc_m"),
                    "speed_mps": gps.get("speed_mps"), "course_deg": gps.get("heading_deg"),
                    "utc_time": gps.get("measurement_time_utc") or gps.get("utc_time"),
                    "utc_status": gps.get("utc_status") or ("valid" if gps.get("utc_time") else "no_data"),
                    "age_s": gps.get("gps_data_age_s", gps.get("age_s")),
                    "data_validity": gps.get("data_validity") or "no_data",
                    "last_fix_age_s": gps.get("age_s"), "rtk_state": rtk_state,
                    "rtk_fallback_active": fix and rtk_state not in {"RTK_FIXED", "RTK_FLOAT"},
                    "navigation_fix_mode": rtk_state if fix else "NO_FIX",
                    "health": {"status": gps_health, "navigation_status": gps_health,
                               "rtk_status": "GOOD" if rtk_state == "RTK_FIXED" else "UNAVAILABLE",
                               "reasons": [str(gps.get("diagnostic") or ("GPS 정상" if healthy else "GPS FIX 대기"))]},
                    "utm_easting": gps.get("utm_easting_m"), "utm_northing": gps.get("utm_northing_m"),
                    "utm_zone": gps.get("utm_zone"), "utm_status": gps.get("utm_status") or "no_data",
                    "heading_source": gps.get("heading_source") or "unsupported",
                    "parser_error_count": gps.get("parser_error_count", 0)},
            "ntrip": ntrip,
            "gps_settings": {"navigation_max_hdop": 3.0, "rtk_fallback_to_gps": True,
                             "rtk_required_for_navigation": False},
            "gps_logging": cache.get("gps_logging") or {"active": False, "samples": 0, "file_path": ""},
            "gps_recording": route.get("recording") or {"active": False, "point_count": 0},
            "ground_test": {"active": bool(ground.get("active")), "state": logger_state,
                            "samples": ground.get("samples", 0), "error": ground.get("error", ""),
                            "folder": ground.get("folder", ""),
                            "actuator_locked": bool(safety.get("actuator_locked", True)),
                            "actuation_enabled": bool(ground.get("actuation_enabled",
                                                                  safety.get("ground_test_actuation_enabled", False)))},
            "route": {"selected_route_id": selected_id, "selected_route_name": selected.get("name", selected_id),
                      "selected_multipath_id": str(route.get("selected_multipath_id") or ""),
                      "execution_target_type": route.get("execution_target_type") or
                                               ("multipath" if (route.get("multipath") or {}).get("enabled") else "single_route"),
                      "active_route_id": active_id, "active_route_name": active.get("name", active_id),
                      "waypoint_index": route.get("target_waypoint_index", 0),
                      "waypoint_count": len(active.get("waypoints") or []),
                      "distance_to_waypoint_m": route.get("distance_to_waypoint_m"),
                      "distance_to_route_m": route.get("distance_to_route_m"),
                      "route_complete": bool(route.get("route_complete")), "load_error": "",
                      "storage_path": "~/rcboat_ros_data/routes.json",
                      "multipath_config_path": "~/rcboat_ros_data/multipath_settings.json",
                      "selected_route_persisted": True, "multipath": multipath,
                      "multipath_group_route_ids": group_ids,
                      "alternative_route_id": route.get("candidate_route_id", ""),
                      "target_path_distance_m": route.get("previous_target_path_distance_m"),
                      "candidate_route_distance_m": route.get("candidate_route_distance_m"),
                      "switch_threshold_exceeded": route.get("switch_threshold_exceeded"),
                      "switch_decision": route.get("switch_decision"),
                      "route_candidates": route.get("route_candidates") or [],
                      "off_route_duration_s": 0.0},
            "routes": routes, "multipaths": multipaths,
            "ground_tests": response.get("ground_tests") or [],
            "hardware_errors": [], "events": [],
        }

    def _download_results(self, destination: str, categories: list[str], test_id: str = "") -> dict[str, Any]:
        response = self._bridge({"action": "download_ground_test", "arguments": {"test_id": test_id}})
        if not response.get("success"):
            raise RuntimeError(str(response.get("error") or "download failed"))
        detail = response.get("response") or {}
        raw = base64.b64decode(str(detail.pop("zip_base64")))
        expected = str(detail.get("sha256") or "")
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError("download checksum mismatch")
        target = Path(destination) / str(detail.get("filename") or "ground_test.zip")
        target.write_bytes(raw)
        return {"folder": str(target), "file_count": 1, "files": [target.name],
                "category_labels": ["전체 ZIP"], "test_id": detail.get("test_id")}

    def _handle_request(self, request: dict[str, Any]) -> None:
        command = str(request["command"]).upper()
        ack = {"type": "ack", "request_id": request["request_id"],
               "command": command, "ok": False, "error": ""}
        try:
            if command == "DOWNLOAD_GROUND_RESULTS":
                result = self._download_results(
                    str(request["destination"]), list(request.get("categories") or []),
                    str(request.get("test_id") or "")
                )
                ack.update(result)
                ack["ok"] = True
            else:
                response = self._bridge(self._translate(request))
                ack["ok"] = bool(response.get("success"))
                detail = response.get("response") or {}
                if isinstance(detail, dict):
                    ack.update(detail)
                ack["error"] = str(response.get("error") or detail.get("error") or "")
        except Exception as exc:
            ack["error"] = str(exc)
        self.acknowledgement.emit(ack)

    def run(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.connected.emit()
        self.log.emit("ROS gateway 직접 연결 시작 · SSH는 별도 관리 채널로 확인합니다")
        last_poll = 0.0; last_ssh_attempt = 0.0; last_ssh_error = ""
        try:
            while not self._stop_requested:
                now = time.monotonic()
                if self._client is None and now - last_ssh_attempt >= 15.0:
                    last_ssh_attempt = now
                    try:
                        client = paramiko.SSHClient(); client.load_system_host_keys()
                        if self.known_hosts_path.exists(): client.load_host_keys(str(self.known_hosts_path))
                        client.set_missing_host_key_policy(ConfirmHostKeyPolicy(self))
                        client.connect(self.host, port=self.port, username=self.username,
                                       password=self._password or None, timeout=3, auth_timeout=4,
                                       banner_timeout=4, look_for_keys=True, allow_agent=True)
                        transport = client.get_transport()
                        if transport is None: raise ConnectionError("SSH transport unavailable")
                        shell = transport.open_session(timeout=4); shell.get_pty(term="xterm-256color", width=120, height=32)
                        shell.invoke_shell(); shell.settimeout(0.0)
                        self._client = client; self._shell_channel = shell
                        self.terminal_state.emit(True, f"{self.username}@{self.host}")
                        self.log.emit("SSH 관리 채널 연결 완료")
                        last_ssh_error = ""
                    except Exception as exc:
                        if self._client is not None:
                            try: self._client.close()
                            except Exception: pass
                        self._client = None; self._shell_channel = None
                        message = str(exc)
                        if message != last_ssh_error:
                            self.log.emit("SSH disconnected (ROS gateway 연결은 계속 시도): " + message)
                            last_ssh_error = message
                        self.terminal_state.emit(False, "SSH disconnected")
                try:
                    while True: self._handle_request(self._commands.get_nowait())
                except queue.Empty: pass
                shell = self._shell_channel
                if shell is not None:
                    try:
                        while True: shell.sendall(self._terminal_commands.get_nowait())
                    except queue.Empty: pass
                    except Exception:
                        try: self._client.close()
                        except Exception: pass
                        self._client = None; self._shell_channel = None
                        self.terminal_state.emit(False, "SSH disconnected")
                    try:
                        while shell.recv_ready():
                            data = shell.recv(65536)
                            if data: self.terminal_output.emit(clean_terminal_output(decoder.decode(data)))
                    except Exception: pass
                if now - last_poll >= 1.0:
                    last_poll = now
                    try:
                        response = self._bridge({"action": "status", "arguments": {}})
                        if not response.get("success"): raise RuntimeError(str(response.get("error") or "ROS status failed"))
                        self.telemetry.emit(self._normalize(response, self._client is not None))
                        if self._backend_error: self.log.emit("ROS gateway 연결 복구")
                        self._backend_error = ""
                    except Exception as exc:
                        message = str(exc)
                        offline = {"success": True, "version": "2.1.4", "backend": "ROS Noetic",
                                   "master_online": False, "gateway_online": False, "telemetry": {}, "nodes": []}
                        self.telemetry.emit(self._normalize(offline, self._client is not None))
                        if message != self._backend_error or now - self._backend_error_at >= 15.0:
                            self.log.emit("ROS gateway offline: " + message)
                            self._backend_error = message; self._backend_error_at = now
                self.msleep(50)
        finally:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self.terminal_state.emit(False, "SSH 터미널 연결 종료")
