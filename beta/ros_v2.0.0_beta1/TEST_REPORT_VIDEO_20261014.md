# RC BOAT ROS v2.0.0-beta.1 - GPS 보행영상 분석 및 구현 검증 (2026-10-14)

영상: https://youtu.be/C5KsczjSD5Y (1시간 9분 58초). 한국어 자동 자막의 영상 전 시간대를 브라우저에서 검토해 구간별 요약을 확보함. 자막의 축어 전문이나 모든 프레임의 원본은 내려받지 못했음.

## 오프라인 검증
- Python unittest discover **31/31 PASS** (기존 26개 + 새로운 영상·QGIS·배포 관련 5개)
- Python AST **28개 PASS**, Bash 문법 검사 PASS
- 합성 GPS CSV **220 샘플 / 4Hz**, RIGHT→CENTER **1회** 경로 전환
- speed/steering/heading-error/cross-track-error/target-route timeline PNG 5종 생성
- GitHub Actions Windows x64 PySide6 GUI smoke / 실제 EXE 빌드 및 EXE smoke **PASS** (성공 run: https://github.com/smini131-maker/RC-BOAT/actions/runs/38423844614)

## 수정/보강
1. Ground Test logger는 최신 액추에이터 중립 명령(6000/6450), safety lock, GPS health 없이는 시작을 거부.
2. Multi-Path ROUTE_SWITCH 이벤트가 CSV 타이밍 경합으로 누락되지 않도록 이벤트 플래그 보완.
3. GPS FIX가 없는 좌표를 QGIS 실제 궤적 CSV에서 제외.
4. 1m resampling에서 timestamp 및 0°/360°를 넘어가는 heading 메타데이터 보존.
5. MATLAB: 기본 Rudder/Heading Error/Speed, 0.6m/s 보행 **참고선**(추진값 아님), 선/범례/축/글꼴 설정과 route-switch 타임라인.
6. QGIS: EPSG:4326, actual/LEFT/CENTER/RIGHT 색상·Index/TimeStep 라벨 자동 설정 및 qgz 저장 스크립트.
7. Windows 배포 도구에 qgis 폴더 전송 추가.

## 미검증/사용자가 직접 할 일
- [ ] Jetson ARM64/Ubuntu 20.04 실제 ROS Noetic 설치/catkin_make, roslaunch 및 rqt_graph
- [ ] GPS/RTK/NTRIP hAcc/heading/speed 4Hz 실측
- [ ] GROUND_TEST에서 실제 PCA·ESC·서보 안전 상태 확인 (프로펠러 제거, 추진 전원 분리)
- [ ] CENTER Non-Disturbance/RIGHT→CENTER Disturbance 보행 기록
- [ ] 실제 MATLAB과 QGIS 프로그램에서 3개 필수 그래프 및 VWorld Satellite 확인
- [ ] ROS와 rcboat.service 배타 제어, ROS→daemon rollback 확인

주의: Python/Actions 테스트는 **하드웨어 안전 검증이 아닙니다**. `actual_steering_pwm` 및 `actual_throttle_pwm`는 기록한 명령값이지 물리 모터 센서의 피드백이 아닙니다. v1.6.0 안정판은 변경하지 않았습니다.

실행 절차: `VIDEO_VALIDATION_20261014_KO.md`, `TODO_FIELD_TEST_KO.md`, `VIDEO_GROUND_TEST_따라하기_설명서.md` 참조.
