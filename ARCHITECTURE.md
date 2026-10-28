# RC-BOAT ROS Noetic v2.1.10 architecture

```text
Windows GUI
  ├─ TCP 8765 ──> gui_bridge_node ──> ROS services/topics
  └─ SSH 22  ───> deployment terminal + operator presence check

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

In v2.1.10 the GUI sends an authenticated `operator_link` heartbeat on a separate TCP
connection; the gateway stamps `/rcboat/gui/link` with Jetson monotonic time. SSH
loss forces MANUAL; missing heartbeats expire after 5 s even if the GUI has crashed.
This does not gate status queries, E-STOP or ground-stop behind an SSH session.
GPS, route, navigation and RC nodes respawn independently so their failure does not
terminate the manual arbitration/output path. Cached source timestamps are checked.
Every failsafe cancels autonomous arming and waits for 0.3 s RC throttle neutral.
E-STOP remains latched regardless of the MANUAL mode label.

Correction diagnostics now distinguish the time since a CRC-valid RTCM3 frame
arrived at the Jetson from receiver-reported GGA differential age. A 2 Hz timer
publishes through network receive/reconnect waits, and gateway/logger recompute
reception age from the original Jetson monotonic timestamp. HTTP chunk framing
is decoded before RTCM validation. Raw bytes and validated frames have separate counters.
The SSH health thread is the only active probe owner. One timeout retains the
current authenticated session; two consecutive failures confirm a disconnect.
Actual shell/transport termination bypasses that tolerance. All motion starts
require GUI/backend release agreement, while stop and read operations remain available.
The installer validates a file manifest before a clean catkin build and verifies
running gateway path/hash plus GPS/NTRIP/safety versions after ROS restart.
