#!/usr/bin/env bash
set -Eeo pipefail
printf 'Jetson: ';uname -m
printf 'OS: ';source /etc/os-release; echo "$PRETTY_NAME"
if [[ $(uname -m) != aarch64 || $VERSION_ID != 20.04 ]];then echo 'WARNING: expected Jetson aarch64 Ubuntu 20.04';fi
[[ -f /opt/ros/noetic/setup.bash ]] || { echo 'ERROR: ROS Noetic not installed; do not switch backend';exit 1; }
source /opt/ros/noetic/setup.bash
command -v catkin_make >/dev/null || { echo 'ERROR: catkin_make not installed';exit 1; }
python3 -c 'import serial,smbus2,pyproj;print("Python dependencies: installed")' || exit 1
for p in /dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 /dev/i2c-1; do
  if [[ ! -e $p ]];then echo "MISSING: $p";exit 1;fi
  echo "DEVICE: $p -> $(readlink -f "$p")"
done
systemctl is-enabled rcboat.service || true
systemctl is-enabled rcboat_ros.service || true
