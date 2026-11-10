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
.\windows_gui\.venv\Scripts\python.exe tests\gui_cruise_calibration.py
.\windows_gui\.venv\Scripts\python.exe tests\gui_workspace_v230.py
Remove-Item Env:QT_QPA_PLATFORM
```

실제 화면 렌더링·창 동작은 별도로 GUI를 실행해서 확인합니다. 테스트 파일명의 버전은 최초 도입 버전이며 현재 회귀 검증에도 사용합니다.

## Windows EXE 빌드

```powershell
.\BUILD_ROS_GUI.cmd
```

빌드 도구는 `%LOCALAPPDATA%\RCBoatBuild` 아래 전용 가상환경과 작업 경로를 사용합니다. 결과는 저장소의 `dist\RCBoatControl_ROS_v2.4.2.exe`입니다. `dist`와 빌드 캐시는 Git에 올리지 않습니다.

빌드 후에는 `--smoke-test`로 시작·종료를 확인할 수 있습니다.

```powershell
.\dist\RCBoatControl_ROS_v2.4.2.exe --smoke-test
```

## 버전·배포 기준

`main`은 현재 정식 소스입니다. 기존 beta·release 브랜치는 과거 작업을 보존하므로, 현재 설치는 `main`의 [VERSION](../VERSION)을 기준으로 합니다. 미완료 기능 브랜치를 정식 버전으로 안내하지 않습니다.

버전은 `MAJOR.MINOR.PATCH`를 사용합니다. 호환성이 깨지는 변경은 MAJOR, 기능 추가는 MINOR, 동작 수정은 PATCH를 올립니다. 문서·저장소 정리만으로 장치 소프트웨어 버전을 올리지 않습니다. 소프트웨어 릴리스에서는 `VERSION`, ROS package/config, GUI·gateway·노드 버전, EXE 이름과 배포 ZIP 이름을 일치시킵니다.

배포 시 소스 hash 검증과 실행 중인 backend 검증을 모두 통과해야 합니다. 정식 바이너리를 배포할 때는 해당 소스에서 빌드하고 검증한 EXE만 GitHub Release 자산으로 올립니다. 현재 남아 있는 v2.1.0 Release 자산을 v2.1.13로 바꿔 표기하지 않습니다.

## 저장소에 포함하는 파일

실행 소스, 기본 설정, 배포·분석 도구, 재현 가능한 테스트와 운용 문서를 관리합니다. 실제 항로·시험 로그·그래프·발표 자료·첨부 설명서·EXE·캐시는 로컬 작업 자료로 분리합니다. NTRIP 비밀번호와 개인 환경 파일은 커밋하지 않습니다.

## 검증 기록

2026-11-04 v2.3.1을 항로 주행·도보 테스트·풍선 추적의 단일 정식 버전으로 승격했습니다. 로컬 정식 폴더는 `RCBoatControl_v2.3.1`이며 구버전 작업 폴더와 독립된 Git 저장소를 사용합니다. 아래 별도 카메라 브랜치 관련 기록은 개발 당시의 이력입니다. 이번 정식 승격은 문서·배포 위치 정리이며 Jetson에 적용한 runtime과 GUI 동작은 변경하지 않았습니다.

v2.3.1은 `codex/vision-install-v2.3.1` 별도 폴더에서 설치 오류만 수정했습니다. 2026-11-04 로컬 검증: unittest 151개, Qt 검사 5개, compileall, 배포 staging 57개 hash, 새 EXE 빌드 및 `--smoke-test` 종료 코드 0을 확인했습니다. 새 설치 회귀 검사는 기존 가상환경 백업, 실제 subprocess의 사용자 패키지 차단, 이름별 바인딩 연결, 호스트 NumPy·TensorFlow 누출 거부, 배열 연산 실패 시 성공 표시 차단을 포함합니다.

Python 3.8·ARM64용 requirements 전체 wheel 다운로드/의존성 해석을 통과했습니다. 별도 Windows Python 3.8.10 환경에도 같은 고정 의존성(NumPy 1.23.5·ORT 1.16.3)을 설치하고 `pip check`, OpenCV 4.8 배열 연산, 실제 배포 ONNX 모델 20회 추론을 통과했습니다. Windows 검사에만 pip OpenCV wheel을 사용했으며 Jetson 설치는 기존 시스템 OpenCV/GStreamer 바인딩을 유지합니다.

같은 날 실제 Jetson Nano(aarch64/Python 3.8.10)에 연결해 기존 소스를 tar로 보존하고 v2.3.1 57개 runtime 파일을 전송·검증했습니다. 전역 상속 환경 백업, 전용 NumPy/ORT 설치, pip check, OpenCV 배열 연산, TensorFlow 미노출, GStreamer YES, 실제 모델 20회 추론, catkin 재빌드, rospy/Execute/netifaces 확인을 모두 통과했습니다. 이전 ROS 실행 실패 로그에서는 `vision_python.sh` 실행 권한 누락을 확인했으며 적용 스크립트의 chmod 후 정상 시작됐습니다. 실행 gateway v2.3.1, master online, 노드 11개, systemd active/running 및 NRestarts=0을 확인했고 PC에서 TCP 8765 직접 상태 조회도 통과했습니다.

연결된 IMX219 CSI/sensor 0의 실영상 20프레임을 처리했습니다(ORT CPU 평균 347.88 ms, p95 540.02 ms). PC에서 8766 JPEG 미리보기 수신도 확인했습니다. 카메라 로컬 유형을 CSI로 설정했고 검사 후 카메라는 껐습니다. 추적 모드/arming 명령을 보내지 않았으며 안전 상태 AUTO_SAFE/armed=false/locked와 명령 조향 6000·스로틀 6450을 확인했습니다. 출력 readback 센서 검증이나 실제 모터·주행 시험은 아닙니다. 초기 검사에는 GPS FIX 부재와 NTRIP 401 응답이 있었으나, 후속 PC 직접 조회에서 GPS FIX 확보·NTRIP connected=true·last_error 빈값으로 회복된 것을 확인했습니다. NTRIP 설정이나 비밀번호는 변경하지 않았습니다. 대회 풍선 검출·수상 접근·파열 성공률은 검증하지 않았습니다.

v2.3.0 카메라 버전은 `codex/balloon-ui-v2.3.0` 별도 폴더에서 기존 v2.1.15를 보존해 작성했습니다. 2026-11-03 로컬 검증: unittest 139개, Qt 점검 5개, 소스 compileall, 배포 staging(55개 hash) 통과. 기존 34개 GUI 버튼 속성을 유지하고, 1024/1280/1440 폭에서 모든 화면·상세 영역의 가로 overflow와 항로 상단 실행 버튼을 검사했습니다. 카메라 공개 설정의 편집/ACK, 한 번 누른 시작의 감지 대기/단일 arming, 정지 취소, E-STOP, 카메라·GPS·SSH 유예/고장, 이전 세션 명령 차단, 좌우 자동 조향·위치 추정·지나침 후 재접근을 가상 입력으로 검사했습니다.

YOLOv8n은 Open Images 실제 풍선 원본 2,189장(학습 1,746 / 검증 199 / 시험 244), box 11,328개로 RTX 4060 Laptop에서 70 epoch 학습했습니다. 독립 시험 mAP50 약 0.653, precision 약 0.739, recall 약 0.559입니다. 실제 ONNX 후처리(IoU 0.5, confidence 0.35)의 큰 box(화면 면적 1% 이상) recall은 약 0.822이며 전체 box recall은 약 0.586입니다. 이는 공개 이미지 시험이며 대회 풍선 성공률이 아닙니다. PC CPU 2-thread ONNX 추론 평균 약 16.2 ms, p95 약 18.8 ms입니다. Jetson 수치로 해석하지 않습니다. ONNX hash·색상 필터·NMS·좌표 복원과 OpenCV fallback 로딩도 확인했습니다. 상세 결과는 models의 training_report.json/runtime_evaluation.json에 있습니다.

v2.3.0 최초 검증에는 Jetson 실제 설치·CSI/USB 카메라 드라이버·TensorRT 엔진·실물 조향·수상 접근/파열 시험이 없었습니다. v2.3.1의 실제 장치 검사 범위는 위 기록을 따릅니다. 카메라 시야각·좌우 조향·E-STOP·수상 주행은 여전히 현장 검증이 필요합니다. 기존 PC 폴더는 보존했고 GitHub main 업로드는 수행하지 않았습니다.

v2.1.15는 최신 origin/main `da08f28`을 확인하고 `codex/rc-forward-7397` 브랜치에서 기존 로컬 작업을 보존해 수정합니다. 최대 전진 7397을 공통 출력 검사와 YAML에 반영하며, 조향·중립·후진 보정과 기존 약 166.7 PWM/s 상승률은 유지합니다. RC 매핑, 원격·항법·도보·actuator 경계값 7397/7398, 비정수 명령 거부, 로거 출력 확인, GUI 끝값 적용을 검증합니다. GPS·RTK·NTRIP의 동작 로직·Arduino·ESC 캘리브레이션은 변경하지 않습니다.

변경 파일은 `control_config.py`(상한·공통 범위 검사·끝값 검증), `boat.yaml`(실제 전진 상한), `safety_supervisor_node.py`(수동·원격·항법·도보 범위), `actuator_node.py`(최종 범위), `navigation_node.py`·`path_tracking.py`(출력 보정 전달·상한 기본값), `ground_test_logger_node.py`(출력 확인 범위), GUI `main_window.py`·`ssh_worker.py`·`mock_worker.py`(7397 입력·전달·원격 범위·잘못된 속도 % 제거)입니다. 관련 calibration/ramp/Qt 테스트와 버전·빌드·설치·운용 문서도 갱신했습니다. GPS·NTRIP 노드 파일은 릴리스 버전 문자열만 갱신했습니다.

2026-11-03 검증: unittest 120개, Qt 점검 4개, compileall, 배포 staging(v2.1.15·42개 hash) 모두 통과했습니다. PyInstaller EXE를 빌드하고 Windows에서 `--smoke-test` 종료 코드 0과 화면 표시를 확인했습니다. Jetson 실제 배포·하드웨어 실측·ESC 캘리브레이션·커밋·GitHub 업로드는 수행하지 않았습니다.

v2.1.14는 최신 origin/main `da08f28`을 확인하고 이전 로컬 수정을 보존한 `codex/rc-input-navigation-ramp` 브랜치에서 작업합니다. RC 끝점을 사용자 지정 정수로 맞추고, 자동항법 상승 제한을 공통 순수 계산 함수와 기존 navigation 노드에 추가했습니다. 방향 오차 감속 함수와 actuator 출력 범위는 이번 램프 추가에서 변경하지 않았습니다. `test_navigation_ramp.py`는 가상 monotonic 시각으로 1.5초 도달·목표 상하향·회전 감속/재가속·재시작·소루트 전환·이전 주행 명령 차단·안전정지를 검사합니다. 소프트웨어 검증이며 실물 속도 검증은 아닙니다.

2026-11-03 검증: unittest 117개, Qt 점검 4개, compileall, 배포 staging(v2.1.14·42개 hash) 모두 통과했습니다. v2.1.14 EXE를 PyInstaller로 빌드하고 Windows 기본 화면 환경에서 `--smoke-test` 종료 코드 0 및 새 램프 카드·한글 표시를 확인했습니다. Jetson 실제 배포·실물 PWM/모터 동작·GitHub 업로드는 수행하지 않았습니다.

v2.1.13은 RC 입력 보정·순항 PWM 적용 확인·항로 지연·HDOP 저장 수정입니다. `tests/test_control_calibration.py`와 `tests/test_navigation_delay_settings.py`는 실제 변환·서비스·안전·actuator 분기 로직을 ROS/장치 없이 검사합니다. `gui_cruise_calibration.py`는 offscreen Qt와 실제 worker→gateway→navigation 코드로 적용/거부/오래된 응답/HDOP 편집 유지·저장을 검증합니다. 검증은 소프트웨어 시뮬레이션이며 실물 PWM·방향·항해 속도 검증이 아닙니다. 이번 작업에서 배포·장치 재시작·실제 모터 시험은 수행하지 않습니다.

2026-11-03 로컬 검증 결과: unittest 106개 통과, 위 Qt 점검 스크립트 4개 통과, 소스 compileall 통과, 배포 staging 점검 통과(v2.1.13·42개 소스 hash). PyInstaller로 `dist/RCBoatControl_ROS_v2.1.13.exe`를 빌드했으며 offscreen 및 Windows 기본 화면 환경에서 `--smoke-test` 종료 코드 0을 확인했습니다. Windows 화면 캡처에서 한글·버전·순항 PWM 적용 상태 표시를 확인했습니다. 네트워크 연결·실물 출력을 검증한 결과는 아닙니다.

다음은 각 버전 배포 당시의 기록입니다. 소프트웨어 테스트 통과와 실제 Jetson·수상 시험을 구분해서 읽습니다.

- [v2.1.12 — Ground Test GPS 유예](validation/v2.1.12.md)
- [v2.1.11 — 기록 유지 및 heartbeat](validation/v2.1.11.md)
- [v2.1.10 — GUI 수명 및 부팅 점검](validation/v2.1.10.md)

v2.3.3는 공통 상승률을 120 PWM/s로 낮춥니다. 다른 기존 제어 동작은 그대로 유지하며 별도 `mobile_android` 클라이언트를 추가했습니다. 모바일은 기존 TCP gateway를 사용하므로 ROS 토픽·서비스와 항법·추적 알고리즘을 바꾸지 않습니다. Android 빌드·검증은 [모바일 안내](mobile.md)를 따릅니다.


v2.4.0은 네이티브 1080p 후보 영역의 단일 추론과 작은 대상 연속 관측, 200m 위치 추정 상한, 추가 학습 모델을 적용합니다. 카메라 프로필은 한 번만 백업·변경하며 원거리 끄기/사용자 해상도를 이후 덮어쓰지 않습니다. 실제 100m 성능은 별도 거리·지름·화각 자료로 검증합니다.

2026-11-08 v2.4.0 검증: Python 164개, Qt 5개, 4개 모바일 화면 크기(새 해상도/원거리 설정 전송·편집 유지 포함), Android 단위 9개·lint·APK 서명, EXE smoke 종료 0을 확인했습니다. Python 3.8.10/NumPy 1.23.5/ORT 1.16.3/OpenCV 4.8.0 조합에서 새 ONNX의 실제 1080p 영역 추론을 PC에서 실행했습니다. 배포 staging은 61개 runtime hash를 검증합니다. Jetson·실물 카메라·실측 100m·수상 주행은 이번 버전에서 미검증입니다.

v2.4.1은 모바일 연결 건강 상태와 영상 전송 수정입니다. ConnectionHealthTest는 일시 timeout/지속 실패/닫힌 세션/지연 회복을 가상 단조시각으로 검증하고 PreviewStoreTest는 최신 한 장·중복 프레임의 수신 시각 보존·잘못된 JPEG 제한을 검사합니다. 실제 HTTP preview 회귀는 인증·ETag 304·새 프레임·오래된 프레임 거부를 확인합니다. 모바일 화면 검사는 SSH/ROS 지연과 신선한 영상의 독립성, 숨긴 GPS DOM 유지, 영상 stale의 LIVE 해제까지 포함합니다. 실제 8m 풍선 사진은 별도 거리 확인 자료가 있어야 평가합니다.

2026-11-10 v2.4.1 로컬 검증: Python 164개, Qt 화면 회귀, Android 단위 15개·lint·release 빌드, 모바일 화면 4종, EXE smoke 종료 0, 배포 staging 61개 hash를 통과했습니다. APK를 실제 연결 휴대폰에 업데이트 설치하고 v2.4.1 화면을 확인했습니다. 기존 YOLO 모델 hash와 PWM/항법/안전 정책은 그대로입니다.

v2.4.2: `tests/test_control_snapshot.py`는 실제 ROS node 메서드와 가상 단조시각을 사용해 콜백 도착 순서를 강제로 겹칩니다. 이전 actuator에서는 새 명령이 판정 시각보다 앞서 보이며 `6000/6450/TIMEOUT`이 재현됐습니다. 수정본은 supervisor의 판단·입력 교체, actuator의 명령·수신 시각·시각 조회를 같은 잠금으로 처리합니다. 풍선과 MANUAL 출력 유지, RC/link/GPS/vision 갱신 경합, 실제 stale/future 거부·잠금·범위 초과 중립, 실제 actuator 유실 시 수동 전환과 진단 로그를 검사합니다. 하드웨어 I/O를 열지 않으며 물리적 서보 소음·전원·링크 검증을 대신하지 않습니다.

2026-11-10 v2.4.2 검증: Python 172개(신규 경합 재현 8개 포함), Python 3.8 소스 컴파일, Qt workspace, 모바일 화면 4종, Android 단위 15개·lint·서명 release 빌드, EXE smoke 종료 0, staging 61개 hash를 확인했습니다. SM-S938N에 APK를 업데이트 설치하고 패키지 versionName 2.4.2/versionCode 20402를 확인했습니다. Jetson에 백업 후 설치하여 소스 61개 hash·실행 gateway 2.4.2·service active/NRestarts=0을 확인했습니다. E-STOP/6000·6450 잠금 상태 50회 조회에서 command age 0.000440~0.069476 s, actuator age 0.019755~0.059332 s였으며 모두 LOCKED였습니다. 기존 ntrip.env와 routes.json hash는 그대로입니다. 실제 비중립 출력·수상 추적·서보 소음 재현 시험은 하지 않았습니다.
