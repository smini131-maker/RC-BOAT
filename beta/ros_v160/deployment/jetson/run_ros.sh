#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-real}"
WS=/home/jetson/rcboat_ros_ws

source /opt/ros/noetic/setup.bash
source "$WS/devel/setup.bash"

export ROS_MASTER_URI=http://127.0.0.1:11311
export ROS_HOSTNAME=127.0.0.1

case "$PROFILE" in
  real) exec roslaunch rcboat_ros rcboat_real.launch runtime_dir:="$WS/runtime" ;;
  hil) exec roslaunch rcboat_ros rcboat_hil.launch runtime_dir:="$WS/runtime" ;;
  *) echo "Unknown ROS profile: $PROFILE" >&2; exit 2 ;;
esac
