# RC-BOAT v2.2.0 — 카메라 · 풍선 자동 추적

기존 v2.1.7 프로젝트와 별도로 만든 ROS Noetic 확장판입니다. Windows 폴더는
`RCBoatControl_Balloon_v2.2.0`, Jetson 소스는 `/home/jetson/rcboat_balloon_ros_ws`,
데이터는 `/home/jetson/rcboat_balloon_data`를 사용합니다.

## 추가된 기능

- USB UVC/V4L2 카메라와 Jetson CSI/GStreamer 카메라 선택
- 학습된 **YOLOv5n** 단일 클래스 `balloon` ONNX 검출
- GUI `카메라 · 풍선 추적` 탭: 검출 영상, 신뢰도, 좌우 오차, 화면 점유율, 추론 지연, PWM 표시
- 풍선 화면 중심 오차로 러더 조향, 중심에 가까울수록 저속 전진
- 큰 좌우 오차에서는 전진을 정지하고 조향
- 풍선이 화면에서 커지면 근접 정지. 화면 점유율은 실제 거리(m)가 아닙니다.
- 연속 3프레임 확인 후 추적 시작 가능
- 타깃 상실/영상 지연/근접 정지 후 출력 중립 및 재시작 버튼 필요
- RC 수동 전환, E-STOP, PCA9685 출력 범위/타임아웃 유지
- 카메라를 켜도 추진기는 자동으로 시작하지 않음
- 최신 풍선 추적 로그 ZIP 다운로드
- 기존 GPS/RTK/항로/대루트/도보검증/원격조종 기능 유지

## 모델과 학습

이 프로젝트는 공개 Matterport Balloon 데이터의 polygon 주석을 YOLO bounding box로 변환하고,
YOLOv5 **v7.0 / nano**를 전이학습합니다. 원래 train 61장, validation 13장을 구분하며 같은 이미지가
두 split에 섞이지 않는지 SHA-256으로 검사합니다. 구체적인 학습 결과는 `models/model_manifest.json`,
`models/results.csv`, `models/training_report.json`을 확인하십시오.

초기 모델은 공개 풍선 사진 기준입니다. 실제 장착 카메라의 수면 반사/역광/멀리 있는 풍선/실제 풍선 색상,
풍선이 없는 장면을 추가하고, 촬영 장소/날짜/영상 단위로 train/val/test를 나눠 재학습해야 합니다.
기본 COCO nano 모델만 복사하면 balloon 전용 모델로 인정하지 않습니다. 실행 시 클래스/입력크기/모델
SHA-256을 manifest와 대조하고 일치하지 않으면 추진 출력을 잠급니다.

현재 제공 초기 모델의 검증 결과는 mAP50 **0.6486**, mAP50–95 **0.4355**입니다.
배포 OpenCV 검출 경로에서 신뢰도 0.45/IoU 매칭 0.5 기준으로 공개 검증 풍선 50개 중 29개를
검출했고 오검출은 8개였습니다(precision 0.784, recall 0.580).
이 수치는 현장 주행 성능이나 풍선 없는 장면의 오검출률을 보증하지 않습니다.
학습 이력은 COCO 사전학습 → 풍선 SGD 60 epoch → Adam 추가 학습(25 epoch에서 조기 종료)이며,
배포된 모델은 마지막 추가 학습의 best checkpoint입니다.

Jetson은 PyTorch 학습을 수행하지 않고 OpenCV DNN으로 320x320 ONNX 추론을 합니다.
기본 5 Hz 요청이며 실제 처리율은 Jetson에서 `check_vision.py`로 확인합니다.
추론 결과가 촬영 후 1초를 넘기면 출력은 중립입니다.

## Windows → Jetson 배포

카메라가 준비됐을 때 진행하십시오. IP가 변경되면 명령과 GUI에서 같은 주소로 수정합니다.

```powershell
Set-Location -LiteralPath "C:\Users\smini\OneDrive\바탕 화면\RCBoatControl_Complete_2026-09-25_UPDATED\RCBoatControl_Balloon_v2.2.0"
Test-NetConnection 10.180.227.215 -Port 22
.\DEPLOY_ROS.cmd -Destination "jetson@10.180.227.215"
ssh jetson@10.180.227.215
```

Jetson SSH 안:

```bash
cd /home/jetson/rcboat_balloon_ros_ws
python3 deployment/jetson/normalize_line_endings.py
bash deployment/jetson/install_vision_dependencies.sh
bash deployment/jetson/install_jetson_ros.sh
bash deployment/jetson/check_ros.sh
python3 deployment/jetson/check_vision.py --model-only
v4l2-ctl --list-devices
```

설치 스크립트가 기존 ROS 서비스 `rcboat_ros.service`를 정지/자동시작 해제한 후 새
`rcboat_balloon_ros.service`를 실행합니다. 두 버전이 동시에 PCA/GPS 장치를 소유하면 안 됩니다.
기존 소스/데이터/ROS 서비스 파일은 삭제하지 않으며 기존 항로와 NTRIP 로컬 설정을 새 데이터 폴더에
처음 한 번 복사합니다. 비밀번호는 배포 ZIP이나 Git에 포함되지 않습니다.

OpenCV가 ONNX 연산을 지원하지 않아 `check_vision.py`에서 오류가 나면 카메라/모델 상태가
not_ready로 유지됩니다. 실제 Jetson의 OpenCV 빌드에서 검사 성공 후 추적을 시작하십시오.
CSI를 쓰려면 해당 카메라의 Jetson 드라이버와 OpenCV GStreamer 지원이 있어야 합니다.

