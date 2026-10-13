# GPS 지상 Path-Tracking 영상 전체 구간 검증표 (2026-10-14)

영상: https://youtu.be/C5KsczjSD5Y / 길이 1:09:58.
방법: 웹 브라우저에서 공개된 자동 생성 한국어 자막을 확인하고 **영상 전체 시간대를 포괄하는 구간별 요약**을 확보. 원문 자막 전사 파일/프레임별 영상 검증은 확보하지 못함.

| 시간 | 영상 내용 | 구현 여부 |
|---|---|---|
| 00:01–04:29 | 실제 GPS 기반 지상 경로 추종 목적 | GROUND_TEST 구현, 보행 미검증 |
| 04:29–07:56 | 조향각/Heading Error/Speed 3개 그래프 | MATLAB 스크립트 구현 |
| 07:56–20:38 | 간섭/비간섭, 조향 좌/우, PWM→각도 | NAV inversion, multipath 계산; 실제 조향 방향 미검증 |
| 20:38–49:31 | clear/clc/close all/readtable, RGB, line width, legend, fonts | MATLAB figure 스타일 반영 |
| 49:31–52:05 | 라벨/축 및 동기화 | MATLAB linkaxes, labels |
| 52:05–57:53 | km/h→m/s, 보행 0.6m/s, 경로 switch | GNSS m/s 1회 변환, 시각적 0.6 기준선, active route 그래프 |
| 57:53–1:09:58 | EPSG:4326, TMS4 Korea, VWorld Satellite, CSV/심볼/라벨 | QGIS 4개 CSV와 스타일 스크립트; 실 QGIS 설치 검증 필요 |

영상의 1100/1500/1900 서보 PWM은 강의용 예제. 실제 RC Boat의 CH0 steering neutral=6000, CH6 ESC stop=6450을 바꾸지 않음. 0.6m/s는 시험 보행 참고값이며 모터 명령 아님.

## 보완 완료(오프라인)
- [x] safety GROUND_TEST 시작에 실제 PWM 명령 freshness/neutral 검사
- [x] route switch event 누락 방지 및 CSV 정렬
- [x] NO FIX 좌표 QGIS 궤적 배제
- [x] timestamp + heading 보존 1m resampling
- [x] MATLAB 러더/헤딩오차/속도, 0.6 기준선, 경로 switch 타임라인
- [x] QGIS 레이어 자동 색상/라벨 및 프로젝트 저장 스크립트
- [x] 30개 순수 Python 회귀 테스트

## 현장 미검증
- [ ] Jetson ROS Noetic catkin_make, roslaunch, rqt_graph
- [ ] 실제 GNSS 4Hz, NTRIP/RTK Fix & heading/speed
- [ ] GROUND_TEST actuator neutral 6000/6450 실측 (프로펠러 제거, ESC 추진 전원 분리)
- [ ] Non-Disturbance와 RIGHT→CENTER Disturbance 실보행 데이터
- [ ] MATLAB 및 QGIS GUI에서 그래프/레이어 표시 실제 실행
- [ ] ROS→daemon 안전 복귀
