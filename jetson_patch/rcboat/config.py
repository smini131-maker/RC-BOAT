from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ARDUINO_BY_ID = (
    "/dev/serial/by-id/"
    "usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00"
)
GPS_BY_ID = (
    "/dev/serial/by-id/"
    "usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00"
)


@dataclass(frozen=True)
class ControlValues:
    # Current measured receiver pulse widths (microseconds).
    steering_low_us: int = 1214
    steering_center_us: int = 1640
    steering_high_us: int = 2000
    throttle_reverse_us: int = 1106
    throttle_center_us: int = 1500
    throttle_forward_us: int = 1786

    # Current measured PCA9685 16-bit duty values.
    steering_low_pwm: int = 4900
    steering_center_pwm: int = 6000
    steering_high_pwm: int = 7300
    throttle_reverse_pwm: int = 5800
    throttle_stop_pwm: int = 6450
    throttle_forward_pwm: int = 7000

    pca_frequency_hz: int = 60
    steering_channel: int = 0
    throttle_channel: int = 6

    # Existing transmitter gestures.
    manual_to_auto_steering_us: int = 1950
    manual_to_auto_neutral_tolerance_us: int = 30
    manual_to_auto_hold_s: float = 3.0
    auto_to_manual_throttle_us: int = 1850
    auto_to_manual_hold_s: float = 0.5
    manual_rearm_hold_s: float = 0.3

    remote_heartbeat_timeout_s: float = 0.7
    serial_stale_timeout_s: float = 0.7
    gps_stale_timeout_s: float = 2.0


VALUES = ControlValues()

AUTO_CRUISE_DEFAULT_PWM = 6650
AUTO_CRUISE_MIN_PWM = 6480
AUTO_CRUISE_MAX_PWM = 6900

MULTIPATH_DEFAULTS: dict[str, bool | float] = {
    "enabled": True,
    "endpoint_tolerance_m": 0.75,
    "off_route_distance_m": 8.0,
    "off_route_hold_s": 3.0,
    "closer_advantage_m": 2.0,
    "switch_cooldown_s": 5.0,
}


