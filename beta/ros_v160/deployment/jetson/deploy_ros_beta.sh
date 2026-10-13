#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WS=/home/jetson/rcboat_ros_ws
STAMP="$(date +%Y%m%d_%H%M%S)"

[[ -f /opt/ros/noetic/setup.bash ]] || { echo "Install ROS dependencies first." >&2; exit 1; }
sudo systemctl stop rcboat_ros.service rcboat_ros_hil.service 2>/dev/null || true

mkdir -p "$WS/src" "$WS/runtime/logs/gps" "$WS/backups/$STAMP" "$WS/deployment"
if [[ -d "$WS/src/rcboat_ros" ]]; then
  cp -a "$WS/src/rcboat_ros" "$WS/backups/$STAMP/rcboat_ros"
fi
rm -rf "$WS/src/rcboat_ros.new"
cp -a "$SOURCE_ROOT/catkin_ws/src/rcboat_ros" "$WS/src/rcboat_ros.new"
rm -rf "$WS/src/rcboat_ros"
mv "$WS/src/rcboat_ros.new" "$WS/src/rcboat_ros"
cp -a "$SOURCE_ROOT/deployment/jetson/." "$WS/deployment/"
chmod +x "$WS/deployment"/*.sh "$WS/deployment"/*.py

if [[ ! -f "$WS/runtime/routes.json" ]]; then
  if [[ -f /home/jetson/rcboat/routes.json ]]; then
    cp -a /home/jetson/rcboat/routes.json "$WS/runtime/routes.json"
  else
    cp -a "$SOURCE_ROOT/catkin_ws/src/rcboat_ros/config/routes.json" "$WS/runtime/routes.json"
  fi
fi
if [[ ! -f "$WS/runtime/.ntrip.env" ]]; then
  if [[ -f /home/jetson/rcboat/.ntrip.env ]]; then
    cp -a /home/jetson/rcboat/.ntrip.env "$WS/runtime/.ntrip.env"
  else
    printf '%s\n' 'NTRIP_ENABLED=false' 'NTRIP_HOST=' 'NTRIP_PORT=2101' 'NTRIP_MOUNTPOINT=' 'NTRIP_USERNAME=' 'NTRIP_PASSWORD=' 'NTRIP_TLS=false' 'NTRIP_TIMEOUT_S=10' 'NTRIP_GGA_INTERVAL_S=10' > "$WS/runtime/.ntrip.env"
  fi
  chmod 600 "$WS/runtime/.ntrip.env"
fi

cd "$WS"
source /opt/ros/noetic/setup.bash
catkin_make

sudo cp -a "$SOURCE_ROOT/systemd/rcboat_ros.service" /etc/systemd/system/rcboat_ros.service
sudo cp -a "$SOURCE_ROOT/systemd/rcboat_ros_hil.service" /etc/systemd/system/rcboat_ros_hil.service
sudo systemctl daemon-reload
sudo systemctl disable rcboat_ros.service rcboat_ros_hil.service >/dev/null 2>&1 || true

echo "ROS beta deployed to $WS"
echo "Existing /home/jetson/rcboat and rcboat.service were not modified."
echo "Run USE_ROS.cmd or: sudo $WS/deployment/rcboat_backend_ctl.sh ros"
