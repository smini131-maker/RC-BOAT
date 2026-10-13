# RC Boat Beta

이 폴더만 실험용 ROS 코드를 포함합니다. 저장소 루트의 기존 Windows GUI, Jetson daemon, 패치, 서비스와 테스트는 운영 버전으로 그대로 유지합니다.

- `ros_noetic_full/`: 기존 daemon을 사용하지 않는 ROS1 Noetic 전용 베타

ROS 베타를 실행할 때는 기존 `rcboat.service`를 먼저 중지해야 합니다. 두 버전이 Arduino, GPS, PCA9685 장치를 동시에 열면 안 됩니다.
