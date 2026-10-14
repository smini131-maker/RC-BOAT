# RC-BOAT ROS Noetic v2.0.0 architecture

```text
Windows GUI
  ├─ TCP 8765 ──> gui_bridge_node ──> ROS services/topics
  └─ SSH 22  ───> optional deployment terminal

gps_node ──> /rcboat/gps/status ──┬─> route_manager_node
ntrip_node ─> /rcboat/gps/rtcm    ├─> navigation_node
                                  ├─> safety_supervisor_node
                                  └─> ground_test_logger_node

navigation desired + RC/manual + E-STOP
  ──> safety_supervisor_node ──> final_command ──> actuator_node ──> PCA9685
```

`gui_bridge_node` exposes the same newline-delimited JSON protocol on a local UNIX socket and TCP. Therefore ROS control and logger stop do not depend on an SSH session. SSH is not a backend health signal.

Routes are an initially empty user-owned collection. Manual upsert normalizes every waypoint to a 1-based number and calculates WGS84 UTM. Ground test start fixes exactly three distinct route IDs; route changes do not silently replace the recorded start snapshot.

The logger subscribes only. It does not own GPS, I2C, serial, or output control. `GROUND_TEST` mode forces safe PWM in both the supervisor and actuator. CSV/JSONL distinguish command write confirmation from unsupported physical feedback.
