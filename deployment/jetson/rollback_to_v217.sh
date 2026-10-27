#!/usr/bin/env bash
set -Eeuo pipefail
# Preserve both workspaces and data; only one ROS actuator owner can run.
[[ -f /etc/systemd/system/rcboat_ros.service ]] || { echo 'Old ROS unit not found'; exit 1; }
sudo systemctl disable --now rcboat_balloon_ros.service
sudo systemctl enable --now rcboat_ros.service
sudo systemctl status rcboat_ros.service --no-pager
