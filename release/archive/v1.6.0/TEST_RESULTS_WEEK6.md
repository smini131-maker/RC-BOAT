# TEST RESULTS WEEK6

실행일: 2026-10-06

## 자동 테스트

```text
Ran 78 tests
OK
```

검증 범위:

- 기존 R12 controller, ModeFix, AUTO speed, REMOTE heartbeat, E-stop
- 기존 route recording, Multi-Path, HIL, route/config persistence
- GGA/RMC/GSA/GSV, checksum, malformed NMEA, NMEA+UBX 혼합 stream
- UBX NAV-PVT RTK Fixed, hAcc, fixType/carrSoln
- GPS Health 위성/HDOP/PDOP/VDOP/stale/NO FIX
- 일반 GPS navigation, RTK-required gate, correction stale
- GPS CSV start/write/flush/stop/restart
- NTRIP Basic authentication success/failure mock, GGA uplink
- Windows GUI 기존 회귀 + GPS Health/RTK/logging smoke
- Python 문법, 서비스/설치/고정 경로 정적 검사

## 빌드 검증

- Python backend/GUI `py_compile`: PASS
- PyInstaller spec과 Windows `build.bat`: 정적 검증 PASS
- Windows EXE: Linux 환경이므로 재빌드하지 않음

## 실제 장비

- Software test: **PASS**
- Mock NTRIP: **PASS**
- Hardware verification: **REQUIRED**

실제 RTK Fixed, cm급 정밀도, 국토지리정보원 caster, ZED-F9R RTCM 주입, 수상 주행을 완료했다고 주장하지 않습니다.
