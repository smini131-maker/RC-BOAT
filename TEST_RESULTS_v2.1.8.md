# v2.1.8 검증 결과

2026-10-28, Windows PC에서 확인했습니다. 카메라 없는 v2.1.7 기반입니다.

- `python -m unittest discover -s tests -v`: 41개 통과 (기존 18 + 안전 전환 23).
- 실제 Supervisor 클래스를 가짜 ROS/시계와 연결해 목표 도착, GPS FIX 소실/오래된 캐시,
  SSH 끊김, GUI 링크 만료, 항법/항로/RC/출력 오류, 추진 이상 입력, 무진행 15초를 검증했습니다.
- MANUAL 중립 인수, RC 끊김 후 재중립 요구, 통신/GPS 복구 시 자동 재출발 방지,
  비상정지 중 수동 출력 금지, GPS/항법 노드만 재시작되는 launch 설정을 검증했습니다.
- `tests/gui_smoke_v218.py`: GUI 상태 변환, SSH disconnected와 ROS online 독립 표시,
  MANUAL 중립 대기 및 E-STOP 표시 확인. screenshot을 시각 검수했습니다.
- PyInstaller Windows EXE 빌드 성공. EXE `--smoke-test --screenshot` 실행 종료 코드 0.
- EXE에 최종 v2.1.8 모드/오류/통신 코드가 들어 있는지 압축 모듈을 검사했습니다.
- ROS 소스 Python 3.8 문법과 package/launch XML 파싱 통과.
- Jetson 배포 스크립트는 소스 전송 후 Linux 줄바꿈 정리를 실행하도록 수정했습니다.
- 과거 beta/archive, v2.1.6/v2.1.7 릴리즈 폴더, 임시 배포 복제본과 v2.1.2~2.1.7 EXE를
  휴지통으로 보냈습니다. 별도 카메라 v2.2.0 및 분석/PPT/QGIS 결과는 보존했습니다.

Jetson에서 catkin_make, 실제 통신 단절, RC, GPS, PCA 출력, 모터/스크류는 아직 검증하지 않았습니다.
실제 적용은 `배포_및_시험_순서_v2.1.8.txt`의 프로펠러 제거 시험을 완료해야 합니다.
전류/RPM 센서가 없으므로 물리적 걸림 확정 검출은 지원하지 않습니다. GPS 무진행은 의심 조건입니다.
