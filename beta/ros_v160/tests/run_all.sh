#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m compileall -q "$ROOT"
for script in "$ROOT"/deployment/jetson/*.sh; do
  bash -n "$script"
done
python3 "$ROOT/tests/test_beta_static.py"
git -C "$ROOT/../.." diff --check

echo "RC Boat ROS beta static/unit checks passed."
