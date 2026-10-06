# RCBoat Multi-Path R12 + Week6 GPS/RTK 패치

이 버전은 R12 항로 저장 기능을 유지하면서 GPS Health, 상세 CSV 로그, NTRIP/RTCM, RTK 상태, 선택형 RTK 항법 Gate를 추가합니다. 안전 PWM은 조향 6000 / 스로틀 6450 그대로입니다.

이 패치는 현재 동작 중인 기능을 유지하면서 다음 기능을 추가·복원합니다.

- 선택한 주행 항로를 `/home/jetson/rcboat/routes.json`에 원자 저장
- daemon 재시작·항로 다시 읽기 후 저장된 선택 항로 복원
- GPS 기록 항로 저장 시 해당 항로를 선택 항로로 함께 기록
- GUI에서 `routes.json`과 `boat_config.json` 실제 저장 경로 표시
- Multi-Path 기준 저장의 요청 중·성공·실패 상태 확인

- Multi-Path ON/OFF
- 공통 출발·도착 허용 거리: 기본 0.75 m, 0.10~1.00 m
- 경로 이탈 거리, 이탈 지속시간, 다른 경로 우위, 전환 재대기시간 설정
- 동일 출발·도착 그룹에서 시작 위치와 가장 가까운 경로 자동 선택
- 운항 중 조건 충족 시 가장 가까운 경로로 전환하고 가장 가까운 구간의 다음 waypoint로 합류
- GPS 기록 항로 이름, 최소 거리, 최소 시간, 도착 반경 설정
- 기존 운항 모드 수정, AUTO 속도 설정, GPS 기록, HIL, 원격조종, SSH 터미널 유지
- MANUAL 원래 실측 매핑 고정: 1106→7000, 1500→6450, 1786→5800

## 중요

Jetson 패치는 `hardware.py`와 `pca_direct.py`를 포함하지도, 덮어쓰지도 않습니다. 현재 복구된 Direct-I2C 드라이버가 확인되지 않으면 설치가 중단됩니다. `Jetson.GPIO`, Blinka, `import board`를 새로 설치하지 마십시오.

## Jetson 적용

압축을 Jetson의 임의 폴더에 풀고 다음을 실행합니다.

```bash
cd jetson_patch
chmod +x install_patch.sh
./install_patch.sh
```

적용 후 GUI의 `GPS · RTK` 탭에서 GPS Health와 NTRIP 상태를 확인합니다. 실제 NTRIP 발급 정보가 없다면 기본 비활성 상태로 두어도 기존 일반 GPS 항법과 나머지 모드는 정상 동작합니다.

GPS 데이터 로그는 `/home/jetson/rcboat/logs/gps/`에 저장되며 기존 `routes.json` 항로 기록과 별도입니다. NTRIP 실제 비밀번호는 `/home/jetson/rcboat/.ntrip.env`에만 저장되고 GitHub에는 올라가지 않습니다.

설치기는 서비스 정지, 대상 4개 파일 백업, Direct-I2C 확인, 문법 검사, 파일 교체, 서비스 재시작과 상태 확인을 수행합니다. 기존 `routes.json`, `boat_config.json`, `hardware.py`, `pca_direct.py`는 덮지 않습니다.

## Windows GUI 재빌드

Windows 10/11 x64에서 압축 최상위의 `BUILD_WINDOWS_EXE.bat`를 실행하십시오. 생성 파일은 `windows_gui_source/windows_app/dist/RCBoatControl.exe`입니다.

Linux 환경에서는 Windows PE 실행 파일을 안전하게 재생성할 수 없어, 이전 EXE를 새 버전인 것처럼 포함하지 않았습니다. 소스와 Windows 빌드 스크립트는 포함되어 있습니다.

## 수동 쓰로틀 확인

MANUAL 선택 후 화면 상태가 `중립 입력 대기`이면 스로틀을 1500±30 us로 0.3초 유지해야 `수동 조종 중`이 됩니다. 그 뒤 당겼을 때 화면에서 아래 값이 확인되어야 합니다.

- RC 입력: 약 1786 us
- ESC CH6 출력: 5800

RC 입력은 변하지만 CH6가 6450이면 모드/중립 활성화 문제입니다. CH6가 5800까지 변하는데 모터가 돌지 않으면 코드 매핑이 아니라 ESC 전원·암 상태·배선·캘리브레이션을 확인해야 합니다.

## 검증

- Python 문법 검사 통과
- 백엔드, GUI, Mock 통신 회귀 테스트 55개 통과
- Direct-I2C 하드웨어 파일 비포함 확인
