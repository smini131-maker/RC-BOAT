from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QCloseEvent, QFontDatabase, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .credentials import delete_password, load_password, save_password
from .mock_worker import MockWorker
from .ssh_worker import SSHWorker
from .widgets import RoutePlot, StatusCard, TelemetryGraph


STYLE = """
QMainWindow, QWidget { background:#09111f; color:#edf4ff; font-family:'Malgun Gothic','Segoe UI'; font-size:10pt; }
QGroupBox { border:1px solid #26334a; border-radius:8px; margin-top:12px; padding:12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px; color:#a9b9d2; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit { background:#101a2b; border:1px solid #31405b; border-radius:5px; padding:6px; }
QPushButton { background:#176fe2; border:0; border-radius:7px; padding:9px 14px; font-weight:600; }
QPushButton:hover { background:#2a79ec; }
QPushButton:disabled { background:#273247; color:#72809a; }
QPushButton#danger { background:#d83c50; font-size:12pt; min-height:34px; }
QPushButton#danger:hover { background:#f04e61; }
QPushButton#safe { background:#1d8d68; }
QLabel#appTitle { font-size:21pt; font-weight:800; color:#f5f9ff; }
QLabel#appSubtitle { color:#8ea4c4; font-size:9pt; }
QLabel#safetyBadge { background:#102b2c; color:#4ee0b0; border:1px solid #245a53; border-radius:12px; padding:5px 10px; font-weight:700; }
QLabel#simulationBadge { background:#5a3510; color:#ffd27a; border:2px solid #d58b2d; border-radius:9px; padding:8px 16px; font-size:12pt; font-weight:800; }
QFrame#statusCard { background:#111a2b; border:1px solid #26334a; border-radius:8px; }
QLabel#cardTitle { color:#8fa1bd; font-size:9pt; }
QLabel#cardValue { color:#e8eef8; font-size:14pt; font-weight:700; }
QTabWidget::pane { border:1px solid #26334a; }
QTabBar::tab { background:#111a2b; padding:9px 18px; }
QTabBar::tab:selected { background:#1c2b45; color:#61caff; }
QSlider::groove:horizontal { height:6px; background:#26334a; border-radius:3px; }
QSlider::handle:horizontal { width:16px; margin:-5px 0; background:#4da3ff; border-radius:8px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.setWindowIcon(QIcon(str(bundle_root / "assets" / "cat_boat_icon.ico")))
        self.setWindowTitle("RC 보트 관제센터")
        self.resize(1420, 900)
        self.setStyleSheet(STYLE)
        self.settings = QSettings("AdventureDesign", "RCBoatControl")
        self.worker: SSHWorker | MockWorker | None = None
        self.is_simulation = False
        self.last_event_timestamp = 0.0
        self.last_hardware_errors: tuple[str, ...] = ()
        self.pending_route_id: str | None = None
        self.pending_route_start_request: str | None = None
        self.current_mode = "MANUAL"
        self._mode_dirty = False
        self._syncing_mode = False
        self._pending_mode_request: str | None = None
        self._pending_mode_target: str | None = None
        self._auto_speed_dirty = False
        self._syncing_auto_speed = False
        self._multipath_dirty = False
        self._syncing_multipath = False
        self._pending_multipath_request: str | None = None
        self._remote_keys: set[int] = set()
        self._build_ui()
        self._load_settings()
        self._set_connected(False)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(68, 68))
        logo.setFixedSize(76, 76)
        logo.setAlignment(Qt.AlignCenter)
        title_box = QVBoxLayout()
        title = QLabel("RC 보트 관제센터")
        title.setObjectName("appTitle")
        subtitle = QLabel("Jetson Nano · Arduino · GPS · PCA9685 통합 제어")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        safety = QLabel("기본 안전 출력  조향 6000 · 스로틀 6450")
        safety.setObjectName("safetyBadge")
        self.simulation_badge = QLabel("SIMULATION MODE / 모의 데이터")
        self.simulation_badge.setObjectName("simulationBadge")
        self.simulation_badge.setVisible(False)
        header.addWidget(logo)
        header.addLayout(title_box)
        header.addStretch(1)
        header.addWidget(self.simulation_badge)
        header.addWidget(safety)
        outer.addLayout(header)

        connect_group = QGroupBox("Jetson SSH 연결")
        connect_layout = QHBoxLayout(connect_group)
        self.host = QLineEdit("10.122.105.215")
        self.host.setMinimumWidth(150)
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(22)
        self.username = QLineEdit("jetson")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.remember = QCheckBox("비밀번호 안전 저장")
        self.simulation = QCheckBox("시뮬레이션")
        self.connect_button = QPushButton("연결")
        self.connect_button.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
        self.connect_button.clicked.connect(self.toggle_connection)
        for label, widget in (("주소", self.host), ("포트", self.port), ("사용자", self.username), ("비밀번호", self.password)):
            connect_layout.addWidget(QLabel(label)); connect_layout.addWidget(widget)
        connect_layout.addWidget(self.remember)
        connect_layout.addWidget(self.simulation)
        connect_layout.addWidget(self.connect_button)
        outer.addWidget(connect_group)

        status_layout = QGridLayout()
        self.cards = {
            "ssh": StatusCard("SSH 연결", "연결 안 됨"),
            "mode": StatusCard("현재 모드", "자동 대기"),
            "arduino": StatusCard("Arduino", "-"),
            "pca": StatusCard("PCA9685", "-"),
            "gps": StatusCard("GPS", "위치 미수신"),
            "armed": StatusCard("GPS 항법", "대기"),
            "estop": StatusCard("비상정지", "정상"),
        }
        for idx, card in enumerate(self.cards.values()):
            status_layout.addWidget(card, 0, idx)
        outer.addLayout(status_layout)

        action_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        for label, value in (("자동 대기", "AUTO"), ("수동 조종", "MANUAL"), ("GPS 항법", "NAVIGATION"), ("PC 원격 조종", "REMOTE")):
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_selected)
        self.mode_button = QPushButton("모드 적용"); self.mode_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton)); self.mode_button.clicked.connect(self.set_mode)
        self.estop_button = QPushButton("비상 정지"); self.estop_button.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxCritical)); self.estop_button.setObjectName("danger"); self.estop_button.clicked.connect(lambda: self.command("EMERGENCY_STOP"))
        self.clear_estop_button = QPushButton("비상정지 해제"); self.clear_estop_button.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton)); self.clear_estop_button.setObjectName("safe"); self.clear_estop_button.clicked.connect(self.clear_estop)
        action_layout.addWidget(QLabel("운항 모드")); action_layout.addWidget(self.mode_combo); action_layout.addWidget(self.mode_button)
        self.auto_speed_slider = QSlider(Qt.Horizontal)
        self.auto_speed_slider.setRange(6480, 6900)
        self.auto_speed_slider.setSingleStep(10)
        self.auto_speed_slider.setPageStep(50)
        self.auto_speed_slider.setValue(6650)
        self.auto_speed_slider.setFixedWidth(180)
        self.auto_speed_spin = QSpinBox()
        self.auto_speed_spin.setRange(6480, 6900)
        self.auto_speed_spin.setSingleStep(10)
        self.auto_speed_spin.setValue(6650)
        self.auto_speed_spin.setSuffix(" PWM")
        self.auto_speed_percent = QLabel("15%")
        self.auto_speed_percent.setMinimumWidth(34)
        self.auto_speed_apply = QPushButton("적용")
        self.auto_speed_apply.clicked.connect(self.apply_auto_speed)
        self.auto_speed_reset = QPushButton("기본값")
        self.auto_speed_reset.clicked.connect(self.reset_auto_speed)
        self.auto_speed_slider.valueChanged.connect(self._auto_speed_from_slider)
        self.auto_speed_spin.valueChanged.connect(self._auto_speed_from_spin)
        action_layout.addSpacing(12)
        action_layout.addWidget(QLabel("자동 속도"))
        action_layout.addWidget(self.auto_speed_slider)
        action_layout.addWidget(self.auto_speed_spin)
        action_layout.addWidget(self.auto_speed_percent)
        action_layout.addWidget(self.auto_speed_apply)
        action_layout.addWidget(self.auto_speed_reset)
        action_layout.addStretch(1)
        action_layout.addWidget(self.clear_estop_button); action_layout.addWidget(self.estop_button)
        outer.addLayout(action_layout)
        auto_speed_note = QLabel("6450 = 정지 / 값이 클수록 전진 속도 증가 · 너무 낮은 값에서는 ESC 특성에 따라 모터가 회전하지 않을 수 있습니다.")
        auto_speed_note.setStyleSheet("color:#8ea4c4; font-size:9pt;")
        outer.addWidget(auto_speed_note)

        tabs = QTabWidget()
        self.tabs = tabs
        tabs.addTab(self._dashboard_tab(), self.style().standardIcon(QStyle.SP_ComputerIcon), "실시간 계기판")
        tabs.addTab(self._gps_rtk_tab(), self.style().standardIcon(QStyle.SP_DriveNetIcon), "GPS · RTK")
        tabs.addTab(self._route_tab(), self.style().standardIcon(QStyle.SP_FileDialogDetailedView), "항로")
        tabs.addTab(self._hil_tab(), self.style().standardIcon(QStyle.SP_DesktopIcon), "HIL")
        tabs.addTab(self._remote_tab(), self.style().standardIcon(QStyle.SP_ArrowRight), "PC 원격 조종")
        self.terminal_tab_index = tabs.addTab(
            self._terminal_tab(),
            self.style().standardIcon(QStyle.SP_ComputerIcon),
            "SSH 터미널",
        )
        tabs.addTab(self._logs_tab(), self.style().standardIcon(QStyle.SP_FileDialogInfoView), "운항 기록")
        outer.addWidget(tabs, 1)

    def _dashboard_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        values = QGridLayout()
        self.value_labels = {}
        fields = [
            ("조종기 조향", "rc_steering"), ("조종기 스로틀", "rc_throttle"),
            ("서보 출력 CH0", "pca_steering"), ("ESC 출력 CH6", "pca_throttle"),
            ("위도", "lat"), ("경도", "lon"),
            ("고도", "altitude"), ("HDOP", "hdop"), ("마지막 FIX 경과", "last_fix_age"),
            ("수신 위성", "satellites"), ("속도", "speed"),
            ("진행 방향", "course"), ("안전 전환 사유", "failsafe"),
        ]
        for idx, (title, key) in enumerate(fields):
            card = StatusCard(title)
            self.value_labels[key] = card
            values.addWidget(card, idx // 5, idx % 5)
        layout.addLayout(values)
        splitter = QSplitter(Qt.Horizontal)
        self.rc_graph = TelemetryGraph("조종기 입력 (조향 / 스로틀, us)", 1000, 2100, ("#35c9ff", "#f8bd58"))
        self.pwm_graph = TelemetryGraph("PCA9685 출력 (조향 / 스로틀)", 4800, 7400, ("#38d996", "#ff6474"))
        splitter.addWidget(self.rc_graph); splitter.addWidget(self.pwm_graph)
        layout.addWidget(splitter, 1)
        return page

    def _route_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        self.route_combo = QComboBox()
        select = QPushButton("항로 선택"); select.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton)); select.clicked.connect(self.select_route)
        self.route_start_button = QPushButton("선택 항로 운행 시작")
        self.route_start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.route_start_button.setObjectName("safe")
        self.route_start_button.clicked.connect(self.start_selected_route)
        reload_button = QPushButton("항로 파일 다시 읽기"); reload_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload)); reload_button.clicked.connect(lambda: self.command("RELOAD_ROUTES"))
        self.route_status = QLabel("항로 정보 없음")
        self.route_storage_status = QLabel("항로 저장 파일: 연결 후 확인")
        self.route_storage_status.setStyleSheet("color:#8ea4c4; font-size:9pt;")
        controls.addWidget(QLabel("주행 항로")); controls.addWidget(self.route_combo); controls.addWidget(select); controls.addWidget(self.route_start_button); controls.addWidget(reload_button); controls.addStretch(1); controls.addWidget(self.route_status)
        self.route_plot = RoutePlot()
        multipath_box = QGroupBox("Multi-Path 기준 (R11 호환)")
        multipath_layout = QGridLayout(multipath_box)
        self.multipath_enabled = QCheckBox("사용")
        self.multipath_enabled.setChecked(True)
        self.multipath_endpoint = self._distance_spin(0.10, 1.00, 0.75, 0.05, " m")
        self.multipath_off_distance = self._distance_spin(1.0, 100.0, 8.0, 0.5, " m")
        self.multipath_hold = self._distance_spin(0.0, 30.0, 3.0, 0.5, " s")
        self.multipath_advantage = self._distance_spin(0.0, 50.0, 2.0, 0.5, " m")
        self.multipath_cooldown = self._distance_spin(0.0, 60.0, 5.0, 0.5, " s")
        self.multipath_apply = QPushButton("기준 저장")
        self.multipath_apply.clicked.connect(self.apply_multipath)
        self.multipath_status = QLabel("설정 대기")
        multipath_layout.addWidget(self.multipath_enabled, 0, 0)
        for column, (label, widget) in enumerate((
            ("공통 출발·도착 허용", self.multipath_endpoint),
            ("이탈 거리", self.multipath_off_distance),
            ("이탈 지속", self.multipath_hold),
            ("다른 경로 우위", self.multipath_advantage),
            ("전환 대기", self.multipath_cooldown),
        ), 1):
            box = QVBoxLayout(); box.addWidget(QLabel(label)); box.addWidget(widget)
            multipath_layout.addLayout(box, 0, column)
        multipath_layout.addWidget(self.multipath_apply, 0, 6)
        multipath_layout.addWidget(self.multipath_status, 1, 0, 1, 7)
        for widget in (
            self.multipath_enabled, self.multipath_endpoint, self.multipath_off_distance,
            self.multipath_hold, self.multipath_advantage, self.multipath_cooldown,
        ):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._mark_multipath_dirty)
            else:
                widget.valueChanged.connect(self._mark_multipath_dirty)
        record_box = QGroupBox("GPS 항로 기록")
        record_layout = QHBoxLayout(record_box)
        self.route_record_name = QLineEdit()
        self.route_record_name.setPlaceholderText("새 항로 이름")
        self.route_record_name.setMaximumWidth(260)
        self.route_record_spacing = self._distance_spin(0.1, 100.0, 1.0, 0.1, " m")
        self.route_record_interval = self._distance_spin(0.1, 60.0, 0.5, 0.1, " s")
        self.route_arrival_radius = self._distance_spin(0.5, 100.0, 3.0, 0.5, " m")
        self.route_record_start = QPushButton("기록 시작")
        self.route_record_start.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.route_record_start.clicked.connect(self.start_gps_recording)
        self.route_record_save = QPushButton("정지 후 저장")
        self.route_record_save.setObjectName("safe")
        self.route_record_save.clicked.connect(self.stop_gps_recording)
        self.route_record_cancel = QPushButton("기록 취소")
        self.route_record_cancel.clicked.connect(self.cancel_gps_recording)
        self.route_record_status = QLabel("기록 대기")
        record_layout.addWidget(QLabel("이름"))
        record_layout.addWidget(self.route_record_name)
        record_layout.addWidget(QLabel("최소 간격")); record_layout.addWidget(self.route_record_spacing)
        record_layout.addWidget(QLabel("최소 시간")); record_layout.addWidget(self.route_record_interval)
        record_layout.addWidget(QLabel("도착 반경")); record_layout.addWidget(self.route_arrival_radius)
        record_layout.addWidget(self.route_record_start)
        record_layout.addWidget(self.route_record_save)
        record_layout.addWidget(self.route_record_cancel)
        record_layout.addStretch(1)
        record_layout.addWidget(self.route_record_status)
        layout.addLayout(controls); layout.addWidget(self.route_storage_status); layout.addWidget(multipath_box); layout.addWidget(record_box); layout.addWidget(self.route_plot, 1)
        return page

    def _gps_rtk_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        health_box = QGroupBox("GPS Health · 수신 상세")
        health_layout = QGridLayout(health_box)
        self.gps_detail_labels: dict[str, QLabel] = {}
        detail_fields = (
            ("FIX", "fix_label"), ("UTC", "utc_time"), ("Satellite", "satellites"),
            ("HDOP", "hdop"), ("PDOP", "pdop"), ("VDOP", "vdop"),
            ("C/N0", "cno"), ("hAcc", "hacc"), ("데이터 age", "age"),
            ("UTM", "utm"), ("RTK 상태", "rtk_state"), ("보정 age", "correction_age"),
        )
        for index, (title, key) in enumerate(detail_fields):
            health_layout.addWidget(QLabel(title), index // 4 * 2, index % 4)
            value = QLabel("-")
            value.setStyleSheet("font-weight:700; color:#edf4ff")
            self.gps_detail_labels[key] = value
            health_layout.addWidget(value, index // 4 * 2 + 1, index % 4)
        self.gps_health_status = QLabel("GPS Health: UNKNOWN")
        self.gps_health_status.setWordWrap(True)
        health_layout.addWidget(self.gps_health_status, 6, 0, 1, 4)

        logging_box = QGroupBox("GPS 데이터 로그 (기존 항로 기록과 별도)")
        logging_layout = QHBoxLayout(logging_box)
        self.gps_log_start = QPushButton("GPS 데이터 기록 시작")
        self.gps_log_start.clicked.connect(lambda: self.command("START_GPS_LOGGING"))
        self.gps_log_stop = QPushButton("GPS 데이터 기록 종료")
        self.gps_log_stop.setObjectName("safe")
        self.gps_log_stop.clicked.connect(lambda: self.command("STOP_GPS_LOGGING"))
        self.gps_log_status = QLabel("기록 대기")
        logging_layout.addWidget(self.gps_log_start); logging_layout.addWidget(self.gps_log_stop)
        logging_layout.addWidget(self.gps_log_status, 1)

        ntrip_box = QGroupBox("RTK / NTRIP 설정 · 비밀번호는 Jetson 보안 파일에만 저장")
        ntrip_layout = QGridLayout(ntrip_box)
        self.ntrip_enabled = QCheckBox("RTK 사용")
        self.ntrip_host = QLineEdit(); self.ntrip_host.setPlaceholderText("발급받은 NTRIP Host")
        self.ntrip_port = QSpinBox(); self.ntrip_port.setRange(1, 65535); self.ntrip_port.setValue(2101)
        self.ntrip_mountpoint = QLineEdit(); self.ntrip_mountpoint.setPlaceholderText("Mount Point")
        self.ntrip_username = QLineEdit(); self.ntrip_username.setPlaceholderText("발급 ID")
        self.ntrip_password = QLineEdit(); self.ntrip_password.setEchoMode(QLineEdit.Password)
        self.ntrip_password.setPlaceholderText("비밀번호 변경 시에만 입력")
        self.ntrip_tls = QCheckBox("TLS")
        ntrip_apply = QPushButton("설정 저장 · 연결")
        ntrip_apply.clicked.connect(self.apply_ntrip)
        ntrip_disable = QPushButton("RTK 연결 해제")
        ntrip_disable.clicked.connect(lambda: self.command("DISABLE_NTRIP"))
        refresh = QPushButton("상태 새로고침")
        refresh.clicked.connect(lambda: self.command("REFRESH_NTRIP"))
        self.ntrip_status = QLabel("NTRIP 비활성")
        ntrip_layout.addWidget(self.ntrip_enabled, 0, 0)
        for column, (label, widget) in enumerate((("Host", self.ntrip_host), ("Port", self.ntrip_port), ("Mount Point", self.ntrip_mountpoint), ("Username", self.ntrip_username), ("Password", self.ntrip_password)), 1):
            box = QVBoxLayout(); box.addWidget(QLabel(label)); box.addWidget(widget)
            ntrip_layout.addLayout(box, 0, column)
        ntrip_layout.addWidget(self.ntrip_tls, 1, 0)
        ntrip_layout.addWidget(ntrip_apply, 1, 1)
        ntrip_layout.addWidget(ntrip_disable, 1, 2)
        ntrip_layout.addWidget(refresh, 1, 3)
        ntrip_layout.addWidget(self.ntrip_status, 1, 4, 1, 2)

        safety_box = QGroupBox("GPS 항법 안전 Gate")
        safety_layout = QHBoxLayout(safety_box)
        self.rtk_required = QCheckBox("NAVIGATION에 RTK Fixed 필수")
        self.gps_max_hdop = QDoubleSpinBox(); self.gps_max_hdop.setRange(0.5, 20.0); self.gps_max_hdop.setValue(3.0); self.gps_max_hdop.setSuffix(" HDOP")
        save_safety = QPushButton("안전 기준 저장")
        save_safety.clicked.connect(self.apply_gps_safety)
        safety_layout.addWidget(self.rtk_required); safety_layout.addWidget(QLabel("최대 허용")); safety_layout.addWidget(self.gps_max_hdop); safety_layout.addWidget(save_safety); safety_layout.addStretch(1)

        layout.addWidget(health_box); layout.addWidget(logging_box); layout.addWidget(ntrip_box); layout.addWidget(safety_box); layout.addStretch(1)
        return page

    def apply_ntrip(self) -> None:
        self.command(
            "CONFIGURE_NTRIP", enabled=self.ntrip_enabled.isChecked(),
            host=self.ntrip_host.text().strip(), port=self.ntrip_port.value(),
            mountpoint=self.ntrip_mountpoint.text().strip(), username=self.ntrip_username.text().strip(),
            password=self.ntrip_password.text(), tls=self.ntrip_tls.isChecked(),
        )
        self.ntrip_password.clear()

    def apply_gps_safety(self) -> None:
        self.command(
            "SET_GPS_SETTINGS",
            navigation_max_hdop=self.gps_max_hdop.value(),
            rtk_required_for_navigation=self.rtk_required.isChecked(),
        )

    @staticmethod
    def _distance_spin(low: float, high: float, value: float, step: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(2)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def _hil_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        warning = QLabel(
            "HIL은 저장 항로의 가상 GPS 위치로 항법 로직을 시험하며 실제 PCA9685 출력이 움직일 수 있습니다. "
            "프로펠러를 분리하고 비상정지를 먼저 확인하세요."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#f8bd58; font-weight:700")
        controls = QHBoxLayout()
        self.hil_start_button = QPushButton("선택 항로 HIL 시작")
        self.hil_start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.hil_start_button.setObjectName("danger")
        self.hil_start_button.clicked.connect(self.start_hil)
        self.hil_stop_button = QPushButton("HIL 정지 · 안전 출력")
        self.hil_stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.hil_stop_button.setObjectName("safe")
        self.hil_stop_button.clicked.connect(lambda: self.command("STOP_HIL"))
        self.hil_status = QLabel("HIL 대기")
        controls.addWidget(self.hil_start_button)
        controls.addWidget(self.hil_stop_button)
        controls.addStretch(1)
        controls.addWidget(self.hil_status)
        layout.addWidget(warning)
        layout.addLayout(controls)
        layout.addStretch(1)
        return page

    def _remote_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        notice = QLabel("PC 원격 조종 모드 전용 · 0.2초마다 연결 신호 전송 · 0.7초 끊기면 자동 안전 모드로 즉시 전환")
        notice.setStyleSheet("color:#f8bd58")
        layout.addWidget(notice)
        form = QFormLayout()
        self.remote_steering = QSlider(Qt.Horizontal); self.remote_steering.setRange(4900, 7300); self.remote_steering.setValue(6000)
        self.remote_throttle = QSlider(Qt.Horizontal); self.remote_throttle.setRange(5800, 7000); self.remote_throttle.setValue(6450)
        self.remote_steering_label = QLabel("6000")
        self.remote_throttle_label = QLabel("6450")
        self.remote_steering.valueChanged.connect(lambda v: self.remote_steering_label.setText(str(v)))
        self.remote_throttle.valueChanged.connect(lambda v: self.remote_throttle_label.setText(str(v)))
        steering_row = QHBoxLayout(); steering_row.addWidget(self.remote_steering); steering_row.addWidget(self.remote_steering_label)
        throttle_row = QHBoxLayout(); throttle_row.addWidget(self.remote_throttle); throttle_row.addWidget(self.remote_throttle_label)
        form.addRow("조향 PWM (4900~7300)", steering_row)
        form.addRow("스로틀 PWM (5800~7000)", throttle_row)
        send = QPushButton("원격 출력 전송"); send.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight)); send.clicked.connect(self.send_remote)
        neutral = QPushButton("조향 중앙 + 모터 정지"); neutral.setIcon(self.style().standardIcon(QStyle.SP_MediaStop)); neutral.setObjectName("safe"); neutral.clicked.connect(self.remote_neutral)
        keyboard_help = QLabel("키보드: W/↑ 전진 · S/↓ 후진 · A/← 좌회전 · D/→ 우회전 · Space 정지 (키를 놓으면 해당 축은 안전 중립)")
        keyboard_help.setStyleSheet("color:#8ea4c4")
        simulation_box = QGroupBox("시뮬레이션 장애 재현")
        simulation_layout = QHBoxLayout(simulation_box)
        self.sim_arduino_offline = QCheckBox("Arduino 분리")
        self.sim_gps_offline = QCheckBox("GPS 분리")
        self.sim_gps_no_fix = QCheckBox("GPS NO FIX")
        self.sim_heartbeat_loss = QPushButton("REMOTE heartbeat 끊김")
        self.sim_multipath = QPushButton("Multi-Path 전환")
        self.sim_arduino_offline.toggled.connect(
            lambda checked: self.command("SIM_SET_ARDUINO", connected=not checked)
        )
        self.sim_gps_offline.toggled.connect(self._send_sim_gps_state)
        self.sim_gps_no_fix.toggled.connect(self._send_sim_gps_state)
        self.sim_heartbeat_loss.clicked.connect(lambda: self.command("SIM_REMOTE_HEARTBEAT_LOSS"))
        self.sim_multipath.clicked.connect(lambda: self.command("SIM_MULTIPATH_SWITCH"))
        self.simulation_controls = [
            self.sim_arduino_offline,
            self.sim_gps_offline,
            self.sim_gps_no_fix,
            self.sim_heartbeat_loss,
            self.sim_multipath,
        ]
        for widget in self.simulation_controls:
            simulation_layout.addWidget(widget)
            widget.setEnabled(False)
        simulation_layout.addStretch(1)
        layout.addLayout(form); layout.addWidget(keyboard_help); layout.addWidget(send); layout.addWidget(neutral); layout.addWidget(simulation_box); layout.addStretch(1)
        return page

    def _logs_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        self.logs = QTextEdit(); self.logs.setReadOnly(True)
        layout.addWidget(self.logs)
        return page

    def _terminal_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page)
        self.terminal_status = QLabel("SSH 연결 후 터미널을 사용할 수 있습니다")
        self.terminal_status.setStyleSheet("color:#8ea4c4")
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setAcceptRichText(False)
        self.terminal_output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.terminal_output.setStyleSheet("background:#050a12; color:#d8e4f3;")
        input_row = QHBoxLayout()
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Jetson에서 실행할 명령을 입력하고 Enter")
        self.terminal_input.returnPressed.connect(self.send_terminal_command)
        self.terminal_send = QPushButton("실행")
        self.terminal_send.clicked.connect(self.send_terminal_command)
        self.terminal_interrupt = QPushButton("Ctrl+C")
        self.terminal_interrupt.clicked.connect(self.interrupt_terminal)
        terminal_clear = QPushButton("화면 지우기")
        terminal_clear.clicked.connect(self.terminal_output.clear)
        input_row.addWidget(self.terminal_input, 1)
        input_row.addWidget(self.terminal_send)
        input_row.addWidget(self.terminal_interrupt)
        input_row.addWidget(terminal_clear)
        layout.addWidget(self.terminal_status)
        layout.addWidget(self.terminal_output, 1)
        layout.addLayout(input_row)
        self._set_terminal_ready(False, "SSH 연결 후 터미널을 사용할 수 있습니다")
        return page

    def _set_terminal_ready(self, ready: bool, message: str) -> None:
        self.terminal_status.setText(message)
        self.terminal_status.setStyleSheet("color:#4ee0b0" if ready else "color:#f8bd58")
        self.terminal_input.setEnabled(ready)
        self.terminal_send.setEnabled(ready)
        self.terminal_interrupt.setEnabled(ready)

    def append_terminal_output(self, text: str) -> None:
        cursor = self.terminal_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.terminal_output.setTextCursor(cursor)
        self.terminal_output.ensureCursorVisible()

    def send_terminal_command(self) -> None:
        command = self.terminal_input.text()
        if not command or not isinstance(self.worker, SSHWorker):
            return
        self.worker.send_terminal_input(command)
        self.terminal_input.clear()

    def interrupt_terminal(self) -> None:
        if isinstance(self.worker, SSHWorker):
            self.worker.interrupt_terminal()

    def _load_settings(self) -> None:
        self.host.setText(self.settings.value("host", "10.122.105.215"))
        self.port.setValue(int(self.settings.value("port", 22)))
        self.username.setText(self.settings.value("username", "jetson"))
        stored = load_password(self.host.text(), self.username.text())
        if stored:
            self.password.setText(stored)
            self.remember.setChecked(True)

    def log(self, text: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {text}")

    def toggle_connection(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
            self._set_connected(False)
            return
        if self.simulation.isChecked():
            worker = MockWorker()
            self.is_simulation = True
        else:
            self.is_simulation = False
            if not self.password.text():
                QMessageBox.warning(self, "비밀번호 필요", "Jetson SSH 비밀번호를 입력하세요. 체크하면 Windows 자격 증명 관리자에 안전하게 저장됩니다.")
                return
            worker = SSHWorker(self.host.text().strip(), self.port.value(), self.username.text().strip(), self.password.text())
            self.settings.setValue("host", self.host.text().strip())
            self.settings.setValue("port", self.port.value())
            self.settings.setValue("username", self.username.text().strip())
            if self.remember.isChecked():
                try:
                    save_password(self.host.text().strip(), self.username.text().strip(), self.password.text())
                except Exception as exc:
                    QMessageBox.warning(self, "비밀번호 저장 실패", f"Windows 자격 증명 관리자에 저장하지 못했습니다: {exc}")
            else:
                delete_password(self.host.text().strip(), self.username.text().strip())
        worker.connected.connect(self.on_connected)
        worker.disconnected.connect(self.on_disconnected)
        worker.telemetry.connect(self.update_telemetry)
        worker.acknowledgement.connect(self.on_ack)
        worker.log.connect(self.log)
        if isinstance(worker, SSHWorker):
            worker.host_key_confirmation.connect(self.confirm_host_key)
            worker.terminal_output.connect(self.append_terminal_output)
            worker.terminal_state.connect(self.on_terminal_state)
        self.worker = worker
        self.connect_button.setText("연결 중...")
        self.connect_button.setEnabled(False)
        worker.start()

    def _set_connected(self, connected: bool) -> None:
        self.connect_button.setEnabled(True)
        self.connect_button.setText("연결 해제" if connected else "연결")
        self.simulation_badge.setVisible(connected and self.is_simulation)
        if connected and self.is_simulation:
            self.cards["ssh"].set_value("시뮬레이션", True)
        else:
            self.cards["ssh"].set_value("연결됨" if connected else "연결 안 됨", connected)
        for widget in (
            self.mode_combo,
            self.mode_button,
            self.estop_button,
            self.clear_estop_button,
            self.auto_speed_slider,
            self.auto_speed_spin,
            self.auto_speed_apply,
            self.auto_speed_reset,
            self.route_start_button,
            self.route_record_name,
            self.route_record_start,
            self.route_record_save,
            self.route_record_cancel,
            self.hil_start_button,
            self.hil_stop_button,
        ):
            widget.setEnabled(connected)
        for widget in getattr(self, "simulation_controls", []):
            widget.setEnabled(connected and self.is_simulation)
        if not connected:
            message = (
                "시뮬레이션에서는 SSH 터미널을 사용할 수 없습니다"
                if self.is_simulation
                else "SSH 연결 후 터미널을 사용할 수 있습니다"
            )
            self._set_terminal_ready(False, message)

    def on_connected(self) -> None:
        self.password.clear()
        self._set_connected(True)

    def on_terminal_state(self, ready: bool, message: str) -> None:
        self._set_terminal_ready(ready, message)
        if ready:
            self.append_terminal_output(f"\n--- SSH 터미널 연결됨: {message} ---\n")
            self.tabs.setCurrentIndex(self.terminal_tab_index)
            self.terminal_input.setFocus()
        elif message:
            self.append_terminal_output(f"\n--- {message} ---\n")

    def confirm_host_key(self, host: str, key_type: str, fingerprint: str) -> None:
        answer = QMessageBox.warning(
            self,
            "처음 보는 SSH 호스트 키",
            "Jetson의 SSH 호스트 키를 처음 확인했습니다.\n\n"
            f"호스트: {host}\n종류: {key_type}\n지문: {fingerprint}\n\n"
            "Jetson에서 확인한 지문과 같을 때만 저장하고 연결하세요. 신뢰합니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if isinstance(self.worker, SSHWorker):
            self.worker.respond_to_host_key(answer == QMessageBox.Yes)

    def on_disconnected(self, reason: str) -> None:
        self._release_remote_controls(send=False)
        self._pending_mode_request = None
        self._pending_mode_target = None
        self._pending_multipath_request = None
        self._mode_dirty = False
        self.mode_button.setText("모드 적용")
        self.multipath_apply.setText("기준 저장 *" if self._multipath_dirty else "기준 저장")
        self.log(f"연결 종료: {reason}")
        self._set_connected(False)

    def command(self, command: str, **kwargs) -> str | None:
        if not self.worker or not self.worker.isRunning():
            self.log("명령을 보내지 못했습니다: Jetson에 연결되어 있지 않습니다")
            return None
        return self.worker.send_command(command, **kwargs)

    def _on_mode_selected(self, _index: int) -> None:
        if self._syncing_mode:
            return
        self._mode_dirty = self.mode_combo.currentData() != self.current_mode
        self.mode_button.setText("모드 적용 *" if self._mode_dirty else "모드 적용")

    def _sync_mode_editor(self, mode: str) -> None:
        mode_index = self.mode_combo.findData(mode)
        if mode_index < 0:
            return
        self._syncing_mode = True
        try:
            self.mode_combo.setCurrentIndex(mode_index)
        finally:
            self._syncing_mode = False
        self._mode_dirty = False
        self.mode_button.setText("모드 적용")
        self.mode_combo.setEnabled(bool(self.worker and self.worker.isRunning()))
        self.mode_button.setEnabled(bool(self.worker and self.worker.isRunning()))

    def _request_mode(self, mode: str) -> str | None:
        if mode != "REMOTE":
            self._release_remote_controls(send=False)
        request_id = self.command("SET_MODE", mode=mode)
        if request_id is not None:
            self._pending_mode_request = request_id
            self._pending_mode_target = mode
            self._mode_dirty = True
            self.mode_button.setText("적용 확인 중...")
            self.mode_combo.setEnabled(False)
            self.mode_button.setEnabled(False)
        return request_id

    def set_mode(self) -> None:
        self._request_mode(str(self.mode_combo.currentData()))

    @staticmethod
    def _auto_speed_percentage(value: int) -> int:
        return round((value - 6450) / (7800 - 6450) * 100)

    def _set_auto_speed_editor(self, value: int, *, dirty: bool) -> None:
        self._syncing_auto_speed = True
        try:
            self.auto_speed_slider.setValue(value)
            self.auto_speed_spin.setValue(value)
            self.auto_speed_percent.setText(f"{self._auto_speed_percentage(value)}%")
        finally:
            self._syncing_auto_speed = False
        self._auto_speed_dirty = dirty

    def _auto_speed_from_slider(self, value: int) -> None:
        if self._syncing_auto_speed:
            return
        self._set_auto_speed_editor(value, dirty=True)

    def _auto_speed_from_spin(self, value: int) -> None:
        if self._syncing_auto_speed:
            return
        self._set_auto_speed_editor(value, dirty=True)

    def apply_auto_speed(self) -> None:
        self.command("SET_AUTO_CRUISE_PWM", value=self.auto_speed_spin.value())

    def reset_auto_speed(self) -> None:
        self._set_auto_speed_editor(6650, dirty=True)

    def clear_estop(self) -> None:
        answer = QMessageBox.question(self, "비상정지 해제", "비상정지 잠금을 해제할까요? 해제 후에도 자동 안전 모드에서 조향 6000, 스로틀 6450을 유지합니다.")
        if answer == QMessageBox.Yes:
            self.command("CLEAR_ESTOP")

    def send_remote(self) -> None:
        self.command("REMOTE_CONTROL", steering_pwm=self.remote_steering.value(), throttle_pwm=self.remote_throttle.value())

    def remote_neutral(self, _checked: bool = False, *, send: bool = True) -> None:
        self.remote_steering.setValue(6000); self.remote_throttle.setValue(6450)
        if send:
            self.send_remote()

    def _release_remote_controls(self, *, send: bool = True) -> None:
        self._remote_keys.clear()
        self.remote_neutral(send=send and self.current_mode == "REMOTE")

    def _send_sim_gps_state(self, _checked: bool = False) -> None:
        connected = not self.sim_gps_offline.isChecked()
        self.command("SIM_SET_GPS_CONNECTED", connected=connected)
        self.command("SIM_SET_GPS_FIX", fix=connected and not self.sim_gps_no_fix.isChecked())

    def _apply_remote_keyboard(self) -> None:
        left = Qt.Key_A in self._remote_keys or Qt.Key_Left in self._remote_keys
        right = Qt.Key_D in self._remote_keys or Qt.Key_Right in self._remote_keys
        forward = Qt.Key_W in self._remote_keys or Qt.Key_Up in self._remote_keys
        reverse = Qt.Key_S in self._remote_keys or Qt.Key_Down in self._remote_keys
        stop = Qt.Key_Space in self._remote_keys
        steering = 4900 if left and not right else 7300 if right and not left else 6000
        throttle = 6450 if stop or forward == reverse else 5800 if forward else 7000
        self.remote_steering.setValue(steering)
        self.remote_throttle.setValue(throttle)
        self.send_remote()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate):
            if self.current_mode == "REMOTE" and self._remote_keys:
                self._release_remote_controls()
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            key = int(event.key())
            remote_keys = {
                Qt.Key_W, Qt.Key_Up, Qt.Key_S, Qt.Key_Down,
                Qt.Key_A, Qt.Key_Left, Qt.Key_D, Qt.Key_Right, Qt.Key_Space,
            }
            focus = QApplication.focusWidget()
            text_entry = isinstance(focus, (QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox))
            if self.current_mode == "REMOTE" and key in remote_keys and not text_entry:
                if event.isAutoRepeat():
                    return True
                if event.type() == QEvent.KeyPress:
                    self._remote_keys.add(key)
                else:
                    self._remote_keys.discard(key)
                self._apply_remote_keyboard()
                return True
        return super().eventFilter(watched, event)

    def select_route(self) -> None:
        route_id = self.route_combo.currentData()
        if route_id:
            self.pending_route_id = str(route_id)
            self.command("SELECT_ROUTE", route_id=route_id)

    def start_gps_recording(self) -> None:
        name = " ".join(self.route_record_name.text().strip().split())
        if not name:
            name = dt.datetime.now().strftime("GPS 기록 %Y-%m-%d %H-%M-%S")
            self.route_record_name.setText(name)
        self.command(
            "START_GPS_RECORDING", name=name,
            minimum_distance_m=self.route_record_spacing.value(),
            minimum_interval_s=self.route_record_interval.value(),
            arrival_radius_m=self.route_arrival_radius.value(),
        )

    def _mark_multipath_dirty(self, *_args) -> None:
        if not self._syncing_multipath:
            self._multipath_dirty = True
            self.multipath_apply.setText("기준 저장 *")

    def apply_multipath(self) -> None:
        request_id = self.command(
            "SET_MULTIPATH",
            enabled=self.multipath_enabled.isChecked(),
            endpoint_tolerance_m=self.multipath_endpoint.value(),
            off_route_distance_m=self.multipath_off_distance.value(),
            off_route_hold_s=self.multipath_hold.value(),
            closer_advantage_m=self.multipath_advantage.value(),
            switch_cooldown_s=self.multipath_cooldown.value(),
        )
        if request_id is not None:
            self._pending_multipath_request = request_id
            self.multipath_apply.setEnabled(False)
            self.multipath_apply.setText("저장 확인 중...")
            self.multipath_status.setText("Jetson 설정 파일 저장 결과를 확인하는 중입니다")

    def stop_gps_recording(self) -> None:
        self.command("STOP_GPS_RECORDING")

    def cancel_gps_recording(self) -> None:
        self.command("CANCEL_GPS_RECORDING")

    def start_hil(self) -> None:
        route_id = self.route_combo.currentData()
        if not route_id:
            QMessageBox.warning(self, "항로 없음", "먼저 HIL에 사용할 저장 항로를 선택하세요.")
            return
        answer = QMessageBox.warning(
            self,
            "HIL 실제 출력 확인",
            "HIL은 실제 조향·ESC 출력을 발생시킬 수 있습니다. 프로펠러를 분리했고 비상정지를 확인했습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        request_id = self.command("START_HIL", route_id=route_id)
        if request_id is not None:
            self._pending_mode_request = request_id
            self._pending_mode_target = "NAVIGATION"
            self._mode_dirty = True
            self.mode_button.setText("HIL 전환 확인 중...")
            self.mode_combo.setEnabled(False)
            self.mode_button.setEnabled(False)

    def start_selected_route(self) -> None:
        route_id = self.route_combo.currentData()
        if not route_id:
            QMessageBox.warning(self, "항로 없음", "먼저 운행할 저장 항로를 선택하세요.")
            return
        if self.current_mode == "REMOTE":
            self._release_remote_controls()
        self.pending_route_id = str(route_id)
        request_id = self.command("SELECT_ROUTE", route_id=route_id)
        if request_id is not None:
            self.pending_route_start_request = request_id
            self.log("선택한 항로를 확인한 뒤 GPS 운행을 시작합니다")

    def on_ack(self, ack: dict) -> None:
        if ack.get("ok"):
            if (
                ack.get("command") == "SELECT_ROUTE"
                and self.pending_route_start_request is not None
                and ack.get("request_id") == self.pending_route_start_request
            ):
                self.pending_route_start_request = None
                self._request_mode("NAVIGATION")
            if ack.get("command") == "SET_AUTO_CRUISE_PWM":
                self._auto_speed_dirty = False
            if (
                ack.get("command") == "SET_MULTIPATH"
                and ack.get("request_id") == self._pending_multipath_request
            ):
                self._pending_multipath_request = None
                self._multipath_dirty = False
                self.multipath_apply.setEnabled(True)
                self.multipath_apply.setText("기준 저장")
            if ack.get("command") == "STOP_GPS_RECORDING":
                self.command("RELOAD_ROUTES")
            if ack.get("command") == "START_HIL":
                self._pending_mode_request = ack.get("request_id")
                self._pending_mode_target = "NAVIGATION"
            if ack.get("command") != "HEARTBEAT":
                self.log(f"명령 완료: {ack.get('command')}")
        else:
            if ack.get("command") == "SELECT_ROUTE":
                self.pending_route_id = None
                if ack.get("request_id") == self.pending_route_start_request:
                    self.pending_route_start_request = None
            if ack.get("request_id") == self._pending_mode_request:
                self._pending_mode_request = None
                self._pending_mode_target = None
                self._sync_mode_editor(self.current_mode)
            if (
                ack.get("command") == "SET_MULTIPATH"
                and ack.get("request_id") == self._pending_multipath_request
            ):
                self._pending_multipath_request = None
                self._multipath_dirty = True
                self.multipath_apply.setEnabled(True)
                self.multipath_apply.setText("기준 저장 *")
                self.multipath_status.setText(f"저장 실패: {ack.get('error', '알 수 없는 오류')}")
            self.log(f"명령 거부 {ack.get('command')}: {ack.get('error')}")

    @staticmethod
    def _fmt(value, digits=6, suffix="") -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.{digits}f}{suffix}"
        return f"{value}{suffix}"

    def update_telemetry(self, state: dict) -> None:
        devices, gps, rc, pca = state.get("devices", {}), state.get("gps", {}), state.get("rc", {}), state.get("pca", {})
        mode = state.get("mode", "-")
        self.current_mode = str(mode)
        if self._pending_mode_target == mode:
            self._pending_mode_request = None
            self._pending_mode_target = None
            self._sync_mode_editor(str(mode))
        elif not self._mode_dirty and self._pending_mode_target is None:
            self._sync_mode_editor(str(mode))
        operation = state.get("operation_state", mode)
        auto_cruise_pwm = state.get("auto_cruise_pwm")
        if not self._auto_speed_dirty and isinstance(auto_cruise_pwm, int):
            self._set_auto_speed_editor(auto_cruise_pwm, dirty=False)
        mode_ko = {"AUTO": "자동 대기", "MANUAL": "수동 조종", "NAVIGATION": "GPS 항법", "REMOTE": "PC 원격"}.get(mode, mode)
        operation_ko = {
            "AUTO": "자동 대기", "AUTO_ACTIVE": "직진 운항 중", "AUTO_SAFE": "안전 정지",
            "MANUAL_WAITING_RC": "조종기 입력 대기", "MANUAL_WAITING_NEUTRAL": "중립 입력 대기", "MANUAL_ACTIVE": "수동 조종 중",
            "NAVIGATION_WAITING_GPS": "GPS 대기", "NAVIGATION_WAITING_ROUTE": "항로 대기",
            "NAVIGATION_WAITING_COURSE": "진행방향 대기",
            "NAVIGATION_STARTING_COURSE": "진행방향 획득 중·직진 출발",
            "NAVIGATION_ACTIVE": "자동 운항 중", "NAVIGATION_ROUTE_COMPLETE": "목적지 도착·정지",
            "REMOTE_ACTIVE": "PC 원격 조종 중", "EMERGENCY_STOP": "비상정지",
            "HIL_ACTIVE": "HIL 항법 시험 중",
        }.get(operation, operation)
        self.cards["mode"].set_value(f"{mode_ko} · {operation_ko}", not state.get("estop", False))
        mock = bool(state.get("mock"))
        self.is_simulation = mock or self.is_simulation
        self.simulation_badge.setVisible(mock)
        ok_text = "모의 정상" if mock else "정상"
        gps_ok_text = "모의 위치" if mock else "위치 수신"
        self.cards["arduino"].set_value(ok_text if devices.get("arduino") else "연결 끊김", bool(devices.get("arduino")))
        self.cards["pca"].set_value(ok_text if devices.get("pca9685") else "연결 끊김", bool(devices.get("pca9685")))
        gps_connected = bool(devices.get("gps"))
        gps_text = gps_ok_text if gps.get("fix") else "GPS NO FIX" if gps_connected else "연결 끊김"
        self.cards["gps"].set_value(gps_text, bool(gps.get("fix")))
        self.cards["armed"].set_value(operation_ko if mode == "NAVIGATION" else "대기", bool(state.get("navigation_active")))
        self.cards["estop"].set_value("작동 중" if state.get("estop") else "정상", not bool(state.get("estop")))
        self.value_labels["rc_steering"].set_value(self._fmt(rc.get("steering_us"), 0, " us"))
        self.value_labels["rc_throttle"].set_value(self._fmt(rc.get("throttle_us"), 0, " us"))
        self.value_labels["pca_steering"].set_value(self._fmt(pca.get("steering_pwm"), 0))
        self.value_labels["pca_throttle"].set_value(self._fmt(pca.get("throttle_pwm"), 0))
        self.value_labels["lat"].set_value(self._fmt(gps.get("lat")))
        self.value_labels["lon"].set_value(self._fmt(gps.get("lon")))
        self.value_labels["altitude"].set_value(self._fmt(gps.get("altitude_m"), 2, " m"))
        self.value_labels["hdop"].set_value(self._fmt(gps.get("hdop"), 2))
        self.value_labels["last_fix_age"].set_value(self._fmt(gps.get("last_fix_age_s"), 1, " s"))
        self.value_labels["satellites"].set_value(self._fmt(gps.get("satellites"), 0))
        self.value_labels["speed"].set_value(self._fmt(gps.get("speed_mps"), 2, " m/s"))
        self.value_labels["course"].set_value(self._fmt(gps.get("course_deg"), 1, "°"))
        failsafe = state.get("failsafe_reason") or "없음"
        failsafe_ko = {
            "BOOT_SAFE": "부팅 안전",
            "BOOT_WAITING_RC": "부팅 후 조종기 입력 대기",
            "EMERGENCY_STOP": "비상정지",
            "REMOTE_HEARTBEAT_TIMEOUT": "PC 연결 신호 끊김",
            "GPS_NO_FIX": "GPS 위치 미수신",
            "GPS_STALE": "GPS 데이터 지연",
            "ARDUINO_OR_RC_LOST": "Arduino/조종기 연결 끊김",
            "ARDUINO_OR_RC_UNAVAILABLE": "Arduino/조종기 사용 불가",
            "GPS_COURSE_UNAVAILABLE": "GPS 진행방향 대기",
            "ROUTE_COMPLETE": "목적지 도착·안전 정지",
            "ESTOP_CLEARED": "비상정지 해제 후 안전 대기",
            "SIMULATION": "시뮬레이션",
        }.get(failsafe, failsafe)
        self.value_labels["failsafe"].set_value(failsafe_ko)
        health = gps.get("health") or {}
        health_status = str(health.get("status") or "UNKNOWN")
        colors = {"GOOD": "#4ee0b0", "WARNING": "#f8bd58", "BAD": "#ff6474", "NO_FIX": "#ff6474", "STALE": "#ff6474"}
        reasons = " · ".join(str(item) for item in health.get("reasons") or [])
        self.gps_health_status.setText(f"GPS Health: {health_status}" + (f"\n{reasons}" if reasons else ""))
        self.gps_health_status.setStyleSheet(f"color:{colors.get(health_status, '#8ea4c4')}; font-weight:700")
        self.gps_detail_labels["fix_label"].setText(str(gps.get("fix_label") or "-"))
        self.gps_detail_labels["utc_time"].setText(str(gps.get("utc_time") or "-"))
        self.gps_detail_labels["satellites"].setText(self._fmt(gps.get("satellites"), 0))
        self.gps_detail_labels["hdop"].setText(self._fmt(gps.get("hdop"), 2))
        self.gps_detail_labels["pdop"].setText(self._fmt(gps.get("pdop"), 2))
        self.gps_detail_labels["vdop"].setText(self._fmt(gps.get("vdop"), 2))
        self.gps_detail_labels["cno"].setText(self._fmt(gps.get("cno_avg_dbhz"), 1, " dB-Hz"))
        self.gps_detail_labels["hacc"].setText(self._fmt(gps.get("hacc_m"), 2, " m"))
        self.gps_detail_labels["age"].setText(self._fmt(gps.get("age_s"), 2, " s"))
        utm_text = "-"
        if gps.get("utm_easting") is not None and gps.get("utm_northing") is not None:
            utm_text = f"{gps.get('utm_zone') or ''} {float(gps['utm_easting']):.2f}, {float(gps['utm_northing']):.2f}"
        self.gps_detail_labels["utm"].setText(utm_text)
        self.gps_detail_labels["rtk_state"].setText(str(gps.get("rtk_state") or "UNKNOWN"))
        ntrip = state.get("ntrip") or {}
        self.gps_detail_labels["correction_age"].setText(self._fmt(ntrip.get("last_correction_age_s"), 1, " s"))
        self.ntrip_status.setText(
            ("연결됨" if ntrip.get("connected") else "연결 안 됨")
            + f" · {ntrip.get('host') or '-'}:{ntrip.get('port') or '-'} / {ntrip.get('mountpoint') or '-'}"
            + f" · {int(ntrip.get('bytes_received') or 0)} bytes"
            + (f" · 오류: {ntrip.get('last_error')}" if ntrip.get("last_error") else "")
        )
        if not self.ntrip_host.hasFocus(): self.ntrip_host.setText(str(ntrip.get("host") or ""))
        if not self.ntrip_mountpoint.hasFocus(): self.ntrip_mountpoint.setText(str(ntrip.get("mountpoint") or ""))
        self.ntrip_port.setValue(int(ntrip.get("port") or 2101))
        self.ntrip_tls.setChecked(bool(ntrip.get("tls")))
        self.ntrip_enabled.setChecked(bool(ntrip.get("enabled")))
        gps_settings = state.get("gps_settings") or {}
        self.rtk_required.setChecked(bool(gps_settings.get("rtk_required_for_navigation", False)))
        self.gps_max_hdop.setValue(float(gps_settings.get("navigation_max_hdop", 3.0)))
        data_logging = state.get("gps_logging") or {}
        logging_active = bool(data_logging.get("active"))
        self.gps_log_start.setEnabled(not logging_active)
        self.gps_log_stop.setEnabled(logging_active)
        self.gps_log_status.setText(
            f"기록 중 · {int(data_logging.get('samples') or 0)} samples · {data_logging.get('file_path') or '-'}"
            if logging_active else f"기록 대기 · 마지막 파일 {data_logging.get('file_path') or '-'}"
        )
        self.rc_graph.append(rc.get("steering_us"), rc.get("throttle_us"))
        self.pwm_graph.append(pca.get("steering_pwm"), pca.get("throttle_pwm"))

        recording = state.get("gps_recording") or {}
        recording_active = bool(recording.get("active"))
        self.route_record_status.setText(
            f"기록 중 · {recording.get('name', '-')} · {int(recording.get('point_count') or 0)}개 지점"
            if recording_active else "기록 대기"
        )
        self.route_record_start.setEnabled(not recording_active)
        self.route_record_save.setEnabled(recording_active)
        self.route_record_cancel.setEnabled(recording_active)
        hil = state.get("hil") or {}
        hil_active = bool(hil.get("active"))
        self.hil_status.setText(
            f"HIL 실행 중 · {self._fmt(hil.get('lat'))}, {self._fmt(hil.get('lon'))}"
            if hil_active else "HIL 대기"
        )
        self.hil_start_button.setEnabled(not hil_active)
        self.hil_stop_button.setEnabled(hil_active)

        route = state.get("route") or {}
        multipath = route.get("multipath") or {}
        route_storage_path = str(route.get("storage_path") or "-")
        multipath_config_path = str(route.get("multipath_config_path") or "-")
        persisted_mark = "저장됨" if route.get("selected_route_persisted") else "저장 확인 중"
        self.route_storage_status.setText(
            f"항로 저장: {route_storage_path} · 선택 항로 {persisted_mark} · "
            f"Multi-Path 설정: {multipath_config_path}"
        )
        if multipath and not self._multipath_dirty:
            self._syncing_multipath = True
            try:
                self.multipath_enabled.setChecked(bool(multipath.get("enabled", True)))
                self.multipath_endpoint.setValue(float(multipath.get("endpoint_tolerance_m", 0.75)))
                self.multipath_off_distance.setValue(float(multipath.get("off_route_distance_m", 8.0)))
                self.multipath_hold.setValue(float(multipath.get("off_route_hold_s", 3.0)))
                self.multipath_advantage.setValue(float(multipath.get("closer_advantage_m", 2.0)))
                self.multipath_cooldown.setValue(float(multipath.get("switch_cooldown_s", 5.0)))
                self.multipath_apply.setText("기준 저장")
            finally:
                self._syncing_multipath = False
        active_id = route.get("active_route_id", "")
        selected_id = route.get("selected_route_id", active_id)
        routes = state.get("routes", [])
        existing = {self.route_combo.itemData(i) for i in range(self.route_combo.count())}
        if {r.get("id") for r in routes} != existing:
            self.route_combo.clear()
            for item in routes:
                self.route_combo.addItem(item.get("name", item.get("id", "route")), item.get("id"))
        if self.pending_route_id == selected_id:
            self.pending_route_id = None
        if self.pending_route_id is None:
            selected_index = self.route_combo.findData(selected_id)
            if selected_index >= 0 and self.route_combo.currentIndex() != selected_index:
                self.route_combo.setCurrentIndex(selected_index)
        selected_name = route.get("selected_route_name", route.get("active_route_name", "-"))
        active_name = route.get("active_route_name", "-")
        route_error = route.get("load_error")
        group_ids = route.get("multipath_group_route_ids") or []
        if self._pending_multipath_request is None:
            self.multipath_status.setText(
                f"{'ON' if multipath.get('enabled', True) else 'OFF'} · 같은 그룹 {len(group_ids)}개"
                f" · 대체 {route.get('alternative_route_id') or '-'}"
                f" · 이탈 지속 {float(route.get('off_route_duration_s') or 0):.1f}s"
                f" · 저장 {multipath_config_path}"
            )
        self.route_status.setText(
            f"선택한 항로: {selected_name} · 활성 항로: {active_name} · "
            f"지점 {route.get('waypoint_index', 0) + 1}/{route.get('waypoint_count', 0)} · "
            f"목표까지 {float(route.get('distance_to_waypoint_m') or 0):.1f} m · "
            f"경로 이탈 {float(route.get('distance_to_route_m') or 0):.1f} m"
            + (f" · 항로 오류: {route_error}" if route_error else "")
        )
        display_gps = dict(gps)
        if hil_active and hil.get("lat") is not None and hil.get("lon") is not None:
            display_gps.update(lat=hil.get("lat"), lon=hil.get("lon"), fix=True)
        self.route_plot.update_data(routes, display_gps, active_id)
        for event in state.get("events", []):
            stamp = float(event.get("timestamp", 0))
            if stamp > self.last_event_timestamp:
                self.log(f"{event.get('level', 'INFO')}: {event.get('message', '')}")
                self.last_event_timestamp = max(self.last_event_timestamp, stamp)
        current_errors = tuple(state.get("hardware_errors", []))
        if current_errors != self.last_hardware_errors:
            for error in current_errors:
                if error and error not in self.last_hardware_errors:
                    self.log(f"하드웨어 오류: {error}")
            self.last_hardware_errors = current_errors

    def closeEvent(self, event: QCloseEvent) -> None:
        self._release_remote_controls()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1200)
        event.accept()
