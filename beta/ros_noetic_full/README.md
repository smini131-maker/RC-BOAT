# RC Boat ROS1 Noetic Full Beta

이 프로젝트는 기존 daemon을 ROS로 감싸는 bridge가 아닙니다. Arduino 입력, u-blox GPS, NTRIP, GPS Health, 제어 상태기계, Multi-Path 항법, GPS 기록과 PCA9685 출력을 ROS1 노드와 토픽으로 다시 구성한 독립 실행형 베타입니다.

## 격리 원칙

- 모든 ROS 코드와 설정은 `beta/ros_noetic_full/` 아래에만 존재합니다.
- 저장소 루트의 운영 코드와 `rcboat.service`는 수정하지 않습니다.
- 운영 버전과 ROS 베타를 동시에 실행하지 않습니다.
- ROS 베타도 하드웨어별 단일 소유 원칙을 지킵니다.
  - Arduino: `arduino_node.py`
  - GPS: `ublox_gps` ROS 노드
  - PCA9685: `pca9685_node.py`
  - NTRIP RTCM은 `/rtcm` 토픽을 통해 `ublox_gps`가 GPS로 주입

## 전체 구조

```text
Receiver -> Arduino -> /rcboat/rc_input -----------+
                                                     |
ZED-F9R/F9P -> ublox_gps -> /ublox_gps/* ----------+-> controller_node
NTRIP -> /rtcm -> ublox_gps -> GPS ----------------+        |
                                                              v
                                                     /rcboat/pwm_command
                                                              |
                                                     pca9685_node -> I2C -> PCA9685
```

ROS를 사용해도 GPS USB 케이블 자체는 시리얼 장치입니다. 차이는 Python에서 `serial.readline()`으로 직접 읽는 대신 `ublox_gps` ROS 드라이버가 포트를 열고 `NavSatFix`, `NavPVT`, `NavDOP`, `NavRELPOSNED` 토픽을 발행한다는 점입니다.

## 보존한 동작

- MANUAL / AUTO / NAVIGATION / REMOTE
- 조종기 MANUAL↔AUTO 제스처와 MANUAL 중립 재활성화
- 비상정지 latch
- REMOTE heartbeat 0.7초 timeout
- Arduino, GPS, PWM command stale failsafe
- Steering CH0, ESC CH6 Direct-I2C
- 안전값 Steering 6000 / Throttle 6450
- AUTO 저속 PWM 설정
- Waypoint, 항로 기록, 선택 항로 영구 저장
- Multi-Path: 8 m, 3초, 2 m 우세, cooldown
- GPS Health와 HDOP gate
- RTK Fixed, Float, 일반 GPS 구분
- RTK 보정 손실 시 일반 GPS 대체 운항
- GPS CSV 기록
- 실제 장치를 열지 않는 Mock launch

## 기준 환경

- Jetson Nano Ubuntu 20.04
- ROS1 Noetic
- Python 3
- catkin workspace
- 실제 장비 GPS: u-blox ZED-F9R
- 강의자료 예제 드라이버: `ros-agriculture/ublox_f9p`

`ublox_f9p`는 ZED-F9P용 오래된 ROS1 드라이버입니다. 현재 장비는 ZED-F9R이므로 실물 적용 전에 U-center에서 현재 포트 baudrate와 UBX 출력 설정을 읽고 백업해야 합니다. 베타 설정은 확인된 현재 값 115200을 기본으로 사용합니다. `config_on_startup: false`라서 항법 모델·GNSS 구성·저장 메모리를 일괄 초기화하지 않지만, 필요한 UBX 메시지 발행률은 드라이버가 세션 중 요청합니다.

## 설치와 빌드

```bash
cd /home/jetson/RC-BOAT/beta/ros_noetic_full
chmod +x setup_dependencies.sh build.sh run_mock.sh run_real.sh
./setup_dependencies.sh
rosdep install --from-paths catkin_ws/src --ignore-src -r -y
./build.sh
```

설치 스크립트가 외부 ROS 패키지를 이 폴더의 `catkin_ws/src/third_party` 안에만 고정 커밋으로 내려받습니다.

## Mock 실행

```bash
./run_mock.sh
rostopic echo /rcboat/state
```

Mock에서는 실제 Arduino, GPS, PCA9685를 열지 않습니다.

Mock은 소프트웨어 검증용입니다. 기존 운영 버전의 실 PWM HIL 기능은 운영 폴더에 그대로 남아 있으며, 베타에서는 실물 GPS 없이 모터를 구동하는 기능을 안전상 자동 제공하지 않습니다.

## 실물 실행 전 충돌 방지

```bash
sudo systemctl stop rcboat.service
sudo systemctl disable rcboat.service
sudo lsof /dev/i2c-1
sudo lsof /dev/serial/by-id/*
```

장치가 다른 프로그램에서 열려 있지 않은 것을 확인한 다음 실행합니다.

```bash
./run_real.sh
```

운영 버전으로 되돌릴 때:

```bash
sudo systemctl stop rcboat-ros.service
sudo systemctl enable --now rcboat.service
```

## 주요 토픽

| 토픽 | 타입 | 방향 |
|---|---|---|
| `/rcboat/rc_input` | `rcboat_msgs/RcInput` | Arduino -> Controller |
| `/rcboat/gps_status` | `rcboat_msgs/GpsStatus` | GPS Health -> Controller |
| `/rcboat/remote_pwm` | `rcboat_msgs/PwmCommand` | 원격 제어 -> Controller |
| `/rcboat/remote_heartbeat` | `std_msgs/Empty` | 원격 제어 -> Controller |
| `/rcboat/pwm_command` | `rcboat_msgs/PwmCommand` | Controller -> PCA9685 |
| `/rcboat/state` | `rcboat_msgs/BoatState` | Controller -> 모니터링 |
| `/rtcm` | `rtcm_msgs/Message` | NTRIP -> ublox_gps |

## 주요 서비스

```text
/rcboat/set_mode
/rcboat/emergency_stop
/rcboat/clear_estop
/rcboat/select_route
/rcboat/set_auto_cruise
/rcboat/set_multipath
/rcboat/start_route_recording
/rcboat/stop_route_recording
/rcboat/cancel_route_recording
/rcboat/start_gps_logging
/rcboat/stop_gps_logging
```

## 안전 주의

ROS master 또는 controller가 끊기면 `pca9685_node` 자체 watchdog이 0.3초 안에 6000/6450을 출력합니다. ROS 베타를 처음 실물에 적용할 때는 프로펠러를 분리하고 CH0/CH6 출력부터 검증하십시오.

NTRIP 계정은 Git에 넣지 않습니다. `config/ntrip.env.example`을 `config/ntrip.env`로 복사하고 권한을 600으로 설정합니다.
