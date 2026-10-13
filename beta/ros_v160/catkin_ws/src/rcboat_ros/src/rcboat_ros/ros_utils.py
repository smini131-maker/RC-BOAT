from __future__ import annotations

import math
import time
from typing import Any


def monotonic_age(last_update: float) -> float:
    if last_update <= 0:
        return float("inf")
    return max(0.0, time.monotonic() - last_update)


def finite_or_nan(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if math.isfinite(result) else float("nan")


def optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clamp_int(value: float, low: int, high: int) -> int:
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
        span = max(1, x1 - x0)
        ratio = max(0.0, min(1.0, (value - x0) / span))
        return int(round(y0 + ratio * (y1 - y0)))
    span = max(1, x2 - x1)
    ratio = max(0.0, min(1.0, (value - x1) / span))
    return int(round(y1 + ratio * (y2 - y1)))
