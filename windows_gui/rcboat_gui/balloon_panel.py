"""Camera tab: asynchronous JPEG preview and balloon-tracking controls."""
import os
import time
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                              QLineEdit, QComboBox, QPushButton, QDoubleSpinBox,
                              QSpinBox, QGroupBox, QCheckBox, QFileDialog)

class BalloonPanel(QWidget):
    request = Signal(str, dict)
    start_tracking = Signal()
    stop_tracking = Signal()

    def __init__(self):
        super().__init__()
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.host = ""
        self.port = 8766
        self.remote_enabled = False
        self.mock = False
        self.camera_enabled = False
        self.last_image = 0
        self.synced = False
        self.dirty = False
        layout = QVBoxLayout(self)
        self.summary = QLabel("카메라 미연결 · 모델 확인 전")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.enable_button = QPushButton("카메라 켜기")
        self.enable_button.clicked.connect(lambda: self.request.emit("VISION_ENABLE", {"enabled": True}))
        self.disable_button = QPushButton("카메라 끄기")
        self.disable_button.clicked.connect(self.disable_camera)
        self.start_button = QPushButton("풍선 자동 추적 시작")
        self.start_button.clicked.connect(self.start_tracking.emit)
        self.stop_button = QPushButton("추적 정지")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_tracking.emit)
        self.download_button = QPushButton("최근 추적 로그 가져오기")
        self.download_button.clicked.connect(self.download_log)
        for button in (self.enable_button, self.disable_button, self.start_button, self.stop_button):
            row.addWidget(button)
        row.addWidget(self.download_button)
        layout.addLayout(row)
        self.image = QLabel("카메라를 켜면 풍선 검출 영상이 표시됩니다")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(480, 270)
        self.image.setMaximumHeight(360)
        self.image.setStyleSheet("background:#050a12; border:1px solid #2c405e; border-radius:8px;")
        self.metrics = QLabel("검출 신뢰도: - · 좌우 오차: - · 화면 점유율: - · 추론: -")
        self.metrics.setWordWrap(True)
        box = QGroupBox("카메라 · 추적 설정 (카메라를 끈 상태에서 저장)")
        form = QFormLayout(box)
        self.camera = QComboBox()
        self.camera.addItem("USB / V4L2", "usb")
        self.camera.addItem("Jetson CSI / GStreamer", "csi")
        self.source = QLineEdit("/dev/video0")
        self.sensor = QSpinBox()
        self.sensor.setRange(0, 3)
        self.model = QLineEdit("~/rcboat_balloon_data/models/balloon_yolov5n.onnx")
        self.confidence = self.spin(.05, .99, .45, .05)
        self.speed = QSpinBox()
        self.speed.setRange(6450, 6650)
        self.speed.setValue(6550)
        self.speed.setSuffix(" PWM")
        self.stop_area = self.spin(.02, .7, .18, .01)
        self.invert = QCheckBox("오른쪽 풍선 → 낮은 조향 PWM (현재 보트 보정)")
        self.invert.setChecked(True)
        self.save_button = QPushButton("카메라·추적 설정 저장")
        self.save_button.clicked.connect(self.save_config)
        for title, widget in (("카메라 연결", self.camera), ("USB 장치", self.source),
                              ("CSI sensor-id", self.sensor), ("Jetson ONNX 파일", self.model),
                              ("최소 검출 신뢰도", self.confidence), ("추적 전진 출력", self.speed),
                              ("정지 화면 점유율", self.stop_area), ("조향 방향", self.invert)):
            form.addRow(title, widget)
        form.addRow(self.save_button)
        body = QHBoxLayout()
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.image, 1)
        preview_layout.addWidget(self.metrics)
        body.addLayout(preview_layout, 3)
        body.addWidget(box, 2)
        layout.addLayout(body)
        note = QLabel(
            "풍선을 연속 3프레임 확인한 후 시작할 수 있습니다. 풍선 상실·카메라 지연·근접 정지는 "
            "출력을 중립으로 잠그며, 다시 시작 버튼을 눌러야 재출발합니다. 화면 점유율은 실제 거리(m)가 아닙니다. "
            "USB/CSI 장착 후 프로펠러를 제거하고 좌우 조향 방향부터 확인하세요."
        )
        note.setWordWrap(True)
        note.setObjectName("sectionHint")
        layout.addWidget(note)
        layout.addStretch(1)
        self.editors = (self.camera, self.source, self.sensor, self.model, self.confidence,
                        self.speed, self.stop_area, self.invert)
        self.timer = QTimer(self)
        self.timer.setInterval(330)
        self.timer.timeout.connect(self.fetch_frame)
        self.timer.start()
        self.set_connected(False)

    @staticmethod
    def spin(low, high, value, step):
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        widget.setSingleStep(step)
        widget.setDecimals(2)
        return widget

    def set_connected(self, connected):
        self.remote_enabled = bool(connected)
        self.enable_button.setEnabled(connected)
        self.disable_button.setEnabled(connected)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(connected)
        self.download_button.setEnabled(connected and not self.mock)
        if not connected:
            self.synced = False
            self.image.clear()
            self.image.setText("ROS 연결 대기")
            self.summary.setText("카메라 미연결 · ROS 상태 확인 전")
            if self.reply:
                self.reply.abort()

    def disable_camera(self):
        self.stop_tracking.emit()
        self.request.emit("VISION_ENABLE", {"enabled": False})

    def download_log(self):
        folder = QFileDialog.getExistingDirectory(self, "풍선 추적 로그 저장 폴더")
        if folder:
            self.request.emit("DOWNLOAD_VISION_LOG", {"destination": folder})

    def save_config(self):
        model = self.model.text().strip()
        manifest = model.rsplit("/", 1)[0]+"/model_manifest.json"
        self.request.emit("VISION_CONFIGURE", {
            "camera_type": self.camera.currentData(), "camera_source": self.source.text().strip(),
            "csi_sensor_id": self.sensor.value(), "model_path": model, "model_manifest": manifest,
            "confidence": self.confidence.value(), "cruise_pwm": self.speed.value(),
            "stop_area_ratio": self.stop_area.value(), "steering_right_sign": -1 if self.invert.isChecked() else 1,
        })

    def update_state(self, state, host):
        vision = state.get("vision") or {}
        demand = state.get("vision_desired") or {}
        backend = state.get("backend") or {}
        self.mock = bool(state.get("mock"))
        self.host = host
        self.port = int(vision.get("preview_port") or 8766)
        self.remote_enabled = bool(backend.get("gateway_online"))
        enabled = bool(vision.get("enabled"))
        self.camera_enabled = enabled
        camera_ok, model_ok = bool(vision.get("camera_online")), bool(vision.get("model_ready"))
        reason = str(vision.get("reason") or "no_data")
        mode = str(state.get("mode"))
        armed = bool(state.get("balloon_armed"))
        self.summary.setText(
            f"카메라: {'online' if camera_ok else 'offline'} · 모델: {'ready' if model_ok else 'not_ready'}"
            f" · {'추적 출력 중' if mode == 'BALLOON' and armed else '출력 대기'} · {reason}"
            + (" · "+str(vision.get("error")) if vision.get("error") else "")
        )
        self.enable_button.setEnabled(self.remote_enabled and not enabled)
        self.disable_button.setEnabled(self.remote_enabled and enabled)
        self.start_button.setEnabled(self.remote_enabled and bool(demand.get("valid")) and not state.get("estop"))
        self.stop_button.setEnabled(self.remote_enabled)
        self.download_button.setEnabled(self.remote_enabled and not self.mock)
        self.save_button.setEnabled(self.remote_enabled and not enabled)
        for editor in self.editors:
            editor.setEnabled(not enabled)
        target = vision.get("target") or {}
        def fmt(value, multiplier=1, suffix=""):
            return "-" if value is None else f"{float(value)*multiplier:.2f}{suffix}"
        self.metrics.setText(
            "검출 신뢰도: "+fmt(target.get("confidence"), 100, "%")+
            " · 좌우 오차: "+fmt(target.get("center_x_normalized"))+
            " · 화면 점유율: "+fmt(target.get("area_ratio"), 100, "%")+
            " · 추론: "+fmt(vision.get("inference_ms"), 1, " ms")+
            " · 프레임 지연: "+fmt(vision.get("frame_age_s"), 1, " s")+
            f" · 최종 PWM: {state.get('pca', {}).get('steering_pwm', '-')} / {state.get('pca', {}).get('throttle_pwm', '-')}"
        )
        config = vision.get("configuration") or {}
        if config and not self.synced:
            self.camera.setCurrentIndex(max(0, self.camera.findData(config.get("camera_type", "usb"))))
            self.source.setText(str(config.get("camera_source", "/dev/video0")))
            self.sensor.setValue(int(config.get("csi_sensor_id", 0)))
            self.model.setText(str(config.get("model_path", self.model.text())))
            self.confidence.setValue(float(config.get("confidence", .45)))
            self.speed.setValue(int(config.get("cruise_pwm", 6550)))
            self.stop_area.setValue(float(config.get("stop_area_ratio", .18)))
            self.invert.setChecked(config.get("steering_right_sign", -1) == -1)
            self.synced = True
        if self.mock:
            self.image.setPixmap(QPixmap())
            self.image.setText("SIMULATION · 풍선 검출/추적 모의 상태\n실제 카메라 영상은 Jetson 연결 시 표시됩니다")
        elif not enabled:
            self.image.setPixmap(QPixmap())
            self.image.setText("카메라 꺼짐")

    def fetch_frame(self):
        if self.reply or not self.isVisible() or not self.remote_enabled or not self.host or self.mock or not self.camera_enabled:
            return
        if self.last_image and time.monotonic()-self.last_image > 2:
            self.image.setPixmap(QPixmap())
            self.image.setText("영상 수신 지연 · 새 프레임 대기")
        host = "["+self.host+"]" if ":" in self.host else self.host
        request = QNetworkRequest(QUrl(f"http://{host}:{self.port}/frame.jpg"))
        request.setTransferTimeout(1500)
        token = os.getenv("RCBOAT_GATEWAY_TOKEN", "")
        if token:
            request.setRawHeader(b"X-RCBoat-Token", token.encode())
        self.reply = self.network.get(request)
        self.reply.finished.connect(self.frame_finished)

    def frame_finished(self):
        reply, self.reply = self.reply, None
        if reply is None:
            return
        if reply.error() == QNetworkReply.NoError:
            raw = bytes(reply.readAll())
            pixmap = QPixmap()
            if len(raw) <= 3_000_000 and pixmap.loadFromData(raw, "JPG"):
                self.image.setPixmap(pixmap.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.last_image = time.monotonic()
        elif not self.last_image or time.monotonic()-self.last_image > 2:
            self.image.setPixmap(QPixmap())
            self.image.setText("새 카메라 영상 없음")
        reply.deleteLater()
