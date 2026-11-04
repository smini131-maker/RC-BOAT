# 아키텍처

[프로젝트 소개](../README.md) · [설치](setup.md) · [인터페이스](interfaces.md)

Jetson backend는 ROS Noetic으로 실행합니다. Windows GUI는 TCP gateway로 상태와 명령을 주고받으며, SSH는 배포·터미널과 운항 중 연결 확인에 사용합니다.

## 노드와 데이터 흐름

```text
Windows GUI ── TCP 8765 ── gui_bridge_node ── ROS services/topics
      └─────── SSH 22 ──── 배포·터미널·연결 확인

GNSS ── gps_node ── /rcboat/gps/status ──┬─ route_manager_node
NTRIP ─ ntrip_node ─ RTCM → gps_node     ├─ navigation_node
                                       ├─ safety_supervisor_node
                                       └─ ground_test_logger_node

navigation_node: desired command ────┐
rc_input_node: manual input ─────────┼─ safety_supervisor_node
E-STOP / GPS / operator link ────────┘          │
                                             final command
                                                  │
                                            actuator_node
                                                  │
                                             PCA9685
```

| 구성 | 책임 |
|---|---|
| `gps_node` | GNSS 수신, 위치·속도·COG·FIX/RTK·수신 시각과 품질 표시 |
| `ntrip_node` | NTRIP 연결, RTCM3 CRC 검사, 보정 수신 상태와 경과 시간 |
| `route_manager_node` | 사용자 항로 저장·선택, 최근접 항로·목표 waypoint 계산 |
| `navigation_node` | 목표 방향과 GNSS 진행 방향으로 조향·스로틀 목표 명령 계산 |
| `balloon_vision_node` | 선택적 USB/CSI 영상, YOLOv8n·핑크 확인, 위치/방향 예측, 추적 desired 명령·저속 JPEG 미리보기. PCA 소유권 없음 |
| `safety_supervisor_node` | 자동·수동 명령 중재, 유효성 검사, E-STOP·수동 전환·GPS 유예 |
| `actuator_node` | 최종 명령 범위 검사, PCA9685 쓰기와 전송 결과 보고 |
| `ground_test_logger_node` | 상태 구독, 원본·파생 데이터 기록, 시험 ZIP 생성 |
| `gui_bridge_node` | TCP/UNIX socket 요청을 ROS 서비스·토픽으로 연결 |

로거는 출력 장치나 GPS를 직접 제어하지 않습니다. 장치 출력은 안전 제어를 통과한 최종 명령만 사용합니다. GPS·항로·항법·RC 노드는 독립적으로 재시작할 수 있도록 구성돼 있습니다.

## 항로 선택과 항법

소루트는 waypoint 좌표를 보유합니다. 대루트(Multi-Path)는 사용자가 선택한 소루트 1개 이상과 기본 소루트를 보유합니다. 초기 항로 저장소는 비어 있으며, 기준 항로를 자동 생성하지 않습니다.

Multi-Path 운항에서는 매 유효 GPS 갱신마다 각 소루트의 경로선까지 최소거리를 비교합니다. 가장 가까운 소루트를 즉시 선택하고, 거리가 수치상 같은 경우 현재 항로를 유지합니다. 단일 항로 운항은 선택한 소루트만 사용합니다.

기본 `HEADING` 제어는 현재 위치에서 목표 waypoint로 향하는 방위각을 계산합니다. 이 방위각과 GNSS COG의 차이가 제어에 사용되는 헤딩 오차입니다. 경로선의 접선 방향과 비교한 오차나 선체 yaw 측정값과는 구분합니다.

## 연결과 안전 제어

GUI는 상태 조회와 별도 TCP 연결로 `operator_link` heartbeat를 보냅니다. gateway는 Jetson monotonic 시각을 기록하고, safety supervisor는 링크 유효성을 검사합니다. 연결 조건은 모드에 따라 다릅니다.

| 조건 | 일반 자동 운항 | Ground Test |
|---|---|---|
| SSH만 단절, ROS heartbeat 정상 | MANUAL 전환 | 시험 유지 |
| ROS heartbeat 5초 이상 단절 | MANUAL 전환 | MANUAL 전환, 기록 유지 |
| GPS 무효·stale | NAVIGATION 데이터 stale만 기본 5초·6650 PWM 유예; 최신 FIX 무효는 MANUAL | 기본 5초 중립 유예 후 복구 판단 |
| E-STOP·목표 도착·항법·RC·출력 오류 | 안전 수동 전환 | 안전 수동 전환, 기록 유지 |

정지 명령과 상태 조회는 SSH 세션에 종속되지 않습니다. 수동 전환 시 자동 arming을 취소하고 RC 스로틀 중립 확인을 기다립니다. E-STOP 출력 잠금은 MANUAL 표시와 별개로 유지됩니다. 정확한 시간과 재개 조건은 [운항·시험](operation.md)을 참고합니다.

RC 보정/순항 범위는 ROS와 GUI가 같은 순수 Python `control_config.py`를 사용합니다. 입력 µs와 출력 duty16을 분리하고, 유효성 검사 뒤에만 포화·변환합니다. GUI는 safety가 발행한 유효 보정값을 표시하고 로거는 시험 metadata에 입력·출력을 별도 저장합니다. 순항 명령은 worker·gateway·navigation에서 같은 정수·범위·10 간격을 검증하며 safety·actuator도 자동 설정의 범위를 방어합니다. SSH 응답 지연은 최대 5초 동안 `delayed`, 명시적 세션 종료는 disconnected로 구분합니다.

## 데이터와 배포 경계

카메라 추적도 `vision/desired → safety_supervisor → actuator` 경로를 사용합니다. 새 BALLOON 세션의 fresh 명령, 실제 카메라 입력과 모델 준비 상태를 검사합니다. 미리보기 TCP 8766과 제어 TCP 8765는 별개입니다. 자세한 상태 전이·지연 유예·공통 PWM·카메라 호환 범위는 [카메라 안내](vision.md)에 정리합니다. RTK 공개 설정은 기존 Jetson 로컬 파일에서 읽고 비밀번호는 발행하지 않습니다.

실행 소스는 `/home/jetson/rcboat_ros_ws`, 운용 데이터는 `~/rcboat_ros_data`에 분리합니다. 재배포 시 항로·NTRIP 자격정보·시험 로그는 운용 데이터 경로에 남습니다.

배포 도구는 실행 파일의 SHA-256 manifest를 생성합니다. 설치기는 소스 해시 확인, 서비스 정지, 잔존 프로세스 검사, catkin 재빌드 후 실행 중인 gateway와 GPS/NTRIP/safety의 버전·소스 정보를 검증합니다. Windows GUI도 backend와 버전이 다르면 신규 운항 시작을 차단합니다.
