#!/usr/bin/env bash
set -Eeuo pipefail
# Preserve the host OpenCV/GStreamer installation without inheriting host TensorFlow.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VISION_ENV="$HOME/.rcboat/vision-venv"
VISION_PY="$VISION_ENV/bin/python3"
SYSTEM_PY=/usr/bin/python3
trap 'echo "VISION INSTALL FAILED at line $LINENO; do not start tracking." >&2' ERR
if systemctl cat rcboat_ros.service >/dev/null 2>&1; then
  sudo systemctl stop rcboat_ros.service
fi
sudo apt-get update
sudo apt-get install -y python3-opencv python3-numpy python3-venv python3-netifaces v4l-utils gstreamer1.0-tools
"$SYSTEM_PY" -I "$ROOT/deployment/jetson/vision_environment.py" --prepare "$VISION_ENV"
"$VISION_PY" -I -m pip --isolated install --upgrade --no-user 'pip==24.3.1'
"$VISION_PY" -I -m pip --isolated install --upgrade --no-user --only-binary=:all: -r "$ROOT/deployment/jetson/vision_requirements.txt"
"$SYSTEM_PY" -I "$ROOT/deployment/jetson/vision_environment.py" --bridge "$VISION_ENV"
"$VISION_PY" -I -m pip check
"$VISION_PY" -I "$ROOT/deployment/jetson/vision_environment.py" --check
# Force ONNX Runtime here: an OpenCV fallback must not conceal a broken ORT import.
"$VISION_PY" -I "$ROOT/deployment/jetson/check_vision.py" --backend onnxruntime
echo 'VISION INSTALL VERIFIED: isolated packages, array operations and real ONNX inference passed.'
