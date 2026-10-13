#!/usr/bin/env bash
set -euo pipefail

if systemctl is-active --quiet rcboat.service; then
  echo "rcboat.service is still active" >&2
  exit 1
fi
if systemctl is-active --quiet rcboat_ros_hil.service; then
  echo "rcboat_ros_hil.service is still active" >&2
  exit 1
fi

for device in \
  /dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 \
  /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 \
  /dev/i2c-1; do
  if [[ -e "$device" ]] && command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then
    echo "Hardware device is busy: $device" >&2
    fuser -v "$device" >&2 || true
    exit 1
  fi
done
