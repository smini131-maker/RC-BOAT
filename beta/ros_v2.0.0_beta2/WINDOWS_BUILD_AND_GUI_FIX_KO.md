# ROS beta.2 Windows 긴 경로 오류·GUI 개선 (2026-10-14)

## 재현한 오류와 해결

원본 ZIP을 Downloads의 중첩 폴더에 압축 해제하면 사용자 로그처럼 `windows_gui\\.venv\\Lib\\site-packages\\PySide6\\qml\\...` 경로가 260자를 초과하여 pip 설치가 실패할 수 있습니다.

이번 패치의 핵심은 **Windows 레지스트리의 LongPathsEnabled를 변경하도록 요구하지 않고**, 가상환경을 `%LOCALAPPDATA%\\RCBoatBuild\\ros-beta2\\venv313` 같은 짧은 경로에 생성한다는 점입니다. PyInstaller도 같은 위치의 `stage/work/spec`에서 빌드합니다. 실패한 이전 `.venv`는 무시하므로 지울 필요가 없습니다.

설치 패키지 역시 PySide6 전체 대신 **PySide6-Essentials**만 사용하여 불필요한 Qt WebEngine/PDF/QML 애드온 설치를 줄입니다. Windows 실행파일은 여전히 `windows_gui\\dist`에 저장합니다.

## 새 GUI

기존 v1.6.0 관제센터를 참고하여 진한 남색 테마, 고양이 보트 아이콘, SSH·GPS·RTK·모드·안전잠금·출력 상태 카드와 한국어 계기판을 복구했습니다. GPS 지도는 실제 위성 배경이 아닌 **좌표 기반 경로도**라고 명시했습니다. 항로 관리·Multi-Path·NTRIP·GPS 실험·다운로드·원격 스로틀 및 SSH 터미널 기능은 유지했습니다. NAVIGATION 실행 승인이나 안전 잠금을 임의로 해제하지 않습니다.

## Windows 실행 순서

1. 새 소스 ZIP을 압축 해제합니다. 이미 받은 오래된 ZIP은 사용하지 마세요.
2. `CHECK_WINDOWS.cmd`에서 Python 3.13 x64를 확인합니다.
3. 이미 받은 Windows EXE를 실행한다면 Python과 Git은 설치할 필요가 없습니다.
4. 직접 빌드하려면 `BUILD_ROS_GUI.cmd`를 실행합니다. 빌드 캐시는 `%LOCALAPPDATA%\\RCBoatBuild\\ros-beta2`에 생성됩니다. 처음에 인터넷으로 pip 패키지를 내려받습니다.
5. 빌드 성공 시 `windows_gui\\dist\\RCBoatControl_ROS_v2.0.0-beta.2.exe`를 실행합니다. 문제 발생 시 `logs\\BUILD_GUI_날짜.log`를 확인합니다.

GitHub Windows CI는 Python 3.11/3.13, 실제 CMD 실행, **일부러 깊게 만든 Windows 폴더**에서의 GUI 빌드와 GUI 스모크/스크린샷을 검사합니다. 이는 Jetson ROS/GPS 실물 동작 검증이 아닙니다.
