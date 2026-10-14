# RC-BOAT ROS Noetic v2.0.0

정식 실행 구조는 ROS Noetic뿐입니다. Jetson backend는 `roslaunch rcboat_ros rcboat.launch`, Windows GUI는 ROS gateway TCP(기본 `8765`)로 통신합니다. SSH는 배포·터미널용 보조 채널이며, SSH가 끊겨도 ROS gateway가 살아 있으면 상태 조회와 `GROUND_TEST_STOP`이 동작합니다.

기존 1.6.0 소스는 `release/1.6.0` 브랜치와 `release/archive/v1.6.0/`에 보존됩니다. `beta/`는 개발 이력일 뿐 정식 실행 위치가 아닙니다.

## 정식 디렉터리

- `catkin_ws/src/rcboat_ros`: ROS package, nodes, messages, service, launch, config
- `windows_gui`: Windows PySide6 GUI
- `deployment/jetson`: Jetson 설치·점검 도구
- `systemd/rcboat_ros.service`: 선택적 ROS 자동 시작 unit
- `tests`: 하드웨어 없이 실행 가능한 회귀 테스트

초기 `routes.json`은 비어 있습니다. LEFT/CENTER/RIGHT 또는 다른 항로가 자동 생성되지 않습니다. 이름은 자유이며 사용자가 GUI에서 직접 추가·수정·삭제합니다. 저장 waypoint에는 번호, 위도, 경도, UTM easting/northing/zone이 모두 들어갑니다.

## Windows PowerShell — 전송

저장소 루트에서 다음을 실행합니다.

```powershell
git clone https://github.com/smini131-maker/RC-BOAT.git
cd RC-BOAT
git switch main
powershell -ExecutionPolicy Bypass -File .\tools\windows\runner.ps1 -Action DEPLOY_ROS -Root . -Destination jetson@JETSON_IP
```

전송과 설치를 한 번에 하려면:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\windows\runner.ps1 -Action INSTALL_ROS -Root . -Destination jetson@JETSON_IP
```

## Jetson SSH 안 — 빌드·실행

수동 실행(권장 점검 경로):

```bash
cd /home/jetson/rcboat_ros_ws
python3 -m pip install --user pyserial smbus2
source /opt/ros/noetic/setup.bash
cd catkin_ws
catkin_make
source devel/setup.bash
roslaunch rcboat_ros rcboat.launch
```

선택적으로 부팅 자동 시작을 설치하려면:

```bash
cd /home/jetson/rcboat_ros_ws
bash deployment/jetson/install_jetson_ros.sh
bash deployment/jetson/check_ros.sh
```

GUI PC가 Jetson의 TCP `8765`에 접근할 수 있어야 합니다. 신뢰할 수 있는 시험용 LAN에서만 열고, 필요하면 Jetson과 Windows 양쪽 환경변수 `RCBOAT_GATEWAY_TOKEN`에 같은 값을 설정합니다. 포트를 바꾸면 Windows에서 `RCBOAT_GATEWAY_PORT`도 설정합니다.

## Windows GUI 실행·빌드

소스 실행:

```powershell
cd windows_gui
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

EXE 빌드:

```powershell
.\BUILD_ROS_GUI.cmd
```

결과: `windows_gui\dist\RCBoatControl_ROS_v2.0.0.exe`

GUI 상단 상태는 서로 독립입니다: `SSH connected/disconnected`, `ROS master online/offline`, `ROS gateway online/offline`, `logger idle/recording/stopping/error`, `GPS valid/invalid/stale`, `RTK fix/float/dgps/no_fix/no_data`.

## 항로와 Ground Test 사용 순서

1. 항로 탭의 **수동 항로 추가**에서 이름과 `waypoint 번호, 위도, 경도`를 입력합니다. 기존 항로는 **선택 항로 수정/삭제**로 관리합니다.
2. 도보 테스트 탭에서 서로 다른 기준 항로 3개를 선택합니다.
3. 프로펠러를 제거하고 ESC 추진 전원을 분리합니다.
4. ROS master/gateway, GPS valid, 필요한 경우 RTK 상태를 확인합니다.
5. **도보 테스트 시작**을 누르고 실제 배를 들고 기준 경로 위를 이동합니다.
6. 시험 중 항로·설정을 바꾸면 시각, 변경 내용, 당시 항로 snapshot이 별도 로그에 기록됩니다.
7. **도보 테스트 종료**를 누릅니다. 이 명령은 SSH 상태가 아니라 ROS gateway를 통해 전달됩니다.
8. 완료된 시험을 선택하고 **선택 결과 다운로드**를 눌러 ZIP을 PC로 가져옵니다.

Jetson 저장 위치:

```text
~/rcboat_ros_data/logs/ground_tests/
  ground_test_YYYYMMDD_HHMMSS/
    ground_test.csv
    ground_test.jsonl
    reference_routes.csv
    reference_routes.json
    route_changes.jsonl
    events.jsonl
    test_metadata.json
    export_manifest.json
```

- `ground_test.csv`: MATLAB/QGIS용 열 기반 측정·판단·출력 데이터
- `ground_test.jsonl`: 각 sample의 원본 구조 보존
- `reference_routes.*`: 시험 시작 시 선택한 기준 항로 3개 전체 좌표/번호/UTM
- `route_changes.jsonl`: 시험 중 항로·설정 변경 시각과 전후 정보
- `events.jsonl`: 수동 개입, 모드, 비상정지, 오류, 정지 이벤트. 비정상 종료 후 logger가 다시 시작되면 `LOGGER_RESTART_DETECTED`가 추가됩니다.
- `test_metadata.json`: 코드 버전, ROS 설정, 서보 보정, 시작/종료 정보
- `export_manifest.json`: 파일 크기와 SHA-256 검증값

CSV의 빈 값은 장치가 제공하지 않았거나 아직 수신되지 않은 값입니다. GUI는 이를 `unsupported`, `no_data`, `invalid`, `stale`로 구분하며 0으로 대체하지 않습니다.

## RTK/NTRIP 비밀정보

자격정보를 저장소 파일에 넣지 마십시오. Jetson 로컬 전용 `/home/jetson/rcboat_ros_data/ntrip.env`(권한 `0600`) 또는 환경변수를 사용합니다.

```bash
install -m 600 /dev/null /home/jetson/rcboat_ros_data/ntrip.env
nano /home/jetson/rcboat_ros_data/ntrip.env
```

필드: `RCBOAT_NTRIP_ENABLED`, `RCBOAT_NTRIP_HOST`, `RCBOAT_NTRIP_PORT`, `RCBOAT_NTRIP_MOUNTPOINT`, `RCBOAT_NTRIP_USERNAME`, `RCBOAT_NTRIP_PASSWORD`, `RCBOAT_NTRIP_TLS`. 이 파일은 `.gitignore` 대상입니다.

## 실제 보트 시험 전 확인

- 프로펠러 제거 상태에서 조향/스로틀 중립 PWM과 E-STOP을 실측합니다.
- GPS 장치의 UBX-NAV-PVT UTC, 위치, 속도, COG와 RTK 상태를 실제 장치로 대조합니다.
- `8765/tcp`는 시험 LAN에서만 허용하고 gateway token 또는 방화벽을 적용합니다.
- `actual_*_pwm`은 PCA에 전송한 명령이지 물리 위치 센서 피드백이 아닙니다.
- 지상 도보 시험 통과는 수상 자율운항 안전 승인을 의미하지 않습니다.
