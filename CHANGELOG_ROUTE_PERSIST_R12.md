# 주행 항로 저장·설정 확인 R12

## 수정 사항

- 사용자가 선택한 주행 항로를 메모리에만 두지 않고 실제 `routes.json`의 `selected_route_id`에 원자 저장합니다.
- daemon 재시작 또는 항로 파일 다시 읽기 후에도 저장된 선택 항로를 복원합니다.
- GPS로 새 항로를 기록해 저장하면 새 항로 ID를 같은 `routes.json`에 선택 항로로 함께 기록합니다.
- Multi-Path 자동 전환으로 바뀐 활성 항로는 운항 중 상태로만 유지하여 사용자가 지정한 기준 항로를 덮어쓰지 않습니다.
- GUI에서 항로 저장 파일과 Multi-Path 설정 파일의 실제 Jetson 경로를 표시합니다.
- Multi-Path 저장 버튼은 ACK를 받을 때까지 `저장 확인 중` 상태를 유지하고 실패 시 원인과 재저장 필요 상태를 표시합니다.

## 유지한 기능

- Multi-Path R11 전체 기준과 동일 출발·도착 그룹 판정
- ModeFix, AUTO 속도 조절, GPS 항로 기록, HIL
- MANUAL 실측 매핑, REMOTE heartbeat, E-Stop
- SSH 터미널, Direct-I2C 하드웨어 보호, 기존 기록 항로 보존

## 저장 위치

- 선택 항로 및 GPS 기록 항로: `/home/jetson/rcboat/routes.json`
- Multi-Path 기준 및 AUTO 속도: `/home/jetson/rcboat/boat_config.json`
