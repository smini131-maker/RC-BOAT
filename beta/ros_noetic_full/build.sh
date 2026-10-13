#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="/opt/ros/noetic/setup.bash"
if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS Noetic not found: ${ROS_SETUP}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ROS_SETUP}"
cd "${ROOT_DIR}/catkin_ws"
if [[ ! -e src/CMakeLists.txt ]]; then
  catkin_init_workspace src
fi
catkin_make -DCMAKE_BUILD_TYPE=Release
