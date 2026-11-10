# v2.4.3 카메라 · 핑크 풍선 원거리 추적

풍선 추적은 `main`의 통합 ROS 정식 v2.4.3에 포함됩니다. 항로 주행·도보 테스트와 같은 앱을 사용합니다. ROS 이전 v1.6.0은 별도 레거시 폴더와 브랜치에 보존합니다. 새 프로젝트 폴더는 `RCBoatControl_v2.4.3`이며 Jetson에는 한 버전의 ROS backend만 실행합니다.

## v2.4.3 처리 구조와 실측

1080p 원본은 Jetson에 남기고 후보 영역/전체 화면을 기존 320×320 모델에 넣습니다. 가중치와 ONNX hash는 유지합니다. 장치에서 만든 TensorRT 8 FP16 엔진과 CUDA runtime I/O를 사용하며 PyCUDA·PyTorch를 추가 설치하지 않습니다. GPU binding 한 개만 분리 환경에 연결하고 전체 사용자 site-packages는 상속하지 않습니다. 설치 시 128MiB workspace로 장치 엔진을 만들거나 검증된 캐시를 재사용합니다. nvpmodel·jetson_clocks를 변경하지 않습니다. CPU fallback에서는 10fps를 보장하지 않습니다.

감지와 JPEG 생성은 별도 주기로 최대 12Hz입니다. 전송용 JPEG 기본값은 480×270 이하·품질 50이며, 원본 1080p와 신경망 입력 320은 그대로입니다. 먼저 크기를 줄인 뒤 표시를 그려 전체 해상도 복사를 줄이고, 새 원본 프레임만 처리합니다. 화면 요청이 없으면 JPEG 인코딩을 생략합니다. 제어 desired는 감지 완료 때 발행하고 상태/원본 JSONL은 5Hz를 유지합니다. 모델이 없을 때 빈 검사를 감지 fps로 세지 않습니다.

2026-11-10 Nano 실제 1920×1080 CSI 시험에서 30초 평균 감지 11.96fps·미리보기 11.93fps, 별도 120초에서 11.78fps·11.81fps였습니다. 이 진단의 전송 영상은 640×360·품질 55였습니다. 120초의 프로세스 CPU는 166.5%(4코어 전체 기준 약 41.6%), 종료 시 CPU/GPU 온도 센서는 25°C/22°C, MemAvailable 약 990MiB였습니다. 미리보기 평균 JPEG는 약 13.2kB, 최대 원본 age는 0.127초였습니다. ROS 서비스들은 실행하되 진단용 publisher를 메모리에 대체한 경로로 측정했으며 actuator는 열지 않았습니다.

실제 ROS backend와 PC Wi-Fi를 함께 사용하는 30.23초 시험에서는 감지 11.80fps·서로 다른 수신 영상 10.29fps를 확인했습니다. 전송 영상은 최종 기본값 480×270·품질 50, 평균 7.93kB, 최대 age 0.168초였으며 앱과 같은 60ms 요청 주기를 사용했습니다. HTTP/1.1 연결 한 개를 유지하고 재접속은 0회였습니다. 기존 640×360 전송은 같은 Wi-Fi에서 9.96fps였기에 전송 크기만 낮췄습니다. 모바일의 실제 화면 표시 계수는 별도 확인에서 10.2fps였으나 순간 표시이며 30초 평균은 아닙니다. 모든 시험에서 AUTO_SAFE/6000·6450 잠금을 유지했습니다. 수상 연속 운항·실물 파열·출력 시험은 별도입니다.

실제 원본 3장과 당시 선택된 입력 crop을 그대로 CPU FP32/GPU FP16에 재생한 비교에서 각 1개 검출을 유지했습니다. 신뢰도 차이 최대 약 0.00150, bbox IoU 0.99847~0.99931이었습니다. 입력별 수치 비교이며 거리별 검출률·실제 풍선 파열·100m 성능을 증명하는 시험은 아닙니다.

