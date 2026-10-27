#!/usr/bin/env python3
"""Offline model/camera probe. No ROS commands or motor writes."""
import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"catkin_ws/src/rcboat_ros/src"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", default="/dev/video0")
    parser.add_argument("--model-only", action="store_true")
    args = parser.parse_args()
    import cv2
    import numpy as np
    from rcboat_ros.balloon_tracking import validate_config
    from rcboat_ros.balloon_detector import BalloonDetector
    print("OpenCV:", cv2.__version__, flush=True)
    config = validate_config({})
    model = BalloonDetector(config)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    start = time.monotonic()
    for _ in range(3):
        model.detect(image)
    print("Average inference ms:", round((time.monotonic()-start)/3*1000, 1), flush=True)
    if not args.model_only:
        capture = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
        try:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("camera read failed: "+args.camera)
            print("Camera:", args.camera, frame.shape)
            print("Detected:", len(model.detect(frame)))
        finally:
            capture.release()
    print("Vision check passed. No actuation was performed.")

if __name__ == "__main__":
    main()
