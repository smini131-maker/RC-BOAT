# v2.3.1 카메라 · 핑크 풍선 추적

풍선 추적은 `main`의 통합 정식 v2.3.1에 포함됩니다. 항로 주행·도보 테스트와 같은 앱을 사용하며, 별도의 비카메라 최신 버전은 운영하지 않습니다. 로컬 프로젝트 폴더는 `RCBoatControl_v2.3.1`입니다. Jetson에는 한 버전의 ROS backend만 실행합니다.

v2.3.1은 설치 환경 수정입니다. NumPy 1.23.5·ONNX Runtime 1.16.3과 ROS용 Python 의존성을 전용 가상환경에 고정합니다. 기존 `--system-site-packages` 환경은 날짜가 붙은 `~/.rcboat/vision-venv.backup-*`로 보존하고 새 환경에서는 전역 TensorFlow·사용자 NumPy를 읽지 않습니다. 기존 OpenCV/GStreamer·선택적 GPU 바인딩과 ROS의 netifaces만 이름별로 연결합니다. 전역 Python 패키지를 삭제하거나 pip OpenCV로 덮어쓰지 않습니다. NumPy 배열→OpenCV 연산, ONNX Runtime CPU의 실제 모델 20회 추론, catkin 재빌드 후 ROS import를 확인하며 실패하면 설치를 중단합니다. v2.3.0의 항법·추적·모델은 변경하지 않습니다.

## 화면 사용

- 상단: 연결·독립 상태 표시, 모드, 순항 목표 PWM, E-STOP. `연결 설정`을 누르면 SSH 정보와 상세 장치 상태가 나옵니다.
- 실시간 관제: 큰 지도, 운항 핵심 수치. GPS·RC 입력은 지도 옆 보조 탭, 출력 차트는 접기 버튼에 있습니다. 정상은 초록, 주의는 노랑, 오류·stale은 빨강, 미수신은 회색으로 표시합니다.
- 항로·Multi-Path: **대루트/소루트 선택·주행 시작·정지는 지도 위에 고정**합니다. 오른쪽 `항로 기록`에서 기존 GPS 기록·정지 후 저장·취소를 그대로 사용합니다. 편집과 표시 설정만 별도 탭으로 묶습니다. 일반 휠은 지도 확대에 사용하지 않고 Ctrl+휠 또는 +/− 버튼으로 확대합니다.
- GPS·RTK: 핵심 GPS 상태와 RTK 연결 두 탭입니다. 상세 품질·참고 기준·GPS 원시 기록은 GPS 상태 아래의 접기 영역에 모았습니다. RTK 설정은 **Jetson의 기존 `~/rcboat_ros_data/ntrip.env`**에서 읽습니다. `Jetson 설정 불러오기`는 조회만 하며, 빈 비밀번호 입력은 기존 비밀번호를 유지합니다. 연결이 잠시 끊겨도 입력란을 빈값으로 덮어쓰지 않습니다.
- 풍선 추적: 카메라 켜기 → 연속 핑크 풍선 검출 확인 → 추적 주행 시작. 정지·카메라 끄기·대상 다시 잡기와 로그 가져오기를 제공합니다. 화면에 표시되는 SIMULATION은 실제 카메라나 모터 검증이 아닙니다.

## 인식·추적

YOLOv8n 단일 `balloon` 클래스로 풍선 모양을 검출한 뒤 HSV 핑크 비율을 확인합니다. 핑크 물체만 보고 모터를 구동하지 않습니다. 기본 신뢰도 0.35, 핑크 비율 0.12, 연속 3프레임 확인을 사용합니다. 초록 상자는 핑크 풍선 검출, 회색 상자는 풍선 검출 중 핑크 조건 미달입니다.

풍선 추적 화면은 실시간 영상, 감지 상자, 추적 시작·정지·로그만 중심에 둡니다. 카메라 설정은 오른쪽에서 왼쪽으로 펼쳐지는 별도 패널이며, 영상 영역이 줄어들어 설정창이 영상을 덮지 않습니다. 마스코트는 사이드바의 작은 32 px 아이콘으로 표시합니다. `풍선 추적 시작`을 누르면 카메라를 켜고 연속 검출이 확보되는 즉시 추적 시작 명령을 한 번 보냅니다. 실제 카메라·GPS·안전 조건을 backend가 승인해야 출력됩니다. 카메라만 켠 경우에는 주행하지 않습니다.

