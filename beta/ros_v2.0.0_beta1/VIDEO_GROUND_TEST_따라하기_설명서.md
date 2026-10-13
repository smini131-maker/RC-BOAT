# RC BOAT ROS v2.0.0-beta.1 | 영상 참고 GPS Path-Tracking 지상 검증 실습 안내서

> 참고 영상: https://youtu.be/C5KsczjSD5Y  
> 확인된 영상 제목: **지상환경에서 GPS 기반 Path-Tracking 알고리즘 검증: Matlab Plot 및 QGIS 시각화 방법 설명**  
> **출처 표시:** 영상의 제목은 확인했으나 장면별 영상·자막은 확보하지 못했다. 이 설명서는 영상 제목에서 확인되는 목표와 사용자가 제공한 실험 조건, 제공 소스의 실제 작동 경로를 바탕으로 재구성한 **RC BOAT용 실행 절차**이다. 영상 속 특정 장면·분·초의 설명을 직접 인용한 것이 아니다.

## 1. 이 실험에서 검증해야 하는 것

이 실험은 RC보트를 실제 물에 띄우거나 추진 모터를 가동하지 않고, **실제 GNSS를 사람이 들고 걸으며** 경로 추종 알고리즘을 검증하는 과정이다. 목표는 `(1) 실제 위치와 방위 측정 → (2) 목표 경로에 대한 헤딩·횡오차 계산 → (3) 좌/우 조향 명령 계산 → (4) 주변 경로로 이탈 시 Multi-Path 전환 → (5) MATLAB 시계열과 QGIS 위치 지도에서 동일한 사건을 교차 확인`이다.

비교 항목:

| 비교 대상 | MATLAB에서 확인 | QGIS에서 확인 |
| --- | --- | --- |
| 실험 중 조향 | 시간-러더 각도, 좌/우 방향 | 당시 GPS 위치와 경로와의 관계 |
| 항법 오차 | 시간-Heading Error (−180~180°) | 좌/우로 얼마나 벗어났는지 |
| 이동 속도 | Time vs Speed [m/s] | 점 사이 이동·TimeStep |
| 경로 변경 | switch 시각에 세로선 | 동일한 TimeStep을 가진 GPS 점의 실제 위치 |

중요: **GROUND_TEST의 `desired_*`는 알고리즘 계산값, `actual_*`는 PCA에 마지막 기록한 명령값**을 뜻한다. 실제 모터 회전을 계측한 물리 피드백은 아니다.

## 2. 실험 전 환경·준비물 체크

- Jetson Nano, Ubuntu 20.04, 검증된 v1.6.0 daemon (`rcboat.service`)
- Arduino Uno + 기존 조종기/수신기, PCA9685, GPS u-blox ZED-F9 계열, 보조 전원
- 실외 GPS 수신 가능한 공간, Windows PC, SSH 연결, 가능하면 RTK/NTRIP 접속
- MATLAB(예: `readtable`, `xline`, `exportgraphics` 사용 가능 버전)과 QGIS
- 실제 서보가 예상치 못하게 움직이지 않도록 **프로펠러 제거 + ESC 추진 전원 분리** (초기 실험 필수)
- 가능한 한 GPS를 동일 방향으로 들고 실험. 걷는 속도에서 GNSS course가 얼마나 안정적인지도 관찰

**보안/장치 주의:** Arduino 시리얼·GNSS 시리얼·I2C는 각각 단 하나의 노드만 연다. `cat /dev/ttyACM0` 같은 별도 점검 프로그램을 동시에 실행하지 않는다. 기존 daemon과 ROS가 동시에 활성화되지 않았는지 확인한다.

**ROS 설치 상태:** `INSTALL_ROS.cmd`는 ROS Noetic 자체의 최초 설치기가 아니다. Jetson에 `/opt/ros/noetic/setup.bash`가 존재하고 ROS1/의존성이 갖춰져 있어야 Catkin 설치 단계가 진행된다. 해당 파일이 없으면 `docs/JETSON_ROS_NOETIC_설치_사전점검.md`부터 확인한다.

