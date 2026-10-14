# ROS topics, services, and GUI gateway

| Name | Type | Purpose |
|---|---|---|
| `/rcboat/gps/status` | `std_msgs/String` JSON | Receiver UTC/status, WGS84, UTM, FIX/RTK, quality, data age |
| `/rcboat/ntrip/status` | `std_msgs/String` JSON | NTRIP connection and correction age; missing is `null` |
| `/rcboat/route/state` | `std_msgs/String` JSON | User subroutes, named Multi-Paths, selected/active route, target waypoint, per-route candidate metrics |
| `/rcboat/navigation/desired` | `std_msgs/String` JSON | Controller decision, desired rudder/PWM, and target speed |
| `/rcboat/safety/state` | `std_msgs/String` JSON | Mode, E-STOP, final PWM, output lock |
| `/rcboat/actuator/status` | `std_msgs/String` JSON | PCA write success, output timestamp, commanded PWM |
| `/rcboat/ground_test/status` | `std_msgs/String` JSON | `idle/recording/stopping/error`, folder, sample count |
| `/rcboat/events` | `std_msgs/String` JSON | Mode, manual intervention, E-STOP, error, route/config changes |

`/rcboat/{route,navigation,safety,ntrip,logger}/execute` use `rcboat_ros/Execute`.

GUI gateway transports the same newline-delimited JSON over:

- `~/rcboat_ros_data/gui_bridge.sock` for local/SSH compatibility
- `JETSON_IP:8765` for the ROS-independent-of-SSH Windows connection

Important actions: `status`, subroute CRUD (`upsert_route`, `delete_route`, `select_route`), named Multi-Path CRUD (`upsert_multipath`, `delete_multipath`, `select_multipath`), `ground_start` with `{target_type: multipath|single_route, target_id}`, idempotent `ground_stop`, `list_ground_tests`, and `download_ground_test` (base64 ZIP with SHA-256).
