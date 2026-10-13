# Jetson Nano에서 ROS Noetic 선행 설치와 확인 (Ubuntu 20.04 aarch64)

## 주의
ROS Noetic은 2025-05-31 공식 지원 종료(EOL). 이 프로젝트는 6주차 강의의 `catkin_make`·`roslaunch` 기반 ROS1을 고려한 별도 베타입니다. 2026년 저장소 및 의존성 상태에 따라 `apt` 설치 실패가 생길 수 있고, 실제 기기에서 검증하지 않았습니다. Ubuntu/JetPack을 임의로 업그레이드하거나 ROS2로 갈아타지 마세요. v1.6.0을 덮어쓰지 않습니다.

## 1. 장비 현황 확인 (Windows PowerShell)

```powershell
ssh jetson@10.85.226.215
```

Jetson 내부에서:

```bash
cat /etc/os-release
uname -m
command -v catkin_make || echo 'catkin_make missing'
ls -l /opt/ros/noetic/setup.bash
ls -l /dev/serial/by-id/
```

정상 기대: Ubuntu 20.04, aarch64, 실제 Arduino·GPS by-id 존재. `setup.bash`가 없으면 ROS Noetic 선행 설치가 아직 안 된 상태입니다.

## 2. 설치 가능 여부 먼저 확인

ROS1 설치 공식 문서(보관 미러): https://ftp.osuosl.org/.1/ros/ros_wiki_mirror/noetic%282f%29Installation.html

- OS 저장소(`focal`, Ubuntu Ports aarch64)와 ROS 패키지 저장소 상태를 확인합니다. 기존 apt sources를 무작정 덮어쓰지 않습니다.
- `apt-cache policy ros-noetic-ros-base`, `apt-cache policy ros-noetic-roslaunch`, `apt-cache policy ros-noetic-roscpp` 등으로 해당 CPU/OS에서 설치 후보가 실제 나오는지 검사합니다.
- 이미 Noetic 패키지가 제대로 있으면 새로 설치하지 않습니다. 설치 후보가 없으면 **STOP**. 해당 ARM64/JetPack 조합에 맞는 archive/보관 패키지 검증 또는 Noetic 소스 빌드 방법을 별도로 확보해야 합니다.

설치 후보가 존재하고 검증되었을 때만:

```bash
sudo apt update
sudo apt install ros-noetic-ros-base ros-noetic-roslaunch ros-noetic-rospy ros-noetic-std-msgs ros-noetic-message-generation python3-catkin-tools python3-serial python3-smbus2 python3-pyproj python3-rospkg python3-numpy psmisc
```

`python3-catkin-tools`와 `catkin_make`는 서로 다른 툴체인입니다. `catkin_make`가 없다면 Noetic의 `ros-noetic-catkin` 및 배포판 `python3-catkin-pkg` 제공 여부를 먼저 확인하세요. 위 설치 명령 자체도 설치 가능성을 보장하지 않습니다.

```bash
source /opt/ros/noetic/setup.bash
command -v roscore roslaunch catkin_make
python3 -c 'import serial, smbus2, pyproj, rospy; print("preflight python imports OK")'
```

정상 출력 전까지 **INSTALL_ROS.cmd**, 특히 **USE_ROS.cmd**를 진행하지 않습니다.

## 3. 배포/빌드(물리 추진 전원 분리)

- `DEPLOY_ROS.cmd` : 신규 workspace만 /home/jetson/rcboat_ros_ws에 복사
- `INSTALL_ROS.cmd` : 기존 ROS가 설치됐는지 확인한 뒤 catkin_make를 실행. **ROS를 처음 설치해주는 도구는 아닙니다.**
- `CHECK_BACKEND.cmd` : daemon가 기본값인지 확인
- `USE_ROS.cmd` : daemon 중지, serial/I2C release, PCA 중립 readback, ROS 서비스 시작
- `CHECK_ROS.cmd` : ROS topics/services 응답 검사
- `USE_DAEMON.cmd` : ROS 정지, 장치 해제, 중립 안전값, 기존 서비스 복귀

## 4. 보안/안전

`rcboat_ros.service` 기본 DISABLED, `rcboat.service` 기본 ENABLED. ROS 코드에 `propulsion_allowed: false`, 실제 NAVIGATION 추진 사용 불가. ROS MASTER를 외부 네트워크에 개방하지 않습니다. 카메라 없는 지상 시험은 반드시 프로펠러 제거·ESC 전원 분리.
