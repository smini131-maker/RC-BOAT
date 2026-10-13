# GROUND_TEST – 실물 GPS를 들고 걷는 경로 추종 실험

안전: 실험 첫 단계에서는 반드시 보트 **프로펠러 제거/ESC 추진 전원 분리**. 계산 PWM과 실제 PCA에 마지막으로 작성한 값을 구분한다. 실제 PCA 레지스터 명령 값만으로 ESC가 움직이지 않았음을 증명할 수는 없다. GNSS Course는 정지/저속에서 흔들릴 수 있으므로 walking 속도와 FIX 상태를 함께 본다.

## 1. 켜기와 노드 확인

1. Jetson 전원을 켜면 기존 daemon이 기본 실행되므로 먼저 `CHECK_BACKEND.cmd`로 확인한다.
2. `USE_ROS.cmd`를 실행한다. legacy 종료 및 hardware release를 검사한 후 ROS가 시작된다.
3. SSH에서 `rostopic echo -n1 /rcboat/gps/status` 확인. `healthy=true`, `fix=true`, `hdop <=3`인지 점검한다.
4. RTK를 사용한다면 `rostopic echo /rcboat/ntrip/status`로 `connected`, `bytes_received`, `correction_age` 확인 후, 독립적으로 `/rcboat/gps/status`의 `rtk_state`를 확인한다. RTK_FLOAT/RTK_FIXED는 수신기 fix state에서 판별한다.
5. Windows ROS GUI를 연결한다. 처음 SSH 접속이면 Windows OpenSSH로 호스트 키를 검증한다.

## 2. 경로 선택 및 실험 시작

6. GPS로 직접 기록한 CENTER/RIGHT/LEFT 경로를 만들고 항로 관리에서 선택한다. GUI의 지도는 좌표 기반 경로 뷰이며 실제 위성지도 바탕은 QGIS에서 검증한다.
7. GROUND TEST 탭에서 **지상 실험 시작**. `GROUND TEST ACTIVE`, `ACTUATOR LOCKED`, `6000 / 6450` 표시가 나오는지 확인한다. Actual은 PCA에 마지막 성공적으로 기록한 duty값이지 모터 회전 피드백이 아니다.
8. 위성 시야가 열린 공간에서 장비를 들고 경로를 따라 걸어간다. 이때 실제 GNSS가 4 Hz 근처로 들어오는지 체크한다.
9. Non-Disturbance: CENTER를 선택하고 경로 좌우 가까이 이동해 cross-track error와 desired steering 방향을 확인한다. route switch 없어야 한다.
10. Disturbance: 같은 시작/끝을 가진 RIGHT와 CENTER 경로를 사용한다. RIGHT 선택 후 CENTER 쪽으로 8 m 이상 이탈하여 3초 이상 유지하고 CENTER가 최소 2 m 더 가까우면 switch가 발생한다. **평행 경로 간격이 1 m 정도면 조건을 만족할 수 없다.** 따라서 시작/끝은 0.75 m 이내에서 합치고 중간 구간은 8 m 이상 벌어지는 형태로 실험 경로를 새로 기록한다.
11. 로그에는 `previous_route`, `candidate_route`, `new_route` 전환 이벤트가 `raw/events.jsonl`에 별도로 남는다. 위치 샘플에는 `multipath_switch` 및 active route를 기록한다.
12. 지상 실험 종료. 파일은 `~/rcboat_ros_data/experiments/experiment_YYYYMMDD_HHMMSS/`에 만들어진다. GUI SFTP 버튼에서 `CSV 다운로드`, `MATLAB 분석용 파일 저장`, `QGIS 파일 저장` 중 선택한다.

## 3. MATLAB

13. 다운로드한 `matlab/analyze_path_tracking.m`을 MATLAB에서 실행한다. 탐색기 파일 선택 창이 뜨면 `raw/path_tracking.csv`를 선택한다.
14. 최소 그래프 3개: `Time vs Rudder Angle`, `Time vs Heading Error`, `Time vs Speed [m/s]`. 추가 `Cross Track Error` 그래프도 있다.
15. `heading_error.png`의 Multi-Path switch 수직 마커에서 시각(예: 12.50s)을 확인한다.

## 4. QGIS

16. QGIS 실행 후 `Plugins → Manage and Install Plugins`를 연다. QGIS 3.x는 공식 Plugin Repository의 **TMS for Korea 3.0.5**를, QGIS 4.x는 개발자 GitHub의 `4.x/main` 안내/호환판을 확인한다. QGIS 버전과 플러그인 호환을 무시하고 강제 설치하지 않는다.
17. TMS for Korea → VWorld Satellite(위성지도)를 추가한다. 플러그인이 없으면 합법적으로 사용할 수 있는 VWorld 공식 지도 서비스/XYZ 타일 연결 방식으로 추가한다.
18. `Layer → Add Layer → Add Delimited Text Layer`에서 `qgis/actual_track.csv`와 3개 target CSV를 연다. X=`Longitude`, Y=`Latitude`, CRS=`EPSG:4326`.
19. 스타일: Actual Green / LEFT Blue / CENTER Gray / RIGHT Red.
20. Target은 `Index`를, Actual은 `TimeStep`을 라벨로 지정한다. `TimeStep=12.50`인 점을 찾아 MATLAB 수직마커와 동일한 위치인지 검증한다.
21. GPS 좌표는 EPSG:4326, VWorld 베이스 타일은 EPSG:3857일 수 있다. QGIS의 온더플라이 좌표변환을 이용한다.

참조: https://plugins.qgis.org/plugins/tmsforkorea/ (QGIS 3) 및 https://github.com/mangosystem/qgis-tmsforkorea-plugin (QGIS 4).

## 5. 요약 및 실패 조건

`summary.txt`: Duration, Samples, Mean GPS Rate, Mean Speed, Max/Mean Abs Heading Error, Max/Mean Cross Track Error, Switch Count, Initial/Final Route, RTK Fixed Ratio, GPS Dropouts.

GPS stale/NO_FIX/HDOP 초과 시 navigation desired 계산이 정지된다. log에는 결측을 기록할 수 있으나 실험에서 경로 유지 성능이 검증됐다고 주장하지 않는다. GPS 센서/모터/서보 출력/ROS graph 검증 결과는 별도로 기록한다.


> **수정 패키지 주의:** Windows 초기 설정 및 오류 로그는 `docs/WINDOWS_빌드_업로드_문제해결.md`를, ROS Noetic 준비는 `docs/JETSON_ROS_NOETIC_설치_사전점검.md`를 참조하세요.
