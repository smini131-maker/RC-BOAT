# RC Boat ROS 2 Bridge Beta

이 폴더는 기존 RC Boat 프로그램을 교체하지 않고 ROS 2 통신을 추가하는 베타 버전입니다.

## 먼저 확인할 점

5주차 강의자료의 통신 구조는 아래와 같습니다.

- Arduino → Jetson Nano: UART(Serial)
- Jetson Nano → PCA9685: I2C
- PCA9685 → Servo/ESC: PWM

ROS 2는 UART나 I2C를 대신하는 전기적 통신 규격이 아니라 프로그램 사이에서 메시지를 전달하는 미들웨어입니다. 따라서 Arduino 수신기와 GPS의 UART, PCA9685의 Direct-I2C는 그대로 두고, 기존 `rcboat_daemon.py`와 다른 프로그램 사이의 통신에 ROS 2 Topic을 추가했습니다.

## 보존한 기능

ROS 2 Bridge는 하드웨어 포트를 직접 열지 않습니다. 하드웨어는 기존 daemon 하나만 제어합니다.

- MANUAL / AUTO / NAVIGATION / REMOTE 모드
- 비상정지와 모든 기존 failsafe
- Steering 6000 / Throttle 6450 안전 정지값
- GPS/RTK 및 RTK 손실 시 일반 GPS 대체 운항
- Waypoint, 항로 기록, 선택 항로 저장
- Multi-Path
- HIL
- Windows GUI와 SSH JSON 통신
- GPS CSV 기록 및 NTRIP 설정

`/rcboat/cmd/json`에 기존 JSON 명령을 보내면 현재 daemon이 지원하는 모든 기능을 그대로 사용할 수 있습니다.

## 구조

```text
Windows GUI ── SSH/TCP JSON ─┐
                             ├─ rcboat_daemon (하드웨어 단독 소유)
ROS 2 Bridge ─ localhost JSON┘       ├─ Arduino/GPS UART
                                    └─ PCA9685 Direct-I2C
```

## ROS 2 토픽

### 발행

| 토픽 | 타입 | 내용 |
|---|---|---|
| `/rcboat/state/json` | `std_msgs/String` | 기존 telemetry 전체 JSON |
| `/rcboat/state/ack_json` | `std_msgs/String` | 명령 ACK 전체 JSON |
| `/rcboat/state/mode` | `std_msgs/String` | 현재 모드 |
| `/rcboat/state/connected` | `std_msgs/Bool` | daemon 연결 상태 |
| `/rcboat/gps/fix` | `sensor_msgs/NavSatFix` | GPS 위치와 hAcc 기반 공분산 |

### 구독

| 토픽 | 타입 | 동작 |
|---|---|---|
| `/rcboat/cmd/json` | `std_msgs/String` | 기존 daemon JSON 명령 그대로 전달 |
| `/rcboat/cmd/mode` | `std_msgs/String` | `SET_MODE` |
| `/rcboat/cmd/pwm` | `std_msgs/Int32MultiArray` | `[steering_pwm, throttle_pwm]` |
| `/rcboat/cmd/heartbeat` | `std_msgs/Empty` | `HEARTBEAT` |
| `/rcboat/cmd/emergency_stop` | `std_msgs/Empty` | `EMERGENCY_STOP` |
| `/rcboat/cmd/clear_estop` | `std_msgs/Empty` | `CLEAR_ESTOP` |
| `/rcboat/cmd/route` | `std_msgs/String` | `SELECT_ROUTE` |

REMOTE 운항 중에는 외부 ROS 제어 노드가 `/rcboat/cmd/heartbeat`를 5 Hz 이상으로 계속 발행해야 합니다. Bridge가 heartbeat를 자동 생성하지 않으므로 제어 노드가 죽으면 기존 daemon이 약 0.7초 뒤 안전 정지합니다.

## Jetson 요구사항

- Ubuntu 20.04 기준 ROS 2 Foxy 또는 호환되는 ROS 2 설치
- 실행 중인 기존 `rcboat.service`
- Python 3의 `rclpy`, `std_msgs`, `sensor_msgs`
- `colcon`

ROS 2 Foxy는 현재 지원 종료 버전이지만 Jetson Nano의 Ubuntu 20.04 환경과 맞추기 위해 이 베타는 Foxy API 범위로 작성했습니다. 기존 운영 환경을 바꾸지 않기 위해 ROS 2 자체를 자동 설치하지 않습니다.

## 빌드

```bash
cd /home/jetson/RC-BOAT/beta/ros2_bridge
chmod +x build_ros2.sh run_bridge.sh
./build_ros2.sh
```

## 실행

기존 daemon이 먼저 실행되어야 합니다.

```bash
systemctl status rcboat.service
cd /home/jetson/RC-BOAT/beta/ros2_bridge
./run_bridge.sh
```

다른 터미널에서 확인합니다.

```bash
source /opt/ros/foxy/setup.bash
source /home/jetson/RC-BOAT/beta/ros2_bridge/install/setup.bash
ros2 topic echo /rcboat/state/mode
ros2 topic echo /rcboat/gps/fix
```

## 명령 예시

비상정지:

```bash
ros2 topic pub --once /rcboat/cmd/emergency_stop std_msgs/msg/Empty '{}'
```

항로 선택:

```bash
ros2 topic pub --once /rcboat/cmd/route std_msgs/msg/String "{data: route_a}"
```

원래 JSON 명령 사용:

```bash
ros2 topic pub --once /rcboat/cmd/json std_msgs/msg/String \
  '{data: "{\"command\":\"SET_AUTO_CRUISE_PWM\",\"value\":6650}"}'
```

REMOTE 제어 예시는 안전을 위해 먼저 바퀴/프로펠러를 지면 또는 수면에서 분리한 상태에서 수행합니다.

```bash
ros2 topic pub --once /rcboat/cmd/mode std_msgs/msg/String "{data: REMOTE}"
ros2 topic pub -r 10 /rcboat/cmd/heartbeat std_msgs/msg/Empty '{}'
ros2 topic pub -r 10 /rcboat/cmd/pwm std_msgs/msg/Int32MultiArray \
  "{data: [6000, 6450]}"
```

## systemd 선택 설치

실물 테스트가 끝난 뒤에만 `rcboat_ros2_bridge.service.example`의 경로를 확인해 설치합니다. 이 파일은 기존 `rcboat.service`를 수정하거나 대체하지 않습니다.

```bash
sudo cp rcboat_ros2_bridge.service.example /etc/systemd/system/rcboat-ros2-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now rcboat-ros2-bridge.service
```

## 소프트웨어 테스트

ROS 2가 없어도 transport와 기존 mock daemon의 연결을 검사할 수 있습니다.

```bash
cd /home/jetson/RC-BOAT
python3 -m unittest beta.ros2_bridge.tests.test_transport -v
```

실제 GPS FIX, NTRIP 계정, I2C 출력, 모터 동작은 Jetson과 보트를 연결한 현장에서 별도 검증해야 합니다.