## 3. Windows 준비, 프로그램 빌드, 연결

1. ZIP 압축을 폴더째 풀고 `CHECK_WINDOWS.cmd`를 실행한다. Python 3.11/3.12 x64, Git for Windows, ssh를 확인한다.
2. 준비가 안 됐다면 `SETUP_WINDOWS.cmd`를 실행해 winget 설치를 **명시적으로 승인**하거나 Python/Git을 수동 설치한다. 설치 후 CMD/PowerShell을 다시 연다.
3. `BUILD_ROS_GUI.cmd`를 실행한다. 끝날 때 창이 닫히지 않으며 `logs/BUILD_GUI_날짜.log`에 성공·실패가 남는다.
4. 성공 결과 위치는 `windows_gui/dist/RCBoatControl_ROS_v2.0.0-beta.1.exe`다. 첫 실행 전 `ssh jetson@<IP>` 명령으로 서버 호스트 키를 확인·등록한다.
5. **Windows EXE가 생기는 것과 Jetson ROS가 실제 설치·실행되는 것은 별개다.** EXE 빌드만으로 보트의 실사용 가능성이 입증되지 않는다.

## 4. Jetson ROS 준비 및 백엔드 변경

1. Jetson 전원을 켠다. 기존 `rcboat.service`가 기본으로 시작하는 것이 정상이다.
2. Windows에서 `CHECK_BACKEND.cmd`로 데몬 상태와 USB/I2C 점유를 확인한다.
3. ROS Noetic 설치·의존성이 없다면 선행 준비(문서 `docs/JETSON_ROS_NOETIC_설치_사전점검.md`). 아예 ROS가 없는 상태에서 `USE_ROS.cmd`를 누르지 않는다.
4. `DEPLOY_ROS.cmd` : ROS 패키지를 `/home/jetson/rcboat_ros_ws/`에만 배포한다. `/home/jetson/rcboat/`를 덮어쓰지 않는다.
5. `INSTALL_ROS.cmd` : 기존 ROS 환경을 로드하고 `catkin_make`; ROS beta 서비스 설치(부팅 자동 실행 X).
6. **프로펠러 제거/ESC 추진 전원 차단 확인 후** `USE_ROS.cmd` 실행. (daemon stop → inactive PID 검사 → USB/I2C release → PCA 6000/6450 레지스터 readback → ROS start.)
7. `CHECK_ROS.cmd`와 다음 명령으로 노드 데이터 흐름 확인:

```bash
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash
rosnode list
rostopic list | grep /rcboat
rostopic hz /rcboat/gps/status
rostopic echo -n 1 /rcboat/gps/status
rostopic echo -n 1 /rcboat/actuator/status
rosservice list | grep /rcboat
# Jetson 데스크톱/X11 환경에서만
rqt_graph
```

일부 필수 topic 수신이 실패하면 **중단하고 로그 확인**. 서비스 active여도 GPS가 유효하지 않으면 실제 이동 검증을 진행하지 않는다.

## 5. GNSS/RTK 품질 확인

- `/rcboat/gps/status`: `fix=true`, `healthy=true`, `hdop≤3.0`, 정상 latitude/longitude, `speed_mps`, `heading_deg`.
- GNSS stale 기본 `2초`. NO FIX/단절/좌표 오류/HDOP 기준 초과 시 항법 계산/실제 추진을 차단해야 한다.
- `NTRIP CONNECTED`와 GNSS `RTK_FLOAT`/`RTK_FIXED`는 별개 지표. NTRIP 연결되었더라도 RTK FIXED가 아닐 수 있다.
- GPS 위성 수, PDOP/VDOP, hAcc, C/N0는 함께 관찰한다. C/N0 단독으로 정지·출발 반복하게 하지 않는다.
- 정지 상태에서 일반 GNSS heading/course는 불안정하거나 비어 있을 수 있다. 실제 걷기와 비교해 판단한다. F9R/F9P 칩 모델별 헤딩 기능은 GNSS 구성에 따라 다르므로 확정하지 않는다.
- GPS 4Hz는 기대 샘플링 목표이며 실제 토픽 주파수를 `rostopic hz`로 확인한다. `GROUND_TEST logger 4Hz`와 GPS 자체 유효 업데이트 속도는 다를 수 있다.

