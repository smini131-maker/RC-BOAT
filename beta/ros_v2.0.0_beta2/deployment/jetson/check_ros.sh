#!/usr/bin/env bash
set -Eeuo pipefail
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash
printf 'Checking ROS master...\n'
rosnode list >/dev/null
printf 'Topics:\n'
rostopic list | grep '/rcboat/'
fail=0
for x in /rcboat/gps/status /rcboat/route/state /rcboat/navigation/desired /rcboat/safety/final_command /rcboat/actuator/status; do
  echo "-- $x"
  if ! timeout 8 rostopic echo -n 1 "$x" > /tmp/rcboat_ros_topic_check.txt 2>&1; then
    cat /tmp/rcboat_ros_topic_check.txt
    echo "ERROR: MISSING/STALE $x"
    fail=1
  else head -n 12 /tmp/rcboat_ros_topic_check.txt; fi
done
printf 'Services:\n'
rosservice list | grep /rcboat || fail=1
if (( fail )); then echo 'ROS HEALTH CHECK FAILED'; exit 1; fi
echo 'ROS topics and services responding. Verify rqt_graph separately with X display.'
