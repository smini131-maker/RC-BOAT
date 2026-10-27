cmake_minimum_required(VERSION 3.0.2)
project(rcboat_ros)
find_package(catkin REQUIRED COMPONENTS rospy std_msgs message_generation)
catkin_python_setup()
add_message_files(FILES ControlCommand.msg GpsState.msg)
add_service_files(FILES Execute.srv)
generate_messages(DEPENDENCIES std_msgs)
catkin_package(CATKIN_DEPENDS rospy std_msgs message_runtime)
catkin_install_python(PROGRAMS
 nodes/rc_input_node.py nodes/gps_node.py nodes/ntrip_node.py
 nodes/route_manager_node.py nodes/navigation_node.py
 nodes/safety_supervisor_node.py nodes/actuator_node.py
 nodes/ground_test_logger_node.py nodes/gui_bridge_node.py
 nodes/balloon_vision_node.py
 DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})
install(DIRECTORY launch config DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
