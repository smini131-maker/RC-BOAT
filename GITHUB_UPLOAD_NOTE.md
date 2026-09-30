# RCBoat Multi-Path R11 Restore

이 저장소/폴더는 Jetson RC Boat 현재 운용 버전에 Multi-Path R11 복구 패치를 적용하기 위한 정리본입니다.

## 포함된 내용

- `jetson_patch/`: Jetson에 적용할 백엔드 패치
- `windows_gui_source/`: Windows GUI 소스와 빌드 스크립트
- `tests/`: 회귀 테스트
- `README_먼저읽기.md`: 설치/적용 순서

## 중요한 주의사항

- 이 패치는 Jetson의 `hardware.py`, `pca_direct.py`, `boat_config.json`, `routes.json`을 덮어쓰지 않습니다.
- Jetson에서는 기존 Direct-I2C PCA9685 구성을 유지해야 합니다.
- `Jetson.GPIO`, Blinka, `import board` 방식으로 되돌리지 않습니다.
- Windows 실행 파일은 GitHub에 직접 포함하지 않고 `BUILD_WINDOWS_EXE.bat` 또는 `windows_gui_source/build.bat`로 빌드합니다.

## Jetson 적용

```bash
cd /home/jetson/jetson_patch
chmod +x install_patch.sh
./install_patch.sh
```

설치 스크립트는 적용 전 현재 파일을 백업하고, Direct-I2C 하드웨어 구성이 유지되는지 검사합니다.

