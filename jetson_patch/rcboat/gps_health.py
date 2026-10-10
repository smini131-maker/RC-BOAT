from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GpsHealthThresholds:
    stale_s: float = 2.0
    satellite_good: int = 8
    satellite_warning: int = 6
    hdop_excellent: float = 1.0
    hdop_good: float = 2.0
    hdop_max_navigation: float = 3.0
    pdop_good: float = 2.0
    pdop_warning: float = 4.0
    vdop_good: float = 1.5
    cno_good: float = 40.0
    cno_warning: float = 35.0
    hacc_good_m: float = 1.5
    hacc_warning_m: float = 3.0
    correction_good_s: float = 5.0
    correction_warning_s: float = 10.0


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def evaluate_gps_health(
    source: Any,
    *,
    connected: bool,
    now: float | None = None,
    correction_age_s: float | None = None,
    thresholds: GpsHealthThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or GpsHealthThresholds()
    now = time.monotonic() if now is None else now
    last_update = float(_value(source, "last_update_monotonic", _value(source, "gps_last_update", 0.0)) or 0.0)
    age_s = max(0.0, now - last_update) if last_update > 0 else None
    fix = bool(_value(source, "fix", _value(source, "gps_fix", False)))
    latitude = _value(source, "latitude", _value(source, "gps_lat"))
    longitude = _value(source, "longitude", _value(source, "gps_lon"))
    satellites = int(_value(source, "satellites", _value(source, "gps_satellites", 0)) or 0)
    hdop = _value(source, "hdop", _value(source, "gps_hdop"))
    pdop = _value(source, "pdop")
    vdop = _value(source, "vdop")
    cno = _value(source, "cno_avg_dbhz")
    hacc = _value(source, "hacc_m")

    reasons: list[str] = []
    levels: list[int] = []  # GOOD 0, WARNING 1, BAD 2
    navigation_levels: list[int] = []
    if not connected:
        return {
            "status": "BAD", "navigation_status": "BAD", "rtk_status": "UNAVAILABLE",
            "reasons": ["GPS disconnected"], "age_s": age_s,
        }
    if age_s is None or age_s > thresholds.stale_s:
        value = "unknown" if age_s is None else f"{age_s:.1f} s"
        return {
            "status": "STALE", "navigation_status": "STALE", "rtk_status": "UNAVAILABLE",
            "reasons": [f"GPS data age {value}"], "age_s": age_s,
        }
    if not fix or latitude is None or longitude is None:
        return {
            "status": "NO_FIX", "navigation_status": "NO_FIX", "rtk_status": "UNAVAILABLE",
            "reasons": ["No valid GPS position"], "age_s": age_s,
        }

    if satellites >= thresholds.satellite_good:
        reasons.append(f"Satellites {satellites}")
        levels.append(0)
        navigation_levels.append(0)
    elif satellites >= thresholds.satellite_warning:
        reasons.append(f"Satellites {satellites} (warning)")
        levels.append(1)
        navigation_levels.append(1)
    else:
        reasons.append(f"Satellites {satellites} (low)")
        levels.append(2)
        navigation_levels.append(2)

    if hdop is None:
        reasons.append("HDOP N/A")
        levels.append(1)
        navigation_levels.append(1)
    elif float(hdop) <= thresholds.hdop_good:
        reasons.append(f"HDOP {float(hdop):.2f}")
        levels.append(0)
        navigation_levels.append(0)
    elif float(hdop) <= thresholds.hdop_max_navigation:
        reasons.append(f"HDOP {float(hdop):.2f} (warning)")
        levels.append(1)
        navigation_levels.append(1)
    else:
        reasons.append(f"HDOP {float(hdop):.2f} > {thresholds.hdop_max_navigation:.1f}")
        levels.append(2)
        navigation_levels.append(2)

    if pdop is not None:
        level = 0 if float(pdop) <= thresholds.pdop_good else 1 if float(pdop) <= thresholds.pdop_warning else 2
        reasons.append(f"PDOP {float(pdop):.2f}" + (" (bad)" if level == 2 else ""))
        levels.append(level)
        navigation_levels.append(level)
    if vdop is not None:
        level = 0 if float(vdop) <= thresholds.vdop_good else 1
        reasons.append(f"VDOP {float(vdop):.2f}" + (" (warning)" if level else ""))
        levels.append(level)
        navigation_levels.append(level)
    if cno is not None:
        level = 0 if float(cno) >= thresholds.cno_good else 1 if float(cno) >= thresholds.cno_warning else 2
        reasons.append(f"C/N0 {float(cno):.1f} dB-Hz" + (" (low)" if level == 2 else ""))
        levels.append(level)
        navigation_levels.append(level)
    if hacc is not None:
        level = 0 if float(hacc) <= thresholds.hacc_good_m else 1 if float(hacc) <= thresholds.hacc_warning_m else 2
        reasons.append(f"hAcc {float(hacc):.2f} m" + (" (bad)" if level == 2 else ""))
        levels.append(level)
        navigation_levels.append(level)
    rtk_status = "UNAVAILABLE"
    if correction_age_s is not None:
        level = 0 if correction_age_s <= thresholds.correction_good_s else 1 if correction_age_s <= thresholds.correction_warning_s else 2
        reasons.append(f"RTK correction {correction_age_s:.1f} s" + (" stale" if level == 2 else ""))
        levels.append(level)
        rtk_status = "BAD" if level == 2 else "WARNING" if level == 1 else "GOOD"

    worst = max(levels, default=1)
    navigation_worst = max(navigation_levels, default=1)
    return {
        "status": "BAD" if worst >= 2 else "WARNING" if worst == 1 else "GOOD",
        "navigation_status": (
            "BAD" if navigation_worst >= 2 else "WARNING" if navigation_worst == 1 else "GOOD"
        ),
        "rtk_status": rtk_status,
        "reasons": reasons,
        "age_s": age_s,
    }


def navigation_gate_reason(
    source: Any,
    health: dict[str, Any],
    *,
    connected: bool,
    hdop_max: float,
    rtk_required: bool,
    correction_age_s: float | None,
    correction_max_s: float = 10.0,
    rtk_fallback_to_gps: bool = True,
) -> str | None:
    if not connected:
        return "GPS_DISCONNECTED"
    status = str(health.get("navigation_status", health.get("status", "BAD")))
    if status == "STALE":
        return "GPS_STALE"
    if not bool(_value(source, "fix", _value(source, "gps_fix", False))):
        return "GPS_NO_FIX"
    latitude = _value(source, "latitude", _value(source, "gps_lat"))
    longitude = _value(source, "longitude", _value(source, "gps_lon"))
    if latitude is None or longitude is None:
        return "GPS_DATA_INVALID"
    hdop = _value(source, "hdop", _value(source, "gps_hdop"))
    if hdop is not None and float(hdop) > hdop_max:
        return "GPS_HDOP_BAD"
    if status == "BAD":
        return "GPS_HEALTH_BAD"
    # RTK/NTRIP improves precision but is not a propulsion safety dependency when
    # fallback is enabled.  A valid ordinary GPS fix therefore keeps navigation
    # running even if RTK Fixed or correction data is lost.
    if rtk_required and not rtk_fallback_to_gps:
        rtk_state = str(_value(source, "rtk_state", "UNKNOWN"))
        if rtk_state != "RTK_FIXED":
            return "RTK_REQUIRED"
        if correction_age_s is None or correction_age_s > correction_max_s:
            return "RTK_CORRECTION_STALE"
    return None

