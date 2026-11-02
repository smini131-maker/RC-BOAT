# RC-BOAT

ROS Noetic 기반 RC 보트 자율운항 및 Windows 관제 시스템입니다. Jetson에서 GNSS/RTK 수신, 항로 선택, 조향·스로틀 제어와 시험 기록을 처리하고, Windows GUI에서 항로 편집과 운항 상태 확인, 시험 로그 다운로드를 수행합니다.

현재 `main`의 소프트웨어 버전은 **v2.1.12**입니다. Windows GUI와 Jetson backend는 같은 버전을 사용합니다.

## 주요 기능

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
git clone https://github.com/smini131-maker/RC-BOAT.git
cd RC-BOAT
```

Windows GUI를 소스에서 실행하려면:

```powershell
py -3 -m venv windows_gui\.venv
.\windows_gui\.venv\Scripts\python.exe -m pip install -r windows_gui\requirements.txt
.\windows_gui\.venv\Scripts\python.exe windows_gui\app.py
```

Jetson의 ROS Noetic 설치와 장치 설정을 확인한 뒤 배포합니다.

```powershell
.\INSTALL_ROS.cmd -Destination "jetson@JETSON_IP"
```

설치 결과에서 `RUNNING GATEWAY VERIFIED: v2.1.12`를 확인합니다. `DEPLOY_ROS.cmd`는 소스 전송만 수행하며, 실행 중인 backend 갱신은 `INSTALL_ROS.cmd`로 완료합니다. 자세한 환경 준비와 설정은 [설치·실행 안내](docs/setup.md)를 따릅니다.

## 문서

| 문서 | 내용 |
|---|---|
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

현재 소스는 `main`과 [VERSION](VERSION)을 기준으로 확인합니다. GitHub Releases에 남아 있는 **v2.1.0 바이너리는 이전 버전**입니다. v2.1.12 GUI는 현재 소스에서 빌드합니다. 이전 버전의 소스와 수정 내역은 Git 이력과 기존 릴리스에서 확인할 수 있습니다.

기본 제어는 `HEADING` 모드와 고정 순항 PWM을 사용하며, 속도 피드백 제어는 기본적으로 꺼져 있습니다. 로그의 GPS 진행 방향은 선체 자세 센서 값과 다르고, `actual_*_pwm`은 장치에 보낸 명령 확인값입니다. 실물 출력 시험은 프로펠러를 제거한 상태에서 중립·RC 수동 전환·E-STOP을 먼저 확인합니다. 세부 조건과 한계는 [운항·시험](docs/operation.md)과 [로그 해석](docs/data-analysis.md)에 정리했습니다.
