# RC BOAT ROS v2.0.0-beta.2 — Windows 체크/빌드/업로드 사용법

## 사용자 출력의 실제 원인

`where git.exe`는 Git을 찾지 못하면 Windows의 '정보: 제공된 패턴에 해당되는 파일을 찾지 못했습니다.'를 출력합니다. **Git은 체크·GUI 실행·EXE 빌드에 필요하지 않고 GitHub 직접 업로드에만 필요합니다.**

`py -0p`에서 Python **3.13 x64**가 확인됐습니다. 이번 버전은 3.11, 3.12, **3.13** x64를 지원하므로 Python 3.11을 추가 설치할 필요가 없습니다.

`WINDOWS_鍮...`로 보이는 문구는 UTF-8 한글을 레거시 CMD 코드페이지에서 출력한 결과였습니다. 배치 파일의 안내문은 영문 ASCII로 정리하고, 한글 지침은 UTF-8 마크다운 문서에 남겼습니다.

## 직접 실행 순서

1. 전체 ZIP을 반드시 실제 폴더로 압축 해제합니다. 예: `C:\RCBoatBeta2`. ZIP 미리보기에서 CMD만 실행하면 필수 파일을 찾지 못합니다.
2. `CHECK_WINDOWS.cmd`를 실행합니다. 정상이라면 `[OK] Windows preflight completed.`가 표시되고 `logs/CHECK_WINDOWS_날짜.log`가 기록됩니다. 검사 과정에 설치/SSH 접속은 없습니다.
3. Git이 없으면 `[OPTIONAL] git.exe is absent`라고 표시되지만 오류가 아닙니다. ssh/scp도 Jetson에 연결할 때만 필요합니다.
4. **GUI만 실행**: 이미 빌드된 `RCBoatControl_ROS_v2.0.0-beta.2.exe`를 실행합니다. Python과 Git은 설치할 필요가 없습니다.
5. **GUI 직접 재빌드**: `BUILD_ROS_GUI.cmd`를 실행합니다. Python 3.13도 지원합니다. 프로젝트 내부 `windows_gui\.venv`에 GUI 패키지를 설치하고 테스트 후 `windows_gui\dist`에 EXE를 생성합니다. 첫 설치에는 인터넷이 필요합니다.
6. Python/Git/SSH 중 필요한 항목이 실제로 빠졌다면 `SETUP_WINDOWS.cmd`로 해당 항목을 *선택적으로* 설치합니다.
7. `UPLOAD_GITHUB.cmd`는 Git for Windows와 GitHub 인증, `git config user.name/user.email`이 있을 때만 사용합니다.
8. Jetson은 확인된 SSH 계정/IP로 접속하세요. `nano.local`처럼 다른 사용자가 연결되는 이름을 기본으로 신뢰하지 마세요.

## 자동화/실패 점검

- 로그: `logs/CHECK_WINDOWS_*.log`, `logs/BUILD_GUI_*.log` 등.
- 자동 테스트: `set "RCBOAT_NO_PAUSE=1"` 후 `call CHECK_WINDOWS.cmd`. 성공/실패는 `%ERRORLEVEL%`로 구분됩니다.
- Python 경로 강제 선택: `set "RCBOAT_PYTHON=C:\경로\python.exe"` (명시 경로가 Python 3.11~3.13 x64여야 함).
- GitHub Actions는 Windows에서 *실제* `CHECK_WINDOWS.cmd`를 정상 경로 및 한글·공백 경로로 실행하고, Python 3.13으로 `BUILD_ROS_GUI.cmd`를 통해 EXE를 새로 빌드·실행합니다. 결과가 성공인지 GitHub Actions에서 확인하세요.
- Python이 32비트이거나 3.10 이하면 로컬 빌드가 지원되지 않아 명시적으로 실패합니다.
- ROS/Jetson 하드웨어가 실제로 안전한지는 Windows 테스트로 증명할 수 없습니다. 기본 `propulsion_allowed=false`를 유지하고 daemon과 ROS를 동시에 실행하지 마세요.
