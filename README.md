# RC-BOAT ROS Noetic v2.1.5

정식 실행 구조는 ROS Noetic뿐입니다. Jetson backend는 `roslaunch rcboat_ros rcboat.launch`, Windows GUI는 ROS gateway TCP(기본 `8765`)로 통신합니다. SSH는 배포·터미널용 보조 채널이며, SSH가 끊겨도 ROS gateway가 살아 있으면 상태 조회와 `GROUND_TEST_STOP`이 동작합니다.

기존 1.6.0 소스는 `release/1.6.0` 브랜치와 `release/archive/v1.6.0/`에 보존됩니다. `beta/`는 개발 이력일 뿐 정식 실행 위치가 아닙니다.

버전은 `MAJOR.MINOR.PATCH` 형식을 사용합니다. 호환성이 깨지는 구조 변경은 MAJOR, 기능 추가는 MINOR, 수정·정리는 PATCH를 올립니다. GUI 제목, ROS 응답, `VERSION`, EXE와 배포 ZIP 파일명은 항상 같은 버전으로 맞춥니다.

## 정식 디렉터리

- `catkin_ws/src/rcboat_ros`: ROS package, nodes, messages, service, launch, config
- `windows_gui`: Windows PySide6 GUI
- `deployment/jetson`: Jetson 설치·점검 도구
- `systemd/rcboat_ros.service`: 선택적 ROS 자동 시작 unit
- `tests`: 하드웨어 없이 실행 가능한 회귀 테스트

초기 `routes.json`은 비어 있습니다. LEFT/CENTER/RIGHT 또는 다른 항로가 자동 생성되지 않습니다. 이름은 자유이며 사용자가 GUI에서 직접 추가·수정·삭제합니다. 저장 waypoint에는 번호, 위도, 경도, UTM easting/northing/zone이 모두 들어갑니다.

항로 구조는 두 단계입니다.

- **소루트**: waypoint 좌표를 가진 실제 항로입니다.
- **대루트(Multi-Path)**: 사용자가 이름을 붙이고 소루트 1개 이상을 명시적으로 묶은 실행 단위입니다. 예를 들어 `대루트 A = [소루트 1, 소루트 2, 소루트 3, ...]`입니다.

대루트 운항을 켜면 현재 Target Path와 보트 위치의 상대거리(경로선까지 최소거리)가 임계값 `2.0 m` 이하일 때 현재 소루트를 유지합니다. 거리가 `2.0 m`를 엄격히 초과할 때만 선택한 대루트 안의 최근접 소루트로 Target Path를 변경합니다. 이는 7주차 강의자료의 `≤ 2 m 유지`, `> 2 m 변경` 조건입니다. 대루트 운항을 끄면 선택한 소루트 하나만 운항·시험합니다. “공통 출발·도착 자동 체크”는 대루트 편집 시 후보를 체크해 주는 선택적 도우미이며 자동 저장 또는 필수 조건이 아닙니다.

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
.\build.bat
```

결과: `windows_gui\dist\RCBoatControl_ROS_v2.1.5.exe`

GUI 상단 상태는 서로 독립입니다: `SSH connected/disconnected`, `ROS master online/offline`, `ROS gateway online/offline`, `logger idle/recording/stopping/error`, `GPS valid/invalid/stale`, `RTK fix/float/dgps/no_fix/no_data`.

## 항로와 Ground Test 사용 순서

1. 항로 탭의 **수동 항로 추가**에서 소루트 이름과 `waypoint 번호, 위도, 경도`를 입력합니다. 기존 소루트는 수정/삭제할 수 있습니다.
2. 여러 소루트를 함께 사용할 경우 **대루트 추가**에서 이름과 포함할 소루트 N개를 직접 선택합니다. 공통 출발·도착 버튼은 후보 자동 체크용이며 결과를 자유롭게 수정할 수 있습니다.
3. 실제 운항은 **이 대루트로 운항 시작** 또는 **이 소루트로 단일 운항 시작**을 선택합니다.
4. 도보 테스트 탭에서 실행 방식을 `대루트` 또는 `소루트(단일)`로 고르고 시험 대상을 선택합니다.
5. 프로펠러를 완전히 제거하고 주변 사람을 통제합니다. 계산·기록만 할 때는 출력 활성화를 체크하지 않고 ESC 추진 전원을 분리합니다. 자동주행과 동일한 실제 PWM 검증이 필요할 때만 ESC를 연결하고 GUI의 **프로펠러 제거 확인 · 자동주행 조향/스로틀 PWM 실제 출력**을 매 시험마다 명시적으로 체크합니다.
6. ROS master/gateway, GPS valid, 필요한 경우 RTK 상태를 확인합니다.
7. **도보 테스트 시작**을 누르고 실제 배를 들고 기준 경로 위를 이동합니다.
8. 시험 중 항로·대루트·설정을 바꾸면 시각, 변경 내용, 당시 항로 snapshot이 별도 로그에 기록됩니다.
9. **도보 테스트 종료**를 누릅니다. 이 명령은 SSH 상태가 아니라 ROS gateway를 통해 전달됩니다.
10. 완료된 시험을 선택하고 **선택 결과 다운로드**를 눌러 ZIP을 PC로 가져옵니다.

GPS 새 항로 기록은 기존에 선택된 항로가 없어도 독립적으로 동작합니다. GUI에는 `유효한 GPS 대기 중`, `새 지점 저장됨`, `다음 거리·시간 조건 대기 중`이 표시됩니다. 최소 2개 지점이 모이기 전에 저장을 시도해도 기록 세션은 취소되지 않으므로 더 이동한 뒤 다시 저장할 수 있습니다.

Jetson 저장 위치:

```text
~/rcboat_ros_data/logs/ground_tests/
  ground_test_YYYYMMDD_HHMMSS/
    ground_test.csv
    ground_test.jsonl
    reference_routes.csv
    reference_routes.json
    route_metrics.csv
    route_switches.csv
    route_changes.jsonl
    events.jsonl
    analysis_manifest.json
    plot_ground_test_week7.m
    test_metadata.json
    export_manifest.json
