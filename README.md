# RC-BOAT

ROS Noetic 기반 RC 보트 자율운항 및 Windows 관제 시스템입니다. Jetson에서 GNSS/RTK 수신, 항로 선택, 조향·스로틀 제어와 시험 기록을 처리하고, Windows GUI에서 항로 편집과 운항 상태 확인, 시험 로그 다운로드를 수행합니다.

최신 ROS 정식 버전은 **v2.4.1**이며 `main`에서 관리합니다. 항로 주행·도보 테스트·풍선 추적을 하나의 Windows GUI와 ROS Noetic backend로 제공합니다. ROS 계열에서 풍선 기능이 없는 별도 최신 버전은 운영하지 않습니다. Windows GUI와 Jetson backend는 같은 버전을 사용합니다.

ROS 이전 **v1.6.0은 별도 레거시로 유지**합니다. 원본은 [release/1.6.0 브랜치](https://github.com/smini131-maker/RC-BOAT/tree/release/1.6.0), 로컬 보존 폴더는 `RCBoatControl_v1.6.0`입니다. ROS 최신 폴더는 `RCBoatControl_v2.4.1`이며 아래 배포 명령은 ROS 버전에만 적용합니다.

v2.4.1은 작은 핑크 풍선의 원거리 감지를 개선합니다. 1080p 원본에서 후보 영역을 찾아 확대 입력하고, 추가 학습한 경량 모델을 사용합니다. 프레임당 신경망 추론은 한 번으로 제한하며, 이동·정지·GPS·RC·E-STOP 제어는 유지합니다. 목표 거리 100m는 풍선 크기·실제 화각·초점·원본 픽셀 수에 따라 별도 검증해야 하며, 현재 실측 100m 성능을 인증한 버전은 아닙니다.

기존 120 PWM/s 상승률, 시작 6650·상한 7397, Windows 지도 일반 휠 확대·축소, 모바일 조이스틱·수동 전환을 유지합니다. 아직 Jetson에 적용하지 않았다면 [카메라·원거리 추적 안내](docs/vision.md)의 처음 설치 순서부터 진행합니다.

Android 휴대폰·태블릿용 `dist/RCBoatMobile_v2.4.1.apk`를 추가했습니다. 모바일에서 기존 ROS gateway로 운항·항로·풍선 추적·GPS/RTK·도보 테스트·로그 다운로드를 이용합니다. 모든 탭의 수동 전환과 모드 변경, 2축 원격 조이스틱, RTK 로컬 프로필 보존을 지원합니다. 기존 항법·RC·안전 제어 기능을 유지합니다. [모바일 설치·사용·빌드](docs/mobile.md)를 참고하세요.

v2.3.1은 카메라 버전의 설치 오류를 수정합니다. 기존 TensorFlow/사용자 NumPy를 상속하던 환경을 백업하고 전용 환경으로 분리하며, 실제 ONNX 추론과 ROS 의존성 확인 후에만 설치 성공을 표시합니다. v2.3.0의 지도 중심 GUI·풍선 연속 추적·RC 보정·7397 출력 상한·안전 제어·도보 테스트는 유지합니다. [카메라 버전 사용·배포](docs/vision.md)에 실행 명령과 실제 검증 범위를 정리했습니다.

v2.4.1은 모바일 SSH 응답 확인과 지연/끊김 표시, 독립적인 영상 수신, 최신 JPEG 한 장 유지와 중복 전송 생략을 적용합니다. 기존 가중치와 항법·출력·안전 정책은 유지합니다. 23cm 풍선은 1920폭/화각 62.2°를 가정하면 8m 약 46px, 100m 약 3.7px입니다. 이 계산은 실측 성능이 아니며 현재 카메라의 정확한 화각을 보장하지 않습니다.

## 주요 기능

- **핑크 풍선**: USB/CSI 카메라, 신경망 풍선 검출+핑크 확인, 실시간 연속 추적, 선택적 저대역폭 미리보기.

- **항로 관리**: waypoint 항로를 직접 추가·편집하고, 여러 항로를 하나의 Multi-Path로 묶습니다.
- **최근접 항로 선택**: 유효한 GPS 갱신마다 그룹 안에서 보트와 경로선의 거리가 가장 가까운 항로를 선택합니다. 항로 전환에 2 m 임계값을 사용하지 않습니다.
- **관제 및 수동 전환**: GPS/RTK, ROS, SSH, 출력 상태를 개별 표시하고 자동·수동 제어와 E-STOP을 관리합니다.
- **시험 기록**: 위치·속도·항로 판단·PWM 명령·수동 개입을 CSV/JSONL로 저장하고, 기준 항로와 설정을 ZIP에 함께 보관합니다.
- **오프라인 분석**: MATLAB 그래프 생성과 QGIS용 좌표 데이터 내보내기를 지원합니다.

## 시스템 구성

```text
Windows GUI ── TCP 8765 ── Jetson / ROS Noetic
    │                         ├─ GNSS + NTRIP/RTK
    └─ SSH: 배포·터미널        ├─ 항로 선택 → 항법 → 안전 제어
                              ├─ RC 수동 입력 → PCA9685 → 서보·ESC
                              └─ 시험 로거 → CSV / JSONL / ZIP
```

| 구성 | 사용 환경 |
|---|---|
| 보트 backend | Jetson, Ubuntu 20.04, ROS Noetic, Python 3 |
| 관제 GUI | Windows, Python 3.11~3.13, PySide6 |
| 입출력 | u-blox GNSS, Arduino RC 입력, PCA9685 조향·스로틀 출력 |
| 분석 | MATLAB, QGIS용 CSV |

## 시작하기

```powershell
Set-Location -LiteralPath "C:\Users\smini\OneDrive\바탕 화면\RCBoatControl_Complete_2026-09-25_UPDATED\RCBoatControl_v2.4.1"
```

Windows GUI를 소스에서 실행하려면:

```powershell
py -3 -m venv windows_gui\.venv
.\windows_gui\.venv\Scripts\python.exe -m pip install -r windows_gui\requirements.txt
.\windows_gui\.venv\Scripts\python.exe windows_gui\app.py
```

Jetson의 ROS Noetic 설치와 장치 설정을 확인한 뒤 배포합니다.

```powershell
.\DEPLOY_ROS.cmd -Destination "jetson@10.123.65.215"
ssh jetson@10.123.65.215
```

이어서 Jetson SSH 안에서 실행합니다.

```bash
cd /home/jetson/rcboat_ros_ws
bash deployment/jetson/install_vision_dependencies.sh
bash deployment/jetson/install_jetson_ros.sh
```

각 명령이 오류 없이 끝나야 다음 명령을 실행합니다. 완료 조건은 `VISION INSTALL VERIFIED`와 `RUNNING GATEWAY VERIFIED: v2.4.1`입니다. `DEPLOY_ROS.cmd`는 소스 전송만 수행합니다. 자세한 환경 준비와 설정은 [설치·실행 안내](docs/setup.md)를 따릅니다.

## 문서

| 문서 | 내용 |
|---|---|
| [카메라 버전 안내](docs/vision.md) | 새 화면, 모델, 카메라·풍선 추적, 정확한 배포 명령 |
| [설치·실행](docs/setup.md) | Windows GUI, Jetson 배포, 장치·NTRIP 설정 |
| [운항·시험](docs/operation.md) | 항로 편집, 운항 시작, Ground Test, 수동 전환·GPS 유예 |
| [로그·MATLAB 분석](docs/data-analysis.md) | 저장 파일, 품질 필터, 헤딩·조향각 해석 |
| [아키텍처](docs/architecture.md) | 노드 구성, 명령 흐름과 제어 책임 |
| [ROS·gateway 인터페이스](docs/interfaces.md) | topics, services, TCP 명령 |
| [개발·검증](docs/development.md) | 로컬 테스트, EXE 빌드, 버전·배포 기준 |
| [문제 해결](docs/troubleshooting.md) | 연결, GUI 종료, 부팅 및 진단 로그 |

## 저장소 구조

```text
catkin_ws/src/rcboat_ros/  ROS 노드·항법·설정·메시지
windows_gui/             Windows 관제 앱
deployment/jetson/       Jetson 설치·진단·검증 도구
systemd/                 ROS 자동 시작 서비스
matlab/                  시험 로그 분석 함수
tools/windows/           Windows 빌드·배포 실행 도구
tests/                   제어·통신·배포 회귀 테스트
docs/                    설치·운용·개발 문서
```

루트의 `.cmd` 파일은 Windows용 실행 바로가기입니다. 실제 시험 로그, 개인 항로, NTRIP 자격정보와 생성된 EXE·그래프는 소스에 포함하지 않습니다.

## 버전 및 시험 범위

정식 소스는 `main`의 [VERSION](VERSION), 실행 파일과 전체 ZIP은 [v2.4.1 릴리스](https://github.com/smini131-maker/RC-BOAT/releases/tag/v2.4.1)를 기준으로 사용합니다. 이전 버전은 Git 이력과 과거 릴리스에 남아 있으며 최신 설치 대상으로 안내하지 않습니다. 로컬 실행 폴더는 `RCBoatControl_v2.4.1`, 실행 파일은 `dist/RCBoatControl_ROS_v2.4.1.exe`입니다.

기본 제어는 `HEADING` 모드와 고정 순항 PWM을 사용하며, 속도 피드백 제어는 기본적으로 꺼져 있습니다. 로그의 GPS 진행 방향은 선체 자세 센서 값과 다르고, `actual_*_pwm`은 장치에 보낸 명령 확인값입니다. 실물 출력 시험은 프로펠러를 제거한 상태에서 중립·RC 수동 전환·E-STOP을 먼저 확인합니다. 세부 조건과 한계는 [운항·시험](docs/operation.md)과 [로그 해석](docs/data-analysis.md)에 정리했습니다.
