"""Small pure helpers; ROS dependency is intentionally optional for unit tests."""
import json
import math
import time

SAFE_STEERING = 6000
SAFE_THROTTLE = 6450

def pack(**kwargs):
    return json.dumps(kwargs, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

def unpack(msg):
    try:
        result = json.loads(msg.data if hasattr(msg, 'data') else msg)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}

def fresh(stamp, max_age, now=None):
    now = time.monotonic() if now is None else now
    return stamp > 0 and 0 <= now - stamp <= max_age

def finite_coordinate(lat, lon):
    try:
        return math.isfinite(float(lat)) and math.isfinite(float(lon)) and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
    except (TypeError, ValueError):
        return False

def gps_is_healthy(data, now=None, stale_s=2.0, max_hdop=None):
    """Return whether a current, finite GNSS FIX is available.

    ``max_hdop`` is retained only for call-site compatibility.  HDOP, hAcc,
    C/N0, speed and course-quality remain diagnostic telemetry and must not
    disable navigation by crossing an operator-selected numeric threshold.
    """
    now = time.monotonic() if now is None else now
    if not data.get('fix') or not finite_coordinate(data.get('latitude'), data.get('longitude')):
        return False
    try:
        return fresh(float(data.get('last_valid_monotonic', 0)), stale_s, now)
    except (TypeError, ValueError):
        return False

def clamp(value, lo, hi):
    return max(lo, min(hi, value))

def lerp(value, old_lo, old_hi, new_lo, new_hi):
    return new_lo + (clamp(value, old_lo, old_hi) - old_lo) * (new_hi - new_lo) / (old_hi - old_lo)

def cno_quality(value):
    return 'UNKNOWN' if value is None else 'GOOD' if value >= 30 else 'WARNING' if value >= 25 else 'BAD'
