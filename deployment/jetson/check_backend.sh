#!/usr/bin/env bash
set -Eeuo pipefail
set +u
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash
set -u
printf 'rcboat_ros.service: '
systemctl is-active rcboat_ros.service || true
printf 'ROS master: '
if rosnode list >/dev/null 2>&1; then echo online; else echo offline; fi
printf 'ROS gateway TCP 8765: '
if timeout 1 bash -c '</dev/tcp/127.0.0.1/8765' 2>/dev/null; then echo online; else echo offline; fi
printf 'Logger: '
timeout 3 rostopic echo -n 1 /rcboat/ground_test/status 2>/dev/null || echo no_data
