# RC-BOAT Changelog

이 프로젝트는 2026-10-13부터 Semantic Versioning 형식 `MAJOR.MINOR.PATCH`를 공식 버전 체계로 사용합니다.

- **MAJOR**: 기존 Jetson/Windows 프로토콜이나 핵심 아키텍처와 호환되지 않는 변경
- **MINOR**: 기존 기능을 유지하면서 새 기능을 추가하는 변경
- **PATCH**: 호환성을 유지하는 버그 수정, 안전 수정, UI 개선

기존 `R11`, `R12`, `R12.1`, 현장 복구용 `R15.1` 표기는 삭제된 이력이 아니라 아래 SemVer 계보에 대응하는 **레거시 별칭**으로만 남깁니다. 과거 Git commit SHA는 재작성하지 않아 기존 링크와 복구 기준을 보존합니다.

## 1.6.0 - 2026-10-13

- GPS 항로 기록 포인트마다 `timestamp`, `lat`, `lon`, `heading_deg` 저장.
- 기존 lat/lon-only routes.json과 완전 하위 호환.
- JSON / CSV / GPX PC 내보내기에서 시간·위도·경도·헤딩 보존.
- Windows 배포 스크립트를 짧은 `%TEMP%` 작업경로 + `tar.exe` 압축 해제 방식으로 변경하여 긴 경로의 `Expand-Archive` 오류 제거.
- 버전 표기를 SemVer로 통일하고 Windows GUI/Jetson telemetry에 버전 노출.

## 1.5.0 - 2026-10-13

기준 commit: `c5fbf6afaa3e56f96e8441f75e09af867016cb14`
release branch: `release/1.5.0`

- UBX NAV-PVT polling을 통한 hAcc 수집 및 NAV-PVT/UBX/NMEA 카운터 표시.
- 자율항법 조향 방향 반전 보정.
- 방향오차 기반 연속 주행·감속 복귀 로직.
- C/N0 품질 진단과 실제 항법 hard gate 분리.
- RTK/NTRIP 상태 카드 가독성 개선.
- Multi-Path 그룹 구성과 활성 경로 표시.

## 1.4.0 - 2026-10-13

기준 commit: `12d56b221cd4594510d8a4c29893294c92e2477e`
release branch: `release/1.4.0`

대표 이력: `0fd39ca`, `7481bd5`, `c2c5893`

- 선택 항로 동기화와 기록 항로 관리 안정화.
- 기록 항로 삭제 안전 게이트.
- 항로 지도/레이어/PC 내보내기.
- RTK 상태 로깅 및 GUI 진단 강화.

## 1.3.1 - 2026-10-10

기준 commit: `6081faa173ce6c2cc672c17e4fe28c5c03523571`
release branch: `release/1.3.1`

- RTK/NTRIP 손실 시 유효한 일반 GPS로 자율항법을 계속하는 fallback 추가.
- GPS 자체가 끊기거나 stale/no-fix/HDOP 불량이면 안전 출력 유지.

## 1.3.0 - 2026-10-06

기준 commit: `7440a3048ab0e9579c8e3e6eaac0823121e007ec`
release branch: `release/1.3.0`

- Week6 GPS health, GPS CSV logging, NTRIP/RTK 지원.
- NMEA + UBX 파서와 GPS 진단 telemetry 추가.

## 1.2.0 - 2026-10-03

레거시 별칭: **R12**

기준 commit: `ce94b2a7a88b601b3506e2558b7b986c3b601e72`
release branch: `release/1.2.0`

- 선택 항로 영구 저장과 저장 결과 피드백 개선.
- 항로 실행/저장 흐름 안정화.

## 1.1.0 - 2026-09-30

레거시 별칭: **R11**

기준 commit: `570b3f3e0646e411608805c6d03eedc884a3732c`
release branch: `release/1.1.0`

- Multi-Path 복구 패키지.
- 기존 daemon / Direct-I2C / Windows GUI 기반 기능 복원.

## 1.0.0 - 2026-09

기준 commit: `c76f62a`
release branch: `release/1.0.0`

- Jetson daemon 단일 하드웨어 제어 구조.
- Windows PySide6 GUI + Paramiko SSH.
- MANUAL / AUTO / NAVIGATION / REMOTE / HIL 기반 제어.
- DirectLinuxPCA9685 기반 안전 출력 구조.

## 레거시 R15.1 메모

`R15.1`은 현장에서 Blinka/Jetson.GPIO 버전을 제거하고 검증된 Direct-I2C `hardware.py + pca_direct.py`를 복구할 때 사용된 복구판 명칭입니다. 저장소에서 독립적인 R15.1 릴리스 commit은 확인되지 않으므로 새로운 SemVer 번호를 임의로 부여하지 않고, **1.2.x 이후 모든 버전이 이 Direct-I2C 호환 기준을 계승한다**고 기록합니다.
