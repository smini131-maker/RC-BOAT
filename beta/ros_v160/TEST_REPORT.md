# Test Report — v0.1.0-beta.1

## 자동 검증 범위

| 항목 | 상태 | 비고 |
|---|---|---|
| Python AST/compileall | PASS | ROS/GUI 전체 Python |
| Bash 문법 | PASS | Jetson 배포/전환 스크립트 |
| XML/launch parse | PASS | package 및 real/HIL launch |
| beta 경로 격리 | PASS | 변경 파일은 `beta/ros_v160`만 |
| HIL actuator node 부재 | PASS | HIL launch 정적 검사 |
| real 단일 actuator | PASS | real launch 정적 검사 |
| final command 단일 publisher 설계 | PASS | safety만 publish하도록 검사 |
| 안전 PWM/채널/baud/by-id | PASS | 회귀값 정적 검사 |
| daemon/ROS systemd conflict | PASS | unit 정적 검사 |
| 핵심 navigation/route/parser unit test | PASS | 하드웨어 독립 테스트 |
| Windows GUI Python compile | PASS | Linux에서 소스 compile |
| PowerShell 실행/Windows EXE smoke | WINDOWS REQUIRED | 현재 검증 환경에 PowerShell/Windows 없음 |
| 기존 v1.6 비-GUI 회귀 | PASS | 77개 통과 |
| 기존 GUI runtime 회귀 | NOT RUN | 현재 Linux 검증 환경에 PySide6/paramiko 없음 |
| Windows EXE 생성 | WINDOWS REQUIRED | `BUILD_ROS_GUI.cmd`로 Windows에서 생성 |
| Jetson `catkin_make` | JETSON REQUIRED | ROS Noetic 설치 후 배포 단계 |
| 실제 Arduino/GPS/NTRIP/PCA | FIELD REQUIRED | 실물 연결 필요 |
| daemon ↔ ROS 왕복 | FIELD REQUIRED | Jetson에서 Stage 순서대로 실행 |

## 현장 검증 기록란

| Stage | 확인 명령/조건 | 결과 |
|---|---|---|
| B HIL | `USE_ROS_HIL.cmd`, `CHECK_ROS.cmd` | 미실행 |
| C graph | `rqt_graph` | 미실행 |
| D GPS/RTK | `/rcboat/gps/status`, `/rcboat/ntrip/status` | 미실행 |
| E Arduino | `/rcboat/rc/input` | 미실행 |
| F PCA safe | 프로펠러 제거, 6000/6450 | 미실행 |
| G steering | 좌/우 방향 | 미실행 |
| H ESC | 프로펠러 제거, 저출력 | 미실행 |
| I–K outdoor | 직선/기록항로/Multi-Path | 미실행 |

실물 시험을 하지 않은 항목은 PASS로 표시하지 않습니다.
