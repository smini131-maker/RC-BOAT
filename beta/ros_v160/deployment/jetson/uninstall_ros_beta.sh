#!/usr/bin/env bash
set -euo pipefail

WS=/home/jetson/rcboat_ros_ws
BACKUP=/home/jetson/rcboat_ros_runtime_backup_$(date +%Y%m%d_%H%M%S).tar.gz
sudo systemctl stop rcboat_ros.service rcboat_ros_hil.service 2>/dev/null || true
if [[ -x "$WS/deployment/set_safe_pwm.py" ]]; then "$WS/deployment/set_safe_pwm.py" || true; fi
sudo systemctl disable rcboat_ros.service rcboat_ros_hil.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/rcboat_ros.service /etc/systemd/system/rcboat_ros_hil.service
sudo systemctl daemon-reload
if [[ -d "$WS" ]]; then
  if [[ -d "$WS/runtime" ]]; then
    tar -czf "$BACKUP" -C "$WS" runtime
    echo "ROS runtime backup: $BACKUP"
  fi
  sudo rm -rf --one-file-system "$WS"
fi
sudo systemctl start rcboat.service
systemctl is-active --quiet rcboat.service
echo "ROS beta removed. daemon v1.6 restored. Shared ROS packages were kept."
