#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source /opt/ros/noetic/setup.bash
# shellcheck disable=SC1091
source "${ROOT_DIR}/catkin_ws/devel/setup.bash"
exec roslaunch rcboat_bringup rcboat_mock.launch
