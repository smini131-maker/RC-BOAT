# RC-BOAT v1.6.0

Jetson Nano 기반 RC 보트를 Windows GUI에서 SSH로 연결해 수동/자동/GPS 항법/HIL/원격 제어하고, GPS·RTK·NTRIP·Multi-Path 상태를 모니터링하는 프로젝트입니다.

현재 공식 버전 체계는 **Semantic Versioning `MAJOR.MINOR.PATCH`**입니다. 과거 `R11`, `R12`, `R12.1`과 현장 복구용 `R15.1` 표기는 `CHANGELOG.md`에서 SemVer 계보에 대응하는 레거시 별칭으로만 보존합니다. 과거 commit SHA는 복구 기준을 깨지 않기 위해 재작성하지 않습니다.

## 현재 버전

- Version: **1.6.0**
- Windows GUI 제목과 Jetson telemetry에 버전 표시
- 기준 파일: `VERSION`
- 버전 이력: `CHANGELOG.md`

버전 규칙:

- **MAJOR**: 프로토콜/아키텍처 호환성을 깨는 변경
- **MINOR**: 하위 호환 기능 추가
- **PATCH**: 하위 호환 버그·안전·UI 수정

## 보존된 안전 기준

- Steering CH0: LOW 4900 / CENTER **6000** / HIGH 7300
- ESC CH6: REVERSE 5800 / STOP **6450** / FORWARD 7000
- 모든 오류·통신 실패·비상정지: **Steering 6000 / Throttle 6450**
- Arduino와 GPS는 `/dev/serial/by-id/` 고정 경로 사용
- PCA9685는 검증된 `DirectLinuxPCA9685` 직접 I2C 방식 유지
- Blinka / `Jetson.GPIO` 방식으로 변경하지 않음
- 설치 패치는 기존 `routes.json`, `boat_config.json`, `.ntrip.env`, `hardware.py`, `pca_direct.py`를 보존

## GPS / RTK

- GGA/RMC/GSA/GSV NMEA + UBX NAV-PVT 파서
- UBX NAV-PVT를 1초 간격으로 poll하여 hAcc와 RTK 상태 수집
- NAV-PVT / 전체 UBX / NMEA 수신 카운터 표시
- UTC, PDOP, VDOP, 평균 C/N0, hAcc, fixType, carrSoln, RTK 상태 telemetry
- GPS 연결·FIX·좌표 freshness·HDOP를 실제 NAVIGATION hard gate로 사용
- C/N0/PDOP/VDOP/hAcc/위성 수는 품질 진단에 사용하며 단독으로 추진을 반복 차단하지 않음
- RTK/NTRIP 손실 시 일반 GPS 조건이 정상이면 fallback 운항 가능
- GPS 자체가 끊기거나 stale/no-fix/HDOP 불량이면 6000/6450 안전 출력

현재 평균 C/N0 표시 기준:

- **GOOD**: ≥30 dB-Hz
- **WARNING**: 25~29.9 dB-Hz
- **BAD**: <25 dB-Hz

## 자율 항법

- 실물 러더 링크 방향에 맞춰 NAVIGATION 조향만 반전
- MANUAL / REMOTE 조향 매핑은 변경하지 않음
- 방향 오차가 작으면 설정 cruise 속도를 유지
- 방향 오차 35~100°에서는 부드럽게 감속
- 100° 이상에서는 최소 cruise delta의 65%로 계속 전진하며 조향
- 약 150° 이상으로 처음 진입할 때만 0.4초 일시 정지 후 저속 복귀
- 같은 큰 오차 상태에서 정지/출발 반복을 하지 않음

## GPS 항로 기록 포맷

v1.6.0부터 새로 기록한 각 waypoint에 다음 값이 함께 저장됩니다.

```json
{
  "timestamp": "2026-10-13T19:20:00.123+09:00",
  "lat": 35.00000000,
  "lon": 129.00000000,
  "heading_deg": 270.5
}
```

