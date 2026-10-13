# RC BOAT ROS v2.0.0-beta.1 – 설치/사용

## 경고 및 전제

이 패키지는 새 ROS1 Noetic용 베타 소스다. 기존 `release/1.6.0`, `/home/jetson/rcboat`, `rcboat.service`와 기존 Windows EXE는 수정하지 않는다. 기본적으로 **실제 추진 PWM을 허용하지 않도록 설정**했다. 현장 테스트 전에는 프로펠러를 제거하고 ESC 추진 전원을 분리한다. PC나 Windows EXE만으로 실물 안전을 보장할 수 없다.

Jetson 로그에서 Ubuntu 20.04.6 / aarch64 확인. ROS Noetic은 2025-05-31 EOL이므로 2026년 현재 apt 저장소에 해당 ARM64 바이너리 패키지가 실제로 존재하는지 확인해야 한다. `ros-noetic-ros-base`, `python3-catkin-tools`, `python3-rosdep` 설치 경로와 소프트웨어 공급원을 검토한다. **아직 설치가 끝났다고 판단하지 않는다**.

## Windows에서 파일 옮기기

`deployment/windows/DEPLOY_ROS.cmd jetson@10.85.226.215` 실행. 경로는 `/home/jetson/rcboat_ros_ws`로 분리된다. `scp` 전송 후:

```bash
ssh jetson@10.85.226.215
lsb_release -a
uname -m
ls -l /dev/serial/by-id/
ls -l /dev/i2c-1
source /opt/ros/noetic/setup.bash
command -v catkin_make
python3 -c 'import serial,smbus2,pyproj'
```

위 사전 검사를 통과했을 때만 `bash ~/rcboat_ros_ws/deployment/jetson/install_jetson_ros.sh` 수행. `INSTALL_ROS.cmd`는 전송 후 설치 스크립트를 실행한다. 설치기는 새 workspace를 `catkin_make`로 빌드하고 ROS 서비스 파일만 신규 추가한다. ROS 시작은 하지 않으며 기존 daemon 부팅 기본값을 유지한다.

Jetson 신규 Python 의존성에는 `pyserial`, `smbus2`, `pyproj`가 필요하다. 그래프 자동 PNG 생성을 원하면 Jetson에 `python3-matplotlib`도 설치한다. 시스템 Python 버전과 ROS Noetic Python 3.8 ABI 호환을 먼저 확인한다. Blinka / Jetson.GPIO 설치 금지.

## Ros 진입과 되돌리기

Windows에서 `USE_ROS.cmd jetson@10.85.226.215`를 실행하면 안전 전환 검사를 거친다. 기존 daemon/serial/I2C 사용자 프로세스가 남아 있으면 시작을 거부한다. 정상 시작 후 `CHECK_ROS.cmd`로 topic/services를 확인한다.

기존으로 즉시 되돌릴 때 `USE_DAEMON.cmd jetson@10.85.226.215`. 실패하면 SSH에서 수동 실행:

```bash
sudo systemctl stop rcboat_ros.service
sudo systemctl status rcboat_ros.service --no-pager
sudo python3 /home/jetson/rcboat_ros_ws/deployment/jetson/set_safe_pwm.py
sudo systemctl start rcboat.service
systemctl is-active rcboat.service
```

중립 설정 스크립트는 **양쪽 서비스가 정지해 I2C 소유권을 해제한 경우에만** 사용한다. `CHECK_BACKEND.cmd`는 sudo 권한으로 서비스와 소유자 정보를 출력하고, **양쪽 서비스가 동시에 active인 충돌을 발견하면 자동으로 둘을 중단한 후 소유권 검사·중립 출력·daemon 복귀를 시도**한다. I2C/Serial 해제 또는 안전값 쓰기를 확인하지 못하면 복구 실패로 보고한다.

## ROS GUI 빌드 (Windows x64에서 실행)

`windows_gui/build.bat` → `windows_gui/dist/RCBoatControl_ROS_v2.0.0-beta.1.exe`. Linux에서 Windows EXE를 빌드했다는 의미가 아니다. Windows에 Python 3.10+와 PySide6/Paramiko/PyInstaller 설치 필요. 최초 SSH 접속 호스트 키를 `ssh jetson@<IP>`로 먼저 확인한 뒤 GUI에서 연결한다. GUI는 모르는 SSH host key를 자동 수락하지 않는다.

NTRIP 비밀번호는 GUI 메모리 내 입력 후 전송되며 Jetson `~/rcboat_ros_data/ntrip.env`에 chmod 600으로 저장된다. GitHub에는 비밀정보를 올리지 않는다. 로컬 GPS serial과 NTRIP 통신 상태는 별개로 표시된다.

## 안전 기동/종료

부팅 기본값: `rcboat.service enabled`, `rcboat_ros.service disabled`. ROS 서비스는 오직 수동 전환시 시작한다. ROS 변경 중 `systemctl enable rcboat_ros.service` 하지 않는다. 실제 NAV 추진은 config의 `propulsion_allowed=false`로 차단한다. 안전성 검증 없이 true로 바꾸지 않는다.

## 나머지

- 상세 실험: `README_GROUND_TEST_KO.md`
- 아키텍처: `ARCHITECTURE.md`
- Topic/Service: `TOPICS_AND_SERVICES.md`
- 개발 검증/미완료: `TEST_REPORT.md`
- MATLAB: `matlab/analyze_path_tracking.m`
- 경로 리샘플링: `python3 tools/resample_route.py raw_routes.json resampled_routes.json --spacing 1.0`
- Windows GUI는 SSH 상에서 실행되는 ROS bridge client만 사용한다. ROS Master를 Windows에 직접 공개하지 않는다.

## GitHub 업로드(별도 검토 후)

GitHub 베타 작업 브랜치 `beta/ros-v2.0.0-beta.1`은 생성되어 있지만 소스 전체 업로드는 아직 하지 않았다. 이 ZIP의 `UPLOAD_GITHUB.cmd`를 Git 인증이 가능한 Windows에서 실행하면 **해당 신규 베타 브랜치에만** 소스를 올리고 GitHub Actions에서 Windows EXE를 빌드한다. 기존 `release/1.6.0`에는 push하지 않는다.


> **수정 패키지 주의:** Windows 초기 설정 및 오류 로그는 `docs/WINDOWS_빌드_업로드_문제해결.md`를, ROS Noetic 준비는 `docs/JETSON_ROS_NOETIC_설치_사전점검.md`를 참조하세요.
