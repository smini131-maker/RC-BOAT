# RTK → GPS 대체 운항 테스트 결과

- 실행일: 2026-10-10
- Python 문법 검사: 통과
- 전체 자동 테스트: 81개 통과

검증 항목:

- RTK FLOAT/NO RTK 상태여도 유효 GPS Fix가 있으면 NAVIGATION 유지
- NTRIP 보정 age가 오래되어도 일반 GPS 항법 상태가 정상이면 운항 유지
- GPS 연결 끊김, GPS 데이터 지연, Fix 소실, HDOP 초과 시 기존 안전정지 유지
- GUI에서 `RTK 손실 → GPS 대체 운항` 표시
- 기존 REMOTE heartbeat, 비상정지, Multi-Path, 항로 저장, 수동 스로틀 방향 테스트 유지
