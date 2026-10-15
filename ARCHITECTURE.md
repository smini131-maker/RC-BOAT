# RC-BOAT ROS Noetic v2.1.1 architecture

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

Routes are an initially empty user-owned collection. A subroute owns waypoints; a named Multi-Path (large route) explicitly owns an ordered list of one or more subroute IDs and a default subroute. Endpoint similarity is only an optional GUI selection helper. The active Target Path is retained at a relative distance of 2 m or less and changes to the nearest member subroute only when that distance is strictly greater than 2 m. With Multi-Path disabled, navigation and ground tests operate on one selected subroute. Ground-test start freezes the complete selected large route or single route; later edits do not replace that snapshot.

The logger subscribes only. It does not own GPS, I2C, serial, or output control. `GROUND_TEST` starts neutral by default. A non-persistent GUI acknowledgement that the propellers have been removed can enable navigation-equivalent steering and throttle PWM for that one test; E-STOP, GPS health, freshness and command-range gates remain active. CSV/JSONL distinguish command write confirmation from unsupported physical feedback. `route_metrics.csv` is a long-format sample-by-subroute table for post-processing heading-error and route-selection graphs.
