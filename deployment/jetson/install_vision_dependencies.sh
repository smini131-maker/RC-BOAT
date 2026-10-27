#!/usr/bin/env bash
set -Eeuo pipefail
# OpenCV with GStreamer comes from the Jetson/Ubuntu package manager.
sudo apt-get update
sudo apt-get install -y python3-opencv python3-numpy v4l-utils
python3 - <<'PY'
import cv2
print("OpenCV", cv2.__version__)
print("GStreamer:", next((line.strip() for line in cv2.getBuildInformation().splitlines() if "GStreamer:" in line), "unknown"))
PY
echo 'Run check_vision.py with the deployed ONNX model before enabling balloon tracking.'
