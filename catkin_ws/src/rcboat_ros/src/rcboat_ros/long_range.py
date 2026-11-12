"""Native-resolution colour proposals with a strict one-neural-pass frame budget.

Colour proposes a crop only. A proposal is never a detection or motor command.
Only the balloon network AND the model profile’s colour check can confirm a target.
"""
import math
import time


def target_colour_mask(hsv, config, cv2):
    """Apply the same HSV gate to ROI proposals and neural detections."""
    if config.get('target_colour', 'pink') == 'red':
        # OpenCV hue wraps at 179. Include warm reds and cool crimson.
        warm = cv2.inRange(hsv, (0, 60, 40), (12, 255, 255))
        cool = cv2.inRange(hsv, (169, 60, 40), (179, 255, 255))
        return cv2.bitwise_or(warm, cool)
    lower = (config['pink_hue_low'], config['pink_min_saturation'], config['pink_min_value'])
    return cv2.inRange(hsv, lower, (config['pink_hue_high'], 255, 255))


def expected_diameter_px(diameter_m, distance_m, width, hfov_deg):
    values = (diameter_m, distance_m, width, hfov_deg)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('finite camera/target values required')
    if min(diameter_m, distance_m, width) <= 0 or not 0 < hfov_deg < 180:
        raise ValueError('positive dimensions and 0 < FOV < 180 required')
    return diameter_m * width / (2 * distance_m * math.tan(math.radians(hfov_deg / 2)))


def square_crop(box, shape, minimum, context):
    h, w = shape[:2]
    x1, y1, x2, y2 = box
    side = min(max(w, h), max(minimum, math.ceil(max(x2-x1, y2-y1)*context)))
    side = min(side, 640)
    left = max(0, min(w-side, math.floor((x1+x2-side)/2)))
    top = max(0, min(h-side, math.floor((y1+y2-side)/2)))
    return int(left), int(top), min(w, int(left+side)), min(h, int(top+side))


class RegionPlanner:
    def __init__(self):
        self.calls = 0
        self.cursor = 0
        self.last_box = None
        self.observed_at = 0.0

    def plan(self, frame, config, cv2, now=None):
        now = time.monotonic() if now is None else now
        h, w = frame.shape[:2]
        self.calls += 1
        full = (0, 0, w, h)
        detail = dict(kind='full', crop=list(full), native_width=w, native_height=h,
                      neural_passes=1, colour_candidates=0)
        if not config.get('long_range_enabled', True):
            return full, detail
        recent = self.last_box is not None and 0 <= now-self.observed_at <= 1.5
        if recent and max(self.last_box[2]-self.last_box[0], self.last_box[3]-self.last_box[1]) >= min(w,h)/3:
            return full, detail  # Keep the whole balloon visible during the final approach.
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = target_colour_mask(hsv, config, cv2)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        rows = []
        for x, y, bw, bh, area in stats[1:]:
            if area < 4 or area > w*h*.2 or min(bw,bh) < 2 or not .15 <= bw/bh <= 6:
                continue
            compact = area/max(1, bw*bh)
            aspect = min(bw,bh)/max(bw,bh)
            score = .5*math.sqrt(min(int(area),256)/256) + .3*compact + .2*aspect
            rows.append((score, [int(x),int(y),int(x+bw),int(y+bh)]))
        rows.sort(key=lambda item: -item[0])
        rows = rows[:config['roi_max_candidates']]
        detail['colour_candidates'] = len(rows)
        chosen = None
        if recent and rows:
            a = self.last_box
            radius = max(config['roi_min_size'], 2*max(a[2]-a[0],a[3]-a[1]))
            near = [(math.hypot((b[0]+b[2]-a[0]-a[2])/2,(b[1]+b[3]-a[1]-a[3])/2), b) for _,b in rows]
            distance, box = min(near,key=lambda item:item[0])
            if distance <= radius:
                chosen = box
        if chosen is None and rows and self.calls % config['roi_full_interval'] != 1:
            chosen = rows[self.cursor % len(rows)][1]
            self.cursor += 1
        if chosen is None:
            return full, detail
        crop = square_crop(chosen, frame.shape, config['roi_min_size'], config['roi_context_scale'])
        detail.update(kind='roi', crop=list(crop))
        return crop, detail

    def observe(self, detections, now=None):
        now = time.monotonic() if now is None else now
        confirmed = [d for d in detections if d.get('pink_confirmed')]
        if not confirmed:
            return
        if self.last_box is not None and now-self.observed_at <= 1.5:
            a = self.last_box
            chosen = min(confirmed,key=lambda d:abs(d['bbox'][0]+d['bbox'][2]-a[0]-a[2])+abs(d['bbox'][1]+d['bbox'][3]-a[1]-a[3]))
        else:
            chosen = max(confirmed,key=lambda d:d['confidence'])
        self.last_box = list(chosen['bbox'])
        self.observed_at = now