내부 추적에는 영상 중심점·이동 속도·크기 변화, GPS 이동·방위 기반 풍선 위치 추정을 유지합니다. 풍선을 지나쳐 카메라 뒤쪽에 있다고 판단하면 좌우 조향을 자동으로 정해 선회하고 추정 위치로 다시 접근합니다. 영상이 돌아오면 즉시 실제 검출을 따릅니다. 잠깐 가려지면 직전 방향을 예측해 추적을 이어갑니다. 관측 기하가 부족하거나 GPS 방향이 불안정하면 정확한 좌표를 만들어 내지 않고 영상 추세와 마지막 사라진 방향을 사용합니다.

위치 추정·재접근·좌우 조향은 내부에서 자동 처리합니다. 예측 시간·탐색 범위·시야각·조향 보정 같은 세부 조절 항목은 GUI에 나열하지 않습니다. 조향 방향은 기존 `nav_invert_steering` 설정을 공통 사용합니다. 기본 카메라 시야각은 62° 가정이며 실제 카메라 선택·장착 후 보정이 필요합니다. 이런 수치 계산은 경량이며 주된 연산 비용은 영상 신경망 추론입니다.

풍선을 향해 공통 순항 목표 PWM으로 접근합니다. 실제 파열 여부를 확인하는 센서는 없으므로 사라졌다는 이유로 `터짐 성공`을 기록하지 않습니다. 최신 카메라 영상은 살아 있어도 15초간 유효한 대상을 전혀 확인하지 못하면 기존 안전 수동 전환을 유지합니다. 카메라 정지·오래된 프레임은 이 유예와 별개로 즉시 출력 유효성을 잃습니다.

속도는 상단 **GPS 항법 순항 PWM**과 공통입니다. 기본 6650, 범위 6480~7390(10 간격) 및 끝값 7397입니다. 출발 6650 이하에서 기존 약 166.7 PWM/s로 상승하며 목표 감속은 즉시 반영합니다. 큰 방향 오차와 가려진 대상의 추적 유지 구간에서는 감속합니다. PWM은 실제 m/s와 비례하지 않습니다. 수동·원격·기존 P 항법·Multi-Path 계산은 그대로 유지합니다.

SSH 단순 응답 지연은 기존 확인 유예를 사용합니다. GPS 데이터 stale에는 기존 항법과 같은 기본 5초 유예를 적용하고 최신 영상 추적을 계속합니다. 확정된 연결 단절, 무효 FIX·GPS I/O 오류, 카메라/추론 stale, RC·출력 오류, E-STOP, 유예 만료는 기존 안전 제어가 우선합니다. 카메라 영상 없이 무제한 항해하지 않습니다. 새 추적 세션의 명령만 출력하며, 이전 미리보기 명령으로 출발하지 않습니다.

## Jetson Nano 부담과 호환 범위

학습은 PC에서 수행합니다. Jetson에는 PyTorch/Ultralytics 학습 환경을 설치하지 않습니다. 정적 320×320 ONNX, 배치 1, 기본 추론 목표 5 Hz, 최신 프레임 한 장만 처리합니다. 장치에서 생성한 TensorRT 8 엔진이 있으면 우선 사용하고 ONNX Runtime CPU, OpenCV DNN CPU 순서로 대체합니다. 2026-11-04 실제 Nano의 ORT CPU 검사에서 빈 영상 20회 평균 324.64 ms, IMX219 CSI 실영상 20회 평균 347.88 ms/p95 540.02 ms였습니다. 캡처·인코딩·전송을 모두 포함한 GUI fps 또는 인식 정확도 시험은 아니며, 현재 CPU 조건에서 목표 5 Hz 달성을 보장하지 않습니다.

USB V4L2와 Jetson Argus CSI를 지원하며 자동은 USB → CSI 순서입니다. Pi 카메라는 센서·CSI 케이블·Jetson 드라이버가 일치해야 합니다. 기종 미정 상태에서 모든 Pi 카메라의 동작을 보장하지 않습니다. RTSP/파일은 미리보기만 가능하고 실물 주행 시작에는 사용할 수 없습니다.

