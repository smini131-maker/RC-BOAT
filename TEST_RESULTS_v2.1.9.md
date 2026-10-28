# v2.1.9 검증 결과

2026-10-28 / Windows PC / 카메라 없는 정식 ROS Noetic 버전.

- 회귀 테스트 60개 통과: 기존 항로/로그/안전 전환 41개 + 보정/배포 검증 19개.
- CRC-24Q 기준 벡터, 분할 RTCM 프레임, 잘못된 CRC, 빈 payload, HTTP chunk 분할을 검증했습니다.
- 미수신 no_data, 경과시간 증가/stale, 구버전 고정 0의 unsupported 처리,
  GGA 수신기 보정 나이 0의 실제 유효값 구분, 빈값/음수/NaN/오래된 보고값을 검증했습니다.
- 파일 해시 불일치/구버전 gateway/구버전 NTRIP/잘못된 실행 소스를 설치 성공으로 인정하지 않는지 확인했습니다.
- tests/gui_smoke_v219.py: 실제 SSHWorker에 가짜 transport/probe를 연결하여
  지연 1회 후 복구는 연결 유지, 2회 연속 실패/종료된 shell은 단절 처리함을 확인했습니다.
- GUI/백엔드 버전이 다르면 신규 운항을 거부하면서 E-STOP 명령은 허용하는지 확인했습니다.
- GUI RTCM 수신 후 경과 0.34 s / 수신기 보정 나이 no_data / Jetson 버전 표시를 확인했습니다.
- tests/check_deploy_staging.ps1: 실제 Windows PowerShell 5에서 SSH/SCP만 가짜 함수로 바꾸고
  runner 전체 전송 경로를 실행했습니다. bytecode 제외/폴더 구조/39개 해시의 Python 교차 검증 통과.
- GUI EXE 빌드 성공, root dist에서 --smoke-test 종료 코드 0.
- EXE에 들어간 GUI와 SSH 모듈 bytecode가 최종 소스 컴파일 결과와 정확히 같음을 확인했습니다.
- ROS/Jetson 스크립트 Python 3.8 문법 및 ROS XML 파싱 통과.

Jetson에 실제 배포/실행한 결과는 아닙니다. catkin_make와 실물 GPS/RTCM/RC/PCA/모터 시험은 미실행입니다.
실제 Wi-Fi나 sshd의 불안정 원인을 모두 해결했다는 의미도 아닙니다. SSH 지연과 종료 사유를 기록해
현장에서 원인을 구분하도록 했습니다. 실제 NTRIP 캐스터/HTTP chunked 입력은 모의 입력으로 검증했습니다.
카메라 v2.2.0은 변경하지 않았습니다. 적용 명령은 배포_및_시험_순서_v2.1.9.txt를 따릅니다.
