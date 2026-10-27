#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -un) == jetson ]] || { echo 'Run as the jetson account'; exit 1; }
[[ -f /opt/ros/noetic/setup.bash ]] || { echo 'ROS Noetic is not installed'; exit 2; }
set +u
source /opt/ros/noetic/setup.bash
set -u
command -v catkin_make >/dev/null || { echo 'catkin_make is unavailable'; exit 3; }
ROOT=/home/jetson/rcboat_balloon_ros_ws
cd "$ROOT"
chmod +x catkin_ws/src/rcboat_ros/nodes/*.py deployment/jetson/*.sh deployment/jetson/*.py
sudo systemctl stop rcboat_balloon_ros.service >/dev/null 2>&1 || true
# Only one ROS/PCA owner may run. Preserve the old unit and workspace.
sudo systemctl stop rcboat_ros.service >/dev/null 2>&1 || true
sudo systemctl disable rcboat_ros.service >/dev/null 2>&1 || true
sudo usermod -a -G video jetson
mkdir -p /home/jetson/rcboat_balloon_data/logs/ground_tests /home/jetson/rcboat_balloon_data/gps_logs
if [[ -f /home/jetson/rcboat_balloon_data/ntrip.env ]]; then
  chmod 600 /home/jetson/rcboat_balloon_data/ntrip.env
fi
if [[ ! -f /home/jetson/rcboat_balloon_data/routes.json ]]; then
  if [[ -f /home/jetson/rcboat_ros_data/routes.json ]]; then
    cp /home/jetson/rcboat_ros_data/routes.json /home/jetson/rcboat_balloon_data/routes.json
  else
    cp "$ROOT/catkin_ws/src/rcboat_ros/config/routes.json" /home/jetson/rcboat_balloon_data/routes.json
  fi
fi
if [[ ! -f /home/jetson/rcboat_balloon_data/ntrip.env && -f /home/jetson/rcboat_ros_data/ntrip.env ]]; then
  install -m 600 /home/jetson/rcboat_ros_data/ntrip.env /home/jetson/rcboat_balloon_data/ntrip.env
fi
mkdir -p /home/jetson/rcboat_balloon_data/models
if [[ -f "$ROOT/models/balloon_yolov5n.onnx" && -f "$ROOT/models/model_manifest.json" ]]; then
  cp "$ROOT/models/balloon_yolov5n.onnx" "$ROOT/models/model_manifest.json" /home/jetson/rcboat_balloon_data/models/
fi
(cd catkin_ws && catkin_make)
sudo cp systemd/rcboat_balloon_ros.service /etc/systemd/system/rcboat_balloon_ros.service
sudo systemctl daemon-reload
sudo systemctl enable --now rcboat_balloon_ros.service
sleep 3
sudo systemctl is-active --quiet rcboat_balloon_ros.service || {
  echo 'rcboat_balloon_ros.service failed. Inspect: journalctl -u rcboat_balloon_ros.service -n 100 --no-pager' >&2
  exit 4
}
echo 'RCBoat ROS Noetic v2.2.0 installed and running.'
