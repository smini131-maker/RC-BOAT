cmake_minimum_required(VERSION 3.0.2)
project(rcboat_ros)

find_package(catkin REQUIRED COMPONENTS
  rospy rosnode rosservice std_msgs std_srvs sensor_msgs diagnostic_msgs message_generation
)

add_message_files(FILES
  RcInput.msg
  GpsStatus.msg
  Rtcm.msg
  NtripStatus.msg
  ControlCommand.msg
  BoatState.msg
  ActuatorStatus.msg
  NavigationStatus.msg
  RouteState.msg
  Event.msg
)

add_service_files(FILES
  SetMode.srv
  SetPwm.srv
  SetMultipath.srv
  SelectRoute.srv
  DeleteRoute.srv
  StartRouteRecording.srv
  StopRouteRecording.srv
  SetGpsSettings.srv
  ConfigureNtrip.srv
  InjectHilFault.srv
)

generate_messages(DEPENDENCIES std_msgs)

catkin_python_setup()
catkin_package(CATKIN_DEPENDS rospy rosnode rosservice std_msgs std_srvs sensor_msgs diagnostic_msgs message_runtime)

catkin_install_python(PROGRAMS
  scripts/rc_input_node.py
  scripts/gps_node.py
  scripts/ntrip_node.py
  scripts/route_manager_node.py
  scripts/navigation_node.py
  scripts/safety_supervisor_node.py
  scripts/actuator_node.py
  scripts/gps_logger_node.py
  scripts/gui_bridge_node.py
  scripts/mock_hardware_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch config DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