```

- `ground_test.csv`: MATLAB/QGIS용 시간축 측정·판단·출력 데이터. 위치, 헤딩, 실제/목표 속도, 조향각/PWM, 안전 상태가 포함됩니다.
- `ground_test.jsonl`: 각 sample의 원본 구조 보존
- `reference_routes.*`: 시험 시작 시 선택한 대루트의 모든 소루트(또는 단일 소루트) 전체 좌표/번호/UTM 고정본
- `route_metrics.csv`: sample × 소루트 장기형 데이터. 각 후보 항로의 거리, 횡오차, 목표점, 목표 헤딩, 헤딩 오차를 저장합니다.
- `route_switches.csv`: 활성 소루트 전환 시각, 전환 전후 항로, 현재 Target Path 거리, 후보 거리, 2m 임계값과 전환 판정
- `route_changes.jsonl`: 시험 중 항로·설정 변경 시각과 전후 정보
- `events.jsonl`: 수동 개입, 모드, 비상정지, 오류, 정지 이벤트. 비정상 종료 후 logger가 다시 시작되면 `LOGGER_RESTART_DETECTED`가 추가됩니다.
- `test_metadata.json`: 코드 버전, ROS 설정, 서보 보정, 시작/종료 정보
- `analysis_manifest.json`: 지도, 조향각, 항로별 헤딩 오차, 활성 항로 밴드, 목표/실제 속도 그래프를 재생성하기 위한 데이터 관계 설명
- `plot_ground_test_week7.m`: 다운로드한 시험 폴더에서 강의자료 형식 PNG 그래프를 생성하는 MATLAB 스크립트
- `export_manifest.json`: 파일 크기와 SHA-256 검증값

항로 탭의 **선택 항로 PC 저장**은 JSON/CSV/GPX로 내보내며, 각 waypoint의 번호·위도·경도·UTM easting/northing/zone(및 있으면 헤딩·기록 시각)을 포함합니다. 반면 **정지 후 항로 저장**은 Jetson ROS 항로 저장소에만 저장하므로, PC 사본이 필요하면 이어서 **선택 항로 PC 저장**을 사용하십시오.

로거는 실시간 그래프 이미지를 계산하지 않고 원본과 기본 파생값을 저장합니다. 따라서 연산 부담을 낮추면서도 MATLAB에서 강의자료 형식의 그래프를 2차 분석으로 재구성할 수 있습니다.

7주차 지상검증 그래프는 `ground_test.csv`의 `final_steering_pwm`, `final_throttle_pwm`, `desired_rudder_angle_deg`, `target_path_distance_m`, `multipath_switch_threshold_m`, `active_route_id`와 `route_metrics.csv`의 소루트별 `heading_error_deg`를 사용해 재구성합니다. 실제 출력 체크를 켠 시험에서는 자동주행과 같은 조향·스로틀 명령이 PCA9685로 전달됩니다. 체크하지 않은 시험은 `6000/6450` 중립을 유지합니다. 어느 경우든 `actual_*_pwm`은 물리 센서 피드백이 아니라 PCA9685에 전송한 명령 확인값입니다.

MATLAB에서 다운로드한 시험 ZIP을 푼 뒤 다음을 실행하면 7주차 강의자료와 도보검증 PPT 형식의 분석 PNG 14개, 분리된 기준 항로/실제 경로 CSV, QGIS용 CSV, PPT 작성·해석·캡처 설계도 TXT가 생성됩니다.

```matlab
addpath('matlab')
plot_ground_test_week7('C:\path\to\ground_test_YYYYMMDD_HHMMSS')
```

생성 그래프는 `01_week7_full_summary.png`부터 `14_data_quality_and_availability_summary.png`까지입니다. 기존 PPT 대응 그래프 8종에 추적·속도 오차, 제어 명령/출력 검증, waypoint/항로 진행, 전환 응답 비교, 항로별 통계, 데이터 품질·가용성 그래프를 추가했습니다. 범례는 플롯 밖으로 이동하고 짧은 구간의 중복 글자를 생략하여 PPT 축소 시에도 겹치지 않게 했습니다. 강의자료의 L/R thrust는 듀얼 추진기 예시이므로, 현재 단일 스로틀+러더 구조에서는 최종 스로틀 PWM과 러더 서보 PWM/각도로 대응해 표시합니다.

분석 결과의 `data` 폴더에는 `reference_route_01_*.csv`부터 `reference_route_03_*.csv`까지의 기준 항로 3개, `actual_path.csv`, 전체 원본/파생 CSV·JSON이 저장됩니다. `qgis` 폴더에는 `qgis_reference_routes.csv`, `qgis_actual_path.csv`, `qgis_route_switch_points.csv`가 생성됩니다. `docs/PPT_QGIS_그래프_해설_및_캡처_설계도.txt`에는 그래프별 해석 문장, 권장 PPT 순서, QGIS 좌표계·표현색·캡처 범위와 전환지점 확대 위치가 기록됩니다.

CSV의 빈 값은 장치가 제공하지 않았거나 아직 수신되지 않은 값입니다. GUI는 이를 `unsupported`, `no_data`, `invalid`, `stale`로 구분하며 0으로 대체하지 않습니다.

## RTK/NTRIP 비밀정보

자격정보를 저장소 파일에 넣지 마십시오. Jetson 로컬 전용 `/home/jetson/rcboat_ros_data/ntrip.env`(권한 `0600`) 또는 환경변수를 사용합니다. 이 파일은 Git 배포와 GUI ZIP에 포함되지 않으며, 재배포 후에도 보존됩니다. `ntrip_node`가 파일을 직접 읽으므로 systemd와 직접 `roslaunch` 실행 모두 같은 설정을 사용합니다.

```bash
cd /home/jetson/rcboat_ros_ws
python3 deployment/jetson/configure_ntrip_local.py
```

화면 안내에 따라 Host, Port, Mount Point, Username을 입력하고 Password는 숨김 입력합니다. 기존 파일이 있으면 비밀번호 입력에서 Enter만 눌러 저장된 비밀번호를 유지합니다. 즉시 적용하려면 ROS 실행 방식에 맞춰 다음 중 하나만 수행합니다.

```bash
# rcboat_ros.service로 실행 중일 때
sudo systemctl restart rcboat_ros.service

