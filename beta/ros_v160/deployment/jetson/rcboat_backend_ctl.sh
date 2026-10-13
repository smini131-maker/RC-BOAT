#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-check}"
WS=/home/jetson/rcboat_ros_ws

safe_pwm() {
  if [[ -x "$WS/deployment/set_safe_pwm.py" ]]; then
    "$WS/deployment/set_safe_pwm.py" || echo "WARNING: standalone safe PWM check failed" >&2
  fi
}

wait_inactive() {
  local service="$1"
  for _ in {1..20}; do
    systemctl is-active --quiet "$service" || return 0
    sleep 0.25
  done
  echo "Service did not stop: $service" >&2
  return 1
}

case "$ACTION" in
  ros)
    sudo systemctl stop rcboat_ros_hil.service rcboat.service || true
    wait_inactive rcboat.service
    safe_pwm
    if ! sudo systemctl start rcboat_ros.service || ! "$WS/deployment/check_ros.sh" real; then
      echo "ROS start/check failed. Restoring daemon..." >&2
      sudo systemctl stop rcboat_ros.service || true
      safe_pwm
      sudo systemctl start rcboat.service
      systemctl is-active --quiet rcboat.service
      exit 1
    fi
    echo "ACTIVE BACKEND: ROS real"
    ;;
  hil)
    sudo systemctl stop rcboat_ros.service rcboat.service || true
    wait_inactive rcboat.service
    safe_pwm
    sudo systemctl start rcboat_ros_hil.service
    "$WS/deployment/check_ros.sh" hil
    echo "ACTIVE BACKEND: ROS HIL (physical actuator node is absent)"
    ;;
  daemon)
    sudo systemctl stop rcboat_ros.service rcboat_ros_hil.service || true
    wait_inactive rcboat_ros.service
    wait_inactive rcboat_ros_hil.service
    safe_pwm
    sudo systemctl start rcboat.service
    systemctl is-active --quiet rcboat.service
    timeout 8 bash -c 'until exec 3<>/dev/tcp/127.0.0.1/8765; do sleep 0.5; done'
    echo "ACTIVE BACKEND: daemon v1.6"
    ;;
  check)
    echo "rcboat.service:         $(systemctl is-active rcboat.service || true)"
    echo "rcboat_ros.service:     $(systemctl is-active rcboat_ros.service || true)"
    echo "rcboat_ros_hil.service: $(systemctl is-active rcboat_ros_hil.service || true)"
    if systemctl is-active --quiet rcboat_ros.service; then "$WS/deployment/check_ros.sh" real; fi
    if systemctl is-active --quiet rcboat_ros_hil.service; then "$WS/deployment/check_ros.sh" hil; fi
    ;;
  *) echo "Usage: $0 {ros|hil|daemon|check}" >&2; exit 2 ;;
esac
