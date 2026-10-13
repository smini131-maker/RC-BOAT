# 변경 파일 요약

모든 신규/변경 파일은 `beta/ros_v160/` 아래에만 있습니다.

| 경로 | 내용 |
|---|---|
| `catkin_ws/src/rcboat_ros/` | ROS package, 10개 기능 노드, custom msg/srv, launch/config |
| `systemd/` | real/HIL 상호 배타 service |
| `deployment/jetson/` | 설치, 배포, preflight, 안전 전환, 검사, 제거 |
| `deployment/windows/` | INSTALL/DEPLOY/USE/CHECK/UNINSTALL/GUI build CMD 및 PowerShell |
| `windows_gui_source/` | v1.6 GUI 기능을 유지한 별도 ROS Beta GUI source/spec |
| `tests/` | beta 격리, ownership, 안전값, launch, 핵심 로직 회귀 검사 |
| `README_KO.md` | Windows/Jetson 설치·실행 명령 및 단계별 안전 절차 |
| `ARCHITECTURE.md` | node, owner, 명령 흐름, daemon 전환 구조 |
| `TOPICS_AND_SERVICES.md` | ROS interface 목록 |
| `TEST_REPORT.md` | 자동검사와 현장검증 구분 |
| `ROLLBACK.md` | daemon 즉시 복귀 및 베타 제거 |

기존 `release/1.6.0` 파일, 루트 `jetson_patch`, 기존 GUI source 및 기존 beta 폴더는 변경하지 않았습니다.
