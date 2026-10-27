# v2.2.0 카메라·풍선 추적 검증 결과

검증일: 2026-10-27 (KST)

- 기존 프로젝트: RCBoatControl_Project / v2.1.7 / 404c072 — 수정하지 않음
- 새 프로젝트: RCBoatControl_Balloon_v2.2.0
- ROS 노드: balloon_vision_node, vision/status, vision/desired, vision/execute
- Windows GUI: RCBoatControl_ROS_v2.2.0.exe
- Jetson 서비스: rcboat_balloon_ros.service (기존 ROS unit과 소스 보존)

## 통과한 검증

- Python unittest 30개: 기존 GPS/RTK/항로/대루트/도보 테스트 및 풍선 제어/타깃 선택/안전 중재
- 풍선 좌/우 위치에 따른 조향과 조향 반전
- 연속 타깃 획득, 다른 풍선으로 갑자기 바뀌는 경우 재획득
- 풍선 상실, 근접, 영상/추론 지연 시 중립 출력
- 카메라 프레임만 새로 들어와도 오래된 추론 시각이 새로워지지 않음
- 타깃 복귀 후 자동 재출발 금지, 수동 시작 필요
- E-STOP 우선 적용
- ONNX 단일 클래스 출력 해석, NMS, 모델 SHA-256 불일치 차단
- GUI 시뮬레이션: 카메라 켜기 → 풍선 모드 시작 → 추적 정지 → 스로틀 6450 확인
- GUI 정지 명령이 ROS AUTO_SAFE / armed=false로 변환되는지 확인
- 최종 Windows EXE 실행 스모크 테스트 종료코드 0
- 학습된 ONNX를 OpenCV DNN으로 직접 로드하고 실제 검증 사진 13장 추론

## 초기 모델 결과

- YOLOv5n v7.0, 고정 320×320, ONNX opset 12, 출력 [1, 6300, 6]
- 원본: Matterport 공개 Balloon 데이터, train 61장 / validation 13장
- 학습/검증 동일 이미지 SHA-256 겹침 없음
- COCO 사전학습 후 풍선 60 epoch, 추가 Adam 학습 25 epoch에서 조기 종료
- 마지막 추가 학습의 best epoch: 5
- validation mAP50: 0.6486
- validation mAP50–95: 0.43551
- 배포 검출 경로 (confidence=0.45, IoU=0.5): TP 29 / FP 8 / FN 21
- precision: 0.7838, recall: 0.5800
- Windows PC CPU 추론 평균 약 51 ms. Jetson Nano 속도를 의미하지 않음.
- 자세한 값과 이미지별 결과: models/training_report.json
- 가중치 원본과 배포 파일: models/balloon_yolov5n.pt, balloon_yolov5n.onnx
- 해시/클래스/입력/학습 설정: models/model_manifest.json

## 미검증 사항

카메라 모델이 아직 정해지지 않아 USB/CSI 실기 연결, 실제 Jetson OpenCV 호환/처리율,
실제 러더 회전 방향, 수면·역광·반사·풍선 없는 장면의 오검출률, 실제 수상 추적은 미검증입니다.
GUI와 ROS 제어 경로를 구현하고 PC에서 검증한 초기 확장판입니다.
실기 배포는 자동으로 수행하지 않았습니다.

카메라가 결정되면 README_BALLOON.md 순서로 모델/카메라부터 확인하고,
장착한 카메라의 실제 촬영 데이터를 추가해 학습·검증하십시오.
