# RTK → GPS 자동 대체 운항

- RTK Fixed 또는 NTRIP 보정이 끊겨도 유효한 일반 GPS Fix가 있으면 NAVIGATION을 계속합니다.
- RTK 보정 상태와 일반 GPS 항법 안전 상태를 분리했습니다.
- GPS 단절, GPS 데이터 지연, Fix 소실, 좌표 오류, HDOP 초과 등 기존 GPS 안전정지는 그대로 유지합니다.
- Windows GUI에 `RTK 손실 → GPS 대체 운항` 상태를 표시합니다.
- 이전 설정 파일에는 새 키가 없어도 `rtk_fallback_to_gps=true`가 기본 적용됩니다.
