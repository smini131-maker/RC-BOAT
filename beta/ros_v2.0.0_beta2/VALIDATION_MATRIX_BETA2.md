# ROS beta2 요구사항 검증 현황

| 요구 | 코드 상태 | 현장 상태 |
|---|---|---|
| v1.6.0 및 beta1 보존 | 독립 브랜치, 신규 폴더 | Jetson 백업/롤백 미실행 |
| ROS1 Noetic/catkin/9 nodes | ROS launch 소스 | Jetson 실행 미확인 |
| Arduino/GPS/RTK/NTRIP/PCA single-owner | 구현/스크립트 | 실기 I2C/serial 미확인 |
| GROUND_TEST 6000/6450 + E-STOP | 소스/오프라인 테스트 | 프로펠러·ESC 물리검증 필요 |
| HEADING baseline | 코드 + 제어 방향 테스트 | 물리 서보 미확인 |
| HEADING_CTE / LOS / PURE_PURSUIT | 계산 + 로깅/GUI 지원 | 실제 수상 정확도 미검증 |
| 새로운 알고리즘 추진 잠금 | safety supervisor 및 config | 현장 시그널 검증 필요 |
| GPS 4Hz/실보행/Multi-Path | 로거+스위치 로직 | 실보행 미실시 |
| MATLAB 필수 3개 그래프 | 소스+합성 CSV | MATLAB GUI 미실행 |
| QGIS 4개 레이어 / VWorld | CSV+QGIS 스크립트 | QGIS GUI 플러그인 미실행 |
| Windows EXE | Actions workflow | 결과 확인 후 성공 판단 |
| ROS→daemon 롤백 | 배포 스크립트 | 실제 장치에서 미확인 |

**통과 조건:** 실제 GPS/RTK 센서값, GPS 이탈 경로, 6000/6450 물리 출력, Windows/Jetson GUI와 catkin, MATLAB/QGIS 표시, ROS→daemon 복귀가 별도 검증되어야 합니다. 오프라인 테스트 통과만으로 전체 시스템의 완성·안전 인증은 불가능합니다.
