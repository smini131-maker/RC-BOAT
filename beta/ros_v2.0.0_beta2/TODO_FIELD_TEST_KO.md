# RC Boat ROS v2.0.0-beta.1 현장 실행 체크리스트

**프로펠러를 제거하고 ESC 추진 전원을 분리한 뒤 테스트하세요.** 이 조건은 ROS 명령 잠금과 별개입니다.

1. **Windows**: GitHub `beta/ros-v2.0.0-beta.1` 브랜치에서 ZIP 다운로드. `CHECK_WINDOWS.cmd`, 필요하면 `SETUP_WINDOWS.cmd`; 빌드 시 `BUILD_ROS_GUI.cmd`. Actions의 최근 성공 실행에서 Windows EXE Artifact 받기.
2. **SSH**: PowerShell에서 `ssh jetson@<Jetson_IP>`. `nano.local` 대신 확인된 IP와 로그인 계정 사용.
3. **기존 서비스 확인**: `CHECK_BACKEND.cmd` → DAEMON 부팅 기본 enabled, ROS disabled. `ls -l /dev/serial/by-id/`로 Arduino/GPS 확인.
4. **Jetson ROS**: `ls /opt/ros/noetic/setup.bash` 확인. 없으면 Noetic 설치 사전점검 문서(지원 종료된 소프트웨어)에 따라 설치 가능 여부 점검. 설치 후 `DEPLOY_ROS.cmd`, `INSTALL_ROS.cmd`.
5. **안전 전환**: ESC 추진 전원 분리 상태에서 `USE_ROS.cmd`, `CHECK_ROS.cmd`. 실패 시 즉시 중지. `rcboat.service`와 `rcboat_ros.service` 동시 active 금지.
6. **ROS topic**: `source /opt/ros/noetic/setup.bash`; `source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash`; `rostopic hz /rcboat/gps/status`; `rostopic echo -n1 /rcboat/actuator/status`; `rosnode list`.
7. **Ground lock**: GROUND_TEST 시작 전 GPS healthy, actuator command_applied true, Steering 6000 / Throttle 6450 최신 상태 확인. 이는 물리 회전 피드백 아님.
8. **경로 3종 기록**: 원점·종점 각각 0.75m 이내인 LEFT/CENTER/RIGHT 기록. 중간 경로 구간을 충분히 떨어뜨림(기본 Multi-Path 이탈 8m/3초, 대체 경로 최소 2m 가까움, 쿨다운 5초).
9. **Non-Disturbance**: CENTER 주변에서 소폭 좌우 이동, 조향 보정은 이탈 반대방향인지 확인, switch 없음.
10. **Disturbance**: RIGHT에서 CENTER 방향으로 8m 이상 이탈을 3초 유지 → 그룹/거리 조건 충족 시 RIGHT→CENTER 전환, CSV/이벤트에 정확한 시간 기록.
11. **MATLAB**: `experiment_.../matlab/analyze_path_tracking.m` 실행. 각도 좌 파랑/우 빨강, Heading Error ±180, Speed m/s + 0.6 참고선, 경로 전환 세로선 확인.
12. **QGIS**: Console에 `import runpy; runpy.run_path(r"C:/.../experiment_.../qgis/setup_qgis_layers.py")` 입력. EPSG:4326/Index/TimeStep/레이어 4종 확인. 플러그인 TMS4 Korea의 VWorld Satellite 가능 여부 별도 확인.
13. **교차 검증**: MATLAB switch t=12.50s이면 QGIS Actual TimeStep 근접 점 찾아 같은 위치인지 확인(샘플 간격 약 0.25초).
14. **복귀**: 안전 검사 후 `USE_DAEMON.cmd` → `CHECK_BACKEND.cmd`에서 daemon만 active 확인.

현장 검증 전 `propulsion_allowed=false`를 유지하세요. 오류는 Windows logs/와 Jetson `journalctl -u rcboat_ros.service -n 100` 확인. 비밀번호·NTRIP credentials 로그 공유 금지.
