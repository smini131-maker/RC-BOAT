# RCBoat Multi-Path R11 기능 복원 패치

이 패치는 현재 동작 중인 기능을 유지하면서 다음 기능을 추가·복원합니다.

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
- 백엔드, GUI, Mock 통신 회귀 테스트 53개 통과
- Direct-I2C 하드웨어 파일 비포함 확인
