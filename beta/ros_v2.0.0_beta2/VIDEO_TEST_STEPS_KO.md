# RC BOAT ROS v2.0.0-beta.2 - YouTube GPS 지상 실험 체크리스트

참고 영상: https://youtu.be/C5KsczjSD5Y (1:09:58). **자동 한국어 자막 구간 요약**을 기반으로 했고, 자막 전문·전 프레임 영상 분석을 수행했다고 주장하지 않습니다.

## 강의 영상 순서

1. [ ] **00:01-04:29** — 야외 실제 GPS 경로 기록: LEFT/CENTER/RIGHT. 시작과 끝은 0.75m 이내, 가운데 구간은 충분히 벌리기.
2. [ ] **04:29-07:56** — 조향각·Heading Error·속도 [m/s] 필수 그래프 세 개 준비.
3. [ ] **07:56-20:38** — Non-Disturbance (CENTER 경로 유지, 좌우 복귀 조향) 및 Disturbance (RIGHT→CENTER 전환) 실험.
4. [ ] **20:38-49:31** — MATLAB `clear;clc;close all; T=readtable(...)`; 색/LineWidth/legend/xlim/ylim/Times New Roman 설정.
5. [ ] **49:31-52:05** — subplot/linkaxes, 공통 시간축과 legend 설정.
6. [ ] **52:05-57:53** — 0.6 m/s는 보행 목표 *참고선*이며 ESC 목표 속도 아님. GNSS 속도가 m/s이면 3.6으로 재차 나누지 않음. Multi-Path 전환 시간 표시.
7. [ ] **57:53-1:09:58** — QGIS EPSG:4326, TMS for Korea/VWorld Satellite(호환성 확인), Actual+LEFT+CENTER+RIGHT 4개 CSV, 목표 Index/실측 TimeStep 라벨.

## 설치와 하드웨어 안전

- [ ] **프로펠러 제거 + ESC 추진 전원 분리**. PCA 6000/6450 기입은 모터의 실제 정지 피드백이 아님.
- [ ] Windows `CHECK_WINDOWS.cmd`; ROS beta2 GitHub Actions 산출 EXE를 설치하고 실 IP로 `ssh jetson@IP` 접속.
- [ ] `CHECK_BACKEND.cmd`에서 daemon만 기본 enabled, ROS disabled. `/dev/serial/by-id`의 Arduino/GPS 실 ID 확인.
- [ ] Jetson ROS1 Noetic (Ubuntu20.04/Jetson aarch64) 실제 설치 가능성 점검 (Noetic은 지원 종료).
- [ ] `DEPLOY_ROS.cmd` → `INSTALL_ROS.cmd` → `USE_ROS.cmd` → `CHECK_ROS.cmd`; daemon과 ROS가 동시에 active면 즉시 중단.
- [ ] `rostopic hz /rcboat/gps/status`, `rostopic echo -n1 /rcboat/gps/status`, `rostopic echo -n1 /rcboat/actuator/status` 확인. 실제 FIX/RTK_FIXED와 NTRIP connected는 별개.

## GPS 실보행 검증

- [ ] 경로마다 `timestamp/lat/lon/heading_deg` 메타데이터를 기록하고 원본을 보존, 사본만 `tools/resample_route.py`로 약 1m 재샘플.
- [ ] GROUND_TEST에서 계산 PWM과 실제 Actuator 명령 PWM 분리: desired 값이 바뀌어도 실제 6000/6450.
- [ ] CENTER 근처에서 각각 `HEADING`, `HEADING_CTE`, `LOS`, `PURE_PURSUIT` 선택 → **각각 별도 걷기 실험** 기록. CTE 왼쪽 +, 오른쪽 -; 이탈 반대방향 수정 확인. 저속 GNSS course 신뢰도 주의.
- [ ] RIGHT 선택 후 CENTER 근처로 벗어나기: 기본 이탈 8m/3초, 후보 거리 이점 2m, 쿨다운 5초를 만족해야 전환됨. `multipath_switch` / `events.jsonl` 시각 일치 확인.
- [ ] 4Hz CSV 기록·다운로드; hAcc, RTK, C/N0, HDOP, Fix 누락 확인. No Fix는 QGIS 실측 궤적에서 제외.
- [ ] MATLAB `matlab/analyze_path_tracking.m` 실행해 3개 필수 그래프/CTE/전환 시각을 저장.
- [ ] QGIS CSV 입력 X=Longitude Y=Latitude CRS=EPSG:4326. QGIS console에서 `qgis/setup_qgis_layers.py` 실행 후 4개 경로 색과 Index/TimeStep 확인.
- [ ] MATLAB 전환 `t=12.50`초이면 QGIS `TimeStep=12.50`의 위치와 일치하는지 확인.
- [ ] 실험 뒤 `USE_DAEMON.cmd` 복귀. `propulsion_allowed=false`, `experimental_nav_actuation_enabled=false` 유지.

## 중요한 판정 제한

같은 GPS 궤적을 여러 조향 공식에 넣어 비교하는 것은 **계산 명령의 차이**만 볼 수 있습니다. GROUND_TEST 동안 사용자가 보트를 직접 들고 걷기 때문에 어느 제어기가 실제 수상에서 오차가 작은지 결정할 수 없습니다. 실제 수상 성능 비교는 별도 안전 승인·현장 주행 데이터가 필요합니다.
