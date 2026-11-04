# 설치·실행

[프로젝트 소개](../README.md) · [운항·시험](operation.md) · [문제 해결](troubleshooting.md)

통합 정식 v2.3.1은 항로 주행·도보 테스트·풍선 추적을 함께 제공합니다. 영상 의존성 설치 순서와 USB/CSI 점검은 [카메라·풍선 추적 안내](vision.md)를 먼저 따릅니다. 기존 Jetson 항로·NTRIP 로컬 정보는 그대로 사용합니다.

## 준비 환경

| 대상 | 준비 사항 |
|---|---|
| Windows PC | Python 3.11~3.13 x64, Git, OpenSSH Client |
| Jetson | Ubuntu 20.04, ROS Noetic, `catkin_make`, Python 3 |
| 장치 | GNSS·Arduino 시리얼 연결, PCA9685 I2C 연결·권한 |
| 네트워크 | PC에서 Jetson의 SSH 22 및 gateway TCP 8765 접근 |

현재 설치 도구는 Jetson 계정 `jetson`, 소스 경로 `/home/jetson/rcboat_ros_ws`를 사용합니다. 다른 계정이나 경로를 사용하려면 설치 스크립트와 systemd unit을 함께 조정해야 합니다.

## 1. 저장소 준비 — Windows PowerShell

```powershell
Set-Location -LiteralPath "C:\Users\smini\OneDrive\바탕 화면\RCBoatControl_Complete_2026-09-25_UPDATED\RCBoatControl_v2.3.1"
```

이후 Windows 명령은 저장소 루트에서 실행합니다. `JETSON_IP`는 실제 장치 주소로 바꿉니다.

```powershell
Test-NetConnection JETSON_IP -Port 22
.\CHECK_WINDOWS.cmd
```

`SETUP_WINDOWS.cmd`는 부족한 도구만 선택해서 설치하는 보조 도구입니다. 이미 Python이 준비돼 있으면 별도 버전을 설치할 필요가 없습니다.

## 2. 장치 및 Python 의존성 — Jetson 터미널

```bash
source /opt/ros/noetic/setup.bash
python3 -m pip install --user pyserial smbus2
ls -l /dev/serial/by-id/
ls -l /dev/i2c-1
```

PC의 [boat.yaml](../catkin_ws/src/rcboat_ros/config/boat.yaml)에서 `gps_port`, `arduino_port`, baudrate, PCA bus/address/channel이 실제 배선과 일치하는지 확인합니다. 기본 시리얼 경로는 기존 시험 장치의 식별자이므로 다른 장치에서는 변경해야 합니다. 실행 계정에 시리얼·I2C 접근 권한이 필요합니다.

조향·스로틀 PWM 값은 기존 보트 보정값입니다. 다른 서보·ESC에 그대로 적용하기 전에 중립과 출력 범위를 확인합니다.

## 3. 전송 및 설치 — Windows PowerShell

프로펠러를 제거하고, 수동으로 실행 중인 ROS가 있으면 해당 Jetson 터미널에서 `Ctrl+C`로 종료합니다. Windows GUI도 종료한 뒤 실행합니다.

```powershell
.\DEPLOY_ROS.cmd -Destination "jetson@JETSON_IP"
ssh jetson@JETSON_IP
```

SSH·sudo 비밀번호는 요청 프롬프트에 직접 입력합니다. 이어서 Jetson SSH 안에서 영상 의존성을 먼저 적용합니다.

```bash
cd /home/jetson/rcboat_ros_ws
bash deployment/jetson/install_vision_dependencies.sh
```

`VISION INSTALL VERIFIED`가 나온 후 다음 명령을 실행합니다.

```bash
bash deployment/jetson/install_jetson_ros.sh
```

설치는 소스 전송 → SHA-256 검증 → ROS 서비스 정지 → 전용 영상 환경·실제 추론 확인 → 잔존 프로세스 확인 → catkin 재빌드 → ROS 의존성 확인 → 서비스 시작 → 실행 버전 검증 순서입니다. 기존 영상 환경의 전역 패키지 상속 설정이 발견되면 `~/.rcboat/vision-venv.backup-날짜_시각` 경로로 보존합니다. 전역 TensorFlow나 NumPy를 삭제하지 않습니다.

