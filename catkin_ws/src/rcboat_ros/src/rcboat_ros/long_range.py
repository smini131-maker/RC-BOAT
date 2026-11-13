"""Native-resolution colour proposals with a strict one-neural-pass frame budget.

Colour proposes a crop only. A proposal is never a detection or motor command.
Only the balloon network AND the model profile’s colour check can confirm a target.
"""
import math
import time

import numpy as np


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


def _rank_colour_candidates(stats, frame_area, limit):
    # OpenCV stats are x, y, width, height, area, with background first.
    components = stats[1:]
    widths, heights, areas = components[:, 2:].T
    plausible = ((areas >= 4) & (areas <= frame_area * .2)
                 & (widths >= 2) & (heights >= 2))
    components = components[plausible]
    widths, heights, areas = components[:, 2:].T
    ratio = widths / heights
    plausible = (ratio >= .15) & (ratio <= 6)
    components = components[plausible]
    widths, heights, areas = components[:, 2:].T
    compactness = areas / (widths * heights)
    aspect = np.minimum(widths, heights) / np.maximum(widths, heights)
    score = .5 * np.sqrt(np.minimum(areas, 256) / 256) + .3 * compactness + .2 * aspect
    # Preserve OpenCV label order for equal scores, as the previous stable sort did.
    ranked = np.argsort(-score, kind='stable')[:limit]
    return [tuple(row) for row in components[ranked, :4].tolist()]


class RegionPlanner:
    def __init__(self):
        self.calls = 0
        self.cursor = 0
        self.last_box = None
        self.observed_at = 0.0
        self.can_reuse_crop = False

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
        if self.can_reuse_crop and recent and now-self.observed_at <= .25:
            # Full-frame colour proposals are expensive on Nano. A confirmed box
            # already supplies a crop; a miss restores the original search next frame.
            crop = square_crop(self.last_box, frame.shape, config['roi_min_size'], config['roi_context_scale'])
            detail.update(kind='roi', crop=list(crop), roi_source='recent_detection')
            return crop, detail
        start = time.monotonic()
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = target_colour_mask(hsv, config, cv2)
        mask_done = time.monotonic()
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        labels_done = time.monotonic()
        boxes = [(x, y, x+bw, y+bh) for x, y, bw, bh in
                 _rank_colour_candidates(stats, w*h, config['roi_max_candidates'])]
        detail['colour_candidates'] = len(boxes)
        detail['timing_ms'] = dict(
            colour_mask=round((mask_done-start)*1000, 2),
            component_label=round((labels_done-mask_done)*1000, 2),
            candidate_rank=round((time.monotonic()-labels_done)*1000, 2))
        chosen = None
        if recent and boxes:
            a = self.last_box
            radius = max(config['roi_min_size'], 2*max(a[2]-a[0],a[3]-a[1]))
            near = [(math.hypot((b[0]+b[2]-a[0]-a[2])/2,(b[1]+b[3]-a[1]-a[3])/2), b) for b in boxes]
            distance, box = min(near,key=lambda item:item[0])
            if distance <= radius:
                chosen = box
        if chosen is None and boxes and self.calls % config['roi_full_interval'] != 1:
            chosen = boxes[self.cursor % len(boxes)]
            self.cursor += 1
        if chosen is None:
            return full, detail
        crop = square_crop(chosen, frame.shape, config['roi_min_size'], config['roi_context_scale'])
        detail.update(kind='roi', crop=list(crop))
        return crop, detail

    def observe(self, detections, now=None):
        now = time.monotonic() if now is None else now
        confirmed = [d for d in detections if d.get('pink_confirmed')]
        self.can_reuse_crop = bool(confirmed)
        if not confirmed:
            return
        if self.last_box is not None and now-self.observed_at <= 1.5:
            a = self.last_box
            chosen = min(confirmed,key=lambda d:abs(d['bbox'][0]+d['bbox'][2]-a[0]-a[2])+abs(d['bbox'][1]+d['bbox'][3]-a[1]-a[3]))
        else:
            chosen = max(confirmed,key=lambda d:d['confidence'])
        self.last_box = list(chosen['bbox'])
        self.observed_at = now
