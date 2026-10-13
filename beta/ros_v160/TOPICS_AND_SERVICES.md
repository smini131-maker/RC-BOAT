# Topics and Services

## Topics

| Topic | Type | Publisher | 주요 subscriber |
|---|---|---|---|
| `/rcboat/rc/input` | `RcInput` | RC 또는 mock | safety, bridge |
| `/fix` | `sensor_msgs/NavSatFix` | GPS | 표준 ROS 도구 |
| `/rcboat/gps/status` | `GpsStatus` | GPS 또는 mock | nav, route, logger, bridge |
| `/rtcm` | `Rtcm` | NTRIP | GPS owner |
| `/rcboat/ntrip/status` | `NtripStatus` | NTRIP 또는 mock | nav, logger, bridge |
| `/rcboat/route/state` | `RouteState` | route manager | nav, logger, bridge |
| `/rcboat/navigation/command` | `ControlCommand` | navigation | safety |
| `/rcboat/navigation/status` | `NavigationStatus` | navigation | logger, bridge |
| `/rcboat/remote/command` | `ControlCommand` | bridge | safety |
| `/rcboat/remote/heartbeat` | `std_msgs/Empty` | bridge | safety |
| `/rcboat/safety/actuator_command` | `ControlCommand` | **safety only** | actuator 또는 HIL mock |
| `/rcboat/safety/state` | `BoatState` | safety | route, nav, logger, bridge |
| `/rcboat/actuator/status` | `ActuatorStatus` | actuator 또는 mock | safety, bridge |
| `/rcboat/gps/logging_state` | `std_msgs/String` | logger | bridge |

## Services

| Service | Type | 용도 |
|---|---|---|
| `/rcboat/set_mode` | `SetMode` | AUTO/MANUAL/NAVIGATION/REMOTE |
| `/rcboat/set_auto_cruise` | `SetPwm` | AUTO cruise 저장 |
| `/rcboat/emergency_stop` | `std_srvs/Trigger` | E-STOP latch |
| `/rcboat/clear_estop` | `std_srvs/Trigger` | E-STOP 해제 후 safe 유지 |
| `/rcboat/safety/force_safe` | `std_srvs/Trigger` | 6000/6450 강제 |
| `/rcboat/gps/set_settings` | `SetGpsSettings` | GPS gate/RTK fallback 저장 |
| `/rcboat/ntrip/configure` | `ConfigureNtrip` | NTRIP 설정 저장/연결 |
| `/rcboat/ntrip/disable` | `std_srvs/Trigger` | NTRIP 끄기 |
| `/rcboat/routes/select` | `SelectRoute` | 항로 선택/영구 저장 |
| `/rcboat/routes/delete` | `DeleteRoute` | 기록 항로 삭제 |
| `/rcboat/routes/start_recording` | `StartRouteRecording` | GPS 항로 기록 시작 |
| `/rcboat/routes/stop_recording` | `StopRouteRecording` | 저장 또는 취소 |
| `/rcboat/routes/reload` | `std_srvs/Trigger` | routes.json 재로드 |
| `/rcboat/set_multipath` | `SetMultipath` | Multi-Path 기준 저장 |
| `/rcboat/gps/start_logging` | `std_srvs/Trigger` | GPS CSV 시작 |
| `/rcboat/gps/stop_logging` | `std_srvs/Trigger` | GPS CSV 종료 |
| `/rcboat/hil/inject_fault` | `InjectHilFault` | HIL 전용 장애 주입 |

HIL fault 이름은 `gps_disconnect`, `gps_no_fix`, `gps_stale`, `gps_hdop_bad`, `rtk_loss`, `rc_disconnect`, `actuator_fault`, `multipath_switch`입니다.
