from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlValues:
    steering_low_us: int = 1214
    steering_center_us: int = 1640
    steering_high_us: int = 2000
    throttle_reverse_us: int = 1106
    throttle_center_us: int = 1500
    throttle_forward_us: int = 1786

    steering_low_pwm: int = 4900
    steering_center_pwm: int = 6000
    steering_high_pwm: int = 7300
    throttle_reverse_pwm: int = 5800
    throttle_stop_pwm: int = 6450
    throttle_forward_pwm: int = 7000

    pca_frequency_hz: int = 60
    steering_channel: int = 0
    throttle_channel: int = 6

    manual_to_auto_steering_us: int = 1950
    manual_to_auto_neutral_tolerance_us: int = 30
    manual_to_auto_hold_s: float = 3.0
    auto_to_manual_throttle_us: int = 1850
    auto_to_manual_hold_s: float = 0.5
    manual_rearm_hold_s: float = 0.3

    remote_heartbeat_timeout_s: float = 0.7
    serial_stale_timeout_s: float = 0.7
    gps_stale_timeout_s: float = 2.0
    pwm_watchdog_timeout_s: float = 0.3


VALUES = ControlValues()
AUTO_CRUISE_MIN_PWM = 6480
AUTO_CRUISE_MAX_PWM = 6900


def clamp(value: float, low: int, high: int) -> int:
    return int(round(max(low, min(high, value))))


def piecewise_map(
    value: int,
    x0: int,
    x1: int,
    x2: int,
    y0: int,
    y1: int,
    y2: int,
) -> int:
    if value <= x1:
        if x1 == x0:
            return y1
        ratio = (max(x0, value) - x0) / (x1 - x0)
        return int(round(y0 + ratio * (y1 - y0)))
    if x2 == x1:
        return y1
    ratio = (min(x2, value) - x1) / (x2 - x1)
    return int(round(y1 + ratio * (y2 - y1)))
