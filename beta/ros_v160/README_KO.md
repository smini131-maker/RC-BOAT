# RC Boat ROS Beta v0.1.0-beta.1

이 폴더는 정상 동작 기준판 `release/1.6.0`을 보존하면서 ROS1 Noetic 구조로 재구현한 독립 베타입니다. 기존 `/home/jetson/rcboat`, `rcboat.service`, Windows v1.6 실행 파일은 수정하거나 삭제하지 않습니다.

> 실물 GPS 사진의 모듈 표기는 **u-blox ZED-F9R-00B**입니다. 강의자료의 F9P 예시와 다르므로 이 베타는 검증된 115200 baud 및 기존 `MixedGpsParser`를 GPS 단일 owner 노드 안에서 사용합니다.

## 왜 ROS1 Noetic인가

Jetson Nano의 Ubuntu 20.04, 강의자료의 catkin/XML launch 구조, 기존 Python 코드를 함께 유지하기 위해 ROS1 Noetic을 선택했습니다. Noetic은 2025-05-31에 공식 지원이 끝난 배포판이므로 신규 장기 제품에는 권장하지 않지만, 이 장치의 고정 Ubuntu 20.04 환경과 수업 구조를 재현하기 위한 호환 선택입니다. ROS는 인터넷에 공개하지 않고 Jetson 내부 loopback에서만 실행하며 Windows는 기존과 동일하게 SSH 터널로 접속합니다.

## 안전상 중요한 차이

- 실물 프로필에서는 `rc_input_node`, `gps_node`, `actuator_node`만 각각 Arduino, GPS serial, PCA9685를 엽니다.
- `safety_supervisor_node`만 최종 명령 topic을 publish합니다.
- `actuator_node`는 0.30초 동안 새 명령이 없으면 6000/6450으로 갑니다.
- ROS 실물 서비스 시작 검사는 `force_safe`를 호출하므로 시작 직후에는 6000/6450이 유지됩니다. GUI에서 운용 모드를 명시적으로 선택해야 합니다.
- HIL launch에는 실물 RC/GPS/NTRIP/actuator 노드가 없습니다.
- `rcboat.service`, `rcboat_ros.service`, `rcboat_ros_hil.service`는 서로 동시에 실행되지 않습니다.

## Windows에서 설치하는 순서

준비물은 Windows 10/11의 OpenSSH Client, `tar.exe`, Jetson SSH 계정입니다. 핫스팟 IP가 바뀌어도 먼저 `nano.local`을 사용합니다.

PowerShell 또는 명령 프롬프트에서 이 폴더로 이동합니다.

```powershell
cd RC-BOAT\beta\ros_v160\deployment\windows
```

1. ROS와 의존성 설치(최초 한 번, Jetson의 sudo 암호 입력):

```powershell
.\INSTALL_ROS.cmd -HostName nano.local
```

2. 베타 전용 소스를 Jetson `/home/jetson/rcboat_ros_ws`로 배포하고 `catkin_make`:

```powershell
.\DEPLOY_ROS.cmd -HostName nano.local
```

3. 먼저 실물 I/O가 없는 HIL 실행:

```powershell
.\USE_ROS_HIL.cmd -HostName nano.local
.\CHECK_ROS.cmd -HostName nano.local
```

4. HIL 확인 후에만 실물 ROS로 전환합니다. **프로펠러를 제거하고 E-STOP을 준비합니다.**

```powershell
.\USE_ROS.cmd -HostName nano.local
.\CHECK_ROS.cmd -HostName nano.local
```

5. 문제가 있으면 즉시 기존 데몬으로 복귀합니다.

```powershell
.\USE_DAEMON.cmd -HostName nano.local
```

`nano.local`이 해석되지 않을 때만 현재 IP를 확인해 같은 명령에 넣습니다.

```powershell
ping nano.local
arp -a
.\CHECK_ROS.cmd -HostName 192.168.x.x
```

IP는 설정 파일에 고정 저장하지 않습니다. GUI의 주소 입력칸도 편집할 수 있습니다.

