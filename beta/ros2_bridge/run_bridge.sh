#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO_NAME="${ROS_DISTRO:-foxy}"
ROS_SETUP="/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
LOCAL_SETUP="${SCRIPT_DIR}/install/setup.bash"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS 2 setup file not found: ${ROS_SETUP}" >&2
  exit 1
fi
if [[ ! -f "${LOCAL_SETUP}" ]]; then
  echo "Bridge has not been built. Run ./build_ros2.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ROS_SETUP}"
# shellcheck disable=SC1090
source "${LOCAL_SETUP}"
exec ros2 launch rcboat_ros2_bridge bridge.launch.py
