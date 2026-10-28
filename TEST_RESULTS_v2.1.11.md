# v2.1.11 검증 결과

2026-10-28 Windows에서 검증했습니다.

실제 Jetson 원인 확인:
- ground_test_20261028_053820의 events.jsonl과 CSV를 ROS gateway로 읽었습니다.
- 13:38:30.230 / 시작 9.268초 후 GPS_INVALID_OR_STALE → MANUAL.
- 13:38:30.311 logger 종료, 37 samples. SSH 지연 13:39:21~23보다 앞선 시각입니다.
- 기존 이벤트에는 원본 GPS snapshot이 없어 FIX 무효/갱신 지연의 세부 원인은 확정하지 않았습니다.

검증:
- `python -m unittest discover -s tests -p "test_*.py"`: 74개 통과.
- 기존 66개 + 도보 SSH 독립/실제 링크 만료/재개/진단 snapshot/E-STOP·목표 도착 재개 거부,
  logger 기록 유지/여러 안전 오류 구간 보존/gateway 재개 서비스 8개.
- GPS 안전 수동 전환을 주입한 뒤 45초 동안 추가 180회 기록, 같은 폴더/CSV 유지,
  복구 후 재개 이벤트 1회, 총 182 samples, 정상 manifest/metadata 마감 확인.
- 오래된 GPS는 gps_healthy=False/gps_validity=stale로 구분하며 정상 위치로 재분류하지 않음.
- `tests/gui_ground_v2111.py`: SSH probe를 2.3초간 멈춰도 독립 heartbeat 3회,
  전송 간격 1.5초 미만. UI 기록 계속/원인/재개 버튼/확인창/command 매핑 통과.
- `tests/gui_lifecycle_v2110.py`: 실제 Qt worker 느린 SSH/반복 해제/비동기 창 닫기/소켓 취소 회귀 통과.
- `tests/gui_smoke_v2110.py`: 보정 경과/미지원값/SSH 일시·지속 실패/구 backend 차단/E-STOP 회귀 통과.
- `tests/check_deploy_staging.ps1`: 가짜 SSH/SCP로 전송 인수 및 v2.1.11 소스 40개 SHA-256 검증 통과.
- 새 EXE smoke 실행 종료코드 0. 배포 EXE 내부 GUI/worker/mock bytecode가 현재 소스와 일치함.
- 새 도보 탭 캡처를 확인했고 상태 문구를 버튼 아래 별도 줄로 배치했습니다.

한계:
- Jetson의 실행 중 버전은 아직 v2.1.10이며 이번에 실제 catkin 빌드/재시작/모터 시험은 하지 않았습니다.
- 사용자가 INSTALL_ROS.cmd로 적용한 뒤 실행 중 gateway/GPS/NTRIP/safety v2.1.11 검증 필요.
- GPS 오류와 전체 통신 소실은 계속 출력 안전 수동 전환합니다. 기록 유지와 명시적 재개로 시험을 이어갑니다.
- 수동 전환 뒤에는 RC 중립 확인 후 실제 수동 조종이 가능합니다.
- 유효하지 않은 GPS 구간을 그래프의 정상 위치 관측으로 해석하지 마십시오.