## 6. CENTER/LEFT/RIGHT 세 항로 만들기

1. 넓은 운동장이나 인적이 없는 직선 보행 통로를 선정한다. 목표 waypoint 간격은 약 1m.
2. `GROUND TEST`가 켜진 상태에서 GPS를 들고 경로 기록. 기록 파일은 timestamp / lat / lon / heading_deg 포함. 기존 lat/lon만 있는 항로도 읽을 수 있다.
3. 세 경로의 **시작점과 끝점은 0.75m 이내**로 일치하도록 하고, 중앙 구간만 LEFT/CENTER/RIGHT로 갈라지게 기록한다. 사용 중인 설정을 확인한다.
4. 원본 GPS 기록은 보존하고 `tools/resample_route.py`로 **복사본**을 1m 간격으로 리샘플링한다. `README_KO.md`의 사용법을 확인한다.
5. 저장된 `selected_route_id`, `active_route_id`, `candidate_route_id`, `target_waypoint_index`가 실제 기록과 일치하는지 GUI에서 확인한다.
6. Multi-Path 기본: 이탈거리 **8m 초과**, 지속 **3초**, 대체 항로 **2m 이상 가까움**, switch cooldown **5초**. 경로 간 1~2m만 간격을 벌리면 기본값 8m 조건으로 경로 전환을 기대할 수 없다.

## 7. GROUND_TEST 잠금 확인(모터 안전)

1. GROUND TEST 탭 → **지상 실험 시작**.
2. GUI에서 `GROUND TEST ACTIVE`, `ACTUATOR LOCKED`, `Steering actual=6000`, `Throttle actual=6450` 확인.
3. ROS topics에서 계산 명령(`/rcboat/navigation/desired`)과 실제 출력(`/rcboat/actuator/status`)을 나란히 비교.
4. 예: desired steering 5300 / desired throttle 6620이어도 actuator 명령은 6000 / 6450이어야 한다.
5. 이 검증은 PCA의 **기록 명령값 확인**이며 물리 모터가 무조건 정지함을 증명하지 않는다. GNSS walking test 동안도 ESC 추진 전원을 분리한다.
6. 로거는 4Hz로 샘플을 모으고, 종료 후 실험 폴더에 CSV·이벤트·QGIS·MATLAB·PNG·요약을 생성한다.

## 8. 실험 A — Non-Disturbance(경로 유지)

1. CENTER 항로 선택. 스스로 중심선을 따라 걷고 우측으로 조금 벗어난다.
2. 우측으로 벗어난 경우 항법의 물리적 조향 명령은 LEFT correction 방향인지 본다.
3. 좌측으로 약간 벗어나 LEFT correction과 반대 방향으로 나오는지 본다.
4. `heading_error_deg`, `cross_track_error_m`, `desired_steering_pwm`, `desired_rudder_angle_deg`의 부호와 변화량을 기록한다.
5. 의도적 교란이 없는 동안 `multipath_switch=False`, `active_route_id=CENTER`인지 검사한다.
6. 경로 추종 오차 감소를 관찰하되, 사람이 방향을 수동으로 바꾸므로 알고리즘 폐루프 자율제어가 입증된 것은 아니다.

## 9. 실험 B — Disturbance(멀티패스 전환)

