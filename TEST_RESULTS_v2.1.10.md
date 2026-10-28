# v2.1.10 검증 결과

2026-10-28 Windows PC에서 검증했습니다.

- 회귀 테스트 66개 통과 (기존 60 + I2C/소유권/부팅 제한/진단 도구 6).
- 실제 QThread와 1.9초 SSH 지연으로 해제 3회, 정리 중 재클릭, 비동기 창 닫기를 검증했습니다.
- 응답 없는 gateway recv 취소 및 UI 변경 신호가 GUI 메인 스레드에서 발생함을 확인했습니다.
- GUI smoke: 보정 경과/미지원 값/SSH 일시·지속 실패/버전 불일치/E-STOP 표시 통과.
- Windows 이벤트에서 기존 v2.1.9의 Qt6Core.dll/c0000409 충돌 4건을 확인했습니다.
  개별 충돌 stack은 없으며 모든 native 오류가 해결됐다고 단정하지 않습니다.
- QThread 수명과 GUI 갱신 경로를 수정하고 새 로컬 종료 진단 로그를 추가했습니다.
- PCA 오류 시 descriptor 정리, 보조 도구의 동일 lock, 부팅 재시도 제한을 검증했습니다.
- Jetson 실제 배포/실물 I2C/GPS/RC/모터 시험은 하지 않았습니다.
- EXE smoke와 최종 소스 bytecode 일치 결과는 릴리즈 manifest에도 기록합니다.
