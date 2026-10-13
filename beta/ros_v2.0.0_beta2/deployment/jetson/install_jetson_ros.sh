#!/usr/bin/env bash
set -Eeuo pipefail
# Installs ROS build workspace under /home/jetson/rcboat_ros_ws; never touches legacy /home/jetson/rcboat.
[[ $(id -un) == jetson ]] || { echo 'Run as jetson account';exit 1; }
[[ -f /opt/ros/noetic/setup.bash ]] || { echo 'ROS Noetic not installed. Check its EOL repository availability first.';exit 2; }
source /opt/ros/noetic/setup.bash
command -v catkin_make >/dev/null || { echo 'catkin_make unavailable';exit 3; }
ROOT=/home/jetson/rcboat_ros_ws
cd "$ROOT"
mkdir -p /home/jetson/rcboat_ros_data/experiments
if [[ ! -f /home/jetson/rcboat_ros_data/routes.json ]];then
 cp "$ROOT/catkin_ws/src/rcboat_ros/config/routes.json" /home/jetson/rcboat_ros_data/routes.json
fi
source /opt/ros/noetic/setup.bash
(cd catkin_ws && catkin_make)
# Must NOT auto-enable ROS; stable daemon stays the boot default.
sudo cp systemd/rcboat_ros.service /etc/systemd/system/rcboat_ros.service
sudo systemctl daemon-reload
sudo systemctl disable rcboat_ros.service >/dev/null 2>&1 || true
sudo systemctl enable rcboat.service
printf 'ROS workspace built; rcboat_ros.service stays DISABLED. Check devices then USE_ROS.cmd.\n'
