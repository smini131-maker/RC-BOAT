# ROS 및 gateway 인터페이스

[프로젝트 소개](../README.md) · [아키텍처](architecture.md)

## 주요 토픽

상태 토픽은 아래 표에 별도 표시가 없으면 `std_msgs/String`의 JSON payload를 사용합니다.

| 토픽 | 내용 |
|---|---|
| `/rcboat/gps/status` | UTC, 위경도·UTM, GNSS 속도·COG, FIX/RTK, 유효성·수신 경과 |
| `/rcboat/ntrip/status` | NTRIP 연결, CRC 정상 RTCM 수신량·경과 시간 |
| `/rcboat/gps/rtcm` | 보정 데이터 전달 (`std_msgs/UInt8MultiArray`) |
| `/rcboat/route/state` | 항로·대루트, 활성 항로, 최근접 선택, 목표 waypoint, 후보별 거리·오차 |
| `/rcboat/navigation/desired` | 항법 판단, 목표 조향각·PWM·속도 |
| `/rcboat/safety/state` | 모드, 수동 전환 원인, E-STOP, 최종 PWM, 출력 잠금·수동 재준비 |
| `/rcboat/actuator/status` | PCA 쓰기 성공 여부, 전송 시각, 명령 PWM |
| `/rcboat/ground_test/status` | `idle/recording/stopping/error`, 시험 폴더·sample 수 |
| `/rcboat/gui/link` | Jetson monotonic 기준 GUI heartbeat, SSH 상태 |
| `/rcboat/propulsion/status` | 선택적 센서 어댑터의 `blocked`·`fault` 상태 |
| `/rcboat/events` | 모드, 수동 개입, E-STOP, 오류, 항로·설정 변경 이벤트 |
| `/rcboat/vision/status` | 카메라·모델·backend, 검출/핑크 비율·예측 상태·위치, 프레임 경과·추론시간·설정 |
| `/rcboat/vision/desired` | BALLOON 목표 조향/스로틀, 세션, frame monotonic, 유효성 |

회전수·전류 센서 어댑터는 기본 구성에 포함하지 않습니다. 센서가 없으면 물리 추진 피드백 상태는 `unsupported`입니다.

서비스 `/rcboat/{route,navigation,safety,ntrip,logger,vision}/execute`는 [Execute.srv](../catkin_ws/src/rcboat_ros/srv/Execute.srv)를 사용합니다. 전체 발행·구독 구성은 [launch 파일](../catkin_ws/src/rcboat_ros/launch/rcboat.launch)과 각 [노드](../catkin_ws/src/rcboat_ros/nodes)에서 확인합니다.

## GUI gateway

같은 줄 단위 JSON 프로토콜을 두 경로로 제공합니다.

- TCP: `JETSON_IP:8765` — Windows GUI 연결
- UNIX socket: `~/rcboat_ros_data/gui_bridge.sock` — Jetson 로컬 연결

한 요청을 JSON 한 줄과 개행으로 전송합니다. 주요 요청 필드는 `action`, `arguments`이며, gateway token 사용 시 `token`을 포함합니다. 구현은 [gui_bridge_node.py](../catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py)를 참고합니다.

| action | 용도 |
|---|---|
| `status` | backend 통합 상태 조회 |
| `operator_link` | 별도 연결에서 GUI heartbeat 갱신 |
| `vision_enable`, `vision_configure`, `vision_reset_tracking`, `vision_status` | 선택적 카메라 활성/설정/추적 초기화/상태. 시작은 `set_mode`의 `BALLOON` 모드로 별도 요청 |
| `download_vision_log` | 최신 추적 JSONL snapshot과 SHA-256 manifest ZIP |
| `upsert_route`, `delete_route`, `select_route` | 소루트 관리 |
| `upsert_multipath`, `delete_multipath`, `select_multipath` | 대루트 관리 |
| `ground_start` | `target_type`(`multipath` 또는 `single_route`), `target_id`로 시험 시작 |
| `ground_stop` | 시험 마감; 이미 종료된 시험에 재요청 가능 |
| `list_ground_tests` | 저장된 시험 목록 조회 |
| `download_ground_test` | 선택한 시험 ZIP을 base64와 SHA-256으로 반환 |
| `set_auto_cruise_pwm` | `value`: duty16 정수 6480~7840을 10 간격으로 입력하거나 7397·7842를 지정합니다. 7397 초과 출력은 NAVIGATION에서만 허용됩니다. 반환 `value`, `cruise_applied_monotonic`은 설정 적용 확인이며 출력 송신 확인과 다름 |
| `set_gps_settings` | `navigation_max_hdop`: 0.5~20 진단 참고값. 로컬 파일에 저장 후 `applied_monotonic`과 실제 값 반환 |

`GROUND_TEST_STOP` 같은 GUI 명령은 worker에서 gateway action으로 변환합니다. GUI와 gateway 사이 전체 매핑은 [ssh_worker.py](../windows_gui/rcboat_gui/ssh_worker.py)에 있습니다. 상태 조회·시험 정지는 SSH 연결 없이 ROS gateway로 처리합니다.

## 시각·품질 필드

`gps_data_age_s`는 GPS 수신 경과 시간입니다. NTRIP의 `last_rtcm_monotonic`, `correction_age_source`, `correction_age_status`, `rtcm_frames_received`, `rtcm_bytes_received`, `rtcm_crc_errors`는 보정 수신 진단에 사용합니다. TCP의 `bytes_received`와 CRC가 정상인 RTCM 프레임 수는 별개입니다.

GPS의 `receiver_correction_age_s/status`는 수신기 GGA에서 제공하는 보정 나이입니다. Jetson의 RTCM 수신 경과 시간이나 서버에서부터의 실제 전송 지연과 동일하지 않습니다.

gateway의 `runtime_identity`와 각 노드의 `software_version`은 배포 후 실행 버전 확인에 사용합니다. 미제공·무효·오래된 값의 해석은 [로그·분석 안내](data-analysis.md)를 참고합니다.

`/rcboat/rc/input`은 Arduino serial의 입력 µs와 `valid`, `monotonic`을 전달합니다. safety는 `rc_input_calibration`과 `pca_output_calibration`을 따로 발행합니다. `/rcboat/gps/status`의 `transport_connected:false`는 명시적 I/O 단절이며, `data_validity:stale`은 데이터 지연입니다. safety의 `gps_grace_active/mode/remaining_s`와 `NAVIGATION_GPS_GRACE` source로 항로 지연 구간을 구분합니다. `operator_link`의 `ssh_state`는 `connected/delayed/disconnected`이며 안전 판정은 Jetson의 heartbeat lease와 확정된 `ssh_connected`도 함께 확인합니다.

`status.gps_settings`는 backend 저장값을 제공하고, `telemetry.navigation.fresh`가 false면 GUI는 순항 적용값을 기본값으로 만들어 내지 않습니다. `cruise_applied_monotonic`은 Jetson 기준 시각이므로 PC monotonic과 직접 비교하지 않습니다.

v2.1.15는 기존 JSON 상태에 항법 `ramp_active`, `ramp_throttle_pwm`, `ramp_rate_pwm_s`, `ramp_session_monotonic`을 추가합니다. `auto_cruise_pwm`은 목표값이며 `desired_throttle_pwm`은 기존 방향 오차 감속 후 램프를 적용한 명령입니다. 안전 상태 `mode_since_monotonic`과 `ramp_session_monotonic`이 같은 NAVIGATION 주행이어야 구동합니다. 토픽·서비스·노드 구조는 유지합니다.
