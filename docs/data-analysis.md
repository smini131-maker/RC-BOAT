# 로그·MATLAB 분석

[프로젝트 소개](../README.md) · [운항·시험](operation.md) · [인터페이스](interfaces.md)

## 시험 파일

Jetson 기본 저장 위치는 `~/rcboat_ros_data/logs/ground_tests/`입니다. GUI에서 시험을 선택해 ZIP으로 다운로드합니다.

```text
ground_test_YYYYMMDD_HHMMSS/
  ground_test.csv
  ground_test.jsonl
  reference_routes.csv
  reference_routes.json
  route_metrics.csv
  route_switches.csv
  route_changes.jsonl
  events.jsonl
  test_metadata.json
  analysis_manifest.json
  export_manifest.json
  plot_ground_test_week7.m
```

| 파일 | 내용 |
|---|---|
| `ground_test.csv` | 시각, GPS/RTK, 속도·진행 방향, 선택 항로, 목표 명령·최종 PWM, 안전 상태 |
| `ground_test.jsonl` | sample별 원본 구조 |
| `reference_routes.*` | 시험 시작 시 선택한 대루트의 모든 소루트 또는 단일 항로의 좌표·번호·UTM 고정본 |
| `route_metrics.csv` | sample × 소루트 형식의 후보별 거리·횡오차·목표점·목표 헤딩·헤딩 오차 |
| `route_switches.csv` | 활성 항로 전환, 이전·후보 항로 거리와 개선량, 전환 판정 |
| `route_changes.jsonl` | 시험 중 항로·설정 변경 및 당시 항로 snapshot |
| `events.jsonl` | 모드·수동 개입·오류·중단·재개·재시작 이벤트 |
| `test_metadata.json` | 코드 버전, 설정·보정값, 시작·종료·중단 정보 |
| `analysis_manifest.json` | 그래프용 파일·열 관계 |
| `export_manifest.json` | 파일 크기 및 SHA-256 |

기준 항로 고정본은 이후 편집으로 덮어쓰지 않습니다. 로거 재시작 후에는 `LOGGER_RESTART_DETECTED` 이벤트가 남습니다. `final_state=complete`는 **파일 마감 성공**이며, 무중단 자동주행 완료를 뜻하지 않습니다.

## MATLAB 실행

ZIP을 풀고 저장소 루트에서 MATLAB을 실행합니다.

```matlab
addpath('matlab')
plot_ground_test_week7('C:\path\to\ground_test_YYYYMMDD_HHMMSS')
```

다운로드된 시험 폴더의 MATLAB 함수도 사용할 수 있습니다. 기본 결과 폴더는 해당 시험 폴더의 `RCBOAT_ground_test_results`이며, 함수의 두 번째 인수로 출력 위치를 지정할 수 있습니다.

생성 결과는 `graphs`(PNG 14개), `data`(기준 항로·실제 경로·파생 CSV/JSON), `qgis`(좌표 CSV), `docs`(그래프 해설), `matlab`으로 구성됩니다. 실제 그래프 생성 함수는 [plot_ground_test_week7.m](../matlab/plot_ground_test_week7.m)입니다.

QGIS에서는 CSV에 포함된 UTM zone과 좌표계를 확인합니다. 위치가 끊긴 구간은 별도 선분으로 표시하고 제외 구간을 선으로 연결하지 않습니다.

## 분석 전 품질·수동 구간 확인

기본 MATLAB 함수는 입력 파일 전체를 사용합니다. **수동 구간을 자동으로 분리·제외하는 함수는 아닙니다.** 자동주행 성능을 산출할 때는 먼저 원본 상태와 이벤트로 분석 구간을 정해야 합니다.

1. `mode`, `effective_source`, `manual_intervention`과 `FAILSAFE_MANUAL` 등 이벤트로 자동·수동 전환을 구분합니다. 좌표 모양이나 속도만으로 수동 구간을 단정하지 않습니다.
2. `test_output_paused`, `output_locked`, `gps_grace_active`, `gps_healthy`, `gps_validity`, `gps_data_age_s`로 중립 대기·무효·stale 구간을 구분합니다.
3. 분석에 포함한 sample과 제외 이유를 따로 보존하고 원본 CSV/JSONL은 유지합니다.
4. 원래 시각·sample 번호를 유지합니다. 제외 구간은 시간축에서 압축하거나 선으로 이어 붙이지 않습니다.

로깅 주기와 GNSS 관측 갱신 주기는 다를 수 있습니다. 같은 GNSS 관측을 여러 로거 sample이 공유하는 경우 독립 관측 횟수와 혼동하지 않습니다.

## 값의 의미

| 값 | 해석 |
|---|---|
| GNSS speed / COG | 지면 기준 속도와 이동 방향. 선체 yaw 센서 측정값과 다름 |
| `heading_error_deg` | 현재 위치→목표 waypoint 방위각과 제어에 사용한 진행 방향의 차이 |
| 경로 접선 대비 진행 방향 오차 | 경로선의 국소 방향과 COG의 차이. waypoint 헤딩 오차와 별도 지표 |
| `desired_*_pwm`, `final_*_pwm` | 항법 목표 명령과 안전 제어 후 최종 명령 |
| `actual_*_pwm` | PCA9685에 보낸 명령 확인값. 물리 조향 위치·추력 피드백이 아님 |
| `target_speed_mps` | 설정 목표값. 속도 피드백이 꺼져 있으면 실제 속도를 보장하지 않음 |
| `correction_age_s` | 출처 필드를 함께 확인할 보정 경과 진단값. 서버 전송 지연과 다름 |

### v2.1.12 조향각 정의

v2.1.12에는 제어기와 로거의 PWM→각도 환산 정의가 다릅니다.

- 제어기 `desired_rudder_angle_deg`: 좌우 PWM 범위를 **±30°**로 환산하고 `nav_invert_steering`을 반영합니다.
- 로거 `final_rudder_angle_deg`: 최종 PWM을 **±45°**로 환산하며 조향 반전을 반영하지 않습니다.

현재 설정처럼 `nav_invert_steering=true`라면 같은 최종 PWM의 제어기 기준 명령각은 `-final_rudder_angle_deg × 30/45`입니다. 이 환산도 물리 러더각 실측값은 아닙니다. 두 각도 열을 그대로 비교해 조향 추종 오차를 계산하지 말고, PWM 또는 같은 환산 정의로 맞춘 명령값을 사용합니다. 목표·최종 명령의 시각도 함께 확인합니다.

### 거리와 속도

코스 거리는 기준 항로 waypoint의 경로선 길이이고, 주행거리는 실제 위치 관측을 연결한 길이입니다. 수동 포함 여부, GPS 품질 필터, 누락 구간 연결 여부에 따라 주행거리가 달라지므로 계산 조건을 같이 표기합니다. GNSS 속도의 평균과 주행거리÷시간도 다른 추정값입니다.

CSV 빈 값은 미제공·미수신일 수 있습니다. `unsupported`, `no_data`, `invalid`, `stale`을 0으로 치환하면 평균과 그래프가 왜곡됩니다.
