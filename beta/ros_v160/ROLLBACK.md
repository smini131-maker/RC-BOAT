# Rollback

## 가장 빠른 복귀

Windows:

```powershell
cd RC-BOAT\beta\ros_v160\deployment\windows
.\USE_DAEMON.cmd -HostName nano.local
```

Jetson:

```bash
sudo /home/jetson/rcboat_ros_ws/deployment/rcboat_backend_ctl.sh daemon
systemctl is-active rcboat.service
```

이 과정은 ROS real/HIL을 정지하고, 가능한 경우 PCA9685에 6000/6450을 기록한 뒤 기존 `rcboat.service`와 포트 8765를 검사합니다.

## ROS 시작 실패 시

`USE_ROS` 전환기는 ROS service나 node/topic/안전 PWM 검사 중 하나라도 실패하면 ROS를 정지하고 daemon을 자동 재시작합니다.

확인:

```bash
systemctl is-active rcboat.service rcboat_ros.service rcboat_ros_hil.service
sudo journalctl -u rcboat_ros.service -n 100 --no-pager
```

## 베타 전체 제거

```powershell
.\UNINSTALL_ROS_BETA.cmd -HostName nano.local
```

또는:

```bash
sudo /home/jetson/rcboat_ros_ws/deployment/uninstall_ros_beta.sh
```

제거 스크립트는 runtime을 홈 디렉터리의 tar.gz로 백업하고 ROS workspace와 ROS용 unit만 제거합니다. `/home/jetson/rcboat`, `rcboat.service`, 공유 ROS 패키지 및 기존 Windows v1.6 파일은 삭제하지 않습니다.
