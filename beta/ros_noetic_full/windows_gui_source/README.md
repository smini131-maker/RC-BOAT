# RC Boat ROS Beta Windows GUI

이 GUI는 기존 운영 daemon에 연결하지 않습니다. SSH 터널을 통해 Jetson의 `127.0.0.1:8876`에서 실행되는 `gui_gateway_node.py`에 연결하고, Gateway가 ROS 토픽과 서비스만 사용합니다.

## 연결 구조

```text
Windows GUI
  └─ SSH direct-tcpip
      └─ Jetson 127.0.0.1:8876
          └─ rcboat_gui_gateway
              ├─ /rcboat/state, /rcboat/gps_status, /rcboat/ntrip_status
              ├─ /rcboat/set_mode, /rcboat/select_route, ...
              └─ /rcboat/remote_pwm, /rcboat/remote_heartbeat
```

포트 8876은 외부 인터페이스에 열지 않고 loopback에만 바인딩됩니다.

## Windows EXE 빌드

Windows 10/11 x64에서 Python 3.11 이상을 설치한 다음:

```bat
cd beta\ros_noetic_full\windows_gui_source
build.bat
```

결과:

```text
windows_app\dist\RCBoatROSControlBeta.exe
```

## 사용 순서

1. Jetson에서 기존 `rcboat.service`를 중지합니다.
2. ROS 베타를 `run_real.sh` 또는 `run_mock.sh`로 실행합니다.
3. Windows에서 `RCBoatROSControlBeta.exe`를 실행합니다.
4. Jetson 주소, SSH 사용자와 비밀번호를 입력하고 연결합니다.

GUI의 SSH 터미널은 기존처럼 별도 SSH shell을 사용하지만, 보트 제어 명령과 상태 데이터는 ROS GUI Gateway를 통해서만 전달됩니다.

HIL은 실제 PWM을 발생시킬 수 있으므로 기본적으로 비활성입니다. 프로펠러를 분리하고 시험할 때만 Jetson의 `config/boat.yaml`에서 `allow_hil: true`로 변경한 뒤 ROS 베타를 재시작하십시오.