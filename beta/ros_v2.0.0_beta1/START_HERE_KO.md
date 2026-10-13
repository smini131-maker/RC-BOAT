# RC BOAT ROS v2.0.0-beta.1 — 수정 패키지 사용 순서

**이번 패키지는 소스와 실행 스크립트 수정본입니다. Windows EXE나 Jetson ROS 설치가 이미 완료된 결과물이 아닙니다.**

1. ZIP을 반드시 압축 해제합니다. ZIP 내부에서 CMD를 바로 실행하지 마세요.
2. `CHECK_WINDOWS.cmd` 실행. Python 3.11/3.12 x64, Git, OpenSSH가 필요한지 확인.
3. 설치가 없다면 `SETUP_WINDOWS.cmd` 실행 후 사용자 승인 아래 winget으로 Python/Git 설치. **새 터미널**을 열어 PATH 갱신.
4. `BUILD_ROS_GUI.cmd` 실행. 실패해도 창은 일시정지하고 `logs/BUILD_GUI_날짜.log` 저장. 성공 시 `windows_gui/dist/RCBoatControl_ROS_v2.0.0-beta.1.exe`를 직접 확인.
5. `UPLOAD_GITHUB.cmd` 실행. 실패해도 창은 일시정지하고 `logs/UPLOAD_GITHUB_날짜.log` 저장. 별도 GitHub 베타 브랜치에만 복사하며 사용자의 Git 인증 필요.
6. GitHub Actions의 Windows Build가 성공한 경우 `Actions → Build RC Boat ROS v2 Windows GUI → Artifact`에서 EXE 다운로드 가능. 워크플로가 실행/성공하지 않았다면 EXE가 없는 것이 정상.
7. **Jetson ROS는 별도 작업**: `docs/JETSON_ROS_NOETIC_설치_사전점검.md`부터 진행. `INSTALL_ROS.cmd`는 Noetic 최초 설치를 자동 수행하지 않습니다.
8. `VIDEO_GROUND_TEST_따라하기_설명서.pdf`/`.md`를 따라 실험. 첫 실험은 프로펠러를 제거하고 ESC 추진 전원을 분리합니다.
9. `TEST_REPORT_UPDATED.md`에서 실제 검사 결과와 아직 미검사 항목 확인.

긴급 복귀: 시스템 간 충돌이 의심되면 두 실행 도구를 동시에 실행하지 말고 장비 전원을 안전하게 차단한 뒤 운영 상태를 점검하세요. 정상 상태에서 `USE_DAEMON.cmd`를 사용하면 ROS 중단 → 장치 해제 → 기존 daemon 복귀를 수행하도록 설계되어 있습니다.
