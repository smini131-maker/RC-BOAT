from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .constants import VALUES, clamp, piecewise_map
from .navigation import RouteManager, angle_error_deg, bearing_deg


@dataclass
class RcSample:
    connected: bool = False
    steering_us: int = 0
    throttle_us: int = 0
    updated_at: float = 0.0


@dataclass
class GpsSample:
    connected: bool = False
    fix: bool = False
    latitude: float = math.nan
    longitude: float = math.nan
    course_deg: float = math.nan
    hdop: float = math.nan
    health: str = "NO_FIX"
    rtk_state: str = "NO_RTK"
    correction_age_s: float = math.nan
    updated_at: float = 0.0


class ControllerLogic:
    MODES = {"AUTO", "MANUAL", "NAVIGATION", "REMOTE"}

    def __init__(self, routes: RouteManager, settings: dict[str, Any]) -> None:
        self.routes = routes
        self.settings = settings
        self.mode = "MANUAL"
        self.operation_state = "MANUAL_WAITING_RC"
        self.failsafe_reason = "BOOT_WAITING_RC"
        self.estop = False
        self.rc = RcSample()
        self.gps = GpsSample()
        self.steering_pwm = VALUES.steering_center_pwm
        self.throttle_pwm = VALUES.throttle_stop_pwm
        self.remote_steering_pwm = VALUES.steering_center_pwm
        self.remote_throttle_pwm = VALUES.throttle_stop_pwm
        self.remote_last_heartbeat = 0.0
        self._gesture_since: float | None = None
        self._manual_rearm_since: float | None = None
        self.manual_waiting_for_neutral = True
        self._auto_to_manual_armed = False
        self.last_route_status: dict[str, Any] = {}

    def update_rc(self, sample: RcSample) -> None:
        self.rc = sample

    def update_gps(self, sample: GpsSample) -> None:
        self.gps = sample

    def safe(self, reason: str, operation_state: str = "AUTO_SAFE") -> None:
        self.mode = "AUTO"
        self.operation_state = operation_state
        self.failsafe_reason = reason
        self.steering_pwm = VALUES.steering_center_pwm
        self.throttle_pwm = VALUES.throttle_stop_pwm
        self.manual_waiting_for_neutral = False
        self._gesture_since = None
        self._manual_rearm_since = None
        self._auto_to_manual_armed = False

    def set_mode(self, mode: str, now: float) -> None:
        mode = mode.upper().replace("-SAFE", "")
        if mode not in self.MODES:
            raise ValueError(f"invalid mode: {mode}")
        if self.estop:
            raise RuntimeError("Emergency Stop is latched")
        self.steering_pwm = VALUES.steering_center_pwm
        self.throttle_pwm = VALUES.throttle_stop_pwm
        self._gesture_since = None
        if mode == "MANUAL":
            if not self._rc_ready(now):
                self.safe("ARDUINO_OR_RC_UNAVAILABLE")
                raise RuntimeError("Arduino/RC data unavailable; MANUAL rejected")
            self.manual_waiting_for_neutral = True
            self._manual_rearm_since = None
            self.operation_state = "MANUAL_WAITING_NEUTRAL"
        elif mode == "REMOTE":
            self.manual_waiting_for_neutral = False
            self.remote_last_heartbeat = now
            self.remote_steering_pwm = VALUES.steering_center_pwm
            self.remote_throttle_pwm = VALUES.throttle_stop_pwm
            self.operation_state = "REMOTE_ACTIVE"
        elif mode == "NAVIGATION":
            self.manual_waiting_for_neutral = False
            self._auto_to_manual_armed = (
                self.rc.connected
                and self.rc.throttle_us < VALUES.auto_to_manual_throttle_us
            )
            self.operation_state = "NAVIGATION_WAITING_GPS"
        else:
            self.manual_waiting_for_neutral = False
            self._auto_to_manual_armed = (
                self.rc.connected
                and self.rc.throttle_us < VALUES.auto_to_manual_throttle_us
            )
            self.operation_state = "AUTO_SAFE"
        self.mode = mode
        self.failsafe_reason = ""

    def emergency_stop(self) -> None:
        self.estop = True
        self.safe("EMERGENCY_STOP", "EMERGENCY_STOP")

    def clear_estop(self) -> None:
        self.estop = False
        self.safe("ESTOP_CLEARED")

    def heartbeat(self, now: float) -> None:
        self.remote_last_heartbeat = now

    def set_remote_pwm(self, steering_pwm: int, throttle_pwm: int) -> None:
        if self.mode != "REMOTE":
            return
        self.remote_steering_pwm = clamp(
            steering_pwm,
            VALUES.steering_low_pwm,
            VALUES.steering_high_pwm,
        )
        self.remote_throttle_pwm = clamp(
            throttle_pwm,
            min(VALUES.throttle_reverse_pwm, VALUES.throttle_forward_pwm),
            max(VALUES.throttle_reverse_pwm, VALUES.throttle_forward_pwm),
        )

    def _rc_ready(self, now: float) -> bool:
        return self.rc.connected and now - self.rc.updated_at <= VALUES.serial_stale_timeout_s

    def _check_gestures(self, now: float) -> None:
        if not self._rc_ready(now):
            self._gesture_since = None
            return
        if self.mode == "MANUAL":
            active = (
                self.rc.steering_us >= VALUES.manual_to_auto_steering_us
                and abs(self.rc.throttle_us - VALUES.throttle_center_us)
                <= VALUES.manual_to_auto_neutral_tolerance_us
            )
            if active:
                self._gesture_since = self._gesture_since or now
                if now - self._gesture_since >= VALUES.manual_to_auto_hold_s:
                    self.set_mode("AUTO", now)
            else:
                self._gesture_since = None
        elif self.mode in {"AUTO", "NAVIGATION"}:
            if not self._auto_to_manual_armed:
                if self.rc.throttle_us < VALUES.auto_to_manual_throttle_us:
                    self._auto_to_manual_armed = True
                self._gesture_since = None
                return
            if self.rc.throttle_us >= VALUES.auto_to_manual_throttle_us:
                self._gesture_since = self._gesture_since or now
                if now - self._gesture_since >= VALUES.auto_to_manual_hold_s:
                    self.set_mode("MANUAL", now)
            else:
                self._gesture_since = None

    def _manual_output(self, now: float) -> tuple[int, int]:
        if self.manual_waiting_for_neutral:
            neutral = abs(self.rc.throttle_us - VALUES.throttle_center_us) <= 30
            if neutral:
                self._manual_rearm_since = self._manual_rearm_since or now
                if now - self._manual_rearm_since >= VALUES.manual_rearm_hold_s:
                    self.manual_waiting_for_neutral = False
                    self.operation_state = "MANUAL_ACTIVE"
            else:
                self._manual_rearm_since = None
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        steering = piecewise_map(
            self.rc.steering_us,
            VALUES.steering_low_us,
            VALUES.steering_center_us,
            VALUES.steering_high_us,
            VALUES.steering_low_pwm,
            VALUES.steering_center_pwm,
            VALUES.steering_high_pwm,
        )
        throttle = piecewise_map(
            self.rc.throttle_us,
            VALUES.throttle_reverse_us,
            VALUES.throttle_center_us,
            VALUES.throttle_forward_us,
            VALUES.throttle_reverse_pwm,
            VALUES.throttle_stop_pwm,
            VALUES.throttle_forward_pwm,
        )
        return steering, throttle

    def _navigation_gate(self, now: float) -> str:
        if not self.gps.connected:
            return "GPS_DISCONNECTED"
        if not self.gps.fix:
            return "GPS_NO_FIX"
        if now - self.gps.updated_at > float(self.settings["gps_stale_s"]):
            return "GPS_STALE"
        if self.gps.health in {"BAD", "NO_FIX", "STALE"}:
            return "GPS_HEALTH_" + self.gps.health
        if math.isfinite(self.gps.hdop):
            if self.gps.hdop > float(self.settings["navigation_max_hdop"]):
                return "GPS_HDOP_BAD"
        if self.settings.get("rtk_required_for_navigation", False):
            rtk_fixed = self.gps.rtk_state == "RTK_FIXED"
            correction_fresh = (
                math.isfinite(self.gps.correction_age_s)
                and self.gps.correction_age_s
                <= float(self.settings["rtk_correction_max_age_s"])
            )
            if not (rtk_fixed and correction_fresh):
                if not self.settings.get("rtk_fallback_to_gps", True):
                    return "RTK_REQUIRED"
        if not math.isfinite(self.gps.latitude) or not math.isfinite(self.gps.longitude):
            return "GPS_POSITION_INVALID"
        return ""

    def _navigation_output(self, now: float) -> tuple[int, int]:
        gate = self._navigation_gate(now)
        if gate:
            self.operation_state = "NAVIGATION_WAITING_GPS"
            self.failsafe_reason = gate
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        if self.routes.active is None:
            self.operation_state = "NAVIGATION_WAITING_ROUTE"
            self.failsafe_reason = "ROUTE_UNAVAILABLE"
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        position = (self.gps.latitude, self.gps.longitude)
        self.last_route_status = self.routes.update_position(position, now)
        if self.last_route_status["route_complete"]:
            self.operation_state = "NAVIGATION_ROUTE_COMPLETE"
            self.failsafe_reason = "ROUTE_COMPLETE"
            return VALUES.steering_center_pwm, VALUES.throttle_stop_pwm
        target = self.last_route_status["target"]
        if not math.isfinite(self.gps.course_deg):
            steering = VALUES.steering_center_pwm
        else:
            error = angle_error_deg(bearing_deg(position, target), self.gps.course_deg)
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
        return int(round(steering)), int(self.settings["auto_cruise_pwm"])

    def step(self, now: float) -> tuple[int, int]:
        if self.routes.recording and self._navigation_gate(now) == "":
            self.routes.record_position((self.gps.latitude, self.gps.longitude), now)
        if self.estop:
            self.safe("EMERGENCY_STOP", "EMERGENCY_STOP")
            return self.steering_pwm, self.throttle_pwm
        self._check_gestures(now)
        if self.mode == "MANUAL":
            if not self._rc_ready(now):
                self.steering_pwm = VALUES.steering_center_pwm
                self.throttle_pwm = VALUES.throttle_stop_pwm
                self.manual_waiting_for_neutral = True
                self._manual_rearm_since = None
                self.operation_state = "MANUAL_WAITING_RC"
                self.failsafe_reason = "ARDUINO_OR_RC_LOST"
            else:
                self.steering_pwm, self.throttle_pwm = self._manual_output(now)
                if self.manual_waiting_for_neutral:
                    self.failsafe_reason = ""
        elif self.mode == "REMOTE":
            if now - self.remote_last_heartbeat >= VALUES.remote_heartbeat_timeout_s:
                self.safe("REMOTE_HEARTBEAT_TIMEOUT")
            else:
                self.operation_state = "REMOTE_ACTIVE"
                self.steering_pwm = self.remote_steering_pwm
                self.throttle_pwm = self.remote_throttle_pwm
        elif self.mode == "NAVIGATION":
            self.steering_pwm, self.throttle_pwm = self._navigation_output(now)
        else:
            if not self._rc_ready(now):
                self.operation_state = "AUTO_SAFE"
                self.failsafe_reason = "ARDUINO_OR_RC_LOST"
                self.steering_pwm = VALUES.steering_center_pwm
                self.throttle_pwm = VALUES.throttle_stop_pwm
            else:
                self.operation_state = "AUTO_ACTIVE"
                self.failsafe_reason = ""
                self.steering_pwm = VALUES.steering_center_pwm
                self.throttle_pwm = int(self.settings["auto_cruise_pwm"])
        return self.steering_pwm, self.throttle_pwm
