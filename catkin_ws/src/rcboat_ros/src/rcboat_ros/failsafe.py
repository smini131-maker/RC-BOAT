"""Autonomous progress monitor. Lack of motion is suspicion, not shaft feedback."""
import math
from .path_tracking import meters


class ProgressMonitor:
    def __init__(self):
        self.reset()

    def reset(self):
        self.since = None
        self.origin = None

    def update(self, now, gps, throttle, enabled=True, timeout=15.0,
               min_pwm=6550, min_speed=0.15, min_distance=1.0):
        try:
            position = (float(gps['latitude']), float(gps['longitude']))
            speed = float(gps['speed_mps'])
            usable = all(math.isfinite(v) for v in (*position, speed))
        except (KeyError, TypeError, ValueError):
            usable = False
        if not enabled or throttle < min_pwm or not usable or speed >= min_speed:
            self.reset()
            return False
        if self.since is None or meters(self.origin, position) >= min_distance:
            self.since, self.origin = now, position
        return now - self.since >= timeout
