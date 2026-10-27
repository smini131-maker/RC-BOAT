#!/usr/bin/env python3
"""Optional camera/YOLO worker. Publishes demands; the supervisor owns actuation."""
import datetime as dt
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rospy
from std_msgs.msg import String
from rcboat_ros.common import pack, unpack, fresh
from rcboat_ros.balloon_tracking import DEFAULTS, validate_config, TargetSelector, tracking_command
from rcboat_ros.srv import Execute, ExecuteResponse

class Vision:
    def __init__(self):
        self.config_path = Path(os.path.expanduser("~/rcboat_balloon_data/vision.local.json"))
        stored = json.loads(self.config_path.read_text()) if self.config_path.exists() else {}
        params = rospy.get_param("/rcboat/vision", {})
        self.config = validate_config(dict(params, **stored))
        self.enabled = False
        self.revision = 0
        self.lock = threading.RLock()
        self.frame = None
        self.frame_at = 0
        self.frame_id = 0
        self.preview = b""
        self.preview_at = 0
        self.model_ready = False
        self.detector = None
        self.selector = TargetSelector()
        self.desired = {}
        self.detail = {"reason": "CAMERA_DISABLED", "target": None, "detections": [],
                       "inference_ms": None, "processed_fps": None}
        self.error = ""
        self.safety = {}
        self.log_file = None
        self.last_log = 0
        self.stopping = False
        self.status_pub = rospy.Publisher("/rcboat/vision/status", String, queue_size=1)
        self.desired_pub = rospy.Publisher("/rcboat/vision/desired", String, queue_size=1)
        self.events = rospy.Publisher("/rcboat/events", String, queue_size=8)
        rospy.Subscriber("/rcboat/safety/state", String, lambda msg: setattr(self, "safety", unpack(msg)))
        rospy.Service("/rcboat/vision/execute", Execute, self.execute)
        rospy.on_shutdown(self.close)
        self.start_preview()
        self.capture_thread = threading.Thread(target=self.capture, daemon=True)
        self.capture_thread.start()
        self.timer = rospy.Timer(rospy.Duration(.1), self.publish)

    def execute(self, request):
        try:
            args = json.loads(request.arguments_json or "{}")
            if request.action == "vision_enable":
                with self.lock:
                    self.enabled = bool(args.get("enabled", False))
                    self.revision += 1
                    self.model_ready = False
                    self.desired = {}
                    self.frame = None
                    self.frame_at = 0
                    self.preview = b""
                    self.selector.reset()
                    self.error = ""
                    self.detail = dict(reason="STARTING" if self.enabled else "CAMERA_DISABLED",
                                       target=None, detections=[], inference_ms=None, processed_fps=None)
                    if self.log_file:
                        self.log_file.close()
                        self.log_file = None
                    if self.enabled:
                        folder = Path(os.path.expanduser("~/rcboat_balloon_data/logs/vision"))
                        folder.mkdir(parents=True, exist_ok=True)
                        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        self.log_file = (folder / ("balloon_" + stamp + ".jsonl")).open("w", encoding="utf-8")
            elif request.action == "vision_configure":
                if self.enabled:
                    raise ValueError("disable camera before changing vision settings")
                if "preview_port" in args:
                    raise ValueError("preview_port is startup-only; edit YAML and relaunch")
                config = validate_config(dict(self.config, **args))
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.config_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
                temporary.replace(self.config_path)
                self.config = config
                self.revision += 1
            elif request.action != "vision_status":
                raise ValueError("unknown vision action")
            self.events.publish(pack(type="VISION_CHANGE", action=request.action, at=time.time()))
            return ExecuteResponse(True, pack(enabled=self.enabled, configuration=self.config))
        except Exception as exc:
            return ExecuteResponse(False, pack(error=str(exc)))

    def capture(self):
        cap, revision = None, -1
        while not self.stopping and not rospy.is_shutdown():
            if not self.enabled:
                if cap is not None:
                    cap.release()
                    cap = None
                time.sleep(.1)
                continue
            try:
                import cv2
                if cap is None or revision != self.revision:
                    if cap is not None:
                        cap.release()
                    config = dict(self.config)
                    revision = self.revision
                    if config["camera_type"] == "csi":
                        pipeline = (
                            "nvarguscamerasrc sensor-id=%d ! video/x-raw(memory:NVMM),width=1280,height=720,"
                            "framerate=%d/1 ! nvvidconv ! video/x-raw,width=%d,height=%d,format=BGRx ! "
                            "videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
                        ) % (config["csi_sensor_id"], config["camera_fps"], config["width"], config["height"])
                        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                    else:
                        cap = cv2.VideoCapture(config["camera_source"], cv2.CAP_V4L2)
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["width"])
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["height"])
                        cap.set(cv2.CAP_PROP_FPS, config["camera_fps"])
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not cap.isOpened():
                        raise RuntimeError("CAMERA_OPEN_FAILED: check device/CSI GStreamer support")
                ok, frame = cap.read()
                captured = time.monotonic()
                if not ok or frame is None:
                    raise RuntimeError("CAMERA_READ_FAILED")
                with self.lock:
                    if not self.enabled or revision != self.revision:
                        continue
                    self.frame, self.frame_at = frame, captured
                    self.frame_id += 1
            except Exception as exc:
                with self.lock:
                    self.frame_at = 0
                    self.desired = {}
                    self.error = str(exc)
                if cap is not None:
                    cap.release()
                cap = None
                time.sleep(.5)
        if cap is not None:
            cap.release()

    def start_preview(self):
        vision = self
        token = os.getenv("RCBOAT_GATEWAY_TOKEN", "")
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if token and self.headers.get("X-RCBoat-Token", "") != token:
                    self.send_error(401)
                    return
                if self.path != "/frame.jpg":
                    self.send_error(404)
                    return
                with vision.lock:
                    payload, stamp = vision.preview, vision.preview_at
                if not payload or not vision.enabled or not fresh(stamp, 2.0):
                    self.send_error(503, "no fresh camera frame")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *_args):
                pass
        self.server = ThreadingHTTPServer(("0.0.0.0", int(self.config["preview_port"])), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, _event):
        now = time.monotonic()
        with self.lock:
            config = dict(self.config)
            status = dict(self.detail)
            camera_online = self.enabled and fresh(self.frame_at, config["max_frame_age_s"], now)
            desired = dict(self.desired)
            if not self.enabled or not self.model_ready or not camera_online or not fresh(
                    float(desired.get("monotonic", 0)), config["max_frame_age_s"], now):
                desired.update(valid=False, desired_steering_pwm=6000, desired_throttle_pwm=6450)
                if self.enabled and self.model_ready and not camera_online:
                    status["reason"] = "STALE_CAMERA"
                elif self.enabled and self.model_ready and not desired.get("valid"):
                    status["reason"] = "STALE_INFERENCE"
            status.update(enabled=self.enabled, camera_online=camera_online, model_ready=self.model_ready,
                          camera_type=config["camera_type"], model_path=config["model_path"],
                          frame_age_s=round(now-self.frame_at, 3) if self.frame_at else None,
                          max_frame_age_s=config["max_frame_age_s"],
                          preview_port=config["preview_port"], error=self.error,
                          configuration=config, monotonic=now)
            self.status_pub.publish(pack(**status))
            self.desired_pub.publish(pack(**desired))
            if self.log_file and now-self.last_log >= .2:
                self.last_log = now
                record = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "vision": status, "desired": desired, "safety": dict(self.safety)}
                self.log_file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                self.log_file.flush()

    def run(self):
        revision, processed, last_preview = -1, -1, 0
        while not rospy.is_shutdown() and not self.stopping:
            if not self.enabled:
                self.detector = None
                time.sleep(.1)
                continue
            start = time.monotonic()
            try:
                if revision != self.revision:
                    revision = self.revision
                    self.detector = None
                    self.selector.reset()
                    try:
                        from rcboat_ros.balloon_detector import BalloonDetector
                        self.detector = BalloonDetector(self.config)
                        with self.lock:
                            self.model_ready = True
                            self.error = ""
                    except Exception as exc:
                        with self.lock:
                            self.error = "MODEL_NOT_READY: " + str(exc)
                            self.model_ready = False
                with self.lock:
                    frame = self.frame.copy() if self.frame is not None else None
                    captured, frame_id = self.frame_at, self.frame_id
                if frame is None or frame_id == processed:
                    time.sleep(.02)
                    continue
                processed = frame_id
                detections = self.detector.detect(frame) if self.detector is not None else []
                target, acquired = self.selector.update(detections, frame.shape[1], frame.shape[0], self.config)
                ended = time.monotonic()
                desired = tracking_command(target, acquired, captured, ended, self.config)
                if self.detector is None:
                    desired["valid"] = False
                    desired["reason"] = "MODEL_NOT_READY"
                with self.lock:
                    if self.enabled and revision == self.revision:
                        self.desired = desired
                        self.detail = dict(reason=desired["reason"], target=target, detections=detections,
                                           inference_ms=round((ended-start)*1000, 1),
                                           processed_fps=round(1/max(.001, ended-start), 2))
                if ended-last_preview >= 1/self.config["preview_hz"]:
                    import cv2
                    last_preview = ended
                    center = frame.shape[1]//2
                    cv2.line(frame, (center, 0), (center, frame.shape[0]), (220, 220, 220), 1)
                    for item in detections:
                        x1, y1, x2, y2 = [int(value) for value in item["bbox"]]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 220, 100), 2)
                        cv2.putText(frame, "balloon %.2f" % item["confidence"], (x1, max(18, y1-5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, .5, (80, 220, 100), 1)
                    cv2.putText(frame, desired["reason"], (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                                .6, (80, 220, 255), 2)
                    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        with self.lock:
                            if self.enabled and revision == self.revision:
                                self.preview, self.preview_at = encoded.tobytes(), captured
            except Exception as exc:
                with self.lock:
                    self.desired = {}
                    self.model_ready = False
                    self.error = "VISION_ERROR: " + str(exc)
                rospy.logwarn_throttle(5, "Balloon vision: %s", exc)
            time.sleep(max(.01, 1/self.config["inference_hz"]-(time.monotonic()-start)))

    def close(self):
        self.stopping = True
        self.enabled = False
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
        with self.lock:
            if self.log_file:
                self.log_file.close()
                self.log_file = None

if __name__ == "__main__":
    rospy.init_node("balloon_vision_node")
    Vision().run()