PCA/GPS 없이 카메라만 점검하려면 별도 Jetson 터미널에서:

```bash
source /opt/ros/noetic/setup.bash
source /home/jetson/rcboat_balloon_ros_ws/catkin_ws/devel/setup.bash
roslaunch rcboat_ros balloon_preview.launch
```

다른 터미널에서 아래 명령을 실행하면 카메라와 모델만 동작합니다.
이 launch에는 모터 출력 노드가 없습니다.

```bash
rosservice call /rcboat/vision/execute '{action: vision_enable, arguments_json: "{\"enabled\":true}"}'
```

## Windows GUI 사용

`windows_gui/dist/RCBoatControl_ROS_v2.2.0.exe` 실행 후 Jetson 주소/계정으로 연결합니다.

1. `카메라 · 풍선 추적` 탭에서 USB 또는 CSI를 선택합니다.
2. USB는 `/dev/video0`, CSI는 sensor-id를 장치에 맞게 지정합니다.
3. 카메라를 끈 상태에서 설정 저장 → 카메라 켜기.
4. 영상과 balloon bounding box, 모델 ready, 신뢰도/지연을 확인합니다.
5. 프로펠러를 제거한 상태에서 좌우에 풍선을 이동해 조향 방향을 먼저 확인합니다.
6. `풍선 자동 추적 시작`을 누릅니다. 시작 버튼은 신선한 타깃이 확보됐을 때 활성화됩니다.
7. `추적 정지` 또는 E-STOP으로 정지합니다.
8. 타깃 상실이나 근접 정지 후에는 다시 타깃을 확인하고 시작 버튼을 눌러야 재출발합니다.

영상은 SSH와 별개인 TCP 8766, 제어/상태는 8765를 사용합니다. 영상은 카메라 탭이 보일 때만
최대 3 FPS로 요청하며 제어 채널과 독립적으로 동작합니다.
`RCBOAT_GATEWAY_TOKEN`을 쓰면 영상 요청도 같은 토큰을 검사합니다.

## 로그

Jetson `~/rcboat_balloon_data/logs/vision/balloon_*.jsonl`에 카메라가 켜진 세션별 로그가 남습니다.
검출 박스/신뢰도/타깃 중심/점유율/영상 지연/추론 시간/목표 PWM/최종 안전 출력 상태/UTC를 기록합니다.
GUI의 `최근 추적 로그 가져오기`에서 ZIP을 PC로 저장할 수 있습니다.
원본 동영상은 기본 저장하지 않습니다.

## 재학습 명령

Python 3.12가 설치된 Windows PowerShell 기준:

```powershell
$trainEnv = "$env:LOCALAPPDATA\RCBoatBalloonTraining\v220\venv"
py -3.12 -m venv $trainEnv
& "$trainEnv\Scripts\python.exe" -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
& "$trainEnv\Scripts\python.exe" -m pip install -r training\requirements.txt
New-Item -ItemType Directory -Path training\downloads -Force
Invoke-WebRequest "https://github.com/matterport/Mask_RCNN/releases/download/v2.1/balloon_dataset.zip" -OutFile training\downloads\balloon_dataset.zip
& "$trainEnv\Scripts\python.exe" training\prepare_matterport.py
& "$trainEnv\Scripts\python.exe" training\train_balloon.py --epochs 60 --device 0 --name balloon_retrain_01
```

직접 촬영한 YOLO 라벨 데이터는 `training/data.example.yaml`을 복사해 경로를 지정하고:

```powershell
& "$trainEnv\Scripts\python.exe" training\train_balloon.py --data C:\RCBoatDataset\data.yaml --epochs 100 --device 0 --name boat_camera_01
```

CUDA GPU가 없으면 `--device cpu`를 사용합니다. 모델 학습은 PC에서 진행하며,
`models/balloon_yolov5n.onnx`와 `model_manifest.json`이 생성됩니다.
재학습 후 두 파일을 함께 다시 배포합니다. 한글 경로 문제를 피하려고 실제 학습 작업은
Windows 로컬 캐시의 영문 경로에서 수행하고 결과를 이 프로젝트로 복사합니다.

## 검증 · GUI 빌드

```powershell
python -m unittest discover -s tests -v
.\BUILD_ROS_GUI.cmd
```

원본 GUI에는 영향을 주지 않는 `%LOCALAPPDATA%\RCBoatBuild\v220` 빌드 환경을 사용합니다.
풍선 데이터/학습 캐시/학습 환경은 GUI EXE에 포함되지 않습니다.

## 기존 v2.1.7로 전환

Jetson:

```bash
bash /home/jetson/rcboat_balloon_ros_ws/deployment/jetson/rollback_to_v217.sh
```

이 명령은 새 ROS 서비스를 정지하고 기존 ROS 서비스를 다시 실행합니다.
PC에서는 기존 v2.1.7 GUI를 실행합니다.

## 자료 출처

- YOLOv5 학습: https://docs.ultralytics.com/yolov5/tutorials/train-custom-data/
- YOLOv5 v7.0: https://github.com/ultralytics/yolov5/tree/v7.0
- 풍선 데이터: https://github.com/matterport/Mask_RCNN/tree/master/samples/balloon
- ONNX/OpenCV DNN: https://docs.opencv.org/4.7.0/d6/d0f/group__dnn.html

고정한 YOLOv5 v7.0의 LICENSE는 학습된 모델과 함께 `models/YOLOv5_LICENSE.txt`에 보존합니다.
