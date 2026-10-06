# CHANGELOG WEEK6

## 기준

- 기준 커밋: Multi-Path R12 `ce94b2a`
- 기존 GUI와 제어 상태기계, PWM, Direct-I2C, Multi-Path, HIL, ModeFix를 보존
- 6주차 강의자료의 ZED-F9P 수치를 실제 ZED-F9R에 자동 적용하지 않음

## 변경 요약

| 기능 | 이전 R12 | Week6 결과 |
|---|---|---|
| GPS NMEA 수신 | GGA/RMC | GGA/RMC/GSA/GSV 강화 |
| GPS FIX·위도·경도·heading | 구현 | 유지 |
| Satellite·HDOP | 구현 | Health 기준과 상세 이유 추가 |
| UTC·PDOP·VDOP | 미구현 | 구현 |
| C/N0 | 미구현 | GSV 제공 시 구현, 미제공 시 N/A |
| hAcc·fixType·carrSoln | 미구현 | UBX NAV-PVT 제공 시 구현, 미제공 시 N/A |
| GPS Health | 단순 FIX/stale | GOOD/WARNING/BAD/NO_FIX/STALE |
| GPS CSV logger | 미구현 | daemon start/stop, flush/fsync 구현 |
| UTM | 미구현 | telemetry/log 분석용 구현 |
| NTRIP·RTCM injection | 미구현 | 동일 GPS serial 공유 구조 구현 |
| RTK Float/Fixed 표시 | 미구현 | NMEA+UBX 상태 구현 |
| RTK navigation gate | 미구현 | 기본 OFF, 선택적 Fixed+correction age gate |
| GUI Health/RTK | 미구현 | 기존 디자인 내 별도 탭 구현 |
| 기존 Multi-Path/HIL/ModeFix/AUTO 속도 | 구현 | 유지, 회귀 테스트 통과 |
| 기존 Direct-I2C | 구현 | 설치 시 검증·보존, Blinka 금지 유지 |

## 보안

- 실제 NTRIP 비밀번호는 `.ntrip.env`에 600 권한으로 저장
- `.gitignore`에서 실제 env와 GPS CSV 제외
- telemetry와 로그에 비밀번호 미포함
- 저장소에는 빈 `ntrip.env.example`만 포함

## 하드웨어 확인 필요

- ZED-F9R 실제 baudrate/update rate
- 실외 FIX, 위성/HDOP/UBX NAV-PVT 출력
- 실제 NTRIP 계정 인증과 RTCM 수신
- RTK FLOAT/FIXED 전환과 cm급 정확도
- 수상 주행과 GPS Health gate