# 터미널에서 roslaunch로 직접 실행 중일 때: Ctrl+C 후 다시 실행
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash
roslaunch rcboat_ros rcboat.launch
```

GUI에서 비밀번호를 한 번 입력하고 `설정 저장 · 연결`을 눌러도 같은 로컬 파일에 저장됩니다. 이후 비밀번호 칸은 비워 두면 기존 비밀번호를 유지합니다. 필드: `RCBOAT_NTRIP_ENABLED`, `RCBOAT_NTRIP_HOST`, `RCBOAT_NTRIP_PORT`, `RCBOAT_NTRIP_MOUNTPOINT`, `RCBOAT_NTRIP_USERNAME`, `RCBOAT_NTRIP_PASSWORD`, `RCBOAT_NTRIP_TLS`. 이 파일은 `.gitignore` 대상입니다.

## 실제 보트 시험 전 확인

- 프로펠러 제거 상태에서 중립 시험과 실제 출력 선택 시험을 분리하고, 실제 출력 시험 전에 E-STOP을 실측합니다.
- GPS 장치의 UBX-NAV-PVT UTC, 위치, 속도, COG와 RTK 상태를 실제 장치로 대조합니다.
- `8765/tcp`는 시험 LAN에서만 허용하고 gateway token 또는 방화벽을 적용합니다.
- `actual_*_pwm`은 PCA에 전송한 명령이지 물리 위치 센서 피드백이 아닙니다.
- 지상 도보 시험 통과는 수상 자율운항 안전 승인을 의미하지 않습니다.