## Windows ROS Beta GUI

Windows x64에 Python 3.11 이상을 설치한 뒤:

```powershell
cd RC-BOAT\beta\ros_v160\deployment\windows
.\BUILD_ROS_GUI.cmd
```

출력:

```text
beta\ros_v160\windows_gui_source\windows_app\dist\RCBoatControl_ROS_v0.1.0_Beta.exe
```

GUI에서 백엔드를 선택합니다.

| 선택 | SSH 터널의 Jetson 로컬 포트 | 대상 |
|---|---:|---|
| ROS Beta | 8876 | `gui_bridge_node` |
| Daemon v1.6 | 8765 | 기존 daemon |

GUI 선택은 접속 대상을 고르는 기능입니다. Jetson 프로세스 전환은 `USE_ROS.cmd`, `USE_ROS_HIL.cmd`, `USE_DAEMON.cmd`로 수행합니다.

## Jetson에서 직접 실행하는 명령

```bash
ssh jetson@nano.local
sudo /home/jetson/rcboat_ros_ws/deployment/rcboat_backend_ctl.sh hil
/home/jetson/rcboat_ros_ws/deployment/rcboat_backend_ctl.sh check
sudo /home/jetson/rcboat_ros_ws/deployment/rcboat_backend_ctl.sh ros
sudo /home/jetson/rcboat_ros_ws/deployment/rcboat_backend_ctl.sh daemon
```

로그:

```bash
sudo journalctl -u rcboat_ros_hil.service -f
sudo journalctl -u rcboat_ros.service -f
sudo journalctl -u rcboat.service -f
```

ROS 상태:

```bash
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/devel/setup.bash
export ROS_MASTER_URI=http://127.0.0.1:11311
export ROS_HOSTNAME=127.0.0.1
rosnode list
rostopic list
rostopic hz /rcboat/gps/status
rostopic echo -n 1 /rcboat/gps/status
rostopic echo -n 1 /rcboat/safety/state
rostopic echo -n 1 /rcboat/actuator/status
rosservice list
rqt_graph
```

systemd 없이 foreground에서 전체 실물 stack을 실행할 때는 `roslaunch rcboat_ros rcboat.launch`를 사용합니다. HIL은 `roslaunch rcboat_ros rcboat_hil.launch`입니다.

HIL 장애 주입 예:

```bash
rosservice call /rcboat/hil/inject_fault gps_stale true
rosservice call /rcboat/hil/inject_fault gps_hdop_bad true
rosservice call /rcboat/hil/inject_fault rtk_loss true
rosservice call /rcboat/hil/inject_fault gps_stale false
```

## 실물 검증 순서

아래 단계는 건너뛰지 않습니다.

1. 코드 compile/unit test
2. ROS HIL 및 topic/service 확인
3. `rqt_graph` 확인
4. GPS와 NTRIP만 확인
5. Arduino 입력 확인
6. 프로펠러 제거 후 PCA9685 6000/6450 확인
7. 조향만 좌/우 확인
8. 프로펠러 제거 상태에서 ESC 저출력 확인
9. 야외 저속 직선 항법
10. 저속 기록 항로 추종
11. Multi-Path 확인

배포 파일과 HIL 정적 검증이 실물 시험을 대신하지 않습니다. 실물 단계의 결과는 [TEST_REPORT.md](TEST_REPORT.md)에 현장에서 기록합니다.

## 제거

```powershell
.\UNINSTALL_ROS_BETA.cmd -HostName nano.local
```

제거 전 ROS runtime은 `/home/jetson/rcboat_ros_runtime_backup_YYYYMMDD_HHMMSS.tar.gz`로 백업되고 기존 daemon이 다시 시작됩니다.

세부 구조는 [ARCHITECTURE.md](ARCHITECTURE.md), 인터페이스는 [TOPICS_AND_SERVICES.md](TOPICS_AND_SERVICES.md), 변경 요약은 [CHANGED_FILES.md](CHANGED_FILES.md), 복구 절차는 [ROLLBACK.md](ROLLBACK.md)를 참고하십시오.
