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
from rcboat_ros.control_config import validate_cruise,output_in_range

from . import JETSON_VERSION, __version__ as GUI_VERSION

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

    STATUS_POLL_INTERVAL_S = 1.0
    STATUS_RETRY_INTERVAL_S = .35
    STATUS_STALE_S = 2.5
    SSH_RETRY_INTERVAL_S = 1.5
    SSH_HEALTH_INTERVAL_S = 1.0
    SSH_HEALTH_TIMEOUT_S = 2.0
    SSH_DELAY_GRACE_S = 5.0

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
        self._connecting_client = None
        self._io_lock = threading.Lock()
        self._active_sockets = set()
        self._link_thread = None
        self._ssh_health_thread = None
        self._status_thread = None
        self._ssh_wakeup = threading.Event()
        self._status_wakeup = threading.Event()
        self._halt = threading.Event()
        self._control_rtt_ms = None
        self._control_ack_at = 0.0
        self._heartbeat_missed = False
        self._route_catalog_revision = ""
        self._route_catalog = {}
        self._host_key_event = threading.Event()
        self._host_key_accepted = False
        self._ssh_lock = threading.RLock()
        self._ssh_confirmed = False
        self._ssh_health_failures = 0
        self._ssh_delay_since = None
        self._ssh_health_failed = threading.Event()
        self._ssh_probe_error = ""
        self._backend_version = ""
        self._status_direct_seen = False
        self._backend_error = ""
        self._backend_error_at = 0.0

    def _close_ssh(self, message: str, *, notify: bool = True, expected_shell=None) -> None:
        """Release both SSH channels before publishing the disconnected state."""
        with self._ssh_lock:
            if expected_shell is not None and expected_shell is not self._shell_channel:
                return
            client, shell = self._client, self._shell_channel
            connecting = self._connecting_client
            self._connecting_client = None
            self._client = None
            self._shell_channel = None
            self._ssh_confirmed = False
            self._ssh_health_failures = 0
            self._ssh_delay_since = None
            self._ssh_health_failed.clear()
        if shell is not None:
            try:
                shell.close()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if connecting is not None and connecting is not client:
            try:connecting.close()
            except Exception:pass
        if notify:
            self.terminal_state.emit(False, message)

    def _ssh_is_healthy(self) -> bool:
        """Actively prove that the authenticated SSH transport still accepts channels.

        Paramiko's ``is_active()`` only reports its local transport-thread state and
        can remain true after Wi-Fi or the remote sshd disappears.  Opening a small
        throw-away channel requires a reply from the Jetson, so a timeout is an
        actual liveness failure rather than a cached connection flag.
        """
        with self._ssh_lock:
            client = self._client
            shell = self._shell_channel
        if shell is None or shell.closed or shell.exit_status_ready():
            return False
        if client is None:
            return False
        transport = client.get_transport()
        if transport is None or not transport.is_active() or not transport.is_authenticated():
            return False
        probe = None
        try:
            probe = transport.open_session(timeout=self.SSH_HEALTH_TIMEOUT_S)
            return not probe.closed
        except Exception as exc:
            self._ssh_probe_error = type(exc).__name__ + ": " + str(exc)
            return False
        finally:
            if probe is not None:
                try:
                    probe.close()
                except Exception:
                    pass

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
        self._halt.set()
        self._ssh_wakeup.set()
        self._status_wakeup.set()
        with self._io_lock:
            sockets=list(self._active_sockets)
        for connection in sockets:
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            try:connection.close()
            except OSError:pass
        self._close_ssh("SSH disconnected", notify=False)

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
        if command=='EMERGENCY_STOP':kwargs.update(origin='desktop',reason='OPERATOR_ESTOP')
        if command=='REMOTE_CONTROL' and not output_in_range(kwargs.get('steering_pwm'),kwargs.get('throttle_pwm')):
            raise ValueError('remote PWM outside calibration')
        direct = {
            "VISION_ENABLE":"vision_enable", "VISION_CONFIGURE":"vision_configure", "VISION_RESET_TRACKING":"vision_reset_tracking",
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
            "GROUND_TEST_STOP": "ground_stop", "GROUND_TEST_RESUME": "ground_resume",
        }
        if command == "SET_MODE":
            mode = str(kwargs.get("mode", "AUTO")).upper()
            arguments = {
                "mode": "AUTO_SAFE" if mode == "AUTO" else mode,
                "armed": mode in {"NAVIGATION","BALLOON"},
            }
            if mode == "BALLOON" and "expected_mode_since_monotonic" in kwargs:
                arguments["expected_mode_since_monotonic"] = kwargs["expected_mode_since_monotonic"]
            return {"action": "set_mode", "arguments": arguments}
        if command == "START_GPS_RECORDING":
            return {"action": "record_start", "arguments": kwargs}
        if command == "SET_MULTIPATH":
            return {"action": "set_multipath", "arguments": {
                "enabled": kwargs.get("enabled", True),
                "endpoint_tolerance_m": kwargs.get("endpoint_tolerance_m", 0.75),
            }}
        if command == "SET_AUTO_CRUISE_PWM":
            return {"action": "set_auto_cruise_pwm", "arguments": {"value": validate_cruise(kwargs.get("value"))}}
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
        status_only = payload.get("action") == "status"
        try:
            with socket.create_connection((self.host, self.gateway_port), timeout=.9 if status_only else 3.0) as connection:
                with self._io_lock:
                    if self._stop_requested:raise InterruptedError('connection cancelled')
                    self._active_sockets.add(connection)
                read_timeout = (1.0 if self._route_catalog_revision else 2.5) if status_only else 15.0
                connection.settimeout(read_timeout)
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
            response = json.loads(data.decode("utf-8"))
            if status_only:
                self._status_direct_seen = True
            return response
        except (OSError, ValueError, json.JSONDecodeError) as direct_error:
            # Compatibility fallback for installations not yet exposing the LAN gateway.
            if self._client is not None and not self._stop_requested and (not status_only or not self._status_direct_seen):
                try:
                    return self._ssh_bridge(payload)
                except Exception:
                    pass
            raise ConnectionError(f"ROS gateway offline: {direct_error}") from direct_error
        finally:
            with self._io_lock:
                self._active_sockets={s for s in self._active_sockets if s.fileno()>=0}

    @staticmethod
    def _normalize(response: dict[str, Any], ssh_connected: bool = False) -> dict[str, Any]:
        cache = response.get("telemetry") or {}
        gps = cache.get("gps") or {}
        rc = cache.get("rc") or {}
        route = cache.get("route") or {}
        nav = cache.get("navigation") or {}
        safety = cache.get("safety") or {}
        actuator = cache.get("actuator") or {}
        ntrip = dict(cache.get("ntrip") or {})
        if ntrip.get("correction_age_source") != "JETSON_RTCM3_CRC_RECEPTION":
            ntrip.update(last_correction_age_s=None, correction_age=None,
                         correction_age_status="unsupported")
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
            "selection_policy": "nearest_route",
            "switch_rule": "nearest_route_each_update",
            "off_route_gate": False, "priority_gate": False, "cooldown_gate": False,
        }
        logger_state = str(ground.get("state") or ("recording" if ground.get("active") else "idle"))
        return {
            "type": "telemetry", "software_version": response.get("version", "2.4.18"),
            "backend": {"name": str(response.get("backend") or "ROS Noetic"),
                        "ready": bool(response.get("gateway_online", True)), "node_count": len(nodes),
                        "master_online": response.get("master_online"),
                        "gateway_online": bool(response.get("gateway_online", True)),
                        "ssh_connected": bool(ssh_connected), "logger_state": logger_state,
                        "ssh_state": (cache.get('operator_link',{}).get('ssh_state','connected') if ssh_connected else 'disconnected'),
                        "version": response.get("version") or "unknown",
                        "runtime_identity": response.get("runtime_identity") or {}},
            "timestamp": time.time(), "mode": mode, "operation_state": (
                "EMERGENCY_STOP" if safety.get("estop") else
                "NAVIGATION_GPS_GRACE" if ros_mode=='NAVIGATION' and safety.get('gps_grace_active') else
                "MANUAL_WAITING_RC" if mode == "MANUAL" and not safety.get("rc_fresh") else
                "MANUAL_WAITING_NEUTRAL" if mode == "MANUAL" and safety.get("manual_rearm_pending") else
                "MANUAL_ACTIVE" if mode == "MANUAL" else ros_mode),
            "navigation_active": ros_mode == "NAVIGATION" and bool(safety.get("armed")) and not safety.get('gps_grace_active'),
            "estop": bool(safety.get("estop")), "failsafe_reason": safety.get("reason") or "",
            "estop_reason":safety.get("estop_reason"),"estop_time_utc":safety.get("estop_time_utc"),"estop_origin":safety.get("estop_origin"),
            "actuator_locked":bool(safety.get("actuator_locked",True)),
            "manual_waiting_for_neutral": bool(safety.get("manual_rearm_pending")),
            "auto_cruise_pwm": nav.get("auto_cruise_pwm") if nav.get('fresh',False) else None,
            "ramp_throttle_pwm": nav.get('ramp_throttle_pwm') if nav.get('fresh',False) else None,
            "final_throttle_pwm": safety.get('throttle_pwm'),
            "vision":cache.get("vision") or {}, "vision_desired":cache.get("vision_desired") or {},
            "balloon_armed":ros_mode=="BALLOON" and bool(safety.get("armed")),
            "mode_since_monotonic":safety.get("mode_since_monotonic"),
            "cruise_applied_monotonic": nav.get('cruise_applied_monotonic'), "mock": False,
            "rc_input_calibration": safety.get('rc_input_calibration'),
            "pca_output_calibration": safety.get('pca_output_calibration'),
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
                    "receiver_correction_age_s": gps.get("receiver_correction_age_s"),
                    "receiver_correction_age_status": gps.get("receiver_correction_age_status") or "unsupported",
                    "receiver_correction_age_monotonic": gps.get("receiver_correction_age_monotonic"),
                    "ubx_message_count": gps.get("ubx_count"),
                    "nav_pvt_message_count": gps.get("nav_pvt_count"),
                    "nmea_sentence_count": gps.get("nmea_count"),
                    "parser_error_count": gps.get("parser_error_count", 0)},
            "ntrip": ntrip,
            "gps_settings": dict(response.get('gps_settings') or {}),
            "gps_logging": cache.get("gps_logging") or {"active": False, "samples": 0, "file_path": ""},
            "gps_recording": route.get("recording") or {"active": False, "point_count": 0},
            "ground_test": {"active": bool(ground.get("active")), "state": logger_state,
                            "output_paused": bool(ground.get("output_paused")),
                            "pause_reason": ground.get("pause_reason", ""),
                            "gps_grace_active": bool(safety.get("gps_grace_active")),
                            "gps_grace_remaining_s": safety.get("gps_grace_remaining_s"),
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
                      "target_path_distance_m": route.get("distance_to_route_m"),
                      "previous_target_path_distance_m": route.get("previous_target_path_distance_m"),
                      "candidate_route_distance_m": route.get("candidate_route_distance_m"),
                      "route_distance_improvement_m": route.get("route_distance_improvement_m"),
                      "selection_metric": route.get("selection_metric"),
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
            starts_motion = command in {"GROUND_TEST_START", "GROUND_TEST_RESUME"} or (
                command == "SET_MODE" and str(request.get("mode") or "").upper() in {"NAVIGATION", "REMOTE", "BALLOON"})
            if starts_motion and self._backend_version != JETSON_VERSION:
                raise RuntimeError(f"GUI v{GUI_VERSION}에는 Jetson v{JETSON_VERSION}이 필요합니다. 현재 Jetson v{self._backend_version or 'unknown'}")
            if command=='DOWNLOAD_VISION_LOG':
                response=self._bridge({'action':'download_vision_log','arguments':{}})
                if not response.get('success'):raise RuntimeError(response.get('error') or 'vision download failed')
                detail=response['response'];raw=base64.b64decode(detail['zip_base64']);name=str(detail['filename'])
                if Path(name).name!=name or not name.endswith('.zip'):raise ValueError('invalid export filename')
                if hashlib.sha256(raw).hexdigest()!=detail['sha256']:raise ValueError('vision export hash mismatch')
                destination=Path(str(request['destination']));destination.mkdir(parents=True,exist_ok=True)
                target=destination/name;target.write_bytes(raw);ack.update(ok=True,path=str(target),bytes=len(raw))
            elif command == "DOWNLOAD_GROUND_RESULTS":
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

    def _send_operator_link(self, ssh_connected: bool) -> None:
        payload = {"action": "operator_link", "arguments": {
            "ssh_connected": ssh_connected,
            "ssh_state": 'delayed' if ssh_connected and self._ssh_delay_since is not None else
                         'connected' if ssh_connected else 'disconnected'}}
        if self.gateway_token:
            payload["token"] = self.gateway_token
        # Separate short-lived connection: ZIP downloads and status queries cannot
        # keep the lease alive accidentally or block safety heartbeats.
        started = time.monotonic()
        with socket.create_connection((self.host, self.gateway_port), timeout=1.0) as connection:
            connection.settimeout(1.0)
            connection.sendall((json.dumps(payload) + "\n").encode())
            result = json.loads(connection.makefile("rb").readline(4096))
            if not result.get("success"):
                raise ConnectionError("operator link rejected")
        now = time.monotonic()
        link_recovered = self._heartbeat_missed or not self._control_ack_at
        self._heartbeat_missed = False
        self._control_rtt_ms = round((now - started) * 1000)
        self._control_ack_at = now
        if link_recovered and not self._stop_requested:
            self._status_wakeup.set()
            self._ssh_wakeup.set()

    def _update_ssh_health(self) -> bool:
        """One owner probes SSH; a transient timeout does not destroy the session."""
        with self._ssh_lock:
            client = self._client
            if client is None:
                self._ssh_confirmed = False
                return False
            transport = client.get_transport()
            shell = self._shell_channel
            ended = (transport is None or not transport.is_active() or
                     not transport.is_authenticated() or shell is None or
                     shell.closed or shell.exit_status_ready())
        healthy = False if ended else self._ssh_is_healthy()
        with self._ssh_lock:
            if self._client is not client:
                return self._ssh_confirmed
            # A transport can close while the channel probe is waiting.
            ended=(ended or not transport.is_active() or not transport.is_authenticated()
                   or shell is None or shell.closed or shell.exit_status_ready())
            if ended:healthy=False
            if healthy:
                if self._ssh_health_failures:
                    self.log.emit("SSH 지연 회복 · 기존 연결 유지")
                self._ssh_health_failures = 0
                self._ssh_delay_since = None
                if not self._ssh_health_failed.is_set():
                    self._ssh_confirmed = True
            else:
                self._ssh_health_failures += 1
                if self._ssh_delay_since is None:self._ssh_delay_since=time.monotonic()
                if ended or time.monotonic()-self._ssh_delay_since>=self.SSH_DELAY_GRACE_S:
                    if not self._ssh_health_failed.is_set():
                        self.log.emit("SSH 단절 확정: " + ("세션 종료" if ended else self._ssh_probe_error))
                        self.terminal_state.emit(False, "SSH disconnected · 응답 확인 실패")
                    self._ssh_confirmed = False
                    self._ssh_health_failed.set()
                elif self._ssh_confirmed:
                    self.log.emit("SSH 응답 지연 1회 · 재확인 중 · " + self._ssh_probe_error)
            return self._ssh_confirmed

    def _operator_link_loop(self) -> None:
        while not self._stop_requested:
            try:
                # Never wait for an SSH exec probe here: even a stalled SSH
                # server must not delay the independent ROS safety lease.
                self._send_operator_link(self._ssh_confirmed)
            except (OSError, ValueError):
                self._heartbeat_missed = True  # The Jetson expires the lease independently.
            for _ in range(10):
                if self._stop_requested:
                    break
                time.sleep(.1)
        try:
            self._send_operator_link(False)
        except (OSError, ValueError):
            pass

    def _open_ssh_terminal(self, last_error: str) -> str:
        client = paramiko.SSHClient()
        try:
            with self._ssh_lock:
                if self._stop_requested:
                    return last_error
                self._connecting_client = client
            client.load_system_host_keys()
            if self.known_hosts_path.exists():
                client.load_host_keys(str(self.known_hosts_path))
            client.set_missing_host_key_policy(ConfirmHostKeyPolicy(self))
            client.connect(self.host, port=self.port, username=self.username,
                           password=self._password or None, timeout=1.5, auth_timeout=4,
                           banner_timeout=4, look_for_keys=True, allow_agent=True)
            transport = client.get_transport()
            if transport is None:
                raise ConnectionError("SSH transport unavailable")
            shell = transport.open_session(timeout=4)
            shell.get_pty(term="xterm-256color", width=120, height=32)
            shell.invoke_shell()
            shell.settimeout(0.0)
            transport.set_keepalive(3)
            with self._ssh_lock:
                if self._stop_requested:
                    client.close()
                    return last_error
                self._connecting_client = None
                self._shell_channel = shell
                self._ssh_health_failed.clear()
                self._ssh_health_failures = 0
                self._ssh_delay_since = None
                self._ssh_confirmed = True
                self._client = client
            self.terminal_state.emit(True, f"{self.username}@{self.host}")
            self.log.emit("SSH 관리 채널 연결 완료")
            self._status_wakeup.set()
            return ""
        except Exception as exc:
            self._close_ssh("SSH disconnected", notify=False)
            message = str(exc)
            if not self._stop_requested and message != last_error:
                self.log.emit("SSH disconnected (ROS gateway 연결은 계속 시도): " + message)
                self.terminal_state.emit(False, "SSH disconnected")
            return message

    def _ssh_health_loop(self) -> None:
        last_attempt = float("-inf")
        last_error = ""
        while not self._stop_requested:
            self._update_ssh_health()
            if self._stop_requested:
                break
            now = time.monotonic()
            if self._ssh_health_failed.is_set():
                self._close_ssh("SSH disconnected · 연속 응답 실패 후 연결 재시도")
                last_attempt = float("-inf")
            if self._client is None and (self._ssh_wakeup.is_set() or now - last_attempt >= self.SSH_RETRY_INTERVAL_S):
                self._ssh_wakeup.clear()
                last_attempt = now
                last_error = self._open_ssh_terminal(last_error)
            if self._client is None:
                self._ssh_wakeup.wait(.25)
            else:
                self._ssh_wakeup.clear()
                self._halt.wait(self.SSH_HEALTH_INTERVAL_S)

    def run(self) -> None:
        reason="연결 작업 종료"
        try:
            self._run_connections()
        except Exception as exc:
            reason="연결 작업 오류: " + str(exc)
            __import__('logging').getLogger('rcboat.worker').exception('connection worker failed')
            self.log.emit(reason)
        finally:
            self.stop()
            self._close_ssh(reason,notify=False)
            if self._link_thread is not None:self._link_thread.join()
            if self._ssh_health_thread is not None:self._ssh_health_thread.join()
            if self._status_thread is not None:self._status_thread.join()
            self.disconnected.emit(reason)

    def _merge_route_catalog(self, response):
        revision = response.get("route_catalog_revision")
        if revision is None:
            return
        route = (response.get("telemetry") or {}).get("route")
        if route is None:
            return
        if "routes" in route and "multipaths" in route:
            self._route_catalog = {key: route[key] for key in ("routes", "multipaths")}
            self._route_catalog_revision = revision
        elif revision == self._route_catalog_revision:
            route.update(self._route_catalog)

    def _status_loop(self):
        last_success = float("-inf")
        while not self._stop_requested:
            started = time.monotonic()
            interval = self.STATUS_RETRY_INTERVAL_S
            try:
                response = self._bridge({"action": "status", "arguments": {
                    "route_catalog_revision": self._route_catalog_revision}})
                if not response.get("success"):
                    raise RuntimeError(str(response.get("error") or "ROS status failed"))
                self._backend_version = str(response.get("version") or "unknown")
                self._merge_route_catalog(response)
                state = self._normalize(response, self._ssh_confirmed)
                if self._ssh_confirmed and self._ssh_delay_since is not None:
                    state["backend"]["ssh_state"] = "delayed"
                last_success = time.monotonic()
                state["backend"]["status_rtt_ms"] = round((last_success - started) * 1000)
                state["backend"]["control_rtt_ms"] = (
                    self._control_rtt_ms if last_success - self._control_ack_at < 3.0 else None)
                self.telemetry.emit(state)
                if self._backend_error:
                    self.log.emit("ROS gateway 연결 복구")
                    self._ssh_wakeup.set()
                self._backend_error = ""
                interval = self.STATUS_POLL_INTERVAL_S
            except Exception as exc:
                if self._stop_requested:
                    break
                now = time.monotonic()
                if now - last_success >= self.STATUS_STALE_S:
                    self.telemetry.emit({
                        "backend": {
                            "status_unavailable": True,
                            "ssh_connected": self._ssh_confirmed,
                            "ssh_state": "delayed" if self._ssh_delay_since is not None else "connected",
                        },
                    })
                    message = str(exc)
                    if message != self._backend_error or now - self._backend_error_at >= 15.0:
                        self.log.emit("ROS gateway offline: " + message)
                        self._backend_error = message
                        self._backend_error_at = now
            self._status_wakeup.wait(max(.05, interval - (time.monotonic() - started)))
            self._status_wakeup.clear()

    def _run_connections(self) -> None:
        link_thread = threading.Thread(target=self._operator_link_loop, daemon=True)
        self._link_thread=link_thread
        link_thread.start()
        self._ssh_health_thread = threading.Thread(target=self._ssh_health_loop, daemon=True)
        self._ssh_health_thread.start()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.connected.emit()
        self.log.emit("ROS gateway 직접 연결 시작 · SSH는 별도 관리 채널로 확인합니다")
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()
        try:
            while not self._stop_requested:
                try:
                    while True: self._handle_request(self._commands.get_nowait())
                except queue.Empty: pass
                shell = self._shell_channel
                if shell is not None:
                    if shell.closed or shell.exit_status_ready():
                        self._close_ssh("SSH disconnected · 터미널 세션 종료", expected_shell=shell)
                        shell = None
                if shell is not None:
                    try:
                        while True: shell.sendall(self._terminal_commands.get_nowait())
                    except queue.Empty: pass
                    except Exception:
                        self._close_ssh("SSH disconnected · 터미널 전송 실패", expected_shell=shell)
                        shell = None
                if shell is not None:
                    try:
                        while shell.recv_ready():
                            data = shell.recv(65536)
                            if data:
                                self.terminal_output.emit(clean_terminal_output(decoder.decode(data)))
                            else:
                                self._close_ssh("SSH disconnected · 터미널 세션 종료", expected_shell=shell)
                                break
                    except Exception:
                        self._close_ssh("SSH disconnected · 터미널 수신 실패", expected_shell=shell)
                self.msleep(50)
        finally:
            self.stop()
            self.terminal_state.emit(False, "SSH 터미널 연결 종료")
