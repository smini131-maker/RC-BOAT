#!/usr/bin/env bash
set -euo pipefail

if [[ "$(. /etc/os-release && echo "$ID:$VERSION_ID")" != "ubuntu:20.04" ]]; then
  echo "This beta installer requires Ubuntu 20.04." >&2
  exit 1
fi
if [[ "$(dpkg --print-architecture)" != "arm64" ]]; then
  echo "WARNING: expected Jetson arm64, found $(dpkg --print-architecture)" >&2
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg2 lsb-release python3-pip python3-serial python3-pyproj i2c-tools psmisc avahi-daemon libnss-mdns

if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
  curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo tee /usr/share/keyrings/ros-archive-keyring.gpg >/dev/null
fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros/ubuntu focal main" | sudo tee /etc/apt/sources.list.d/ros1-latest.list >/dev/null
sudo apt-get update
sudo apt-get install -y ros-noetic-ros-base ros-noetic-rospy ros-noetic-roslaunch ros-noetic-rosnode ros-noetic-rostopic ros-noetic-rosservice ros-noetic-rqt-graph ros-noetic-sensor-msgs ros-noetic-diagnostic-msgs ros-noetic-std-srvs ros-noetic-message-generation python3-catkin-pkg python3-rospkg
python3 -m pip install --user 'pyserial>=3.5,<4' 'smbus2>=0.4,<1'

echo "ROS dependency installation complete. No RC Boat service was started."
