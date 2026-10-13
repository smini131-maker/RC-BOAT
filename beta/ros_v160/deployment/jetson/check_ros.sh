#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-real}"
WS=/home/jetson/rcboat_ros_ws
SERVICE=rcboat_ros.service
if [[ "$PROFILE" == "hil" ]]; then SERVICE=rcboat_ros_hil.service; fi

systemctl is-active --quiet "$SERVICE"
source /opt/ros/noetic/setup.bash
source "$WS/devel/setup.bash"
export ROS_MASTER_URI=http://127.0.0.1:11311
export ROS_HOSTNAME=127.0.0.1

timeout 8 bash -c 'until rosnode list >/dev/null 2>&1; do sleep 0.5; done'

required_nodes=(/gui_bridge_node /route_manager_node /navigation_node /safety_supervisor_node /gps_logger_node)
if [[ "$PROFILE" == "real" ]]; then
  required_nodes+=(/rc_input_node /gps_node /ntrip_node /actuator_node)
else
  required_nodes+=(/mock_hardware_node)
fi

nodes="$(rosnode list)"
for node in "${required_nodes[@]}"; do
  grep -qx "$node" <<<"$nodes" || { echo "Missing node: $node" >&2; exit 1; }
done

for topic in /rcboat/safety/actuator_command /rcboat/safety/state /rcboat/route/state /rcboat/navigation/status; do
  rostopic list | grep -qx "$topic" || { echo "Missing topic: $topic" >&2; exit 1; }
done

publisher_count="$(rostopic info /rcboat/safety/actuator_command | awk '/Publishers:/{flag=1;next}/Subscribers:/{flag=0}flag && /^ \* /{count++}END{print count+0}')"
[[ "$publisher_count" == "1" ]] || { echo "Expected exactly one final-command publisher, got $publisher_count" >&2; exit 1; }

if [[ "$PROFILE" == "real" ]]; then
  rosservice call /rcboat/safety/force_safe '{}' >/dev/null
  actuator_status="$(timeout 5 rostopic echo -n 1 /rcboat/actuator/status)"
  grep -q 'steering_pwm: 6000' <<<"$actuator_status"
  grep -q 'throttle_pwm: 6450' <<<"$actuator_status"
fi

echo "ROS CHECK OK: profile=$PROFILE service=$SERVICE final_command_publishers=1"
