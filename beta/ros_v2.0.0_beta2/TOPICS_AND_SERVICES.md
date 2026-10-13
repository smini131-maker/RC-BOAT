# ROS Topic / Service 명세

모든 이름은 Jetson 내부 ROS1 Master(`roscore`) 기준. Windows는 SSH Unix-socket bridge만 이용한다.

## Topics

| 이름 | 형식 | Owner / 기능 |
|---|---|---|
| `/rcboat/rc/input` | `std_msgs/String` JSON | rc_input_node / steering_us,throttle_us,monotonic |
| `/rcboat/gps/status` | `std_msgs/String` JSON | gps_node / WGS84,heading,speed,RTK,HDOP,hAcc,C/N0,fix |
| `/rcboat/gps/rtcm` | `std_msgs/UInt8MultiArray` | ntrip_node → gps_node / correction bytes |
| `/rcboat/ntrip/status` | `std_msgs/String` JSON | ntrip_node / connected,bytes_received,correction_age,last_error |
| `/rcboat/route/state` | `std_msgs/String` JSON | route_manager / current route, waypoint, switch |
| `/rcboat/route/commands` | `std_msgs/String` JSON | alternate internal route-control channel; use service preferred |
| `/rcboat/navigation/desired` | `std_msgs/String` JSON | navigation / desired steering/throttle/rudder angle |
| `/rcboat/safety/final_command` | `rcboat_ros/ControlCommand` | supervisor → actuator (sole actuation input) |
| `/rcboat/safety/state` | `std_msgs/String` JSON | supervisor / mode, lock, estop |
| `/rcboat/actuator/status` | `std_msgs/String` JSON | actuator / applied command and health (NOT physical feedback) |
| `/rcboat/ground_test/status` | `std_msgs/String` JSON | logger / active,folder,samples |
| `/rcboat/events` | `std_msgs/String` JSON | route/safety / errors and route switches |

`ControlCommand`: Header, mode, source, steering_pwm, throttle_pwm, actuator_locked. `GpsState.msg` exists as reserved typed model while current MVP GPS topic uses JSON for compatibility with Windows bridge.

## Services (`rcboat_ros/Execute`)

Request: `string action`, `string arguments_json`. Response: `bool success`, `string response_json`. GUI receives structured success and error, not optimistic success.

| ROS service | Action names | Arguments |
|---|---|---|
| `/rcboat/safety/execute` | set_mode, estop, reset_estop, set_remote_pwm, heartbeat, status | mode / armed, PWM, etc |
| `/rcboat/route/execute` | select_route, delete_route, list_routes, record_start, record_stop, set_multipath | route_id, name |
| `/rcboat/logger/execute` | start, stop, status | {} |
| `/rcboat/ntrip/execute` | configure | enabled,host,port,mountpoint,username,password,tls |

### Bridge actions

`status`, `ground_start`, `ground_stop`, other `Execute` action names. `ground_start` first sets safety mode `GROUND_TEST`, waits, then starts logger. `ground_stop` stops logger before restoring `AUTO_SAFE`. Bridge socket file: `~/rcboat_ros_data/gui_bridge.sock` mode 0600.

### Shell verification

```bash
source /opt/ros/noetic/setup.bash
source ~/rcboat_ros_ws/catkin_ws/devel/setup.bash
rosnode list
rostopic list
rostopic hz /rcboat/gps/status
rostopic echo /rcboat/navigation/desired
rosservice list
rqt_graph
```
