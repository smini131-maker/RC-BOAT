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

회전수·전류 센서 어댑터는 기본 구성에 포함하지 않습니다. 센서가 없으면 물리 추진 피드백 상태는 `unsupported`입니다.

서비스 `/rcboat/{route,navigation,safety,ntrip,logger}/execute`는 [Execute.srv](../catkin_ws/src/rcboat_ros/srv/Execute.srv)를 사용합니다. 전체 발행·구독 구성은 [launch 파일](../catkin_ws/src/rcboat_ros/launch/rcboat.launch)과 각 [노드](../catkin_ws/src/rcboat_ros/nodes)에서 확인합니다.

## GUI gateway

같은 줄 단위 JSON 프로토콜을 두 경로로 제공합니다.

- TCP: `JETSON_IP:8765` — Windows GUI 연결
- UNIX socket: `~/rcboat_ros_data/gui_bridge.sock` — Jetson 로컬 연결

한 요청을 JSON 한 줄과 개행으로 전송합니다. 주요 요청 필드는 `action`, `arguments`이며, gateway token 사용 시 `token`을 포함합니다. 구현은 [gui_bridge_node.py](../catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py)를 참고합니다.

| action | 용도 |
|---|---|
| `status` | backend 통합 상태 조회 |
| `operator_link` | 별도 연결에서 GUI heartbeat 갱신 |
| `upsert_route`, `delete_route`, `select_route` | 소루트 관리 |
| `upsert_multipath`, `delete_multipath`, `select_multipath` | 대루트 관리 |
| `ground_start` | `target_type`(`multipath` 또는 `single_route`), `target_id`로 시험 시작 |
| `ground_stop` | 시험 마감; 이미 종료된 시험에 재요청 가능 |
| `list_ground_tests` | 저장된 시험 목록 조회 |
| `download_ground_test` | 선택한 시험 ZIP을 base64와 SHA-256으로 반환 |

`GROUND_TEST_STOP` 같은 GUI 명령은 worker에서 gateway action으로 변환합니다. GUI와 gateway 사이 전체 매핑은 [ssh_worker.py](../windows_gui/rcboat_gui/ssh_worker.py)에 있습니다. 상태 조회·시험 정지는 SSH 연결 없이 ROS gateway로 처리합니다.

## 시각·품질 필드

`gps_data_age_s`는 GPS 수신 경과 시간입니다. NTRIP의 `last_rtcm_monotonic`, `correction_age_source`, `correction_age_status`, `rtcm_frames_received`, `rtcm_bytes_received`, `rtcm_crc_errors`는 보정 수신 진단에 사용합니다. TCP의 `bytes_received`와 CRC가 정상인 RTCM 프레임 수는 별개입니다.

GPS의 `receiver_correction_age_s/status`는 수신기 GGA에서 제공하는 보정 나이입니다. Jetson의 RTCM 수신 경과 시간이나 서버에서부터의 실제 전송 지연과 동일하지 않습니다.

gateway의 `runtime_identity`와 각 노드의 `software_version`은 배포 후 실행 버전 확인에 사용합니다. 미제공·무효·오래된 값의 해석은 [로그·분석 안내](data-analysis.md)를 참고합니다.
