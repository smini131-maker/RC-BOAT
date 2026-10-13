cmake_minimum_required(VERSION 3.0.2)
project(rcboat_core)

find_package(catkin REQUIRED COMPONENTS
  rcboat_msgs
  rospy
  sensor_msgs
  std_msgs
  std_srvs
)

catkin_python_setup()
catkin_package()

catkin_install_python(PROGRAMS
  scripts/arduino_node.py
  scripts/controller_node.py
  scripts/gps_health_node.py
  scripts/gps_logger_node.py
  scripts/mock_io_node.py
  scripts/ntrip_node.py
  scripts/pca9685_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
