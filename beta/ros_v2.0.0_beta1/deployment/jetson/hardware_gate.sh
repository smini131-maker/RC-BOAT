#!/usr/bin/env bash
set -Eeuo pipefail
# Mandatory gate on EVERY systemd start. Starts only if legacy service and all hardware are released.
if systemctl is-active --quiet rcboat.service;then echo 'FAILED: legacy rcboat.service still active';exit 1;fi
command -v fuser >/dev/null || { echo 'FAILED: fuser not installed';exit 1; }
for dev in /dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 /dev/i2c-1; do
 [[ -e $dev ]] || { echo "FAILED: missing $dev";exit 2; }
 if fuser "$(readlink -f "$dev")" >/dev/null 2>&1;then echo "FAILED: busy $dev";exit 3;fi
done
python3 /home/jetson/rcboat_ros_ws/deployment/jetson/set_safe_pwm.py
