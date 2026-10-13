# ROS v2.0.0-beta.1 수정 패키지 내부 QA 보고서

**평가 날짜:** 2026-10-13 / 작업 환경: Linux Python 3.13.5, ROS/Jetson 하드웨어 및 Windows 환경 없음.

## 확인한 원인 및 수정

- 기존 BUILD_ROS_GUI.cmd와 UPLOAD_GITHUB.cmd에 오류 발생 시 창 유지 기능이 없고 로그가 없어 더블클릭 실패 원인 추적 불가 → 공통 PowerShell runner를 만들고 항상 pause + 날짜별 로그 기록.
- Python 미설치·Git 미설치 상태에서도 즉시 종료 → CHECK_WINDOWS / SETUP_WINDOWS 도구 제공, Python 3.11/3.12 x64 검사.
- Windows GUI가 /home/jetson/rcboat_ros_ws/bridge_client.py (존재하지 않는 배포 경로) 호출 → 배포된 deployment/jetson/bridge_client.py로 정정.
- ROS 점검이 topic 실패여도 성공처럼 보고할 수 있음 → 필수 topic 하나라도 수신 실패 시 exit 1.
- ROS NAV 조향 inversion 때 desired rudder angle의 물리 좌우 부호가 뒤집혀 MATLAB 색 구분이 부정확 → 계산된 각도 부호 보정.
- 영상 실험 안내가 간략 → 출처 확인 범위 표기, 14단계 장비·보행·MATLAB·QGIS·결과해석 설명서 PDF+MD 제공.
- Windows 빌드 성공 시에는 GUI offscreen smoke, 26개 회귀 테스트, EXE 파일 존재와 SHA256을 확인하도록 준비.
- GitHub Actions workflow는 Windows 환경에서 PySide6 smoke→EXE 컴파일→artifact 체크를 수행하도록 구성.

## 실제 수행한 내부 검사

- `python -m unittest discover -s tests -v` : **26 / 26 PASS**.
- 순수 Python 소스 AST 검사, GPS UBX NAV-PVT 파싱, GPS health, 경로 선택 저장, Multi-Path 3초 전환, 경로 기록 timestamp/heading, QGIS CSV export, ROS 안전 게이트 정적 검사, 설치/GUI 경로 검사: PASS.
- ROS 안전 출력 기본값: steering 6000 / throttle 6450; `propulsion_allowed: false` : 소스 및 테스트 PASS.
- PDF 텍스트 추출 및 전체 7페이지 존재 확인: PASS.
- ZIP 완성/무결성 검사: 제작 직후 PASS (아래 설명).

## 아직 검증하지 못한 사항

- CMD 및 PowerShell 동작을 실제 Windows 10/11에서 끝까지 실행한 결과: **없음**.
- Windows PyInstaller EXE 실제 생성/실행/GUI 렌더링: **없음**. 소스 테스트만으로 EXE 성공을 뜻하지 않음.
- GitHub 전체 소스 업로드: **미완료**. 사용자의 git 로그인/업로드 필요.
- Jetson catkin_make, Noetic 설치 및 ROS Master/rqt_graph: **미검증**.
- GPS, NTRIP, 실물 ZED-F9 칩, Arduino serial, I2C/PCA 레지스터 실제 확인: **미검증**.
- 서보 모터/ESC 안전, 정지/출발, 수상 항법 및 ROS↔daemon 복귀: **미검증**.
- MATLAB 소프트웨어로 `.m` 실행 또는 QGIS 프로그램의 실물 데이터 화면 확인: **미검증** (샘플 파일/구조는 존재).
- 참고 영상의 전체 자막/장면/정확한 타임라인: **접근 불가**. 제목만 직접 확인. 나머지는 사용자 요구사항 기반 재구성.

**운용 제한:** 위 항목들이 실제로 검사되기 전까지 ROS 베타 추진은 잠긴 상태로 유지. 특히 GROUND_TEST에서도 초기 실험 동안 프로펠러 제거/ESC 추진전원 분리.