실제 연결 장치는 `/dev/video0`의 IMX219 CSI 센서로 확인했습니다. Jetson 로컬 카메라 설정은 CSI/sensor 0으로 적용했고, 실제 프레임 20회 처리와 PC→8766 JPEG 미리보기 수신을 확인했습니다. 검사 후 카메라는 다시 껐고 추적 모드·arming 명령은 보내지 않았습니다. 시험 중 핑크 풍선 검출은 0건이었으므로 대회 풍선 인식 성능을 검증한 결과로 해석하지 않습니다.

미리보기는 TCP 8766의 JPEG 요청 방식, 기본 최대 5 fps, 640×360 이하, JPEG 품질 55입니다. 추적 명령과 heartbeat는 기존 TCP 8765를 사용합니다. 풍선 페이지가 숨겨져 있거나 영상 표시를 끄면 요청을 중단하고 Jetson도 요청이 없으면 JPEG 인코딩을 생략합니다. 실제 전송량·추론 시간·처리 fps를 표시합니다. 5 fps는 설정 목표이며 장치 처리 한계를 넘는 fps를 보장하지 않습니다. `RCBOAT_GATEWAY_TOKEN` 설정 시 영상도 같은 토큰을 사용합니다. 지도는 선택한 경우에만 OpenStreetMap 타일을 받고 로컬 캐시와 표시 영역 제한을 적용합니다.

## 배포 — Windows PowerShell

프로펠러를 제거하고 GUI를 종료한 뒤 최신 정식 폴더에서 실행합니다. 이전 소스는 Git 이력·과거 릴리스에서 확인합니다.

```powershell
Set-Location -LiteralPath "C:\Users\smini\OneDrive\바탕 화면\RCBoatControl_Complete_2026-09-25_UPDATED\RCBoatControl_v2.3.1"
Test-NetConnection 10.123.65.215 -Port 22
ssh -t jetson@10.123.65.215 "sudo systemctl stop rcboat_ros.service"
$env:RCBOAT_NO_PAUSE = "1"
.\DEPLOY_ROS.cmd -Destination "jetson@10.123.65.215"
ssh jetson@10.123.65.215
```

## 적용 — Jetson SSH 안

```bash
cd /home/jetson/rcboat_ros_ws
bash deployment/jetson/install_vision_dependencies.sh
```

`VISION INSTALL VERIFIED`가 나온 후 다음 명령을 실행합니다. 오류가 있으면 ROS 설치로 넘어가지 않습니다.

```bash
bash deployment/jetson/install_jetson_ros.sh
```

완료 조건은 `RUNNING GATEWAY VERIFIED: v2.3.1`입니다. 기존 항로·NTRIP 로컬 파일·시험 로그는 유지됩니다. 카메라 설정은 `~/.rcboat/vision.json`에 저장하고 부팅 시 카메라·추적은 꺼진 상태로 시작합니다.

설치 때 `tensorflow ... numpy ... incompatible`이 표시되면 기존 환경의 상속이 남은 것입니다. 전역 TensorFlow를 삭제하지 말고 새 설치 스크립트를 실행합니다. 성공 문구 앞에 `RuntimeError`, `ImportError`가 있던 이전 설치 결과는 완료로 인정하지 않습니다. 새 설치의 NumPy 경로는 `~/.rcboat/vision-venv/` 아래여야 합니다.

정지 상태에서 모델·카메라를 점검합니다. 이 명령은 PCA9685를 열거나 출력 명령을 보내지 않습니다.

```bash
~/.rcboat/vision-venv/bin/python3 deployment/jetson/check_vision.py
~/.rcboat/vision-venv/bin/python3 deployment/jetson/check_vision.py --live --camera-type auto
# CSI를 지정하려면:
~/.rcboat/vision-venv/bin/python3 deployment/jetson/check_vision.py --live --camera-type csi --sensor-id 0
```

TensorRT 8과 PyCUDA가 실제 JetPack 환경에서 사용 가능할 때만 장치에서 엔진을 생성합니다. 다른 PC의 엔진을 복사하지 않습니다. 실패하면 ONNX backend를 사용합니다.

```bash
~/.rcboat/vision-venv/bin/python3 deployment/jetson/build_vision_engine.py models/balloon_yolov8n.onnx
```

서비스 대신 터미널에서 수동 ROS 실행이 필요하면 먼저 중복 실행을 해제합니다.

