"""Shared, ROS-free input calibration and command validation (microseconds != duty16)."""
from copy import deepcopy
import math

CRUISE_MIN = 6480
THROTTLE_FORWARD_MAX = 7397
CRUISE_MAX = THROTTLE_FORWARD_MAX
CRUISE_STEP = 10
CRUISE_DEFAULT = 6650
NAV_RAMP_RATE = 250.0 / 1.5  # 6650 -> 6900 in 1.5 s; fixed PWM/s, not vessel speed.
RC_STALE_S = .75
RC_DEFAULTS = {
    'steering': dict(min_us=1004.0, center_us=1620.0, max_us=1985.0,
                     deadband_us=4.0, valid_min_us=970.0, valid_max_us=2011.0),
    # 31 preserves the previous entire 1470..1530 neutral interval after recentering.
    'throttle': dict(min_us=1118.0, center_us=1499.0, max_us=1881.0,
                     deadband_us=31.0, valid_min_us=1090.0, valid_max_us=1908.0),
}
OUTPUT_DEFAULTS = dict(steering_low=4900, steering_center=6000, steering_high=7300,
                       throttle_reverse_max=5800, throttle_stop=6450, throttle_forward_max=THROTTLE_FORWARD_MAX)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite numeric value required')
    return float(value)


def validate_rc(config):
    if not isinstance(config, dict) or set(config) != set(RC_DEFAULTS):
        raise ValueError('rc_input_calibration requires steering and throttle')
    result = deepcopy(config)
    for name, axis in result.items():
        if not isinstance(axis, dict) or set(axis) != set(RC_DEFAULTS[name]):
            raise ValueError('invalid RC calibration fields: ' + name)
        axis.update({key: number(value) for key, value in axis.items()})
        lo, center, hi, dead = (axis[k] for k in ('min_us', 'center_us', 'max_us', 'deadband_us'))
        if not (700 <= axis['valid_min_us'] <= lo < center-dead <= center+dead < hi <= axis['valid_max_us'] <= 2300) or dead < 0:
            raise ValueError('invalid RC calibration ordering/range: ' + name)
    return result


def load_rc(get_param):
    return validate_rc(get_param('/rcboat/rc_input_calibration', deepcopy(RC_DEFAULTS)))


def load_output(get_param):
    result = {key: get_param('/rcboat/' + key, value) for key, value in OUTPUT_DEFAULTS.items()}
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535 for v in result.values()):
        raise ValueError('PCA calibration must contain integer duty16 values')
    if not (result['steering_low'] < result['steering_center'] < result['steering_high'] and
            result['throttle_reverse_max'] < result['throttle_stop'] < result['throttle_forward_max']):
        raise ValueError('invalid PCA output calibration ordering')
    if result['throttle_forward_max'] != THROTTLE_FORWARD_MAX:
        raise ValueError('throttle_forward_max must be 7397 for this release')
    if not result['throttle_stop'] < CRUISE_MIN <= CRUISE_MAX <= result['throttle_forward_max']:
        raise ValueError('cruise range outside PCA output calibration')
    return result


def validate_cruise(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('cruise PWM must be an integer duty16 value')
    if not CRUISE_MIN <= value <= CRUISE_MAX or (value != CRUISE_MAX and (value-CRUISE_MIN) % CRUISE_STEP):
        raise ValueError('cruise PWM must be 6480..7390 in steps of 10, or exactly 7397')
    return value


def output_in_range(steering, throttle, calibration=None):
    """Shared physical command envelope; never saturate invalid output commands."""
    limits = OUTPUT_DEFAULTS if calibration is None else calibration
    return (type(steering) is int and type(throttle) is int and
            limits['steering_low'] <= steering <= limits['steering_high'] and
            limits['throttle_reverse_max'] <= throttle <= min(limits['throttle_forward_max'],THROTTLE_FORWARD_MAX))


def rc_valid(data, config, now, stale_s=RC_STALE_S):
    try:
        stamp = number(data.get('monotonic'))
        if stamp <= 0 or not 0 <= now-stamp <= stale_s or ('valid' in data and data['valid'] is not True):
            return False
        return all(axis['valid_min_us'] <= number(data.get(name+'_us')) <= axis['valid_max_us']
                   for name, axis in config.items())
    except (ValueError, TypeError, AttributeError):
        return False


def neutral(value, axis):
    return abs(number(value)-axis['center_us']) <= axis['deadband_us']


def normalized(value, axis):
    value = number(value)
    if not axis['valid_min_us'] <= value <= axis['valid_max_us']:
        raise ValueError('RC input outside valid signal envelope')
    low = axis['center_us']-axis['deadband_us']
    high = axis['center_us']+axis['deadband_us']
    if low <= value <= high:
        return 0.0
    if value < low:
        return max(-1.0, (value-low)/(low-axis['min_us']))
    return min(1.0, (value-high)/(axis['max_us']-high))


def map_axis(value, axis, output_low, output_center, output_high):
    portion = normalized(value, axis)
    return round(output_center + portion * (output_center-output_low if portion < 0 else output_high-output_center))


class NavigationThrottleRamp:
    """Limit upward NAVIGATION demand only; reductions are immediate."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.current = None
        self.last_at = None

    def update(self, demand, now):
        demand = number(demand)
        now = number(now)
        if not OUTPUT_DEFAULTS['throttle_stop'] <= demand <= CRUISE_MAX:
            raise ValueError('navigation demand outside output range')
        if self.current is None:
            self.current = min(CRUISE_DEFAULT, demand)
        elif demand <= self.current:
            self.current = demand
        else:
            self.current = min(demand, self.current + NAV_RAMP_RATE * max(0.0, now-self.last_at))
        self.last_at = now
        return min(int(demand), round(self.current))
