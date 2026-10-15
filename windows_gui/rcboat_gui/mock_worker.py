from __future__ import annotations

import math
import time
import uuid
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QThread, QTimer, Signal


class MockWorker(QThread):
    connected = Signal()
    disconnected = Signal(str)
    telemetry = Signal(dict)
    acknowledgement = Signal(dict)
    log = Signal(str)

    ROUTES = [
        {"id": "training_a", "name": "훈련 경로 A", "waypoints": [{"lat": 35.078, "lon": 129.086}, {"lat": 35.07812, "lon": 129.08615}, {"lat": 35.07824, "lon": 129.0863}]},
        {"id": "training_b", "name": "훈련 경로 B", "waypoints": [{"lat": 35.07802, "lon": 129.08608}, {"lat": 35.07813, "lon": 129.08623}, {"lat": 35.07826, "lon": 129.08638}]},
        {"id": "training_c", "name": "훈련 경로 C", "waypoints": [{"lat": 35.07798, "lon": 129.08592}, {"lat": 35.07811, "lon": 129.08607}, {"lat": 35.07822, "lon": 129.08622}]},
    ]
    MULTIPATHS = [
        {"id": "training_set_a", "name": "훈련 대루트 A",
         "route_ids": ["training_a", "training_b", "training_c"], "default_route_id": "training_a"},
    ]

    def __init__(self):
        super().__init__()
        self._stop_requested = False
        self.mode = "AUTO"
        self.operation_state = "AUTO"
        self.estop = False
        self.steering = 6000
        self.throttle = 6450
        self.selected_route_id = "training_a"
        self.active_route_id = "training_a"
        self.arduino_connected = True
        self.gps_connected = True
        self.gps_fix = True
        self.failsafe_reason = ""
        self.auto_cruise_pwm = 6650
        self.routes = deepcopy(self.ROUTES)
        self.multipaths = deepcopy(self.MULTIPATHS)
        self.selected_multipath_id = "training_set_a"
        self.gps_recording = False
        self.gps_recording_name = ""
        self.gps_recording_points: list[dict[str, float]] = []
        self.ground_test_active = False
        self.ground_test_samples = 0
        self.ground_test_actuation_enabled = False
        self.ground_test_phase = "normal"
        self.ground_test_marker_count = 0
        self.multipath = {
            "enabled": True, "endpoint_tolerance_m": 0.75,
            "switch_threshold_m": 2.0,
            "switch_rule": "active_target_distance_gt_threshold_then_nearest",
            "off_route_gate": False, "priority_gate": False, "cooldown_gate": False,
        }
        self.recording_minimum_distance_m = 1.0
        self.recording_minimum_interval_s = 0.5
        self.recording_arrival_radius_m = 3.0
        self.gps_data_logging = False
        self.gps_data_samples = 0
        self.gps_scenario = "RTK_FIXED"
        self.rtk_fallback_to_gps = True
        self.gps_max_hdop = 3.0
        self.ntrip = {
            "enabled": False, "connected": False, "host": "", "port": 2101,
            "mountpoint": "", "tls": False, "last_correction_age_s": None,
            "bytes_received": 0, "reconnect_count": 0, "last_error": "",
        }

    def stop(self) -> None:
        self._stop_requested = True

    def send_command(self, command: str, **kwargs: Any) -> str:
        request_id = uuid.uuid4().hex[:12]
        ok, error = True, ""
        try:
            if command == "SET_MODE":
                mode = str(kwargs["mode"]).upper()
                if mode not in {"AUTO", "MANUAL", "NAVIGATION", "REMOTE"}:
                    raise ValueError(f"invalid mode: {mode}")
                if self.estop:
                    raise RuntimeError("Emergency Stop is latched")
                if mode == "MANUAL" and not self.arduino_connected:
                    raise RuntimeError("Arduino/RC data is unavailable; MANUAL rejected")
                self.mode = mode
                requested_state = {
                    "AUTO": "AUTO",
                    "MANUAL": "MANUAL_ACTIVE",
                    "NAVIGATION": "NAVIGATION_ACTIVE",
                    "REMOTE": "REMOTE_ACTIVE",
                }[mode]
                if mode == "NAVIGATION" and (not self.gps_connected or not self.gps_fix):
                    requested_state = "NAVIGATION_WAITING_GPS"
                    self.failsafe_reason = "GPS_NO_FIX"
                else:
                    self.failsafe_reason = ""
                self.operation_state = requested_state
                self.steering, self.throttle = 6000, (
                    self.auto_cruise_pwm if requested_state == "NAVIGATION_ACTIVE"
                    else self.auto_cruise_pwm if requested_state == "AUTO"
                    else 6450
                )
                if mode == "AUTO":
                    self.operation_state = "AUTO_ACTIVE"
            elif command == "REMOTE_CONTROL":
                if self.mode != "REMOTE":
                    raise RuntimeError("REMOTE mode is not active")
                self.steering = int(kwargs["steering_pwm"])
                self.throttle = int(kwargs["throttle_pwm"])
            elif command == "SET_AUTO_CRUISE_PWM":
                value = kwargs.get("value")
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("auto_cruise_pwm must be an integer")
                self.auto_cruise_pwm = value
                if self.mode == "AUTO" and not self.failsafe_reason and not self.estop:
                    self.steering, self.throttle = 6000, value
                elif self.mode == "NAVIGATION" and self.operation_state == "NAVIGATION_ACTIVE" and not self.estop:
                    self.throttle = value
            elif command == "SET_MULTIPATH":
                limits = {
                    "endpoint_tolerance_m": (0.10, 1.00),
                    "switch_threshold_m": (0.10, 100.0),
                }
                if "enabled" in kwargs:
                    self.multipath["enabled"] = bool(kwargs["enabled"])
                for key, (low, high) in limits.items():
                    if key in kwargs:
                        value = float(kwargs[key])
                        if not low <= value <= high:
                            raise ValueError(f"multipath {key} out of range")
                        self.multipath[key] = value
            elif command == "EMERGENCY_STOP":
                self.estop, self.mode, self.operation_state = True, "AUTO", "EMERGENCY_STOP"
                self.steering, self.throttle = 6000, 6450
                self.failsafe_reason = "EMERGENCY_STOP"
            elif command == "CLEAR_ESTOP":
                self.estop, self.mode, self.operation_state = False, "AUTO", "AUTO"
                self.steering, self.throttle = 6000, 6450
                self.failsafe_reason = "ESTOP_CLEARED"
            elif command == "SELECT_ROUTE":
                route_id = str(kwargs["route_id"])
                if route_id not in {route["id"] for route in self.routes}:
                    raise ValueError(f"unknown route: {route_id}")
                self.selected_route_id = route_id
                self.active_route_id = route_id
            elif command == "SELECT_MULTIPATH":
                multipath_id = str(kwargs["multipath_id"])
                group = next((item for item in self.multipaths if item["id"] == multipath_id), None)
                if not group: raise ValueError(f"unknown multipath: {multipath_id}")
                self.selected_multipath_id = multipath_id
                self.selected_route_id = self.active_route_id = group.get("default_route_id") or group["route_ids"][0]
            elif command == "UPSERT_MULTIPATH":
                multipath_id = str(kwargs.get("multipath_id") or f"multipath_{int(time.time())}")
                route_ids = list(dict.fromkeys(str(value) for value in kwargs.get("route_ids") or []))
                known = {route["id"] for route in self.routes}
                if not route_ids or any(value not in known for value in route_ids):
                    raise ValueError("select valid subroutes")
                item = {"id": multipath_id, "name": str(kwargs["name"]), "route_ids": route_ids,
                        "default_route_id": str(kwargs.get("default_route_id") or route_ids[0])}
                self.multipaths = [item if group["id"] == multipath_id else group for group in self.multipaths]
                if not any(group["id"] == multipath_id for group in self.multipaths): self.multipaths.append(item)
                self.selected_multipath_id = multipath_id
            elif command == "DELETE_MULTIPATH":
                multipath_id = str(kwargs["multipath_id"])
                self.multipaths = [item for item in self.multipaths if item["id"] != multipath_id]
                if self.selected_multipath_id == multipath_id:
                    self.selected_multipath_id = self.multipaths[0]["id"] if self.multipaths else ""
            elif command == "UPSERT_ROUTE":
                route_id = str(kwargs.get("route_id") or f"route_{int(time.time())}")
                item = {"id": route_id, "name": str(kwargs["name"]),
                        "arrival_radius_m": float(kwargs.get("arrival_radius_m", 3.0)),
                        "waypoints": list(kwargs.get("waypoints") or [])}
                self.routes = [item if route["id"] == route_id else route for route in self.routes]
                if not any(route["id"] == route_id for route in self.routes): self.routes.append(item)
                self.selected_route_id = self.active_route_id = route_id
            elif command == "DELETE_ROUTE":
                route_id = str(kwargs["route_id"]); self.routes = [route for route in self.routes if route["id"] != route_id]
                for group in self.multipaths:
                    group["route_ids"] = [value for value in group["route_ids"] if value != route_id]
                    if group.get("default_route_id") == route_id:
                        group["default_route_id"] = group["route_ids"][0] if group["route_ids"] else ""
                self.multipaths = [group for group in self.multipaths if group["route_ids"]]
                self.selected_route_id = self.active_route_id = self.routes[0]["id"] if self.routes else ""
            elif command == "START_GPS_RECORDING":
                name = " ".join(str(kwargs.get("name", "")).strip().split())
                if not name:
                    raise ValueError("recording route name is required")
                if not self.gps_connected or not self.gps_fix:
                    raise RuntimeError("GPS FIX is required before route recording")
                self.gps_recording = True
                self.gps_recording_name = name
                self.gps_recording_points = []
                self.recording_minimum_distance_m = float(kwargs.get("minimum_distance_m", 1.0))
                self.recording_minimum_interval_s = float(kwargs.get("minimum_interval_s", 0.5))
                self.recording_arrival_radius_m = float(kwargs.get("arrival_radius_m", 3.0))
            elif command == "STOP_GPS_RECORDING":
                if not self.gps_recording:
                    raise RuntimeError("GPS route recording is not active")
                if len(self.gps_recording_points) < 2:
                    raise RuntimeError("at least two GPS points are required to save a route")
                route_id = f"recorded_{int(time.time())}"
                self.routes.append(
                    {
                        "id": route_id,
                        "name": self.gps_recording_name,
                        "waypoints": list(self.gps_recording_points),
                        "arrival_radius_m": self.recording_arrival_radius_m,
                    }
                )
                self.selected_route_id = route_id
                self.active_route_id = route_id
                self.gps_recording = False
                self.gps_recording_name = ""
                self.gps_recording_points = []
            elif command == "CANCEL_GPS_RECORDING":
                if not self.gps_recording:
                    raise RuntimeError("GPS route recording is not active")
                self.gps_recording = False
                self.gps_recording_name = ""
                self.gps_recording_points = []
            elif command == "START_GPS_LOGGING":
                if self.gps_data_logging:
                    raise RuntimeError("GPS data logging is already active")
                self.gps_data_logging = True
                self.gps_data_samples = 0
            elif command == "STOP_GPS_LOGGING":
                if not self.gps_data_logging:
                    raise RuntimeError("GPS data logging is not active")
                self.gps_data_logging = False
            elif command == "SET_GPS_SETTINGS":
                self.rtk_fallback_to_gps = bool(
                    kwargs.get("rtk_fallback_to_gps", self.rtk_fallback_to_gps)
                )
                self.gps_max_hdop = float(kwargs.get("navigation_max_hdop", self.gps_max_hdop))
            elif command == "CONFIGURE_NTRIP":
                self.ntrip.update({
                    "enabled": bool(kwargs.get("enabled", False)),
                    "connected": bool(kwargs.get("enabled", False)),
                    "host": str(kwargs.get("host", "")), "port": int(kwargs.get("port", 2101)),
                    "mountpoint": str(kwargs.get("mountpoint", "")), "tls": bool(kwargs.get("tls", False)),
                    "last_correction_age_s": 0.2 if kwargs.get("enabled") else None,
                    "last_error": "",
                })
            elif command == "DISABLE_NTRIP":
                self.ntrip["enabled"] = False
                self.ntrip["connected"] = False
                self.ntrip["last_correction_age_s"] = None
            elif command == "REFRESH_NTRIP":
                pass
            elif command == "SIM_SET_GPS_SCENARIO":
                scenario = str(kwargs.get("scenario", "RTK_FIXED")).upper()
                if scenario not in {"NO_FIX", "GPS_FIX", "DGPS", "RTK_FLOAT", "RTK_FIXED", "HDOP_BAD", "SATELLITE_LOW", "GPS_STALE"}:
                    raise ValueError("unknown GPS scenario")
                self.gps_scenario = scenario
            elif command == "GROUND_TEST_START":
                target_type = str(kwargs.get("target_type") or "")
                target_id = str(kwargs.get("target_id") or "")
                if target_type == "multipath":
                    group = next((item for item in self.multipaths if item["id"] == target_id), None)
                    if not group: raise ValueError("select a saved multipath")
                    self.selected_multipath_id = target_id; self.multipath["enabled"] = True
                    self.selected_route_id = self.active_route_id = group.get("default_route_id") or group["route_ids"][0]
                elif target_type == "single_route":
                    if target_id not in {route["id"] for route in self.routes}: raise ValueError("select a saved subroute")
                    self.multipath["enabled"] = False; self.selected_route_id = self.active_route_id = target_id
                else: raise ValueError("select a ground-test target")
                self.ground_test_active = True
                self.ground_test_samples = 0
                self.ground_test_actuation_enabled = bool(kwargs.get("actuation_enabled", False))
                self.ground_test_phase = "normal"
                self.ground_test_marker_count = 1
                self.mode = "GROUND_TEST"
                self.operation_state = "GROUND_TEST"
                self.steering, self.throttle = 6000, self.auto_cruise_pwm if self.ground_test_actuation_enabled else 6450
            elif command == "GROUND_TEST_MARK":
                if not self.ground_test_active: raise ValueError("ground test is not recording")
                marker_type = str(kwargs.get("marker_type") or "").upper()
                if marker_type == "DISTURBANCE_START":
                    if self.ground_test_phase == "disturbance": raise ValueError("disturbance is already active")
                    self.ground_test_phase = "disturbance"
                elif marker_type in {"DISTURBANCE_END", "NORMAL_OPERATION"}:
                    if marker_type == "DISTURBANCE_END" and self.ground_test_phase != "disturbance":
                        raise ValueError("disturbance is not active")
                    self.ground_test_phase = "normal"
                else: raise ValueError("unknown ground-test marker type")
                self.ground_test_marker_count += 1
            elif command == "GROUND_TEST_STOP":
                self.ground_test_active = False
                self.ground_test_actuation_enabled = False
                self.ground_test_phase = "normal"
                self.mode = "AUTO"
                self.operation_state = "AUTO_SAFE"
                self.steering, self.throttle = 6000, 6450
            elif command == "DOWNLOAD_GROUND_RESULTS":
                categories = list(kwargs.get("categories") or [])
                if not categories:
                    raise ValueError("다운로드할 결과 종류를 하나 이상 선택하세요")
            elif command == "SIM_SET_ARDUINO":
                self.arduino_connected = bool(kwargs["connected"])
                if not self.arduino_connected and self.mode == "MANUAL":
                    self.mode, self.operation_state = "AUTO", "AUTO"
                    self.steering, self.throttle = 6000, 6450
                    self.failsafe_reason = "ARDUINO_OR_RC_LOST"
            elif command == "SIM_SET_GPS_CONNECTED":
                self.gps_connected = bool(kwargs["connected"])
                if not self.gps_connected:
                    self.gps_fix = False
                if self.mode == "NAVIGATION" and not self.gps_connected:
                    self.operation_state = "NAVIGATION_WAITING_GPS"
                    self.steering, self.throttle = 6000, 6450
                    self.failsafe_reason = "GPS_NO_FIX"
            elif command == "SIM_SET_GPS_FIX":
                self.gps_fix = self.gps_connected and bool(kwargs["fix"])
                if self.mode == "NAVIGATION":
                    if self.gps_fix:
                        self.operation_state = "NAVIGATION_ACTIVE"
                        self.steering, self.throttle = 6000, self.auto_cruise_pwm
                        self.failsafe_reason = ""
                    else:
                        self.operation_state = "NAVIGATION_WAITING_GPS"
                        self.steering, self.throttle = 6000, 6450
                        self.failsafe_reason = "GPS_NO_FIX"
            elif command == "SIM_REMOTE_HEARTBEAT_LOSS":
                if self.mode != "REMOTE":
                    raise RuntimeError("REMOTE mode is not active")
                self.mode, self.operation_state = "AUTO", "AUTO"
                self.steering, self.throttle = 6000, 6450
                self.failsafe_reason = "REMOTE_HEARTBEAT_TIMEOUT"
            elif command == "SIM_MULTIPATH_SWITCH":
                if self.mode != "NAVIGATION":
                    raise RuntimeError("NAVIGATION mode is not active")
                alternatives = [route["id"] for route in self.routes if route["id"] != self.active_route_id]
                if alternatives:
                    self.active_route_id = alternatives[0]
            elif command in {"RELOAD_ROUTES", "GET_STATE", "HEARTBEAT"}:
                pass
            else:
                raise ValueError(f"unknown command: {command}")
        except Exception as exc:
            ok, error = False, str(exc)
        acknowledgement = {
            "type": "ack",
            "request_id": request_id,
            "command": command,
            "ok": ok,
            "error": error,
        }
        if command == "DOWNLOAD_GROUND_RESULTS" and ok:
            labels = {
                "all": "전체 ZIP",
            }
            acknowledgement.update({
                "folder": str(kwargs.get("destination") or "") + "/simulation_experiment",
                "file_count": len(categories),
                "category_labels": [labels[item] for item in categories if item in labels],
            })
        QTimer.singleShot(0, lambda: self.acknowledgement.emit(acknowledgement))
        return request_id

    def run(self) -> None:
        self.connected.emit()
        self.log.emit("시뮬레이션을 시작했습니다. 실제 하드웨어는 제어하지 않습니다")
        start = time.monotonic()
        while not self._stop_requested:
            t = time.monotonic() - start
            lat = 35.078 + math.sin(t / 20) * 0.00003
            lon = 129.086 + math.cos(t / 20) * 0.00003
            if self.gps_recording and (not self.gps_recording_points or int(t * 2) > len(self.gps_recording_points)):
                self.gps_recording_points.append({"lat": lat, "lon": lon})
            if self.gps_data_logging:
                self.gps_data_samples += 1
            if self.ground_test_active:
                self.ground_test_samples += 1
                if self.ground_test_actuation_enabled:
                    self.steering, self.throttle = 6000 + int(math.sin(t) * 500), self.auto_cruise_pwm
            selected = next(route for route in self.routes if route["id"] == self.selected_route_id)
            active = next(route for route in self.routes if route["id"] == self.active_route_id)
            nav_active = self.operation_state == "NAVIGATION_ACTIVE"
            self.telemetry.emit(
                {
                    "type": "telemetry",
                    "backend": {"name": "SIM", "ready": True, "node_count": 9,
                                "master_online": True, "gateway_online": True,
                                "ssh_connected": False,
                                "logger_state": "recording" if self.ground_test_active else "idle"},
                    "timestamp": time.time(),
                    "uptime_s": round(t, 1),
                    "mode": self.mode,
                    "operation_state": self.operation_state,
                    "navigation_active": nav_active,
                    "estop": self.estop,
                    "failsafe_reason": self.failsafe_reason,
                    "manual_waiting_for_neutral": False,
                    "auto_cruise_pwm": self.auto_cruise_pwm,
                    "gps_recording": {"active": self.gps_recording, "name": self.gps_recording_name, "point_count": len(self.gps_recording_points), "minimum_distance_m": self.recording_minimum_distance_m, "minimum_interval_s": self.recording_minimum_interval_s, "arrival_radius_m": self.recording_arrival_radius_m},
                    "gps_logging": {"active": self.gps_data_logging, "file_path": "/home/jetson/rcboat/logs/gps/mock_week6.csv" if self.gps_data_samples else "", "samples": self.gps_data_samples, "started_at": "simulation" if self.gps_data_logging else None},
                    "ntrip": dict(self.ntrip),
                    "gps_settings": {"baudrate": 115200, "health_stale_s": 2.0, "navigation_max_hdop": self.gps_max_hdop, "rtk_required_for_navigation": not self.rtk_fallback_to_gps, "rtk_fallback_to_gps": self.rtk_fallback_to_gps, "rtk_correction_max_age_s": 10.0},
                    "ground_test": {"active": self.ground_test_active,
                                    "state": "recording" if self.ground_test_active else "idle",
                                    "samples": self.ground_test_samples,
                                    "actuator_locked": not self.ground_test_actuation_enabled,
                                    "actuation_enabled": self.ground_test_actuation_enabled,
                                    "test_phase": self.ground_test_phase,
                                    "disturbance_active": self.ground_test_phase == "disturbance",
                                    "marker_count": self.ground_test_marker_count},
                    "mock": True,
                    "rc": {"steering_us": 1640 + int(math.sin(t) * 60) if self.arduino_connected else None, "throttle_us": 1500 if self.arduino_connected else None, "age_s": 0.01 if self.arduino_connected else None},
                    "pca": {"frequency_hz": 60, "steering_channel": 0, "throttle_channel": 6, "steering_pwm": self.steering, "throttle_pwm": self.throttle},
                    "gps": self._gps_telemetry(t, lat, lon),
                    "devices": {"arduino": self.arduino_connected, "gps": self.gps_connected, "pca9685": True},
                    "route": {"selected_route_id": self.selected_route_id, "selected_route_name": selected["name"],
                              "selected_multipath_id": self.selected_multipath_id,
                              "execution_target_type": "multipath" if self.multipath["enabled"] else "single_route",
                              "active_route_id": self.active_route_id, "active_route_name": active["name"],
                              "waypoint_index": 0, "waypoint_count": 3, "distance_to_waypoint_m": 5.4,
                              "distance_to_route_m": 1.1, "route_complete": False, "load_error": "",
                              "target_path_distance_m": 1.1, "candidate_route_distance_m": 1.1,
                              "switch_threshold_exceeded": False,
                              "switch_decision": "KEEP_ACTIVE_WITHIN_THRESHOLD",
                              "multipath": dict(self.multipath),
                              "multipath_group_route_ids": next((group["route_ids"] for group in self.multipaths
                                                                 if group["id"] == self.selected_multipath_id), [self.selected_route_id]),
                              "route_candidates": [],
                              "alternative_route_id": next((route["id"] for route in self.routes if route["id"] != self.active_route_id), ""), "off_route_duration_s": 0.0},
                    "routes": self.routes,
                    "multipaths": self.multipaths,
                    "ground_tests": [{"id": "ground_test_SIMULATION", "sample_count": 120, "complete": True}],
                    "hardware_errors": [],
                    "events": [],
                }
            )
            time.sleep(0.1)
        self.disconnected.emit("시뮬레이션이 종료되었습니다")

    def _gps_telemetry(self, t: float, lat: float, lon: float) -> dict[str, Any]:
        scenario = self.gps_scenario
        fix = self.gps_connected and self.gps_fix and scenario != "NO_FIX"
        quality = {"DGPS": 2, "RTK_FLOAT": 5, "RTK_FIXED": 4}.get(scenario, 1 if fix else 0)
        hdop = 4.5 if scenario == "HDOP_BAD" else 0.8 if fix else None
        satellites = 5 if scenario == "SATELLITE_LOW" else 18 if fix else 0
        age = 6.0 if scenario == "GPS_STALE" else 0.02 if self.gps_connected else None
        status = "STALE" if scenario == "GPS_STALE" else "NO_FIX" if not fix else "BAD" if scenario in {"HDOP_BAD", "SATELLITE_LOW"} else "GOOD"
        rtk_fixed = quality == 4 and bool(self.ntrip.get("connected"))
        fallback_active = fix and not rtk_fixed
        return {
            "fix": fix, "quality": quality,
            "fix_label": {0: "NO FIX", 1: "GPS", 2: "DGPS", 4: "RTK FIXED", 5: "RTK FLOAT"}.get(quality, "UNKNOWN"),
            "lat": lat if fix else None, "lon": lon if fix else None,
            "altitude_m": 4.2 if fix else None, "hdop": hdop, "pdop": 1.2 if fix else None,
            "vdop": 1.1 if fix else None, "cno_avg_dbhz": 43.0 if fix else None,
            "hacc_m": 0.02 if quality == 4 else 0.8 if fix else None,
            "satellites": satellites, "speed_mps": 1.2 if fix else 0.0,
            "course_deg": (t * 8) % 360 if fix else None, "utc_time": "12:34:56.00",
            "age_s": age, "data_validity": "valid" if fix else "invalid",
            "utc_status": "valid", "last_fix_age_s": 0.02 if fix else None,
            "health": {"status": status, "navigation_status": status, "rtk_status": "GOOD" if rtk_fixed else "UNAVAILABLE", "reasons": [f"Satellites {satellites}", f"HDOP {hdop}" if hdop is not None else "No valid GPS position"]},
            "rtk_state": "RTK_FIXED" if quality == 4 else "RTK_FLOAT" if quality == 5 else "DGPS" if quality == 2 else "NO_RTK",
            "rtk_fallback_active": fallback_active,
            "navigation_fix_mode": "RTK_FIXED" if rtk_fixed else "GPS_FALLBACK" if fix else "NO_FIX",
            "utm_easting": 508000.0 if fix else None, "utm_northing": 3882000.0 if fix else None,
            "utm_zone": "52N" if fix else None, "utm_status": "valid" if fix else "no_data",
            "heading_source": "GNSS_COG_SIM" if fix else "unsupported", "parser_error_count": 0,
        }
