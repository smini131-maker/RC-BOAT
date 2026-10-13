cmake_minimum_required(VERSION 3.0.2)
project(rcboat_msgs)

find_package(catkin REQUIRED COMPONENTS message_generation std_msgs)

add_message_files(FILES
  RcInput.msg
  PwmCommand.msg
  GpsStatus.msg
  NtripStatus.msg
  GpsLogStatus.msg
  BoatState.msg
)

add_service_files(FILES
  SetMode.srv
  SelectRoute.srv
  SetAutoCruise.srv
  SetMultipath.srv
  StartRouteRecording.srv
  ConfigureNtrip.srv
  SetGpsSettings.srv
  StartHil.srv
)

generate_messages(DEPENDENCIES std_msgs)
catkin_package(CATKIN_DEPENDS message_runtime std_msgs)