- `timestamp`: timezone offset이 포함된 실제 기록 시각
- `lat`: 위도
- `lon`: 경도
- `heading_deg`: GPS course/heading, 0~360°. 진행방향이 아직 없으면 `null`
- 기존 lat/lon-only `routes.json`도 그대로 읽음
- 새 항로를 저장하면 route-level `recorded_at_start`, `recorded_at_end`, `saved_at`도 기록
- Windows GUI의 JSON/CSV/GPX 내보내기에서도 시간·좌표·헤딩을 보존

CSV 형식:

```text
index,timestamp,latitude,longitude,heading_deg
1,2026-10-13T19:20:00.123+09:00,35.00000000,129.00000000,270.50
```

## Multi-Path

별도 group id를 저장하는 구조가 아닙니다. 선택 기준 항로와 다른 항로의 **시작점과 도착점이 모두 `endpoint_tolerance_m` 안에 있으면 같은 그룹**으로 자동 판단합니다.

Windows GUI에는 다음을 표시합니다.

- 기준 경로
- 현재 활성 경로
- 같은 Multi-Path 그룹의 경로 이름
- 각 경로의 시작점/도착점 간격
- 대체 후보와 이탈 지속시간

## Windows → Jetson 배포

Windows GUI를 종료하고 **프로펠러를 제거하거나 ESC 추진 전원을 분리한 상태**에서 배포합니다.

v1.6.0 배포 도구는 긴 Downloads 하위 경로에서 PowerShell `Expand-Archive`가 `.github` 처리 중 실패하던 문제를 피하기 위해:

1. `%TEMP%\RCBoatDeploy_...`의 짧은 작업 경로 사용
2. GitHub ZIP 다운로드
3. Windows 기본 `tar.exe`로 압축 해제
4. 필요한 `jetson_patch`만 SCP
5. Jetson 기존 설정/항로/Direct-I2C 드라이버 hash 확인
6. 설치 후 AUTO_SAFE 6000/6450과 version/GPS telemetry 확인

방식으로 동작합니다.

## Jetson에서 직접 패치 적용

```bash
cd /home/jetson/jetson_patch
chmod +x install_patch.sh
./install_patch.sh
```

설치기는 현재 소스를 `/home/jetson/rcboat/backups/` 아래에 백업하고, Direct-I2C 드라이버를 확인한 뒤 필요한 모듈만 복사합니다. 문법 검사나 서비스 시작이 실패하면 기존 파일을 복원합니다.

## GPS 연결 확인

```bash
ls -l /dev/serial/by-id/
readlink -f /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00
systemctl status rcboat.service
journalctl -u rcboat.service -n 100 --no-pager
```

GPS serial port는 daemon 한 프로세스만 사용해야 합니다. 서비스 실행 중 별도 `cat`, GPS Python 프로그램, 다른 NTRIP 프로그램으로 같은 포트를 동시에 열지 마십시오.

## NTRIP 설정

실제 caster 주소, 계정, 비밀번호는 저장소에 포함하지 않습니다. GUI 또는 Jetson의 `.ntrip.env`에만 저장합니다.

```bash
cd /home/jetson/rcboat
chmod 600 .ntrip.env
sudo systemctl restart rcboat.service
journalctl -u rcboat.service -f
```

Windows GUI는 NTRIP link 상태와 GNSS RTK solution을 별도 카드로 표시합니다.

## GPS CSV 진단 로그

항로 기록과 별도 기능입니다.

```bash
ls -lh /home/jetson/rcboat/logs/gps/
tail -n 20 /home/jetson/rcboat/logs/gps/gps_*.csv
```

## Windows GUI 빌드

Windows 10/11 x64:

```bat
BUILD_WINDOWS_EXE.bat
```

기본 PyInstaller 출력은:

```text
windows_gui_source\windows_app\dist\RCBoatControl.exe
```

GitHub Actions release artifact 이름은 현재 SemVer 기준 `RCBoatControl_v1.6.0`을 사용합니다.

## 테스트

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=jetson_patch:windows_gui_source/windows_app python3 -m unittest discover -s tests -p "test_*.py"
```

자동 테스트는 parser, GPS health, NTRIP, route persistence, timestamp/heading metadata, Multi-Path, 안전 gate, GUI route export와 PyInstaller 빌드를 검사합니다. 실제 수상 운항, 서보 방향, RTK FIX 정밀도는 현장에서 최종 확인합니다.
