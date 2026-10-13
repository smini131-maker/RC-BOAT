# Windows EXE 빌드와 GitHub 업로드 진단

## 핵심 변경 사항

이전 CMD는 성공/실패에 관계없이 종료될 수 있었고 로그가 남지 않았습니다. 이번 CMD는 창을 유지하고 `logs/BUILD_GUI_날짜.log`, `logs/UPLOAD_GITHUB_날짜.log`를 작성합니다. 더블클릭했을 때 마지막의 `계속하려면 아무 키나 누르십시오`를 누르기 전까지 닫히지 않습니다.

## 빌드

1. ZIP을 압축 해제하고 `BUILD_ROS_GUI.cmd`를 **해제된 폴더에서** 실행합니다.
2. Python 3.11 또는 3.12 x64가 필요합니다. Windows의 `py -0p`로 설치 버전을 확인합니다. Python 3.13만 있으면 3.11을 추가 설치합니다.
3. 최초 실행 시 pip가 PySide6·Paramiko·PyInstaller를 내려받으므로 인터넷 연결이 필요합니다. 네트워크/권한/보안 프로그램 오류는 로그에서 확인합니다.
4. 성공 시 `windows_gui/dist/RCBoatControl_ROS_v2.0.0-beta.1.exe`가 생깁니다. `Windows GUI` 빌드는 Jetson ROS 설치를 수행하지 않습니다.
5. SSH 접속 전에 Git Bash/Windows OpenSSH로 호스트키를 확인해야 합니다. 프로그램의 호스트키 정책은 자동 신뢰가 아닌 RejectPolicy입니다.

## GitHub 업로드

1. Windows에 Git for Windows를 설치합니다. PowerShell에서 `git --version`을 확인합니다.
2. `git config --global user.name "Your Name"` 와 `git config --global user.email "you@example.com"`를 최초 한 번 설정합니다.
3. `UPLOAD_GITHUB.cmd`를 실행합니다. 기존 `release/1.6.0`이 아닌 `beta/ros-v2.0.0-beta.1`의 **별도 디렉터리**로만 업로드합니다.
4. GitHub 인증이 필요하면 Git Credential Manager 브라우저 로그인을 완료합니다. 암호/토큰을 스크립트에 저장하지 않습니다.
5. GitHub 저장소의 Actions에서 **Build RC Boat ROS v2 Windows GUI** 실행/완료 여부를 보고 artifact를 다운로드합니다. 워크플로가 업로드되기 전에는 실행되지 않습니다.
6. 업로드 실패 시 `logs/UPLOAD_GITHUB_날짜.log`를 보고, 임시 clone 경로에서 git status를 확인합니다. GitHub 저장소에 업로드되었다고 가정하지 마세요.

## 오류별 확인

- `py.exe not found` / `Python 3.11...`: Python 3.11 x64 설치 + Windows용 Python launcher 활성화
- `No module named pip`: Python 설치 프로그램에서 pip 포함 재설치
- `No matching distribution found`: Python 버전, x64 여부, 인터넷/프록시 확인
- `Microsoft Visual C++ Runtime` 오류: Windows 런타임 설치 확인
- `Git author not configured`: git config user.name, user.email 설정
- `Authentication failed`: Git Credential Manager 인증 또는 GitHub 계정 권한 확인
- `src refspec` / branch missing: GitHub에 해당 beta 브랜치가 있는지 확인
- `SSH Host key ...` 또는 `Unknown host key`: SSH 콘솔에서 먼저 지문을 검증해 known_hosts에 등록
- `ROS Noetic missing`: Jetson에 ROS1 Noetic 선행 설치 필요, 실행 실패와 빌드 실패는 다른 문제

## 점검 결과의 의미

Windows `.exe` 파일 생성은 PyInstaller 빌드 성공만 뜻합니다. Jetson에서 ROS Noetic 설치, 노드 구동, 실제 GPS·RTK 연결, PCA9685 안전 출력을 검증하지 않는 한 수상 운항을 허용하지 않습니다.
