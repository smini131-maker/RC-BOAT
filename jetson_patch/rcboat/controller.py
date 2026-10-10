from __future__ import annotations

import logging
import time
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

from .config import RuntimeSettings, VALUES
from .gps_health import GpsHealthThresholds, evaluate_gps_health, navigation_gate_reason
from .gps_logger import GpsCsvLogger
from .hardware import BaseHardware
from .gps_runtime import install_hardware_extension
from .navigation import RouteManager, angle_error_deg, bearing_deg, haversine_m

install_hardware_extension()

LOG = logging.getLogger("rcboat.controller")


def clamp(value: float, low: int, high: int) -> int:
    return int(round(max(low, min(high, value))))


def piecewise_map(value: int, x0: int, x1: int, x2: int, y0: int, y1: int, y2: int) -> int:
    if value <= x1:
        if x1 == x0:
            return y1
        ratio = (max(x0, value) - x0) / (x1 - x0)
        return int(round(y0 + ratio * (y1 - y0)))
    if x2 == x1:
        return y1
    ratio = (min(x2, value) - x1) / (x2 - x1)
    return int(round(y1 + ratio * (y2 - y1)))


class BoatController:
    """All mode transitions and fail-safe output decisions live in this process."""

    MODES = {"AUTO", "MANUAL", "NAVIGATION", "REMOTE"}

    def __init__(
        self, hardware: BaseHardware, routes: RouteManager, settings: RuntimeSettings
    ) -> None:
        self.hardware = hardware
        self.routes = routes
        self.settings = settings
        self.mode = "MANUAL"
        self.operation_state = "MANUAL_WAITING_RC"
        self.estop = False
        self.steering_pwm = VALUES.steering_center_pwm
        self.throttle_pwm = VALUES.throttle_stop_pwm
        self.failsafe_reason = "BOOT_WAITING_RC"
        self.remote_steering_pwm = VALUES.steering_center_pwm
        self.remote_throttle_pwm = VALUES.throttle_stop_pwm
        self.remote_last_heartbeat = 0.0
        self._gesture_since: float | None = None
        self._auto_to_manual_armed = False
        self._manual_rearm_since: float | None = None
        self._manual_waiting_for_neutral = True
        self._last_route_status: dict[str, Any] = {}
        self.hil_enabled = False
        self._hil_started_at = 0.0
        self._hil_position: tuple[float, float] | None = None
        self._hil_course_deg: float | None = None
        self._events: list[dict[str, Any]] = []
        self.started_monotonic = time.monotonic()
        self._navigation_route_prepared = False
        self.gps_logger = GpsCsvLogger(self.routes.route_path.parent / "logs" / "gps")
        self._last_logged_gps_update = 0.0
        self.routes.configure_multipath(self.settings.multipath_settings())

    def _ntrip_state(self) -> dict[str, Any]:
        status = getattr(self.hardware, "ntrip_status", None)
        if callable(status):
            return status()
        return {
            "enabled": False, "connected": False, "host": "", "port": 2101,
            "mountpoint": "", "tls": False, "last_correction_age_s": None,
            "bytes_received": 0, "reconnect_count": 0, "last_error": "",
        }

    def _gps_data(self, snap: Any, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        quality = int(getattr(snap, "gps_quality", 0) or 0)
        result: dict[str, Any] = {
            "connected": bool(getattr(snap, "gps_connected", False)),
            "fix": bool(getattr(snap, "gps_fix", False)),
            "fix_quality": quality,
            "fix_label": {0: "NO FIX", 1: "GPS", 2: "DGPS", 4: "RTK FIXED", 5: "RTK FLOAT"}.get(quality, f"FIX {quality}"),
            "latitude": getattr(snap, "gps_lat", None),
            "longitude": getattr(snap, "gps_lon", None),
            "altitude_m": getattr(snap, "gps_altitude_m", None),
            "satellites": int(getattr(snap, "gps_satellites", 0) or 0),
            "hdop": getattr(snap, "gps_hdop", None),
            "pdop": None, "vdop": None, "cno_avg_dbhz": None, "hacc_m": None,
            "speed_mps": float(getattr(snap, "gps_speed_mps", 0.0) or 0.0),
            "course_deg": getattr(snap, "gps_course_deg", None),
            "utc_time": None,
            "last_update_monotonic": float(getattr(snap, "gps_last_update", 0.0) or 0.0),
            "last_valid_fix_monotonic": float(getattr(snap, "gps_last_fix", 0.0) or 0.0),
            "parser_error_count": 0,
            "rtk_state": "RTK_FIXED" if quality == 4 else "RTK_FLOAT" if quality == 5 else "DGPS" if quality == 2 else "NO_RTK",
            "utm_easting": None, "utm_northing": None, "utm_zone": None,
        }
        provider = getattr(self.hardware, "week6_gps_snapshot", None)
        if callable(provider) and not (self.hil_enabled and isinstance(snap, SimpleNamespace)):
            result.update(provider())
        ntrip = self._ntrip_state()
        thresholds = GpsHealthThresholds(stale_s=self.settings.gps_health_stale_s)
        health = evaluate_gps_health(
            result,
            connected=bool(result.get("connected")),
            now=now,
            correction_age_s=ntrip.get("last_correction_age_s"),
            thresholds=thresholds,
        )
        result["health"] = health
        correction_age = ntrip.get("last_correction_age_s")
        correction_fresh = (
            correction_age is not None
            and float(correction_age) <= self.settings.rtk_correction_max_age_s
        )
        rtk_fixed = str(result.get("rtk_state")) == "RTK_FIXED"
        rtk_usable = rtk_fixed and (not bool(ntrip.get("enabled")) or correction_fresh)
        fallback_active = bool(result.get("fix")) and not rtk_usable
        result["rtk_fallback_active"] = fallback_active
        result["navigation_fix_mode"] = (
            "RTK_FIXED" if rtk_usable else "GPS_FALLBACK" if fallback_active else "NO_FIX"
        )
        result["age_s"] = health.get("age_s")
        last_fix = float(result.get("last_valid_fix_monotonic") or 0.0)
        result["last_fix_age_s"] = max(0.0, now - last_fix) if last_fix > 0 else None
        return result

    def start_gps_data_logging(self) -> str:
        path = self.gps_logger.start()
        self._last_logged_gps_update = 0.0
        self._event("INFO", f"GPS data logging started: {path}")
        return path

    def stop_gps_data_logging(self) -> str:
        path = self.gps_logger.stop()
        self._event("INFO", f"GPS data logging stopped: {path}")
        return path

    def configure_ntrip(self, values: dict[str, Any]) -> dict[str, Any]:
        configure = getattr(self.hardware, "configure_ntrip", None)
        if not callable(configure):
            raise RuntimeError("NTRIP is unavailable on this hardware runtime")
        status = configure(values)
        self._event("INFO", "NTRIP configuration updated without exposing the password")
        return status

    def set_gps_settings(self, values: dict[str, Any]) -> dict[str, bool | float | int]:
        checked = self.settings.save_gps_settings(values)
        self._event("INFO", f"GPS safety settings saved: {checked}")
        return checked

    def _event(self, level: str, message: str) -> None:
        item = {"timestamp": time.time(), "level": level, "message": message}
        self._events = (self._events + [item])[-100:]
        method = level.lower() if level.lower() in {"info", "warning", "error"} else "info"
        getattr(LOG, method)(message)

    def _safe_outputs(self) -> None:
        self.steering_pwm = VALUES.steering_center_pwm
        self.throttle_pwm = VALUES.throttle_stop_pwm

    def return_to_auto(self, reason: str, *, log: bool = True) -> None:
        changed = self.mode != "AUTO" or self.failsafe_reason != reason
        self.mode = "AUTO"
        self.operation_state = "AUTO"
        self._manual_waiting_for_neutral = False
        self._manual_rearm_since = None
        self._gesture_since = None
        self._auto_to_manual_armed = False
        self.hil_enabled = False
        self._hil_position = None
        self._hil_course_deg = None
        self._safe_outputs()
        self.failsafe_reason = reason
        if log and changed:
            self._event("WARNING", f"AUTO safe: {reason}")

    def force_safe(self, reason: str) -> None:
        """Compatibility entry point: all fail-safe paths now return to AUTO."""
        self.return_to_auto(reason)

    def set_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode == "AUTO-SAFE":
            mode = "AUTO"
        if mode not in self.MODES:
            raise ValueError(f"invalid mode: {mode}")
        if self.estop:
            raise RuntimeError("Emergency Stop is latched")

        if mode != "NAVIGATION":
            self.hil_enabled = False
            self._hil_position = None
            self._hil_course_deg = None

        now = time.monotonic()
        snap = self.hardware.snapshot()
        self._safe_outputs()
        self._gesture_since = None
        if mode == "MANUAL":
            rc_ready = (
                snap.arduino_connected
                and snap.rc_steering_us is not None
                and snap.rc_throttle_us is not None
                and now - snap.rc_last_update <= VALUES.serial_stale_timeout_s
            )
            if not rc_ready:
                self.return_to_auto("ARDUINO_OR_RC_UNAVAILABLE")
                raise RuntimeError("Arduino/RC data is unavailable; MANUAL rejected")
            self._manual_waiting_for_neutral = True
            self._manual_rearm_since = None
            self.operation_state = "MANUAL_WAITING_NEUTRAL"
        elif mode == "NAVIGATION":
            self._manual_waiting_for_neutral = False
            self._auto_to_manual_armed = (
                snap.rc_throttle_us is not None
                and snap.rc_throttle_us < VALUES.auto_to_manual_throttle_us
            )
            self.operation_state = "NAVIGATION_WAITING_GPS"
            self._navigation_route_prepared = False
        elif mode == "REMOTE":
            self._manual_waiting_for_neutral = False
            self.remote_last_heartbeat = now
            self.remote_steering_pwm = VALUES.steering_center_pwm
            self.remote_throttle_pwm = VALUES.throttle_stop_pwm
            self.operation_state = "REMOTE_ACTIVE"
        else:
            self._manual_waiting_for_neutral = False
            self._auto_to_manual_armed = (
                snap.rc_throttle_us is not None
                and snap.rc_throttle_us < VALUES.auto_to_manual_throttle_us
            )
            self.operation_state = "AUTO"
        self.mode = mode
        self.failsafe_reason = ""
        self._event("INFO", f"Mode changed to {mode}")

    def emergency_stop(self) -> None:
        self.estop = True
        self.return_to_auto("EMERGENCY_STOP")
        self.operation_state = "EMERGENCY_STOP"
        self._event("ERROR", "Emergency Stop latched")

    def clear_estop(self) -> None:
        self.estop = False
        self.return_to_auto("ESTOP_CLEARED")
        self._event("INFO", "Emergency Stop cleared; AUTO safe output remains")

    def heartbeat(self) -> None:
        self.remote_last_heartbeat = time.monotonic()

    def set_remote_pwm(self, steering: int, throttle: int) -> None:
        if self.mode != "REMOTE":
            raise RuntimeError("REMOTE mode is not active")
        self.remote_steering_pwm = clamp(
            steering, VALUES.steering_low_pwm, VALUES.steering_high_pwm
        )
        self.remote_throttle_pwm = clamp(
            throttle,
            min(VALUES.throttle_forward_pwm, VALUES.throttle_reverse_pwm),
            max(VALUES.throttle_forward_pwm, VALUES.throttle_reverse_pwm),
        )

    def set_auto_cruise_pwm(self, value: int) -> None:
        checked = self.settings.validate_auto_cruise_pwm(value)
        self.settings.save_auto_cruise_pwm(checked)
        self._event("INFO", f"AUTO cruise PWM saved: {checked}")

    def set_multipath(self, values: dict[str, Any]) -> None:
        checked = self.settings.save_multipath_settings(values)
        self.routes.configure_multipath(checked)
        self._navigation_route_prepared = False
        self._event("INFO", f"Multi-Path settings saved: {checked}")

    def start_gps_recording(
        self, name: str, *, minimum_distance_m: float = 1.0,
        minimum_interval_s: float = 0.5, arrival_radius_m: float = 3.0
    ) -> None:
        snap = self.hardware.snapshot()
        now = time.monotonic()
        if (
            not snap.gps_connected
            or not snap.gps_fix
            or snap.gps_lat is None
            or snap.gps_lon is None
            or now - snap.gps_last_update > VALUES.gps_stale_timeout_s
        ):
            raise RuntimeError("GPS FIX is required before route recording")
        self.routes.start_recording(
            name, minimum_distance_m=minimum_distance_m,
            minimum_interval_s=minimum_interval_s, arrival_radius_m=arrival_radius_m,
        )
        self.routes.record_position((snap.gps_lat, snap.gps_lon), now)
        self._event("INFO", f"GPS route recording started: {self.routes.recording_name}")

    def stop_gps_recording(self, *, save: bool) -> str | None:
        recorded_name = self.routes.recording_name
        route_id = self.routes.stop_recording(save=save)
        if save:
            self._event("INFO", f"GPS route saved: {recorded_name} ({route_id})")
        else:
            self._event("INFO", f"GPS route recording cancelled: {recorded_name}")
        return route_id

    def start_hil(self, route_id: str | None = None) -> None:
        if self.estop:
            raise RuntimeError("Emergency Stop is latched")
        if route_id:
            self.routes.select(route_id)
        active = self.routes.active
        if active is None or len(active.points) < 2:
            raise RuntimeError("HIL requires a route with at least two waypoints")
        self.routes.select(active.route_id)
        self.hil_enabled = True
        self._hil_started_at = time.monotonic()
        self._hil_position = active.points[0]
        self._hil_course_deg = bearing_deg(active.points[0], active.points[1])
        try:
            self.set_mode("NAVIGATION")
        except Exception:
            self.hil_enabled = False
            self._hil_position = None
            self._hil_course_deg = None
            raise
        self.operation_state = "HIL_ACTIVE"
        self._event("WARNING", f"HIL started with real PWM output: {active.name}")

    def stop_hil(self) -> None:
        if not self.hil_enabled:
            raise RuntimeError("HIL is not active")
        self.return_to_auto("HIL_STOPPED", log=False)
        self.operation_state = "AUTO_SAFE"
        self._event("INFO", "HIL stopped; safe output applied")

    def select_route(self, route_id: str) -> None:
        """Select a route while immediately returning navigation output to safe."""

        self.routes.select(route_id)
        self._last_route_status = {}
        self._navigation_route_prepared = False
        self._safe_outputs()
        if self.mode == "NAVIGATION":
            self.operation_state = "NAVIGATION_WAITING_GPS"
        try:
            self.hardware.write_pwm(VALUES.steering_center_pwm, VALUES.throttle_stop_pwm)
        except Exception as exc:
            self.return_to_auto(f"PCA_WRITE_EXCEPTION:{type(exc).__name__}")
            self._event("ERROR", f"Safe output after route selection failed: {exc}")
            raise

    def _manual_output(self, steering_us: int, throttle_us: int, now: float) -> tuple[int, int]:
        if self._manual_waiting_for_neutral:
            neutral = abs(throttle_us - VALUES.throttle_center_us) <= 30
            if neutral:
                self._manual_rearm_since = self._manual_rearm_since or now
                if now - self._manual_rearm_since >= VALUES.manual_rearm_hold_s:
                    self._manual_waiting_for_neutral = False
                    self.operation_state = "MANUAL_ACTIVE"
                    self._event("INFO", "MANUAL activated after neutral hold")
            else:
                self._manual_rearm_since = None
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm

        steering = piecewise_map(
            steering_us,
            VALUES.steering_low_us,
            VALUES.steering_center_us,
            VALUES.steering_high_us,
            VALUES.steering_low_pwm,
            VALUES.steering_center_pwm,
            VALUES.steering_high_pwm,
        )
        throttle = piecewise_map(
            throttle_us,
            VALUES.throttle_reverse_us,
            VALUES.throttle_center_us,
            VALUES.throttle_forward_us,
            VALUES.throttle_reverse_pwm,
            VALUES.throttle_stop_pwm,
            VALUES.throttle_forward_pwm,
        )
        return steering, throttle

    def _check_gestures(self, steering_us: int, throttle_us: int, now: float) -> None:
        if self.mode == "MANUAL":
            active = (
                steering_us >= VALUES.manual_to_auto_steering_us
                and abs(throttle_us - VALUES.throttle_center_us)
                <= VALUES.manual_to_auto_neutral_tolerance_us
            )
            if active:
                self._gesture_since = self._gesture_since or now
                if now - self._gesture_since >= VALUES.manual_to_auto_hold_s:
                    self.set_mode("AUTO")
                    self._gesture_since = None
            else:
                self._gesture_since = None
        elif self.mode in {"AUTO", "NAVIGATION"}:
            # A throttle already held high when AUTO/NAVIGATION is selected is
            # not a new return-to-MANUAL gesture. Require one release first.
            if not self._auto_to_manual_armed:
                if throttle_us < VALUES.auto_to_manual_throttle_us:
                    self._auto_to_manual_armed = True
                self._gesture_since = None
                return
            if throttle_us >= VALUES.auto_to_manual_throttle_us:
                self._gesture_since = self._gesture_since or now
                if now - self._gesture_since >= VALUES.auto_to_manual_hold_s:
                    self.set_mode("MANUAL")
                    self._gesture_since = None
            else:
                self._gesture_since = None

    def _navigation_output(self, snap: Any, now: float) -> tuple[int, int]:
        gps_data = self._gps_data(snap, now)
        ntrip = self._ntrip_state()
        gate = navigation_gate_reason(
            gps_data,
            gps_data["health"],
            connected=bool(gps_data.get("connected")),
            hdop_max=self.settings.gps_navigation_max_hdop,
            rtk_required=self.settings.rtk_required_for_navigation,
            correction_age_s=ntrip.get("last_correction_age_s"),
            correction_max_s=self.settings.rtk_correction_max_age_s,
            rtk_fallback_to_gps=self.settings.rtk_fallback_to_gps,
        )
        if gate:
            self.operation_state = "NAVIGATION_WAITING_GPS"
            self.failsafe_reason = gate
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        active_route = self.routes.active
        if not self.routes.routes or active_route is None or not active_route.points:
            self.operation_state = "NAVIGATION_WAITING_ROUTE"
            self.failsafe_reason = "ROUTE_UNAVAILABLE"
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm

        position = (snap.gps_lat, snap.gps_lon)
        if not self._navigation_route_prepared and not self.hil_enabled:
            changed = self.routes.choose_nearest_group_route(position)
            self._navigation_route_prepared = True
            if changed and self.routes.active is not None:
                self._event("INFO", f"MULTI-PATH START ROUTE: {self.routes.active.name}")
        self._last_route_status = self.routes.update_position(position, now)
        if self._last_route_status.get("switched_route"):
            self._event("WARNING", f"MULTI-PATH ROUTE CHANGE: {self._last_route_status['active_route_name']}")
        if self._last_route_status.get("route_complete"):
            self.operation_state = "NAVIGATION_ROUTE_COMPLETE"
            self.failsafe_reason = "ROUTE_COMPLETE"
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        if snap.gps_course_deg is None:
            # A stationary GNSS receiver commonly has no course-over-ground.
            # Start straight so the receiver can establish a course, then the
            # normal bearing controller takes over on the next valid update.
            self.operation_state = "NAVIGATION_ACTIVE"
            self.failsafe_reason = ""
            return VALUES.steering_center_pwm, self.settings.auto_cruise_pwm

        target = (
            self._last_route_status["target_lat"],
            self._last_route_status["target_lon"],
        )
        error = angle_error_deg(bearing_deg(position, target), snap.gps_course_deg)
        if error >= 0:
            steering = VALUES.steering_center_pwm + min(error / 90.0, 1.0) * (
                VALUES.steering_high_pwm - VALUES.steering_center_pwm
            )
        else:
            steering = VALUES.steering_center_pwm + max(error / 90.0, -1.0) * (
                VALUES.steering_center_pwm - VALUES.steering_low_pwm
            )
        self.operation_state = "NAVIGATION_ACTIVE"
        self.failsafe_reason = ""
        return int(round(steering)), self.settings.auto_cruise_pwm

    def _hil_snapshot(self, snap: Any, now: float) -> Any:
        active = self.routes.active
        if active is None or len(active.points) < 2:
            raise RuntimeError("HIL route became unavailable")
        remaining = max(0.0, now - self._hil_started_at)
        position = active.points[-1]
        course = bearing_deg(active.points[-2], active.points[-1])
        for start, end in zip(active.points, active.points[1:]):
            segment_m = max(0.001, haversine_m(start, end))
            if remaining <= segment_m:
                ratio = remaining / segment_m
                position = (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                )
                course = bearing_deg(start, end)
                break
            remaining -= segment_m
        self._hil_position = position
        self._hil_course_deg = course
        values = vars(snap).copy()
        values.update(
            gps_connected=True,
            gps_fix=True,
            gps_quality=4,
            gps_lat=position[0],
            gps_lon=position[1],
            gps_satellites=max(8, int(getattr(snap, "gps_satellites", 0) or 0)),
            gps_hdop=getattr(snap, "gps_hdop", None) or 0.8,
            gps_course_deg=course,
            gps_last_update=now,
            gps_last_fix=now,
        )
        return SimpleNamespace(**values)

    def step(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        try:
            snap = self.hardware.snapshot()
            gps_data = self._gps_data(snap, now)
            if (
                self.routes.recording
                and snap.gps_connected
                and snap.gps_fix
                and snap.gps_lat is not None
                and snap.gps_lon is not None
                and now - snap.gps_last_update <= VALUES.gps_stale_timeout_s
            ):
                self.routes.record_position((snap.gps_lat, snap.gps_lon), now)
            update_at = float(gps_data.get("last_update_monotonic") or 0.0)
            if self.gps_logger.active and update_at > self._last_logged_gps_update:
                ntrip = self._ntrip_state()
                active = self.routes.active
                self.gps_logger.write({
                    "utc_time": gps_data.get("utc_time"),
                    "latitude": gps_data.get("latitude"), "longitude": gps_data.get("longitude"),
                    "altitude_m": gps_data.get("altitude_m"), "fix_quality": gps_data.get("fix_quality"),
                    "fix_label": gps_data.get("fix_label"), "satellites": gps_data.get("satellites"),
                    "hdop": gps_data.get("hdop"), "pdop": gps_data.get("pdop"), "vdop": gps_data.get("vdop"),
                    "speed_mps": gps_data.get("speed_mps"), "course_deg": gps_data.get("course_deg"),
                    "cno_avg_dbhz": gps_data.get("cno_avg_dbhz"), "hacc_m": gps_data.get("hacc_m"),
                    "rtk_state": gps_data.get("rtk_state"),
                    "rtk_correction_age_s": ntrip.get("last_correction_age_s"),
                    "gps_health": gps_data.get("health", {}).get("status"),
                    "active_route_id": active.route_id if active else "",
                    "navigation_state": self.operation_state,
                    "utm_easting": gps_data.get("utm_easting"), "utm_northing": gps_data.get("utm_northing"),
                    "utm_zone": gps_data.get("utm_zone"),
                })
                self._last_logged_gps_update = update_at
            if self.estop:
                self.return_to_auto("EMERGENCY_STOP", log=False)
                self.operation_state = "EMERGENCY_STOP"
            elif snap.rc_steering_us is not None and snap.rc_throttle_us is not None:
                self._check_gestures(snap.rc_steering_us, snap.rc_throttle_us, now)

            if self.estop:
                self._safe_outputs()
            elif self.mode == "MANUAL":
                if (
                    not snap.arduino_connected
                    or snap.rc_steering_us is None
                    or snap.rc_throttle_us is None
                    or now - snap.rc_last_update > VALUES.serial_stale_timeout_s
                ):
                    self._safe_outputs()
                    self._manual_waiting_for_neutral = True
                    self._manual_rearm_since = None
                    self.operation_state = "MANUAL_WAITING_RC"
                    self.failsafe_reason = "ARDUINO_OR_RC_LOST"
                else:
                    self.steering_pwm, self.throttle_pwm = self._manual_output(
                        snap.rc_steering_us, snap.rc_throttle_us, now
                    )
                    if self._manual_waiting_for_neutral:
                        self.failsafe_reason = ""
            elif self.mode == "REMOTE":
                if now - self.remote_last_heartbeat >= VALUES.remote_heartbeat_timeout_s:
                    self.return_to_auto("REMOTE_HEARTBEAT_TIMEOUT")
                else:
                    self.operation_state = "REMOTE_ACTIVE"
                    self.steering_pwm = self.remote_steering_pwm
                    self.throttle_pwm = self.remote_throttle_pwm
            elif self.mode == "NAVIGATION":
                navigation_snap = self._hil_snapshot(snap, now) if self.hil_enabled else snap
                self.steering_pwm, self.throttle_pwm = self._navigation_output(
                    navigation_snap, now
                )
                if self.hil_enabled and self.operation_state == "NAVIGATION_ACTIVE":
                    self.operation_state = "HIL_ACTIVE"
            else:
                rc_ready = (
                    snap.arduino_connected
                    and snap.rc_steering_us is not None
                    and snap.rc_throttle_us is not None
                    and now - snap.rc_last_update <= VALUES.serial_stale_timeout_s
                )
                if self.failsafe_reason:
                    self.operation_state = "AUTO_SAFE"
                    self._safe_outputs()
                elif not rc_ready:
                    self.operation_state = "AUTO_SAFE"
                    self.failsafe_reason = "ARDUINO_OR_RC_LOST"
                    self._safe_outputs()
                else:
                    self.operation_state = "AUTO_ACTIVE"
                    self.steering_pwm = VALUES.steering_center_pwm
                    self.throttle_pwm = self.settings.auto_cruise_pwm

            self.hardware.write_pwm(self.steering_pwm, self.throttle_pwm)
        except Exception as exc:
            self.return_to_auto(f"CONTROL_EXCEPTION:{type(exc).__name__}")
            try:
                self.hardware.write_pwm(VALUES.steering_center_pwm, VALUES.throttle_stop_pwm)
            except Exception as safe_exc:
                self._event("ERROR", f"Safe PWM write also failed: {safe_exc}")
            self._event("ERROR", f"Control exception: {exc}")

    def _route_state(self) -> dict[str, Any]:
        result = dict(self._last_route_status)
        active = self.routes.active
        selected = self.routes.selected
        result.setdefault("active_route_id", active.route_id if active else "")
        result.setdefault("active_route_name", active.name if active else "-")
        result["selected_route_id"] = selected.route_id if selected else ""
        result["selected_route_name"] = selected.name if selected else "-"
        result["persisted_selected_route_id"] = self.routes.persisted_selected_route_id
        result["selected_route_persisted"] = bool(
            selected and selected.route_id == self.routes.persisted_selected_route_id
        )
        result["storage_path"] = str(self.routes.route_path)
        result["multipath_config_path"] = (
            str(self.settings.config_path) if self.settings.config_path is not None else ""
        )
        result.setdefault("route_complete", self.routes.route_complete)
        result["load_error"] = self.routes.load_error
        result["multipath"] = self.routes.multipath_settings()
        return result

    def state(self) -> dict[str, Any]:
        snap = self.hardware.snapshot()
        gps_data = self._gps_data(snap)
        ntrip = self._ntrip_state()
        navigation_active = self.operation_state == "NAVIGATION_ACTIVE"
        return {
            "type": "telemetry",
            "timestamp": time.time(),
            "uptime_s": round(time.monotonic() - self.started_monotonic, 1),
            "mode": self.mode,
            "operation_state": self.operation_state,
            "navigation_active": navigation_active,
            "estop": self.estop,
            "failsafe_reason": self.failsafe_reason,
            "manual_waiting_for_neutral": self._manual_waiting_for_neutral,
            "auto_to_manual_gesture_armed": self._auto_to_manual_armed,
            "auto_cruise_pwm": self.settings.auto_cruise_pwm,
            "manual_throttle_mapping": {
                "reverse_input_us": VALUES.throttle_reverse_us,
                "neutral_input_us": VALUES.throttle_center_us,
                "forward_input_us": VALUES.throttle_forward_us,
                "reverse_pwm": VALUES.throttle_reverse_pwm,
                "stop_pwm": VALUES.throttle_stop_pwm,
                "forward_pwm": VALUES.throttle_forward_pwm,
            },
            "gps_recording": self.routes.recording_state(),
            "gps_logging": self.gps_logger.state(),
            "ntrip": ntrip,
            "gps_settings": self.settings.gps_settings(),
            "hil": {
                "active": self.hil_enabled,
                "lat": self._hil_position[0] if self._hil_position else None,
                "lon": self._hil_position[1] if self._hil_position else None,
                "course_deg": self._hil_course_deg,
            },
            "mock": bool(self.hardware.is_mock),
            "rc": {
                "steering_us": snap.rc_steering_us,
                "throttle_us": snap.rc_throttle_us,
                "age_s": round(max(0.0, time.monotonic() - snap.rc_last_update), 3),
            },
            "pca": {
                "frequency_hz": VALUES.pca_frequency_hz,
                "steering_channel": VALUES.steering_channel,
                "throttle_channel": VALUES.throttle_channel,
                "steering_pwm": self.steering_pwm,
                "throttle_pwm": self.throttle_pwm,
            },
            "gps": {
                "fix": gps_data.get("fix"), "quality": gps_data.get("fix_quality"),
                "fix_label": gps_data.get("fix_label"), "lat": gps_data.get("latitude"),
                "lon": gps_data.get("longitude"), "satellites": gps_data.get("satellites"),
                "altitude_m": gps_data.get("altitude_m"), "hdop": gps_data.get("hdop"),
                "pdop": gps_data.get("pdop"), "vdop": gps_data.get("vdop"),
                "cno_avg_dbhz": gps_data.get("cno_avg_dbhz"), "hacc_m": gps_data.get("hacc_m"),
                "speed_mps": gps_data.get("speed_mps"), "course_deg": gps_data.get("course_deg"),
                "utc_time": gps_data.get("utc_time"), "age_s": gps_data.get("age_s"),
                "last_fix_age_s": gps_data.get("last_fix_age_s"),
                "health": gps_data.get("health"), "rtk_state": gps_data.get("rtk_state"),
                "rtk_fallback_active": gps_data.get("rtk_fallback_active"),
                "navigation_fix_mode": gps_data.get("navigation_fix_mode"),
                "parser_error_count": gps_data.get("parser_error_count"),
                "utm_easting": gps_data.get("utm_easting"), "utm_northing": gps_data.get("utm_northing"),
                "utm_zone": gps_data.get("utm_zone"),
            },
            "devices": {
                "arduino": snap.arduino_connected,
                "gps": snap.gps_connected,
                "pca9685": snap.pca_connected,
            },
            "route": self._route_state(),
            "routes": self.routes.public_routes(),
            "hardware_errors": snap.errors,
            "events": self._events[-20:],
            "measured_values": asdict(VALUES),
        }

    def close(self) -> None:
        self.return_to_auto("DAEMON_SHUTDOWN")
        try:
            self.hardware.write_pwm(VALUES.steering_center_pwm, VALUES.throttle_stop_pwm)
        except Exception as exc:
            self._event("ERROR", f"Safe PWM write during shutdown failed: {exc}")
        finally:
            try:
                self.gps_logger.close()
            except Exception as exc:
                self._event("ERROR", f"GPS log close during shutdown failed: {exc}")
            finally:
                self.hardware.close()