```bash
sudo systemctl stop rcboat_ros.service
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_ros_ws/catkin_ws/devel/setup.bash
roslaunch rcboat_ros rcboat.launch
```

## Windows 실행·빌드

```powershell
# 새 폴더의 빌드된 앱
.\dist\RCBoatControl_ROS_v2.3.1.exe
# 다시 빌드할 때
.\BUILD_ROS_GUI.cmd
```

Jetson 주소 10.123.65.215를 입력합니다. 기존 PC 접속 설정이 있으면 그대로 복원되므로 IP가 바뀐 경우 연결 설정에서 수정합니다. GUI와 backend 버전이 다르면 신규 주행은 차단합니다.

## 기록·학습 재현

추적 로그는 `~/rcboat_ros_data/logs/vision/vision_*.jsonl`에 UTC, 실제 검출·색상 비율, 예측 상태·위치, 모델·설정, GPS, 안전 판단, 명령·출력 전송 결과를 기록합니다. GUI는 최신 로그를 manifest·SHA-256을 포함한 ZIP으로 내려받습니다. 기록 중 다운로드는 마지막 완성 JSON 행까지의 snapshot입니다. 32 MiB보다 큰 파일은 SCP로 가져옵니다. 기존 도보 CSV/JSONL·기준 항로 export는 그대로 유지합니다.

자료 원본 2,189장(학습 1,746장/검증 199장/독립 시험 244장), 물리 풍선 box 11,328개로 70 epoch 학습했습니다. 최종 학습·검증·독립 시험 지표는 `models/training_report.json`, 실제 runtime 후처리 점검은 `models/runtime_evaluation.json`, 출처·hash는 `models/model_manifest.json`에 저장합니다. 데이터 수는 증강을 새 원본으로 세지 않습니다. `training/prepare_openimages.py`는 Open Images V6 Balloon 클래스 중 실제 풍선 box를 변환하고 유사 이미지 그룹 단위로 학습/검증/시험을 나눕니다. 최종 모델에는 이전 13장 검증 모델을 재사용하지 않습니다.

PC 학습 환경 Python 3.12와 호환되는 PyTorch CUDA를 준비한 뒤 `training/requirements.txt`를 설치합니다. Google Drive의 [RC-BOAT_PinkBalloon_Training](https://drive.google.com/drive/folders/1SXWVRvEo1ZDCrLwWCS21Nr0myx4XVzaA) 폴더에 자료·라벨·출처와 결과를 보관합니다. ZIP을 같은 데이터 폴더에 풀고 실행합니다.

```powershell
py -3.12 -m venv training\.venv
.\training\.venv\Scripts\python.exe -m pip install -r training\requirements.txt
.\training\.venv\Scripts\python.exe training\train_balloon.py --data "C:\RCBoatTraining\data.yaml" --runs "C:\RCBoatTraining\runs" --epochs 70 --imgsz 320 --batch 32 --device 0
```

학습을 재실행하면 `models/`의 모델과 hash가 갱신되므로 모델·manifest를 함께 재배포합니다. 대회용 풍선·실제 카메라·수면 장면으로 검증한 결과는 아닙니다. 공개 이미지 성능과 현장 성공률을 구분합니다.

## 참고·출처

- [QGroundControl 화면 구성](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/ui_overview.html): 지도 중심 운항 화면과 계획/설정 분리를 참고했습니다.
- [YOLOv8](https://docs.ultralytics.com/models/yolov8/), [Jetson 지원 안내](https://docs.ultralytics.com/guides/nvidia-jetson/): 경량 모델·장치별 TensorRT 사용.
- [Open Images V6](https://storage.googleapis.com/openimages/web/factsfigures.html): Kuznetsova et al., IJCV 2020. 이미지별 원저작자·원본 링크·라이선스는 학습 자료의 `image_attribution.csv`에 보존합니다. 크기 조정·JPEG 재인코딩을 수행했습니다.
- [OpenStreetMap 타일 정책](https://operations.osmfoundation.org/policies/tiles/): 표시 영역만 요청, User-Agent·출처 표시·캐시 사용, 대량 사전 다운로드 없음.

Ultralytics 모델/도구는 AGPL-3.0, 기존 프로젝트 코드의 라이선스는 루트 LICENSE를 따릅니다. 모델의 원본 라이선스는 `models/ULTRALYTICS_LICENSE.txt`에 보존합니다.