## 근접 소실과 비상정지

중앙 45% 안에 있는 풍선이 화면 높이 80% 이상 또는 면적 40% 이상으로 두 번 이상 관측된 뒤 사라지면 즉시 중립으로 확인합니다. 신선한 카메라에서 최소 3회 유실과 0.35초가 확인되면 `BALLOON_POP_ESTIMATED`로 기록하고 MANUAL로 전환합니다. 영상만으로 실제 파열을 확정할 수 없어 표시도 ‘파열 추정’입니다. 일반적인 일시 가림·화면 가장자리 이탈·지나침에서는 기존 위치 예측·되돌아가기를 유지합니다. 카메라 자체의 단절/만료는 파열로 분류하지 않습니다.

목표 도착·확정 SSH 단절·추진/RC/카메라 이상은 수동 전환 사유입니다. E-STOP 잠금은 명시적인 비상정지 요청에서만 설정하며 자동으로 해제하지 않습니다. 상태와 이벤트에 `estop_reason`, `estop_origin`, `estop_time_utc`를 저장하고 GUI에는 한국 시각으로 표시합니다. 해제 후에도 수동 중립 재허용이 필요하며 추적·항로는 자동 재시작하지 않습니다.

## 이전 수정

v2.4.2는 안전 판단과 입력 교체를 같은 잠금으로 보호하고, actuator의 명령·수신 시각·판정 시각을 한 번에 읽습니다. 판정 도중 새 콜백의 시각이 앞서 보이면서 발생하던 잘못된 timeout을 제거합니다. `FAILSAFE_MANUAL` 이벤트에 actuator 원본과 각 입력의 판정 당시 age를 기록하고 출력 상태에 명령 수신 시각·age·source를 추가합니다. 실제 timeout 기준과 수동 재허용 절차는 유지합니다. SSH를 끊은 뒤 MANUAL에서는 유효한 조종기 입력이 출력을 결정합니다. 앱 종료가 서보 전원 차단을 의미하지 않습니다. 소리가 계속 나면 선체 전원을 끄고 무부하 상태의 전원·링크 간섭을 확인한 후 사용합니다. 이번 수정에서 물리적 서보 출력 시험은 하지 않습니다.

v2.4.1의 가중치와 감지 알고리즘은 v2.4.0과 같습니다. 모바일 연결/영상 전송을 수정한 버전입니다. 2026-11-10 사용자가 약 8m에 둔 23cm 풍선 장면의 원본 사진에서 약 42px, 신뢰도 0.89, 핑크 비율 0.90으로 확인했습니다. 같은 사진을 여러 번 추론한 결과를 독립 영상/감지율 시험으로 세지 않습니다. 조명을 켠 뒤 인식됐다는 사용자 확인이 있었으며 이 장면으로 다른 거리나 어두운 환경의 성능을 보장하지 않습니다.

## 100m 목표와 현재 검증 범위

기존 640×480 → 320 입력은 작은 물체를 과도하게 줄입니다. v2.4.1은 1920×1080 원본을 사용하고, 작은 핑크 후보 영역을 골라 320 모델에 넣습니다. 색상 후보만으로 추적·출력을 시작하지 않고 신경망 풍선 검출, 원본 픽셀의 핑크 확인, 연속 관측 확인을 통과해야 합니다. 가까워지면 전체 화면을 사용하고, 기존 위치 예측·재접근·수동 전환·E-STOP을 유지합니다.

풍선 지름과 실제 카메라 화각이 아직 확인되지 않았으므로 **최소 100m 추적 성공을 보장하지 않습니다.** 아래는 수평 화각 62.2°를 가정한 핀홀 계산입니다. 거리 측정값이나 실험 결과가 아닙니다.

