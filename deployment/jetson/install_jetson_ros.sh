#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -un) == jetson ]] || { echo 'Run as the jetson account'; exit 1; }
[[ -f /opt/ros/noetic/setup.bash ]] || { echo 'ROS Noetic is not installed'; exit 2; }
set +u
source /opt/ros/noetic/setup.bash
set -u
command -v catkin_make >/dev/null || { echo 'catkin_make is unavailable'; exit 3; }
ROOT=/home/jetson/rcboat_ros_ws
cd "$ROOT"
python3 deployment/jetson/normalize_line_endings.py
python3 deployment/jetson/verify_release.py --sources-only
chmod +x catkin_ws/src/rcboat_ros/nodes/*.py deployment/jetson/*.sh deployment/jetson/*.py
if systemctl cat rcboat_ros.service >/dev/null 2>&1; then
  sudo systemctl stop rcboat_ros.service
fi
python3 deployment/jetson/verify_release.py --sources-only --idle --clean-build
mkdir -p /home/jetson/rcboat_ros_data/logs/ground_tests /home/jetson/rcboat_ros_data/gps_logs
if [[ -f /home/jetson/rcboat_ros_data/ntrip.env ]]; then
  chmod 600 /home/jetson/rcboat_ros_data/ntrip.env
fi
if [[ ! -f /home/jetson/rcboat_ros_data/routes.json ]]; then
  cp "$ROOT/catkin_ws/src/rcboat_ros/config/routes.json" /home/jetson/rcboat_ros_data/routes.json
fi
(cd catkin_ws && catkin_make)
sudo cp systemd/rcboat_ros.service /etc/systemd/system/rcboat_ros.service
sudo systemctl daemon-reload
sudo systemctl reset-failed rcboat_ros.service
sudo systemctl enable --now rcboat_ros.service
sleep 3
sudo systemctl is-active --quiet rcboat_ros.service || {
  echo 'rcboat_ros.service failed. Inspect: journalctl -u rcboat_ros.service -n 100 --no-pager' >&2
  exit 4
}
python3 deployment/jetson/verify_release.py --timeout 45
echo 'RCBoat ROS Noetic v2.1.11 source AND running gateway verified.'