@dataclass
class RuntimeSettings:
    # Kept for compatibility with older boat_config.json files. Normal GPS
    # navigation now uses auto_cruise_pwm, the same value as straight AUTO.
    nav_throttle_pwm: int | None = None
    mock_nav_throttle_pwm: int = 6200
    reconnect_interval_s: float = 1.0
    auto_cruise_pwm: int = AUTO_CRUISE_DEFAULT_PWM
    multipath_enabled: bool = True
    multipath_endpoint_tolerance_m: float = 0.75
    multipath_off_route_distance_m: float = 8.0
    multipath_off_route_hold_s: float = 3.0
    multipath_closer_advantage_m: float = 2.0
    multipath_switch_cooldown_s: float = 5.0
    gps_baudrate: int = 115200
    gps_health_stale_s: float = 2.0
    gps_navigation_max_hdop: float = 3.0
    rtk_required_for_navigation: bool = False
    rtk_fallback_to_gps: bool = True
    rtk_correction_max_age_s: float = 10.0
    config_path: Path | None = field(default=None, repr=False, compare=False)

    def navigation_throttle(self, is_mock: bool) -> int | None:
        value = self.mock_nav_throttle_pwm if is_mock else self.nav_throttle_pwm
        if value is None:
            return None
        lower = min(VALUES.throttle_stop_pwm, VALUES.throttle_forward_pwm)
        upper = max(VALUES.throttle_stop_pwm, VALUES.throttle_forward_pwm)
        if not lower <= value <= upper:
            raise ValueError(
                f"navigation throttle must be between {VALUES.throttle_forward_pwm} "
                f"and {VALUES.throttle_stop_pwm}: {value}"
            )
        return value

    def validate_auto_cruise_pwm(self, value: int | None = None) -> int:
        checked = self.auto_cruise_pwm if value is None else value
        if isinstance(checked, bool) or not isinstance(checked, int):
            raise ValueError("auto_cruise_pwm must be an integer")
        if not AUTO_CRUISE_MIN_PWM <= checked <= AUTO_CRUISE_MAX_PWM:
            raise ValueError("auto_cruise_pwm out of allowed range")
        return checked

    def save_auto_cruise_pwm(self, value: int) -> None:
        checked = self.validate_auto_cruise_pwm(value)
        if self.config_path is None:
            raise RuntimeError("boat_config.json path is unavailable")

        payload: dict[str, Any] = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["auto_cruise_pwm"] = checked
        temporary = self.config_path.with_name(f".{self.config_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.config_path)
        self.auto_cruise_pwm = checked

    def multipath_settings(self) -> dict[str, bool | float]:
        values: dict[str, bool | float] = {
            "enabled": self.multipath_enabled,
            "endpoint_tolerance_m": self.multipath_endpoint_tolerance_m,
            "off_route_distance_m": self.multipath_off_route_distance_m,
            "off_route_hold_s": self.multipath_off_route_hold_s,
            "closer_advantage_m": self.multipath_closer_advantage_m,
            "switch_cooldown_s": self.multipath_switch_cooldown_s,
        }
        if not isinstance(values["enabled"], bool):
            raise ValueError("multipath enabled must be boolean")
        limits = {
            "endpoint_tolerance_m": (0.10, 1.00),
            "off_route_distance_m": (1.0, 100.0),
            "off_route_hold_s": (0.0, 30.0),
            "closer_advantage_m": (0.0, 50.0),
            "switch_cooldown_s": (0.0, 60.0),
        }
        for key, (low, high) in limits.items():
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"multipath {key} must be numeric")
            if not low <= float(value) <= high:
                raise ValueError(f"multipath {key} must be between {low} and {high}")
            values[key] = float(value)
        return values

    def save_multipath_settings(self, values: dict[str, Any]) -> dict[str, bool | float]:
        unknown = set(values) - set(MULTIPATH_DEFAULTS)
        if unknown:
            raise ValueError(f"unknown multipath setting: {sorted(unknown)[0]}")
        candidate_values = self.multipath_settings()
        candidate_values.update(values)
        candidate = RuntimeSettings(
            multipath_enabled=candidate_values["enabled"],
            multipath_endpoint_tolerance_m=candidate_values["endpoint_tolerance_m"],
            multipath_off_route_distance_m=candidate_values["off_route_distance_m"],
            multipath_off_route_hold_s=candidate_values["off_route_hold_s"],
            multipath_closer_advantage_m=candidate_values["closer_advantage_m"],
            multipath_switch_cooldown_s=candidate_values["switch_cooldown_s"],
        )
        checked = candidate.multipath_settings()
        if self.config_path is None:
            raise RuntimeError("boat_config.json path is unavailable")
        payload: dict[str, Any] = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["multipath"] = checked
        temporary = self.config_path.with_name(f".{self.config_path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.config_path)
        for key, value in checked.items():
            setattr(self, f"multipath_{key}", value)
        return checked

    def gps_settings(self) -> dict[str, bool | float | int]:
        if self.gps_baudrate <= 0:
            raise ValueError("gps_baudrate must be positive")
        if not 0.5 <= self.gps_health_stale_s <= 30.0:
            raise ValueError("gps_health_stale_s must be between 0.5 and 30")
        if not 0.5 <= self.gps_navigation_max_hdop <= 20.0:
            raise ValueError("gps_navigation_max_hdop must be between 0.5 and 20")
        if not 1.0 <= self.rtk_correction_max_age_s <= 120.0:
            raise ValueError("rtk_correction_max_age_s must be between 1 and 120")
        return {
            "baudrate": int(self.gps_baudrate),
            "health_stale_s": float(self.gps_health_stale_s),
            "navigation_max_hdop": float(self.gps_navigation_max_hdop),
            "rtk_required_for_navigation": bool(self.rtk_required_for_navigation),
            "rtk_fallback_to_gps": bool(self.rtk_fallback_to_gps),
            "rtk_correction_max_age_s": float(self.rtk_correction_max_age_s),
        }

    def save_gps_settings(self, values: dict[str, Any]) -> dict[str, bool | float | int]:
        allowed = {
            "health_stale_s", "navigation_max_hdop",
            "rtk_required_for_navigation", "rtk_fallback_to_gps", "rtk_correction_max_age_s",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown GPS setting: {sorted(unknown)[0]}")
        if "health_stale_s" in values:
            self.gps_health_stale_s = float(values["health_stale_s"])
        if "navigation_max_hdop" in values:
            self.gps_navigation_max_hdop = float(values["navigation_max_hdop"])
        if "rtk_required_for_navigation" in values:
            self.rtk_required_for_navigation = bool(values["rtk_required_for_navigation"])
        if "rtk_fallback_to_gps" in values:
            self.rtk_fallback_to_gps = bool(values["rtk_fallback_to_gps"])
        if "rtk_correction_max_age_s" in values:
            self.rtk_correction_max_age_s = float(values["rtk_correction_max_age_s"])
        checked = self.gps_settings()
        if self.config_path is None:
            raise RuntimeError("boat_config.json path is unavailable")
        payload: dict[str, Any] = json.loads(self.config_path.read_text(encoding="utf-8"))
        current = payload.get("gps") if isinstance(payload.get("gps"), dict) else {}
        current.update(checked)
        payload["gps"] = current
        temporary = self.config_path.with_name(f".{self.config_path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.config_path)
        return checked


def load_runtime_settings(path: str | Path) -> RuntimeSettings:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    multipath = payload.get("multipath") if isinstance(payload.get("multipath"), dict) else {}
    gps = payload.get("gps") if isinstance(payload.get("gps"), dict) else {}
    settings = RuntimeSettings(
        nav_throttle_pwm=(
            None if payload.get("nav_throttle_pwm") is None else int(payload["nav_throttle_pwm"])
        ),
        mock_nav_throttle_pwm=int(payload.get("mock_nav_throttle_pwm", 6200)),
        reconnect_interval_s=float(payload.get("reconnect_interval_s", 1.0)),
        auto_cruise_pwm=int(payload.get("auto_cruise_pwm", AUTO_CRUISE_DEFAULT_PWM)),
        multipath_enabled=multipath.get("enabled", MULTIPATH_DEFAULTS["enabled"]),
        multipath_endpoint_tolerance_m=float(multipath.get("endpoint_tolerance_m", MULTIPATH_DEFAULTS["endpoint_tolerance_m"])),
        multipath_off_route_distance_m=float(multipath.get("off_route_distance_m", MULTIPATH_DEFAULTS["off_route_distance_m"])),
        multipath_off_route_hold_s=float(multipath.get("off_route_hold_s", MULTIPATH_DEFAULTS["off_route_hold_s"])),
        multipath_closer_advantage_m=float(multipath.get("closer_advantage_m", MULTIPATH_DEFAULTS["closer_advantage_m"])),
        multipath_switch_cooldown_s=float(multipath.get("switch_cooldown_s", MULTIPATH_DEFAULTS["switch_cooldown_s"])),
        gps_baudrate=int(gps.get("baudrate", 115200)),
        gps_health_stale_s=float(gps.get("health_stale_s", VALUES.gps_stale_timeout_s)),
        gps_navigation_max_hdop=float(gps.get("navigation_max_hdop", 3.0)),
        rtk_required_for_navigation=bool(gps.get("rtk_required_for_navigation", False)),
        rtk_fallback_to_gps=bool(gps.get("rtk_fallback_to_gps", True)),
        rtk_correction_max_age_s=float(gps.get("rtk_correction_max_age_s", 10.0)),
        config_path=config_path,
    )
    settings.validate_auto_cruise_pwm()
    settings.multipath_settings()
    settings.gps_settings()
    return settings