| 100m에서 풍선 지름 | 640 원본 폭 | 1920 원본 폭 | 320 전체 화면 입력 |
|---|---:|---:|---:|
| 0.3m 가정 | 약 1.6 px | 약 4.8 px | 약 0.8 px |
| 0.5m 가정 | 약 2.7 px | 약 8.0 px | 약 1.3 px |
| 1.0m 가정 | 약 5.3 px | 약 15.9 px | 약 2.7 px |

원거리 영역 선택은 원본의 8~16픽셀을 신경망 입력에서 더 크게 보존합니다. 초점·렌즈·모션 블러로 이미 사라진 형상은 복원하지 않습니다. 지름 0.5m를 100m에서 16픽셀 이상 확보하려면 1920 원본 기준 계산상 수평 화각 약 33° 이하가 필요합니다. 실제 센서 읽기 모드/렌즈의 화각은 직접 보정해야 합니다. IMX219라는 센서명만으로 화각을 확정할 수 없습니다. [공식 카메라 사양](https://www.raspberrypi.com/documentation/accessories/camera.html)을 참고하되 사용 장치가 같은 렌즈인지 확인합니다.

현재 추가 학습은 원본 2,189장의 기존 분할을 보존합니다. 학습용 원본 1,746장에 크기/시야 증강 3,492개와 핑크 비풍선 배경 500개를 추가했습니다. 증강 시야는 새 원본 사진이나 실측 100m 자료로 세지 않습니다. 별도 보류 원본 244장은 학습에 사용하지 않습니다. 모델·전체 영상 방식·원거리 영역 방식의 비교 결과는 `models/long_range_evaluation.json`, 일반 사진 성능은 `models/runtime_evaluation.json`에 저장합니다. 이 비교는 실제 해상·실측 거리 성능과 구분합니다.

모델은 기존 가중치에서 30 epoch 추가 학습했습니다. 보류 원본 244장, 신뢰도 0.35/IoU 0.5의 신경망 검출 비교는 정밀도 74.1% → 76.9%, 재현율 58.6% → 61.2%입니다. 이는 모든 색 풍선 검출 수치이며 핑크 풍선의 실제 100m 성공률이 아닙니다.

작은 대상 개발 비교는 보류 사진 40장의 풍선 조각을 인공 배경에 배치한 200개 시퀀스(각 6프레임)입니다. 모든 방식에 같은 원본 픽셀 형태 확인을 적용했습니다. 기존 가중치+전체 화면은 16/200, 기존 가중치+원거리 영역은 111/200, 새 가중치+원거리 영역은 139/200에서 연속 포착했습니다. 새 방식의 8/12/16/24/32픽셀별 연속 포착은 12/28/31/34/34개(각 40개 중)입니다. **8픽셀에서는 여전히 유실이 많습니다.** 분홍색 띠 30개 개발 배경의 오포착은 0개였지만, 이 배경은 형태 필터 개발에도 사용했으므로 독립적인 해상 오탐 검증 수치가 아닙니다. 추가로 실제 물결·선체·다른 물체 자료가 필요합니다.

작은 검출은 가장 큰 핑크 연결 영역이 가늘고 긴 띠이면 확정하지 않습니다. 이 검사는 신경망 검출 뒤의 거부 조건이며 색상만으로 풍선을 생성하지 않습니다.

기본 원거리 모드는 영상 한 번당 신경망 추론 한 번, 최대 12개 색상 후보 탐색, 최신 영상 한 장만 사용합니다. 수많은 타일을 한꺼번에 추론하는 방식을 기본으로 사용하지 않습니다. 80m였던 위치 추정 상한은 200m로 늘렸으며, 충분한 이동 기하와 잔차 검사를 통과하지 않으면 좌표를 만들지 않습니다. 풍선 크기를 모르는 상태에서 크기만으로 거리를 표시하지 않습니다.

## 아직 Jetson에 적용하지 않았다면

1. v2.4.3 전체 ZIP을 풀고 PC·모바일 관제 앱을 종료합니다. Jetson을 같은 네트워크/휴대폰 핫스팟에 연결합니다. Jetson의 `hostname -I` 또는 핫스팟 연결 기기 목록에서 현재 IP를 확인합니다.
2. **Windows PowerShell**에서 다음 순서로 전송합니다. IP는 접속할 때 입력합니다.

```powershell
Set-Location -LiteralPath "C:\Users\smini\OneDrive\바탕 화면\RCBoatControl_Complete_2026-09-25_UPDATED\RCBoatControl_v2.4.3"
$jetsonIp = Read-Host "Jetson 현재 IP"
if (-not (Test-NetConnection $jetsonIp -Port 22 -InformationLevel Quiet)) { throw "SSH 연결 불가" }
$env:RCBOAT_NO_PAUSE = "1"
.\DEPLOY_ROS.cmd -Destination "jetson@$jetsonIp"
if ($LASTEXITCODE -ne 0) { throw "전송 실패: 설치하지 마세요" }
ssh "jetson@$jetsonIp"
```

3. **Jetson SSH 안에서** 처음 영상 환경 설치와 ROS 적용을 실행합니다. ROS Noetic이 이미 설치된 Ubuntu 20.04 Jetson/account `jetson` 기준입니다. 수동 `roslaunch`가 실행 중이면 그 터미널에서 먼저 Ctrl+C로 종료합니다.

```bash
cd /home/jetson/rcboat_ros_ws
bash deployment/jetson/install_vision_dependencies.sh
```

`VISION INSTALL VERIFIED`가 나온 뒤 실행합니다.

```bash
bash deployment/jetson/install_jetson_ros.sh
```

완료 기준은 `RUNNING GATEWAY VERIFIED: v2.4.3`입니다. 설치 스크립트가 ROS를 시작하므로 추가로 `roslaunch`를 중복 실행하지 않습니다. 기존 항로·로그·NTRIP 자격정보는 유지합니다. 옛 카메라 설정에는 1080p/원거리 모드를 한 번 적용하고 원본 `~/.rcboat/vision.json.before_v2.4.0_*`을 보존합니다. 이후 사용자가 설정한 해상도나 원거리 끄기는 덮어쓰지 않습니다.

4. GUI를 열기 전, 실제 카메라/처리 시간을 검사합니다. 아래는 기존 IMX219 CSI/sensor 0 예시이며 실제 연결 방식이 다르면 `--camera-type usb`를 사용합니다. GUI의 카메라는 꺼둡니다.

```bash
~/.rcboat/vision-venv/bin/python3 deployment/jetson/check_vision.py --live --camera-type csi --sensor-id 0
```

`actual_frame_height_width`가 `[1080, 1920]`, `requested_resolution_met`가 `true`인지 확인합니다. 실제 프레임이 640×480이면 100m용 원본 픽셀을 확보한 것이 아닙니다. `mean/p95_inference_ms`도 확인합니다. 위 실측 구성 외의 처리 성능은 장치에서 측정해야 합니다. CPU fallback과 다른 부하에서 같은 fps를 보장하지 않습니다.

5. 선택적으로 Jetson에서만 FP16 TensorRT 엔진을 만듭니다. 이전 모델용 엔진은 새 모델 SHA와 다르면 거부하고 ONNX로 대체합니다.

```bash
~/.rcboat/vision-venv/bin/python3 deployment/jetson/build_vision_engine.py models/balloon_yolov8n.onnx
```

6. PC EXE 또는 모바일 APK v2.4.3 한 개를 제어 연결합니다. 풍선 화면 → 카메라 설정 → CSI/센서 0(장치에 맞게 변경) → 1920×1080 → 작은 풍선 원거리 감지 체크 → 저장 → 카메라 켜기입니다. 실제 감지 상자와 작은 대상 확대 창이 표시됩니다. 전체 영상 통신량은 기존 640×360 이하 JPEG를 유지합니다.

## 거리별 감지 확인 후 추적 시작

먼저 E-STOP으로 출력을 잠근 채 감지만 검사합니다. 풍선 지름을 측정하고 10/30/50/100m에서 원본 영상, 감지 유지 여부, 오탐과 원본 픽셀 크기를 기록합니다. 미리보기 확대만으로 100m 합격을 판단하지 않습니다. 선체·물결·핑크 물체를 풍선으로 잘못 인식하지 않는지도 포함합니다. 실제 100m에서 신뢰할 수 있는 연속 감지와 조향 방향을 확인한 뒤 추적을 시작합니다.

실측 자료를 남기려면 GUI 카메라를 끄고 E-STOP을 유지한 상태에서 Jetson SSH에서 실행합니다. 입력 거리는 사람이 확인한 값으로 기록하며 도구가 거리를 측정하는 것은 아닙니다. 지름을 모르면 `--diameter-m`은 생략합니다.

```bash
cd /home/jetson/rcboat_ros_ws
~/.rcboat/vision-venv/bin/python3 deployment/jetson/capture_range_test.py --camera-type csi --sensor-id 0 --distance-m 100 --seconds 20
```

원본 사진과 시각/해상도/버전/거리 입력값이 `~/rcboat_ros_data/vision_validation/range_100m_*.zip`에 저장됩니다. 이 도구는 모터 명령을 발행하지 않습니다. **Windows PowerShell**에서 받을 수 있습니다.

```powershell
scp "jetson@${jetsonIp}:/home/jetson/rcboat_ros_data/vision_validation/*.zip" "$env:USERPROFILE\Downloads\"
```

사진에서 실제 풍선 위치를 표시한 뒤 감지율·오탐·유실/복구를 평가해야 100m 수용 여부를 판단할 수 있습니다. 원본 촬영만으로 자동 합격 처리하지 않습니다.

## 기존 설치·운항 설명

v2.3.1은 설치 환경 수정입니다. NumPy 1.23.5·ONNX Runtime 1.16.3과 ROS용 Python 의존성을 전용 가상환경에 고정합니다. 기존 `--system-site-packages` 환경은 날짜가 붙은 `~/.rcboat/vision-venv.backup-*`로 보존하고 새 환경에서는 전역 TensorFlow·사용자 NumPy를 읽지 않습니다. 기존 OpenCV/GStreamer·선택적 GPU 바인딩과 ROS의 netifaces만 이름별로 연결합니다. 전역 Python 패키지를 삭제하거나 pip OpenCV로 덮어쓰지 않습니다. NumPy 배열→OpenCV 연산, ONNX Runtime CPU의 실제 모델 20회 추론, catkin 재빌드 후 ROS import를 확인하며 실패하면 설치를 중단합니다. v2.3.0의 항법·추적·모델은 변경하지 않습니다.

## 화면 사용

- 상단: 연결·독립 상태 표시, 모드, 순항 목표 PWM, E-STOP. `연결 설정`을 누르면 SSH 정보와 상세 장치 상태가 나옵니다.
- 실시간 관제: 큰 지도, 운항 핵심 수치. GPS·RC 입력은 지도 옆 보조 탭, 출력 차트는 접기 버튼에 있습니다. 정상은 초록, 주의는 노랑, 오류·stale은 빨강, 미수신은 회색으로 표시합니다.
- 항로·Multi-Path: **대루트/소루트 선택·주행 시작·정지는 지도 위에 고정**합니다. 오른쪽 `항로 기록`에서 기존 GPS 기록·정지 후 저장·취소를 그대로 사용합니다. 편집과 표시 설정만 별도 탭으로 묶습니다. 지도 위에서는 마우스 휠만으로 커서 위치를 기준으로 확대·축소합니다. Ctrl+휠과 +/− 버튼도 유지합니다. 지도 밖의 기존 스크롤은 그대로입니다.
- GPS·RTK: 핵심 GPS 상태와 RTK 연결 두 탭입니다. 상세 품질·참고 기준·GPS 원시 기록은 GPS 상태 아래의 접기 영역에 모았습니다. RTK 설정은 **Jetson의 기존 `~/rcboat_ros_data/ntrip.env`**에서 읽습니다. `Jetson 설정 불러오기`는 조회만 하며, 빈 비밀번호 입력은 기존 비밀번호를 유지합니다. 연결이 잠시 끊겨도 입력란을 빈값으로 덮어쓰지 않습니다.
- 풍선 추적: 카메라 켜기 → 연속 핑크 풍선 검출 확인 → 추적 주행 시작. 정지·카메라 끄기·대상 다시 잡기와 로그 가져오기를 제공합니다. 화면에 표시되는 SIMULATION은 실제 카메라나 모터 검증이 아닙니다.

## 인식·추적

YOLOv8n 단일 `balloon` 클래스로 풍선 모양을 검출한 뒤 HSV 핑크 비율을 확인합니다. 핑크 물체만 보고 모터를 구동하지 않습니다. 기본 신뢰도 0.35, 핑크 비율 0.12, 연속 3프레임 확인을 사용합니다. 초록 상자는 핑크 풍선 검출, 회색 상자는 풍선 검출 중 핑크 조건 미달입니다.

풍선 추적 화면은 실시간 영상, 감지 상자, 추적 시작·정지·로그만 중심에 둡니다. 카메라 설정은 오른쪽에서 왼쪽으로 펼쳐지는 별도 패널이며, 영상 영역이 줄어들어 설정창이 영상을 덮지 않습니다. 마스코트는 사이드바의 작은 32 px 아이콘으로 표시합니다. `풍선 추적 시작`을 누르면 카메라를 켜고 연속 검출이 확보되는 즉시 추적 시작 명령을 한 번 보냅니다. 실제 카메라·GPS·안전 조건을 backend가 승인해야 출력됩니다. 카메라만 켠 경우에는 주행하지 않습니다.

내부 추적에는 영상 중심점·이동 속도·크기 변화, GPS 이동·방위 기반 풍선 위치 추정을 유지합니다. 풍선을 지나쳐 카메라 뒤쪽에 있다고 판단하면 좌우 조향을 자동으로 정해 선회하고 추정 위치로 다시 접근합니다. 영상이 돌아오면 즉시 실제 검출을 따릅니다. 잠깐 가려지면 직전 방향을 예측해 추적을 이어갑니다. 관측 기하가 부족하거나 GPS 방향이 불안정하면 정확한 좌표를 만들어 내지 않고 영상 추세와 마지막 사라진 방향을 사용합니다.

위치 추정·재접근·좌우 조향은 내부에서 자동 처리합니다. 예측 시간·탐색 범위·시야각·조향 보정 같은 세부 조절 항목은 GUI에 나열하지 않습니다. 조향 방향은 기존 `nav_invert_steering` 설정을 공통 사용합니다. 기본 카메라 시야각은 62° 가정이며 실제 카메라 선택·장착 후 보정이 필요합니다. 이런 수치 계산은 경량이며 주된 연산 비용은 영상 신경망 추론입니다.

풍선을 향해 공통 순항 목표 PWM으로 접근합니다. 실제 파열 여부를 확인하는 센서는 없으므로 사라졌다는 이유로 `터짐 성공`을 기록하지 않습니다. 최신 카메라 영상은 살아 있어도 15초간 유효한 대상을 전혀 확인하지 못하면 기존 안전 수동 전환을 유지합니다. 카메라 정지·오래된 프레임은 이 유예와 별개로 즉시 출력 유효성을 잃습니다.

속도는 상단 **GPS 항법 순항 PWM**과 공통입니다. 기본 6650, 범위 6480~7390(10 간격) 및 끝값 7397입니다. 출발 6650 이하에서 120 PWM/s로 상승하며 목표 감속은 즉시 반영합니다. 큰 방향 오차와 가려진 대상의 추적 유지 구간에서는 감속합니다. PWM은 실제 m/s와 비례하지 않습니다. 수동·원격·기존 P 항법·Multi-Path 계산은 그대로 유지합니다.

SSH 단순 응답 지연은 기존 확인 유예를 사용합니다. GPS 데이터 stale에는 기존 항법과 같은 기본 5초 유예를 적용하고 최신 영상 추적을 계속합니다. 확정된 연결 단절, 무효 FIX·GPS I/O 오류, 카메라/추론 stale, RC·출력 오류, E-STOP, 유예 만료는 기존 안전 제어가 우선합니다. 카메라 영상 없이 무제한 항해하지 않습니다. 새 추적 세션의 명령만 출력하며, 이전 미리보기 명령으로 출발하지 않습니다.

## Jetson Nano 부담과 호환 범위

학습은 PC에서 수행합니다. Jetson에는 PyTorch/Ultralytics 학습 환경을 설치하지 않습니다. 정적 320×320 ONNX, 배치 1, 기본 추론 목표 12 Hz, 최신 프레임 한 장만 처리합니다. 장치에서 생성한 TensorRT 8 엔진이 있으면 우선 사용하고 ONNX Runtime CPU, OpenCV DNN CPU 순서로 대체합니다. 과거 v2.3.1의 2026-11-04 Nano ORT CPU 검사에서 빈 영상 20회 평균 324.64 ms, CSI 실영상 평균 347.88 ms/p95 540.02 ms였습니다. 이는 v2.4.1의 1080p 원거리 경로 성능 시험이 아닙니다. 새 경로의 속도는 장치에서 별도로 검사합니다.

USB V4L2와 Jetson Argus CSI를 지원하며 자동은 USB → CSI 순서입니다. Pi 카메라는 센서·CSI 케이블·Jetson 드라이버가 일치해야 합니다. 기종 미정 상태에서 모든 Pi 카메라의 동작을 보장하지 않습니다. RTSP/파일은 미리보기만 가능하고 실물 주행 시작에는 사용할 수 없습니다.

실제 연결 장치는 `/dev/video0`의 IMX219 CSI 센서로 확인했습니다. Jetson 로컬 카메라 설정은 CSI/sensor 0으로 적용했고, 실제 프레임 20회 처리와 PC→8766 JPEG 미리보기 수신을 확인했습니다. 검사 후 카메라는 다시 껐고 추적 모드·arming 명령은 보내지 않았습니다. 시험 중 핑크 풍선 검출은 0건이었으므로 대회 풍선 인식 성능을 검증한 결과로 해석하지 않습니다.

미리보기는 TCP 8766의 JPEG 요청 방식, 기본 최대 12 fps, 480×270 이하, JPEG 품질 50입니다. HTTP/1.1 연결 재사용·ETag 중복 생략·작은 응답의 즉시 전송을 사용합니다. 추적 명령과 heartbeat는 기존 TCP 8765를 사용합니다. 풍선 페이지가 숨겨져 있거나 영상 표시를 끄면 요청을 중단하고 Jetson도 요청이 없으면 JPEG 인코딩을 생략합니다. 실제 전송량·추론 시간·처리 fps를 표시합니다. 12 fps는 설정 상한이며 실제 새 프레임 처리·수신 횟수를 확인합니다. `RCBOAT_GATEWAY_TOKEN` 설정 시 영상도 같은 토큰을 사용합니다. 지도는 선택한 경우에만 OpenStreetMap 타일을 받고 로컬 캐시와 표시 영역 제한을 적용합니다.

## Windows 실행·빌드

```powershell
# 새 폴더의 빌드된 앱
.\dist\RCBoatControl_ROS_v2.4.3.exe
# 다시 빌드할 때
.\BUILD_ROS_GUI.cmd
```

현재 Jetson IP를 연결 설정에 입력합니다. 휴대폰 핫스팟의 연결 기기 IP도 사용할 수 있습니다. GUI와 backend 버전이 다르면 신규 주행은 차단합니다.

## 기록·학습 재현

추적 로그는 `~/rcboat_ros_data/logs/vision/vision_*.jsonl`에 UTC, 실제 검출·색상 비율, 예측 상태·위치, 모델·설정, GPS, 안전 판단, 명령·출력 전송 결과를 기록합니다. GUI는 최신 로그를 manifest·SHA-256을 포함한 ZIP으로 내려받습니다. 기록 중 다운로드는 마지막 완성 JSON 행까지의 snapshot입니다. 32 MiB보다 큰 파일은 SCP로 가져옵니다. 기존 도보 CSV/JSONL·기준 항로 export는 그대로 유지합니다.

기존 Open Images 원본 분할(학습 1,746/검증 199/시험 244)은 그대로 보존합니다. 원거리 모델은 `prepare_small_objects.py`의 시야 증강·핑크 배경 음성 패치를 더해 기존 가중치를 추가 학습합니다. `model_manifest.json`에 부모 가중치 hash·원본 ID·분할·증강 기록을 보존합니다. `training_report.json`과 `long_range_evaluation.json`에서 실제 시험과 합성 픽셀 시험을 구분합니다. 실제 100m 자료 수는 현재 0입니다.

학습을 재현할 때는 Python 3.12/PyTorch CUDA 환경과 `training/requirements.txt`, 기존 Open Images 자료가 필요합니다. 원본 자료는 이전 [학습 자료 폴더](https://drive.google.com/drive/folders/1SXWVRvEo1ZDCrLwWCS21Nr0myx4XVzaA)를 사용할 수 있습니다. 부모 checkpoint는 [v2.3.3 전체 ZIP](https://github.com/smini131-maker/RC-BOAT/releases/tag/v2.3.3)의 `models/balloon_yolov8n.pt`입니다. 아래 경로는 사용자 PC에 맞게 바꿉니다.

```powershell
.\training\.venv\Scripts\python.exe training\prepare_small_objects.py --source "C:\RCBoatTraining\openimages_dataset" --output "C:\RCBoatTraining\small_dataset"
.\training\.venv\Scripts\python.exe training\finetune_small.py --weights "C:\RCBoatTraining\v2.3.3\balloon_yolov8n.pt" --data "C:\RCBoatTraining\small_dataset\data.yaml" --output "C:\RCBoatTraining\small_runs" --epochs 30 --batch 64 --workers 2
```

후보는 별도 `candidate` 폴더로 내보냅니다. 정상 사진·작은 대상·음성 배경을 비교한 뒤에만 모델과 manifest를 함께 적용합니다. 새 ONNX에는 기존 장치용 TensorRT engine을 재사용하지 않습니다. 학습 원본이나 보정 자격정보를 GitHub에 올리지 않습니다.

## 참고·출처

- [QGroundControl 화면 구성](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/ui_overview.html): 지도 중심 운항 화면과 계획/설정 분리를 참고했습니다.
- [YOLOv8](https://docs.ultralytics.com/models/yolov8/), [Jetson 지원 안내](https://docs.ultralytics.com/guides/nvidia-jetson/): 경량 모델·장치별 TensorRT 사용.
- [Open Images V6](https://storage.googleapis.com/openimages/web/factsfigures.html): Kuznetsova et al., IJCV 2020. 이미지별 원저작자·원본 링크·라이선스는 학습 자료의 `image_attribution.csv`에 보존합니다. 크기 조정·JPEG 재인코딩을 수행했습니다.
- [OpenStreetMap 타일 정책](https://operations.osmfoundation.org/policies/tiles/): 표시 영역만 요청, User-Agent·출처 표시·캐시 사용, 대량 사전 다운로드 없음.

Ultralytics 모델/도구는 AGPL-3.0, 기존 프로젝트 코드의 라이선스는 루트 LICENSE를 따릅니다. 모델의 원본 라이선스는 `models/ULTRALYTICS_LICENSE.txt`에 보존합니다.