1. RIGHT 항로 선택 후 중앙 구간으로 접근한다.
2. RIGHT 항로와 8m 이상 거리 차이가 생기는 지점으로 이동하고 3초 이상 유지한다.
3. CENTER가 RIGHT보다 2m 이상 더 가까워지고 그룹/쿨다운 조건도 충족하면 `RIGHT → CENTER` 전환을 확인한다.
4. GUI에 `Reference`, `Active`, `Candidate`, `Off-route Time`을 기록한다.
5. `raw/events.jsonl`에서 `previous_route`, `candidate_route`, `new_route`, `wall_timestamp`, `TimeStep` 확인.
6. CSV의 `multipath_switch` 필드와 `active_route_id` 변화가 같은 시간대인지 검사한다.

## 10. 실험 종료와 파일 구성

지상 실험 종료 → GUI `CSV 다운로드` / `MATLAB 분석용 파일 저장` / `QGIS 파일 저장`을 선택한다. 복사 위치는 다운로드 대화상자에서 지정한다. 가능한 기본 구조:

```text
experiment_YYYYMMDD_HHMMSS/
  raw/path_tracking.csv
  raw/events.jsonl
  matlab/analyze_path_tracking.m
  qgis/actual_track.csv
  qgis/target_left.csv
  qgis/target_center.csv
  qgis/target_right.csv
  plots/steering_angle.png
  plots/heading_error.png
  plots/speed.png
  plots/cross_track_error.png
  experiment_info.json
  summary.json
  summary.txt
```

CSV 열: `index`, `timestamp`, `elapsed_time_s`, `latitude`, `longitude`, `utm_easting_m`, `utm_northing_m`, `heading_deg`, `target_heading_deg`, `heading_error_deg`, `speed_mps`, `desired_steering_pwm`, `desired_rudder_angle_deg`, `desired_throttle_pwm`, `actual_steering_pwm`, `actual_throttle_pwm`, `selected_route_id`, `active_route_id`, `target_waypoint_index`, `distance_to_waypoint_m`, `cross_track_error_m`, `multipath_candidate_id`, `multipath_switch`, `gps_fix`, `rtk_state`, `satellites`, `hdop`, `hacc_m`, `cno_dbhz`, `gps_update_monotonic`.

`timestamp`는 절대시각(현지 오프셋 포함), `elapsed_time_s`는 실험 시작부터 흐른 초. 두 분석 시스템은 **경과시간(TimeStep=elapsed_time_s)** 기준으로 맞춘다.

## 11. MATLAB — 영상 제목의 첫 번째 검증 축

1. MATLAB을 실행한다. `matlab/analyze_path_tracking.m`을 열고 실행한다.
2. 스크립트가 같은 실험 폴더의 `raw/path_tracking.csv`를 자동 찾지 못하면 파일 선택창에서 지정한다.
3. 필수 plot 3개: `Time vs Rudder Angle`, `Time vs Heading Error`, `Time vs Speed`.
4. Rudder Angle 그래프: X=Time[s], Y=Angle[deg], 0° neutral, **좌(-) Blue / 우(+) Red**. 이 부호는 실제 서보 방향 반전 설정을 반영하도록 소스에서 보정한다.
5. Heading Error: −180~+180°, 0° 기준선, switch 발생 시 수직선. 경로 전환 시점(예: 12.50초)을 메모한다.
6. Speed: 속도 단위 m/s. ROS GPS topic이 이미 m/s이면 **다시 ÷3.6 하지 않는다**.
7. 추가 그래프 Cross Track Error를 확인한다. 출력 PNG는 `plots/`에 저장한다.
8. 해석: heading error가 줄었는지, 좌/우 조향이 실제 이탈 방향에 반대인지, switch 이후 새로운 경로 기준으로 오차가 해석되는지 확인한다.

## 12. QGIS — 영상 제목의 두 번째 검증 축

