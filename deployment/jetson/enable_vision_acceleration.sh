#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VISION_ENV="$HOME/.rcboat/vision-venv"
VISION_PY="$VISION_ENV/bin/python3"
/usr/bin/python3 -I "$ROOT/deployment/jetson/vision_environment.py" --gpu-bridge "$VISION_ENV"
if ! "$VISION_PY" -I -c 'import tensorrt; print("TensorRT",tensorrt.__version__)'; then
  echo 'TensorRT binding unavailable; CPU fallback retained. 10 fps is not verified on this configuration.'
  exit 0
fi
# Static batch 1, FP16, bounded workspace; never changes nvpmodel/jetson_clocks.
"$VISION_PY" -I "$ROOT/deployment/jetson/build_vision_engine.py" "$ROOT/models/balloon_yolov8n.onnx" --if-needed
"$VISION_PY" -I "$ROOT/deployment/jetson/check_vision.py" --backend tensorrt
echo 'VISION GPU VERIFIED: actual model inference passed; no actuator accessed.'
