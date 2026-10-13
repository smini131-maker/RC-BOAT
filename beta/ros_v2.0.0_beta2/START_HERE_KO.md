# RC BOAT ROS v2.0.0-beta.2 — 시작 안내

**GitHub 베타 소스 업로드와 Windows x64 EXE 빌드가 완료되었습니다.** Jetson에 ROS가 설치되었거나 현장 안전 시험이 끝났다는 뜻은 아닙니다.

## GitHub에서 EXE 다운로드
1. https://github.com/smini131-maker/RC-BOAT/actions/runs/38413477441 열기
2. 아래 **Artifacts**에서 `RCBoatControl_ROS_v2.0.0-beta.2_Windows_x64` 선택
3. ZIP 압축 해제 후 `RCBoatControl_ROS_v2.0.0-beta.2.exe` 실행
4. 최초 SSH 호스트 키를 PC의 `ssh jetson@<Jetson IP>`로 확인한 뒤 GUI에서 연결

## 소스에서 Windows EXE 직접 다시 만들기
1. 베타 브랜치를 Clone 또는 ZIP 다운로드
2. `beta/ros_v2.0.0_beta2` 폴더 안에서 `CHECK_WINDOWS.cmd` 실행
3. Python 3.11/3.12 x64 또는 Git이 없으면 `SETUP_WINDOWS.cmd` 실행
4. `BUILD_ROS_GUI.cmd` 실행
5. 실패 시 콘솔은 일시 정지하며 `logs/BUILD_GUI_날짜.log` 확인

## Jetson 실기시험 (아직 별도 검증 필요)
- 먼저 `docs/JETSON_ROS_NOETIC_설치_사전점검.md` 확인
- ROS Noetic 및 catkin 빌드 가능 여부 검증
- 기존 `rcboat.service` 자동실행 유지, ROS 서비스 자동 enable 금지
- 프로펠러 제거/ESC 추진 전원 분리 후 `CHECK_BACKEND.cmd`, `INSTALL_ROS.cmd`, `USE_ROS.cmd`, `CHECK_ROS.cmd` 순서로 점검
- `VIDEO_GROUND_TEST_따라하기_설명서.md`에 따라 실제 GPS/RTK 보행 실험
- 문제가 생기면 안전 정지 후 `USE_DAEMON.cmd`로 기존 backend 복귀

## 현재 검증 수준
- GitHub Actions: Python 자동 테스트, Windows GUI 스모크, 실제 Windows EXE 스모크, 파일 체크섬 검증 통과
- Jetson/Arduino/GPS/NTRIP/RTK/PCA9685 실기 검증: 미실시
- 추진 허용 설정: `propulsion_allowed=false` 유지

> **Windows script fix (2026-10-14):** Local Python 3.13 x64 is supported. Git is optional unless uploading. Run `CHECK_WINDOWS.cmd` and consult `docs/WINDOWS_빌드_업로드_문제해결.md`.
