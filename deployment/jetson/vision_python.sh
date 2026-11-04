#!/usr/bin/env bash
set -Eeuo pipefail
VISION_PY="$HOME/.rcboat/vision-venv/bin/python3"
export PYTHONNOUSERSITE=1
if [[ -x "$VISION_PY" ]]; then exec "$VISION_PY" "$@"; fi
echo 'Vision environment missing. Run bash deployment/jetson/install_vision_dependencies.sh' >&2
exit 78
