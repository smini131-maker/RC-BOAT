# 개발·검증

[프로젝트 소개](../README.md) · [아키텍처](architecture.md) · [설치](setup.md)

## 코드 위치

| 경로 | 내용 |
|---|---|
| `catkin_ws/src/rcboat_ros/src/rcboat_ros/` | 항로 선택·좌표 변환·GNSS/RTCM·출력 관련 모듈 |
| `catkin_ws/src/rcboat_ros/nodes/` | ROS 노드와 상태·명령 연결 |
| `windows_gui/rcboat_gui/` | GUI·gateway/SSH worker·상태 표시 |
| `deployment/jetson/` | 설치·manifest·장치·부팅 진단 |
| `tests/` | unittest 및 Qt·배포 통합 점검 |

## 기본 회귀 테스트

저장소 루트에서 실행합니다. 기본 unittest는 ROS와 물리 장치 없이 주요 로직을 검증하며 표준 라이브러리로 실행할 수 있습니다.

Windows PowerShell:

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m compileall -q catkin_ws windows_gui
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\check_deploy_staging.ps1
```

Linux:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q catkin_ws windows_gui
```

`check_deploy_staging.ps1`은 SSH/SCP를 가짜 함수로 대체해 전송 인수와 소스 SHA-256을 확인합니다. 실제 Jetson 연결이나 서비스 변경은 수행하지 않습니다. GitHub Actions의 [Tests](../.github/workflows/ci.yml)는 Windows·Linux의 Python 3.10에서 unittest와 소스 컴파일을 실행합니다.

## GUI 통합 점검

GUI 의존성을 설치한 가상환경에서 실행합니다. 네트워크는 각 점검의 mock을 사용합니다. 아래 명령은 저장소 루트 기준입니다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\windows_gui\.venv\Scripts\python.exe tests\gui_lifecycle_v2110.py
.\windows_gui\.venv\Scripts\python.exe tests\gui_smoke_v2110.py
.\windows_gui\.venv\Scripts\python.exe tests\gui_ground_v2111.py
Remove-Item Env:QT_QPA_PLATFORM
```

실제 화면 렌더링·창 동작은 별도로 GUI를 실행해서 확인합니다. 테스트 파일명의 버전은 최초 도입 버전이며 현재 회귀 검증에도 사용합니다.

## Windows EXE 빌드

```powershell
.\BUILD_ROS_GUI.cmd
```

빌드 도구는 `%LOCALAPPDATA%\RCBoatBuild` 아래 전용 가상환경과 작업 경로를 사용합니다. 결과는 저장소의 `dist\RCBoatControl_ROS_v2.1.12.exe`입니다. `dist`와 빌드 캐시는 Git에 올리지 않습니다.

빌드 후에는 `--smoke-test`로 시작·종료를 확인할 수 있습니다.

```powershell
.\dist\RCBoatControl_ROS_v2.1.12.exe --smoke-test
```

## 버전·배포 기준

`main`은 현재 정식 소스입니다. 기존 beta·release 브랜치는 과거 작업을 보존하므로, 현재 설치는 `main`의 [VERSION](../VERSION)을 기준으로 합니다. 미완료 기능 브랜치를 정식 버전으로 안내하지 않습니다.

버전은 `MAJOR.MINOR.PATCH`를 사용합니다. 호환성이 깨지는 변경은 MAJOR, 기능 추가는 MINOR, 동작 수정은 PATCH를 올립니다. 문서·저장소 정리만으로 장치 소프트웨어 버전을 올리지 않습니다. 소프트웨어 릴리스에서는 `VERSION`, ROS package/config, GUI·gateway·노드 버전, EXE 이름과 배포 ZIP 이름을 일치시킵니다.

배포 시 소스 hash 검증과 실행 중인 backend 검증을 모두 통과해야 합니다. 정식 바이너리를 배포할 때는 해당 소스에서 빌드하고 검증한 EXE만 GitHub Release 자산으로 올립니다. 현재 남아 있는 v2.1.0 Release 자산을 v2.1.12로 바꿔 표기하지 않습니다.

## 저장소에 포함하는 파일

실행 소스, 기본 설정, 배포·분석 도구, 재현 가능한 테스트와 운용 문서를 관리합니다. 실제 항로·시험 로그·그래프·발표 자료·첨부 설명서·EXE·캐시는 로컬 작업 자료로 분리합니다. NTRIP 비밀번호와 개인 환경 파일은 커밋하지 않습니다.

## 검증 기록

다음은 각 버전 배포 당시의 기록입니다. 소프트웨어 테스트 통과와 실제 Jetson·수상 시험을 구분해서 읽습니다.

- [v2.1.12 — Ground Test GPS 유예](validation/v2.1.12.md)
- [v2.1.11 — 기록 유지 및 heartbeat](validation/v2.1.11.md)
- [v2.1.10 — GUI 수명 및 부팅 점검](validation/v2.1.10.md)
