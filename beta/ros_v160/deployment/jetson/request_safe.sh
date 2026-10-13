#!/usr/bin/env bash
set -u

if [[ -f /opt/ros/noetic/setup.bash && -f /home/jetson/rcboat_ros_ws/devel/setup.bash ]]; then
  source /opt/ros/noetic/setup.bash
  source /home/jetson/rcboat_ros_ws/devel/setup.bash
  timeout 2 rosservice call /rcboat/safety/force_safe '{}' >/dev/null 2>&1 || true
fi
exit 0
