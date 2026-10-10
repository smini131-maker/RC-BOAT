# RC-BOAT Week6 GPS / RTK 확장판

기존 Multi-Path R12의 GUI, ModeFix, AUTO 속도, 항로 기록, HIL, SSH 터미널과 Direct-I2C PCA9685 제어를 유지하면서 6주차 GPS 환경 구축 기능을 추가한 프로젝트입니다.

## 보존된 안전 기준

- Steering CH0: LOW 4900 / CENTER **6000** / HIGH 7300
- ESC CH6: REVERSE 5800 / STOP **6450** / FORWARD 7000
- 모든 오류·통신 실패·비상정지: **Steering 6000 / Throttle 6450**
- Arduino와 GPS는 `/dev/serial/by-id/` 고정 경로만 사용
- `hardware.py`를 Blinka 또는 `Jetson.GPIO` 방식으로 바꾸지 않음
- `routes.json`, `boat_config.json`, 기존 기록 항로를 설치 패치가 초기화하지 않음

## Week6 추가 기능

- GGA/RMC/GSA/GSV NMEA 파서와 UBX NAV-PVT 파서
- NMEA+UBX 혼합 바이트 스트림 방어, checksum 검사, parser error count
- UTC, PDOP, VDOP, C/N0, hAcc, fixType, carrSoln, RTK 상태 telemetry
- GOOD / WARNING / BAD / NO_FIX / STALE GPS Health와 상세 이유
- HDOP·stale·위치 유효성·선택적 RTK Fixed 기준을 적용한 NAVIGATION 안전 Gate
- 기존 `routes.json` 항로 기록과 별도인 `/home/jetson/rcboat/logs/gps/gps_YYYYMMDD_HHMMSS.csv`
- daemon 내부 NTRIP client, VRS GGA uplink, RTCM 동일 GPS serial 연결 주입
- WGS84 → UTM 분석 좌표(기존 haversine Multi-Path 계산은 유지)
- 기존 디자인을 유지한 Windows `GPS · RTK` 탭과 시뮬레이션 telemetry

## GPS 연결 확인

```bash
ls -l /dev/serial/by-id/
readlink -f /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00
systemctl status rcboat.service
journalctl -u rcboat.service -n 100 --no-pager
```

GPS 포트는 daemon 한 프로세스만 엽니다. 서비스 실행 중 `cat`, 별도 GPS Python 프로그램, 별도 NTRIP 프로그램으로 같은 포트를 열지 마십시오.

## Jetson 패치 적용

```bash
cd /home/jetson/jetson_patch
chmod +x install_patch.sh
./install_patch.sh
```

설치기는 현재 소스를 `/home/jetson/rcboat/backups/week6_gps_날짜_시간/`에 백업하고, Direct-I2C 드라이버를 확인한 뒤 Week6 모듈만 복사합니다. 의존성 설치와 문법 검사 후 서비스를 재시작하며 실패 시 기존 파일을 복원합니다.

## NTRIP 설정

실제 국토지리정보원 주소, 계정, 비밀번호, Mount Point는 이 저장소에 들어 있지 않습니다. 발급받은 값만 사용하십시오.

```bash
cd /home/jetson/rcboat
cp -n /home/jetson/jetson_patch/ntrip.env.example .ntrip.env
chmod 600 .ntrip.env
nano .ntrip.env
sudo systemctl restart rcboat.service
journalctl -u rcboat.service -f
```

Windows GUI의 `GPS · RTK` 탭에서도 설정할 수 있습니다. GUI 비밀번호 입력칸은 전송 후 즉시 비워지며, 비밀번호는 Jetson의 `/home/jetson/rcboat/.ntrip.env`에 권한 600으로만 저장됩니다. telemetry에는 비밀번호가 포함되지 않습니다.

## RTK와 GPS Health 확인

1. GPS 연결이 `연결`인지 확인
2. FIX가 GPS / DGPS / RTK FLOAT / RTK FIXED 중 무엇인지 확인
3. Satellite, HDOP, PDOP, VDOP, C/N0, hAcc와 상세 이유 확인
4. NTRIP `연결됨`, correction age, 수신 byte 증가 확인
5. `RTK 끊김 시 일반 GPS로 계속 운항`이 켜져 있는지 확인

기본값은 `rtk_fallback_to_gps=true`입니다. RTK Fixed 또는 NTRIP 보정이 끊겨도 GPS 연결, 유효 FIX, 좌표, HDOP 등 일반 GPS 안전조건이 정상이면 현재 항로 운항을 계속합니다. 화면에는 `RTK 손실 → GPS 대체 운항`이 표시됩니다. GPS 자체가 끊기거나 FIX가 사라지거나 데이터가 지연되면 기존과 동일하게 6000/6450으로 정지 대기합니다.

## GPS CSV 로그

GUI의 `GPS 데이터 기록 시작/종료`는 항로 기록 버튼과 다른 기능입니다.

```bash
ls -lh /home/jetson/rcboat/logs/gps/
tail -n 20 /home/jetson/rcboat/logs/gps/gps_*.csv
```

## U-center 설정 주의

강의자료의 ZED-F9P 예시 baudrate와 update rate를 ZED-F9R에 그대로 강제하지 않습니다. 현재 장비는 이미 115200 baud에서 NMEA+UBX를 수신한 기록이 있으므로 먼저 U-center에서 실제 설정을 읽고 백업하십시오. 코드는 baudrate, 출력 프로토콜, GNSS 구성, factory reset, update rate를 자동 변경하지 않습니다. 실습용 보트는 1~4 Hz부터 데이터 안정성과 CPU 사용량을 확인한 뒤 결정합니다.

## Windows GUI 빌드

Windows 10/11 x64에서 실행합니다.

```bat
BUILD_WINDOWS_EXE.bat
```

결과: `windows_gui_source\windows_app\dist\RCBoatControl.exe`

Linux에서는 Windows PE 실행 파일을 새 버전인 것처럼 만들지 않습니다. 이 제출물은 소스, `build.bat`, PyInstaller spec을 문법·오프스크린 GUI 테스트로 검증했습니다.

## 테스트

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=jetson_patch:windows_gui_source/windows_app python3 -m unittest discover -s tests -p "test_*.py"
```

Software test와 Mock NTRIP은 통과했습니다. 실제 Jetson, 야외 GPS FIX, 국토지리정보원 계정, RTK FLOAT/FIXED, cm급 정밀도와 수상 주행은 현장에서 추가 확인해야 합니다.
