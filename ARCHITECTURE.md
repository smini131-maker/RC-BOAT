# RC-BOAT ROS Noetic v2.2.0 architecture

The camera extension is isolated in the balloon workspace/data directory and optional
`balloon_vision_node`. Its capture thread keeps only the newest frame, its inference
worker runs YOLOv5n ONNX, and an independent ROS timer publishes status and demands.
The original frame monotonic timestamp is retained through inference and checked again
by the safety supervisor. A fresh camera frame cannot make an old detection fresh.

`BALLOON` mode requires explicit arming after target acquisition. Camera/model loss,
target loss, stale inference and the configured image-size stop condition latch a neutral
output until the operator rearms. Manual RC takeover and E-STOP override vision.
The actuator remains the sole PCA9685 owner. JPEG preview is a separate HTTP connection
on 8766, requested only while the GUI camera tab is visible.

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

Routes are an initially empty user-owned collection. A subroute owns waypoints; a named Multi-Path (large route) explicitly owns an ordered list of one or more subroute IDs and a default subroute. Endpoint similarity is only an optional GUI selection helper. At every valid GPS update, the active Target Path is the member subroute with the smallest point-to-polyline distance. There is no distance threshold, hold timer, priority gate, or cooldown; an exact distance tie retains the current route. With Multi-Path disabled, navigation and ground tests operate on one selected subroute. Ground-test start freezes the complete selected large route or single route; later edits do not replace that snapshot.

The logger subscribes only. It does not own GPS, I2C, serial, or output control. `GROUND_TEST` starts neutral by default. A non-persistent GUI acknowledgement that the propellers have been removed can enable navigation-equivalent steering and throttle PWM for that one test; E-STOP, GPS health, freshness and command-range gates remain active. CSV/JSONL distinguish command write confirmation from unsupported physical feedback. `route_metrics.csv` is a long-format sample-by-subroute table for post-processing heading-error and route-selection graphs.
