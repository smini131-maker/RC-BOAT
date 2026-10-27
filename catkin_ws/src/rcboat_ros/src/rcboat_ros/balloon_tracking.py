"""Pure balloon selection and control logic, independent of ROS and camera drivers."""
import math
from .common import clamp, fresh, SAFE_STEERING, SAFE_THROTTLE

DEFAULTS = {
    "camera_type": "usb", "camera_source": "/dev/video0",
    "csi_sensor_id": 0, "width": 640, "height": 480, "camera_fps": 15,
    "model_path": "~/rcboat_balloon_data/models/balloon_yolov5n.onnx",
    "model_manifest": "~/rcboat_balloon_data/models/model_manifest.json",
    "input_size": 320, "confidence": 0.45, "nms_iou": 0.45,
    "inference_hz": 5.0, "max_frame_age_s": 1.0, "acquire_frames": 3,
    "steering_gain": 0.7, "steering_deadband": 0.06,
    "steering_right_sign": -1, "cruise_pwm": 6550, "max_throttle_pwm": 6650,
    "stop_area_ratio": 0.18, "stop_box_height_ratio": 0.70,
    "align_before_forward": 0.65,
    "preview_port": 8766, "preview_hz": 3.0,
}

def validate_config(values):
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown vision settings: " + ",".join(sorted(unknown)))
    config = dict(DEFAULTS, **values)
    if config["camera_type"] not in ("usb", "csi"):
        raise ValueError("camera_type must be usb or csi")
    # USB sources are local devices only; no file/network playback can drive motors.
    if not str(config["camera_source"]).startswith("/dev/video"):
        raise ValueError("camera_source must be a local /dev/video device")
    for key, low, high in (
        ("width", 160, 1920), ("height", 120, 1080), ("camera_fps", 1, 60),
        ("input_size", 160, 640), ("confidence", .05, .99), ("nms_iou", .05, .9),
        ("inference_hz", .5, 15), ("max_frame_age_s", .2, 2.0),
        ("acquire_frames", 1, 20), ("steering_gain", .05, 1.5),
        ("steering_deadband", 0, .3), ("cruise_pwm", 6450, 6650),
        ("max_throttle_pwm", 6450, 6650), ("stop_area_ratio", .02, .7),
        ("stop_box_height_ratio", .2, .95), ("align_before_forward", .1, 1),
        ("csi_sensor_id", 0, 3), ("preview_port", 1024, 65535), ("preview_hz", .5, 5),
    ):
        value = float(config[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError("%s must be in %s..%s" % (key, low, high))
    if config["steering_right_sign"] not in (-1, 1):
        raise ValueError("steering_right_sign must be -1 or 1")
    if int(config["input_size"]) % 32:
        raise ValueError("input_size must be a multiple of 32")
    if config["cruise_pwm"] > config["max_throttle_pwm"]:
        raise ValueError("cruise_pwm must not exceed max_throttle_pwm")
    return config

def iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, right-left)*max(0, bottom-top)
    area_a = max(0, a[2]-a[0])*max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0])*max(0, b[3]-b[1])
    return overlap / max(1e-9, area_a+area_b-overlap)

class TargetSelector:
    def __init__(self):
        self.box = None
        self.streak = 0

    def reset(self):
        self.box = None
        self.streak = 0

    def update(self, detections, width, height, config):
        candidates = [item for item in detections if item.get("class_id") == 0
                      and float(item.get("confidence", 0)) >= config["confidence"]]
        if not candidates:
            self.reset()
            return None, False
        if self.box is not None:
            candidate = max(candidates, key=lambda item: iou(self.box, item["bbox"]))
            if iou(self.box, candidate["bbox"]) < .15:
                self.reset()
                return None, False
        else:
            candidate = max(candidates, key=lambda item:
                            (item["bbox"][2]-item["bbox"][0]) *
                            (item["bbox"][3]-item["bbox"][1]) * item["confidence"])
        self.box = list(candidate["bbox"])
        self.streak += 1
        target = dict(candidate)
        target["center_x_normalized"] = ((self.box[0]+self.box[2])/2-width/2)/(width/2)
        target["area_ratio"] = ((self.box[2]-self.box[0])*(self.box[3]-self.box[1]))/(width*height)
        target["box_height_ratio"] = (self.box[3]-self.box[1])/height
        target["acquire_streak"] = self.streak
        return target, self.streak >= int(config["acquire_frames"])

def tracking_command(target, acquired, frame_time, now, config):
    output = {"valid": False, "desired_steering_pwm": SAFE_STEERING,
              "desired_throttle_pwm": SAFE_THROTTLE, "monotonic": frame_time,
              "reason": "NO_TARGET", "horizontal_error": None, "area_ratio": None}
    if not fresh(frame_time, config["max_frame_age_s"], now):
        output["reason"] = "STALE_FRAME"
        return output
    if target is None:
        return output
    error = float(target["center_x_normalized"])
    area = float(target["area_ratio"])
    if not all(math.isfinite(value) for value in (error, area, float(target["box_height_ratio"]))):
        output["reason"] = "INVALID_TARGET"
        return output
    output.update(horizontal_error=error, area_ratio=area)
    if not acquired:
        output["reason"] = "ACQUIRING_TARGET"
        return output
    if area >= config["stop_area_ratio"] or target["box_height_ratio"] >= config["stop_box_height_ratio"]:
        output["reason"] = "TARGET_CLOSE_STOP"
        return output
    demand = 0 if abs(error) <= config["steering_deadband"] else clamp(
        config["steering_right_sign"]*error*config["steering_gain"], -1, 1)
    span = 1300 if demand >= 0 else 1100
    steering = round(SAFE_STEERING+demand*span)
    forward_scale = max(0.0, 1-abs(error)/config["align_before_forward"])
    throttle = round(SAFE_THROTTLE+(config["cruise_pwm"]-SAFE_THROTTLE)*forward_scale)
    output.update(valid=True, desired_steering_pwm=int(clamp(steering, 4900, 7300)),
                  desired_throttle_pwm=int(clamp(throttle, 6450, config["max_throttle_pwm"])),
                  reason="TRACKING" if throttle > SAFE_THROTTLE else "ALIGNING")
    return output

def safe_balloon_output(vision, desired, now):
    """Second independent gate used by the ROS safety supervisor."""
    if not vision.get("enabled") or not vision.get("model_ready") or not vision.get("camera_online"):
        return None
    try:
        age_limit = float(vision.get("max_frame_age_s", 1.0))
        stamp = float(desired.get("monotonic", 0))
        if not math.isfinite(age_limit) or not math.isfinite(stamp):
            return None
        age_limit = min(2.0, max(.2, age_limit))
        if not desired.get("valid") or not fresh(stamp, age_limit, now):
            return None
        steering, throttle = int(desired["desired_steering_pwm"]), int(desired["desired_throttle_pwm"])
        if not (4900 <= steering <= 7300 and 6450 <= throttle <= 6650):
            return None
        return steering, throttle
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
