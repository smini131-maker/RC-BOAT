# v2.1.12 검증 결과

2026-10-28, Windows 로컬 검증. 실제 Jetson 재설치/물리 모터 시험은 수행하지 않았습니다.

- 전체 unittest 85개 통과: v2.1.11의 74개 + GPS 유예/복구/기록/항법 관측 provenance 11개.
- 실제 Supervisor 코드: GPS 무효/stale에서 GROUND_TEST 유지, 조향 6000/스로틀 6450 중립 잠금.
- 유예 시작 뒤 0.1/1/3/4.99초 중립 유지 및 남은 시간 확인.
- 2초 내 유효 FIX/새 항법 명령 복구 시 자동 재개, STARTED/RECOVERED 각 1회 기록.
- 끊기기 전 캐시된 항법 명령은 GPS 복구 후에도 적용 거부.
- 유효 FIX만 잠깐 돌아왔다 다시 끊겨도 기존 유예 deadline 연장 없음.
- 5초 경계 만료 시 MANUAL, opt-in 해제, 이후 GPS 복구만으로 자동 재개하지 않음.
- GPS는 복구됐으나 새 항법 계산이 없는 채 만료되면 NAVIGATION_INVALID 수동 전환.
- 일반 AUTO/NAVIGATION/REMOTE에는 GPS 유예를 적용하지 않음. 무효 GPS로 신규 시험 시작 거부.
- E-STOP, 모드 변경, 목표 도착, RC 소실, actuator 오류, 추진 고장, ROS 링크/항법/항로 응답 소실은 유예 중에도 우선 적용.
- 0초 설정은 즉시 수동 전환. NaN/무한대/범위 밖 설정은 시작 거부.
- 실제 Logger 코드: 유예 구간을 출력 pause로 기록하고 같은 폴더/recording/sample 증가 유지.
- 실제 Navigation 코드: 계산 도중 subscriber가 GPS dict를 교체해도 사용한 FIX의 타임스탬프를 유지.
- Qt GUI: 남은 3.2초·중립 출력 표시, 유예 중 재개 버튼 비활성, 종료 버튼 활성 확인. 캡처 시각 검수.
- 독립 heartbeat, 반복 SSH 해제/비동기 창 닫기, 보정 경과/구 backend 거부/E-STOP 회귀 검증 통과.
- 배포 staging: 가짜 SSH/SCP로 파일 40개 SHA-256 및 v2.1.12 일치 확인.
- Windows EXE 빌드 성공, smoke 종료코드 0. EXE 내부 GUI/worker/mock bytecode가 현재 소스와 일치.

유예는 GPS 무효/stale 감지부터 추가 5초이며, 기존 stale 판단 2초는 유지됩니다.
전체 갱신이 끊긴 경우 마지막 유효 FIX부터 수동 전환까지 약 7초가 될 수 있습니다.
유예 중 위치는 추정하지 않으며 무효/stale 구간을 정상 위치 관측으로 해석하면 안 됩니다.
Jetson에서 INSTALL_ROS 완료 및 RUNNING GATEWAY VERIFIED: v2.1.12 확인 후 실물 도보 시험이 필요합니다.