완료 조건은 다음 출력입니다.

```text
RUNNING GATEWAY VERIFIED: v2.3.1
```

`DEPLOY_ROS`만으로 실행 중인 프로세스가 새 코드로 바뀌지는 않습니다. `INSTALL_ROS.cmd`는 영상 의존성을 이미 검증한 재설치에서 사용할 수 있습니다.

## 4. NTRIP 설정 — Jetson 터미널

RTK 보정을 사용할 경우 로컬 설정 도구를 실행합니다.

```bash
cd /home/jetson/rcboat_ros_ws
python3 deployment/jetson/configure_ntrip_local.py
```

Host, Port, Mount Point, Username을 입력하고 Password는 숨김 입력합니다. 기존 비밀번호를 유지하려면 비밀번호 입력에서 Enter를 누릅니다. 설정은 권한 `0600`인 `~/rcboat_ros_data/ntrip.env`에 저장되며 재배포 후에도 보존됩니다.

GUI의 NTRIP 설정에서도 같은 로컬 파일에 저장할 수 있습니다. 저장소 YAML이나 문서에 실제 자격정보를 넣지 않습니다.

서비스로 실행 중이라면 설정 후 재시작합니다.

```bash
sudo systemctl restart rcboat_ros.service
```

## 5. Windows GUI 실행

```powershell
py -3 -m venv windows_gui\.venv
.\windows_gui\.venv\Scripts\python.exe -m pip install -r windows_gui\requirements.txt
.\windows_gui\.venv\Scripts\python.exe windows_gui\app.py
```

GUI에서 Jetson 주소와 SSH 접속 정보를 설정하고 연결합니다. SSH, ROS master, ROS gateway, Logger, GPS, RTK 카드는 각각 독립적인 상태입니다. GUI와 backend 버전이 다르면 새 운항 시작이 차단됩니다.

EXE가 필요하면 저장소 루트에서 `BUILD_ROS_GUI.cmd`를 실행합니다. 결과는 `dist\RCBoatControl_ROS_v2.3.1.exe`입니다. 자세한 빌드·테스트 절차는 [개발·검증](development.md)을 참고합니다.

## 6. 설치 확인 및 수동 ROS 실행

Jetson 터미널에서:

```bash
cd /home/jetson/rcboat_ros_ws
cat VERSION
source /opt/ros/noetic/setup.bash
source catkin_ws/devel/setup.bash
python3 deployment/jetson/verify_release.py --timeout 45
bash deployment/jetson/check_ros.sh
```

서비스 대신 터미널에서 직접 실행할 때는 먼저 서비스를 정지합니다.

```bash
sudo systemctl stop rcboat_ros.service
roslaunch rcboat_ros rcboat.launch
```

직접 실행을 `Ctrl+C`로 종료한 뒤 자동 시작 서비스로 돌아가려면 `sudo systemctl start rcboat_ros.service`를 실행합니다. 두 실행 방식을 동시에 사용하지 않습니다.

## 네트워크 및 저장 위치

gateway 기본 포트는 `8765`입니다. 신뢰할 수 있는 시험 LAN에서 사용하고 외부 인터넷에 직접 공개하지 않습니다. token 인증을 사용할 경우 Windows GUI와 Jetson ROS 프로세스 환경에 같은 `RCBOAT_GATEWAY_TOKEN`을 설정합니다. 포트를 변경하면 `boat.yaml`과 Windows의 `RCBOAT_GATEWAY_PORT`를 맞춥니다.

| 위치 | 내용 |
|---|---|
| `/home/jetson/rcboat_ros_ws` | 배포 소스와 catkin workspace |
| `~/rcboat_ros_data/routes.json` | 사용자 항로 |
| `~/rcboat_ros_data/ntrip.env` | 로컬 NTRIP 설정 |
| `~/rcboat_ros_data/logs/ground_tests/` | 시험 기록 |
| `%LOCALAPPDATA%\RCBoatControl\logs` | Windows 앱 진단 로그 |
