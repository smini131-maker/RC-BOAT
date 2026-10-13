#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO_NAME="${ROS_DISTRO:-foxy}"
ROS_SETUP="/opt/ros/${ROS_DISTRO_NAME}/setup.bash"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS 2 setup file not found: ${ROS_SETUP}" >&2
  echo "Install a ROS 2 distribution compatible with this Jetson first." >&2
  exit 1
fi

if ! command -v colcon >/dev/null 2>&1; then
  echo "colcon is not installed." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ROS_SETUP}"
cd "${SCRIPT_DIR}"
colcon build --symlink-install --packages-select rcboat_ros2_bridge
