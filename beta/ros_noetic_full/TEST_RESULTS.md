# ROS Noetic Full Beta Test Results

검증일: 2026-10-13

## 통과

- 베타 순수 로직 단위 테스트: 10/10
  - MANUAL 안전 부팅과 중립 재활성화
  - RC 입력 손실 안전 출력
  - REMOTE heartbeat 0.7초 timeout
  - Emergency Stop latch
  - RTK 필수/일반 GPS fallback gate
  - NTRIP GGA checksum과 RTCM 조각 재조립
  - CH0/CH6 및 PWM 안전 상수
- Python 전체 구문 컴파일
- Shell 전체 `bash -n`
- package.xml, launch XML, YAML, JSON 파싱
- `ublox_f9p` 고정 커밋 대상 RTCM 의존성 패치 적용 검사
- `git diff --check`

## 기존 운영 버전 회귀 검사

- 기존 테스트 65개 중 63개 통과
- 나머지 2개는 코드 실패가 아니라 현재 검사 환경에 `paramiko`, `PySide6`가 없어 import 단계에서 미실행
- 변경 파일 경로는 모두 `beta/` 아래로 제한

## 이 환경에서 실행하지 못한 검사

- ROS1 Noetic이 설치된 Jetson에서의 `catkin_make`
- 실제 ZED-F9R, Arduino, PCA9685 연결 시험

실물 검증 시 프로펠러를 분리하고 `/rcboat/state`, `/ublox_gps/fix`, `/ublox_gps/navpvt`, `/rcboat/pwm_command` 순서로 확인해야 합니다.
