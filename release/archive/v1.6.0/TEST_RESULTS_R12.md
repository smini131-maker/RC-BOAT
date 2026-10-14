# R12 테스트 결과

실행일: 2026-10-03

## 결과

- Python 문법·import 검사: PASS
- backend 상태 전이 및 안전 출력: PASS
- ModeFix·AUTO 속도·GPS 기록·HIL: PASS
- Multi-Path R11 그룹 판정·자동 전환: PASS
- 선택 항로 `routes.json` 저장·재시작 복원: PASS
- GPS 기록 항로 저장 후 선택 상태 복원: PASS
- Multi-Path `boat_config.json` 저장·재로딩: PASS
- GUI 저장 ACK 대기·실패 표시·저장 경로 표시: PASS
- Direct-I2C 설치 보호: PASS
- Mock protocol 및 GUI offscreen smoke: PASS

전체 회귀 테스트: **55 tests, PASS**

실제 Jetson과 수상 하드웨어 연결 시험은 이 환경에서 수행하지 않았습니다. 적용 전에 `install_patch.sh`가 출력하는 백업 경로를 확인하고, 프로펠러를 분리한 상태에서 서비스·PWM·GPS FIX를 점검해야 합니다.
