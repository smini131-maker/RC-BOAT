#!/usr/bin/env bash
# Invoke under sudo on actual Jetson (no remote automatic privilege escalation).
set -Eeuo pipefail
TARGET=${1:?expected ros or daemon}
ROOT=/home/jetson/rcboat_ros_ws
cd "$ROOT"
wait_inactive(){
 local name=$1
 for x in {1..40};do if ! systemctl is-active --quiet "$name";then return 0;fi;sleep .25;done
 echo "ERROR: $name still active" >&2;return 1
}
verify_release(){
 local device
 command -v fuser >/dev/null || { echo 'ERROR: fuser required for owner check' >&2;return 1; }
 for device in /dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 /dev/i2c-1;do
   [[ -e $device ]] || { echo "Missing device $device" >&2;return 1; }
   if fuser "$(readlink -f "$device")" >/dev/null 2>&1;then echo "BUSY hardware: $device" >&2;return 1;fi
 done
}
if [[ $TARGET == ros ]];then
  [[ -f /opt/ros/noetic/setup.bash ]] || { echo 'ROS Noetic missing';exit 3; }
  systemctl stop rcboat.service
  wait_inactive rcboat.service
  if pgrep -f '^/home/jetson/rcboat/.venv/bin/python.*rcboat_daemon.py' >/dev/null;then echo 'LEGACY PID STILL PRESENT';exit 4;fi
  verify_release
  python3 deployment/jetson/set_safe_pwm.py
  systemctl disable rcboat_ros.service >/dev/null 2>&1 || true
  systemctl start rcboat_ros.service
  sleep 3
  systemctl is-active --quiet rcboat_ros.service || { echo 'ROS start failure: reverting to daemon';systemctl start rcboat.service;exit 5; }
  echo 'ROS BETA ACTIVE (not enabled on boot)';
elif [[ $TARGET == daemon ]];then
  systemctl stop rcboat_ros.service
  wait_inactive rcboat_ros.service
  verify_release
  python3 deployment/jetson/set_safe_pwm.py
  systemctl start rcboat.service
  sleep 2
  systemctl is-active --quiet rcboat.service || exit 6
  echo 'STABLE DAEMON ACTIVE'
else echo 'Use ros or daemon';exit 2;fi
bash deployment/jetson/check_backend.sh