1. QGIS → `Layer` → `Add Layer` → `Add Delimited Text Layer`.
2. `actual_track.csv`를 추가한다. X=Longitude, Y=Latitude, Geometry CRS=EPSG:4326 (WGS84).
3. `target_left.csv`, `target_center.csv`, `target_right.csv`를 같은 방식으로 추가한다.
4. 레이어 스타일: Actual **Green**, LEFT **Blue**, CENTER **Gray**, RIGHT **Red**.
5. Target CSV의 `Index`를 라벨로, actual_track CSV의 `TimeStep`을 라벨로 지정한다.
6. QGIS 3.x면 Plugins → Manage and Install Plugins → **TMS for Korea**를 검색한다. QGIS 공식 저장소에는 3.0.5 버전(3.16 이상~3.99 이하)이 등록돼 있다. 설치 후 VWorld Satellite가 보이면 선택한다.
7. QGIS 4.x나 플러그인이 호환되지 않으면 강제 설치하지 말고 VWorld의 현재 공식·라이선스에 맞는 XYZ/TMS 연결 방법을 확인한다. 기본 지도가 없어도 CSV 점 좌표 검증 자체는 가능하다.
8. 좌표계 EPSG:4326이 아닌 지도 타일의 CRS가 달라도 QGIS의 온더플라이 좌표변환을 사용한다.
9. `TimeStep=12.50`인 실제 궤적 점을 찾는다. 해당 점이 새 경로 가까이에 있는지와 MATLAB `t=12.50`의 수직선을 대조한다.
10. Timestamp의 소수초를 시간 형식으로 변환할 때 `+09:00` 시간대를 잃지 않도록 주의한다.

공식 플러그인 참고: https://plugins.qgis.org/plugins/tmsforkorea/  
참고 저장소: https://github.com/mangosystem/qgis-tmsforkorea-plugin

## 13. 성공/실패 판단 체크표

| 단계 | 성공 판정 기준 | 실패 시 |
| --- | --- | --- |
| Windows Build | 실제 EXE 존재, 로그에 빌드 성공, GUI headless smoke 통과 | BUILD_GUI 로그 검사, Python/PySide6 점검 |
| ROS install | catkin_make 정상, ROS 노드 확인 | ROS Noetic/의존성/장치 접근 확인 |
| Backend | daemon와 ROS 동시 active 아님 | 즉시 점검·전환 중단, 장치 오너 검사 |
| GPS | 위치 정상, stale/NO FIX 아닌 상태 | 외부 GNSS 수신 가능 위치로 이동 |
| GROUND_TEST | 실제 PWM 명령 6000/6450, desired 별도 기록 | 실험 중단, ESC 전원 차단 |
| Non-Disturbance | 작은 편차 교정 방향 정상, 불필요한 route switch 없음 | 조향 부호/헤딩 기반/route geometry 확인 |
| Disturbance | 조건 충족 시 RIGHT→CENTER, 이벤트·CSV 일치 | 8m/3s/2m/경로그룹/쿨다운 확인 |
| MATLAB | 3개 그래프 생성, TimeStep 축 정확 | CSV 값 누락/버전/경로 확인 |
| QGIS | 실측궤적 및 3개 타깃 경로 중첩 | EPSG:4326, X/Y 순서 확인 |
| 복귀 | USE_DAEMON 이후 rcboat.service만 active | 장치 해제/안전 PWM 검사 |

## 14. 실제 실험 보고서 양식

- 사용 기기 / GNSS 모델(실물 확인):
- ROS Noetic/catkin_make 결과:
- GPS 업데이트 실측 평균(Hz):
- RTK 상태(FLOAT/FIXED) 및 Fixed 비율:
- CENTER 경로 Non-Disturbance 횡오차(평균/최대):
- RIGHT→CENTER switch TimeStep:
- switch 전후 Heading Error / Rudder Demand:
- 실제 PCA 중립값 명령 기록: CH0=6000 / CH6=6450:
- MATLAB 그래프 3개 파일명:
- QGIS 실제 궤적과 타깃 경로 스크린샷:
- ROS→daemon 복귀 결과:
- 실패/보완 사항 및 재실험 필요 여부:

**주의:** 제공된 `samples/`와 `sample_ground_test.csv`는 생성된 합성 검증자료이다. 이를 실제 GPS RTK 보행시험 결과인 것처럼 제출해서는 안 된다.
