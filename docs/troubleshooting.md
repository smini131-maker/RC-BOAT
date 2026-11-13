# 문제 해결

[프로젝트 소개](../README.md) · [설치](setup.md) · [운항·시험](operation.md)

## 연결·버전 확인

| 증상 | 확인할 항목 |
|---|---|
| SSH 연결 가능, ROS offline | `rcboat_ros.service`, ROS master·gateway 로그 |
| SSH 단절, ROS gateway online | 배포·터미널 연결 문제와 ROS 통신 상태를 구분. Ground Test 정지는 gateway로 가능 |
| 신규 운항 시작 차단 | GUI/backend 버전, GPS·RC·출력·E-STOP 상태 |
| 설치 후 이전 버전 표시 | 전송만 수행했는지 확인하고 `INSTALL_ROS`와 실행 버전 검증 완료 |
| GPS 무효·stale | 장치 경로·권한·전원·수신 상태와 `gps_data_age_s` |
| RTCM 수신 중인데 RTK FIX 안 됨 | CRC 정상 프레임, 수신기 상태, 안테나·위성 환경. TCP 트래픽만으로 RTK 성공을 판단하지 않음 |

Jetson 터미널에서:

```bash
cd /home/jetson/rcboat_ros_ws
systemctl status rcboat_ros.service --no-pager
journalctl -u rcboat_ros.service -n 100 --no-pager
python3 deployment/jetson/verify_release.py --timeout 45
bash deployment/jetson/check_backend.sh
```

일반 운항과 Ground Test의 연결 단절·GPS 유예 정책은 [운항·시험](operation.md)을 참고합니다. GPS 유예는 수신 장애 자체를 해결하는 기능이 아닙니다.

## GNSS 수신 상태 확인

HDOP는 수평, PDOP는 3차원 위치에 대한 위성 배치의 영향입니다. 숫자가 낮을수록 위성 배치가 유리합니다. 실내나 건물 옆에서는 신호가 가려지거나 반사돼 DOP가 낮은 순간에도 위치 오차가 클 수 있습니다. [GPS 정확도에 영향을 주는 요인](https://www.gps.gov/gps-accuracy)

개방된 야외에서 보트를 정지한 채 수신기를 켜고, FIX와 RTK 상태가 안정되는 동안 HDOP·PDOP, 평균 C/N0, hAcc와 GPS 데이터 지연을 함께 확인합니다. RTCM 누적량이 증가해도 RTK 상태가 DGPS나 FLOAT일 수 있습니다. v2.4.19부터 유효한 DOP만 숫자로 표시하고, 값이 없거나 잘못됐거나 갱신이 늦으면 카드에 해당 상태를 표시합니다.

## Windows GUI가 종료되거나 연결 해제가 멈춤

앱 로그는 파일 탐색기에서 `%LOCALAPPDATA%\RCBoatControl\logs`로 열 수 있습니다.

- `app.log`: 연결·정리·Qt 경고·예외. 최대 2 MB, 이전 3개 순환 보관
- `native_crash.log`: faulthandler가 남길 수 있는 native 오류 흔적

현재 GUI는 worker의 `finished` 전까지 소유권을 유지하고, 정리 중 재연결을 막으며, 창을 비동기로 닫습니다. 두 연결이 모두 끊기면 `재연결 중 · 중지`를 표시합니다. Windows 이벤트의 `Qt6Core.dll` 또는 `c0000409`만으로 개별 원인을 확정하지 말고 앱 로그와 발생 시각을 함께 확인합니다. 과거 v2.1.9 충돌 및 수정 기록은 [v2.1.10 검증](validation/v2.1.10.md)에 있습니다.

## Jetson 부팅·장치 진단

```bash
cd /home/jetson/rcboat_ros_ws
sudo python3 deployment/jetson/collect_diagnostics.py
```

도구가 출력한 `~/rcboat_ros_data/diagnostics/boot_날짜_시각.txt`를 확인합니다. 이 도구는 로그·버전·메모리·마운트·온도를 읽어 파일로 저장하며 서비스 상태를 변경하거나 I2C 스캔을 수행하지 않습니다. 이전 부팅 journal이 없으면 해당 기록은 `unavailable`입니다.

| 로그 | 해석 범위 |
|---|---|
| `Failed to start RCBoat ROS` | 서비스 기동 실패. journal에서 장치·권한·빌드·경로 오류 확인 |
| IMX219 probe 오류 | 카메라 초기화 문제. 이 메시지만으로 RCBoat 종료 원인을 확정할 수 없음 |
| EDID / I2C `0x50` 오류 | 디스플레이 경로 등 확인. PCA 기본 주소 `0x40` 오류와 구분 |
| SQUASHFS XATTR 경고 | 이미지·커널 기능·읽기 상태를 확인. 경고만으로 SD 카드 고장을 확정하지 않음 |
| `/etc/resolv.conf` dangling symlink | 링크 대상·DNS 서비스 확인. 도메인 이름을 쓰는 통신에 영향 가능 |

ROS 서비스는 10초 재시도 간격과 120초 내 3회 시작 제한을 사용합니다. 반복 기동 실패 시 원인을 확인한 뒤 설치·검증 절차로 복구합니다.
