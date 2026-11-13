"""Compact map-first shell; existing feature pages and their slots are retained."""
from bisect import bisect_left, bisect_right
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from pathlib import Path
import sys
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QFrame,QGroupBox,
    QLineEdit,QSpinBox,QCheckBox,QPushButton,QComboBox,QSlider,QTabWidget,QListWidget,
    QScrollArea,QSplitter,QSizePolicy)
from .widgets import StatusCard,RoutePlot,TelemetryGraph
from .balloon_panel import BalloonPanel
from rcboat_ros.control_config import CRUISE_DEFAULT, CRUISE_MIN, CRUISE_MAX, CRUISE_STEP, THROTTLE_FORWARD_MAX

CRUISE_SLIDER_VALUES = tuple(range(CRUISE_MIN, CRUISE_MAX, CRUISE_STEP)) + (CRUISE_MAX,)


class CruiseSpinBox(QSpinBox):
    def stepBy(self, steps):
        if steps == 0:
            return
        values = CRUISE_SLIDER_VALUES
        value = self.value()
        index = bisect_right(values, value) + steps - 1 if steps > 0 else bisect_left(values, value) + steps
        self.setValue(values[max(0, min(len(values) - 1, index))])

STYLE='''
QMainWindow {background:#0b1220;} QWidget {color:#e5edf7; font-family:'Malgun Gothic','Segoe UI'; font-size:9pt;}
QLabel {background:transparent;} QFrame#rail {background:#101b2b;border-right:1px solid #243347;}
QLabel#brand {font-size:14pt;font-weight:900;color:#f3f7fc;} QLabel#eyebrow {font-size:8pt;color:#5fe3d0;font-weight:800;}
QLabel#appTitle {font-size:17pt;font-weight:800;} QLabel#appSubtitle,QLabel#sectionHint {color:#91a5bd; font-size:8pt;}
QLabel#safetyBadge {background:#12312d;color:#68e5c0;border:1px solid #26554b;border-radius:7px;padding:6px 10px;}
QLabel#simulationBadge {background:#573d17;color:#ffda81;border-radius:5px;padding:5px 8px;font-weight:700;}
QListWidget#navigation {background:transparent;border:0;outline:0;padding:4px;}
QListWidget#navigation::item {padding:13px 8px;margin:3px 0;border-radius:7px;color:#9eafc6;}
QListWidget#navigation::item:selected {background:#1b3b48;color:#66e6d4;border-left:3px solid #43d2bc;}
QGroupBox {background:#111e2e;border:1px solid #26384e;border-radius:9px;margin-top:12px;padding:12px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 6px;color:#a7bfd6;}
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTextEdit,QPlainTextEdit {background:#0c1726;color:#e7effa;border:1px solid #30435b;border-radius:5px;padding:6px;selection-background-color:#237e83;}
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus {border:1px solid #48cdbd;}
QPushButton {background:#1c4552;border:1px solid #2f6270;border-radius:6px;padding:8px 12px;color:#e0f8f4;font-weight:600;}
QPushButton:hover {background:#265c68;} QPushButton:pressed {background:#133b43;}
QPushButton:disabled {background:#172232;color:#65758b;border-color:#253346;}
QPushButton#danger {background:#bc334b;border-color:#dc5065;color:white;min-height:28px;font-weight:800;}
QPushButton#danger:hover {background:#d84058;} QPushButton#safe {background:#205c4c;border-color:#347961;color:#9ef2c7;}
QFrame#statusCard,QFrame#metricCard {background:#111e2e;border:1px solid #24364d;border-radius:8px;}
QLabel#cardTitle,QLabel#metricTitle {color:#93a9c2;font-size:8pt;} QLabel#cardValue {font-size:11pt;font-weight:750;}
QLabel#metricValue {font-size:15pt;font-weight:800;} QLabel#metricHint {font-size:8pt;color:#91a5bd;}
QLabel#healthHeadline {font-size:12pt;font-weight:800;}
QTabWidget::pane {border:0;background:transparent;} QTabBar::tab {background:#16273a;padding:7px 12px;color:#a6bdd5;border-radius:4px;}
QTabBar::tab:selected {background:#22505c;color:#b7fff0;}
QScrollArea {border:0;background:transparent;} QScrollBar:vertical {background:#101b2b;width:10px;margin:0;}
QScrollBar::handle:vertical {background:#354b63;border-radius:4px;min-height:28px;}
QScrollBar:horizontal {background:#101b2b;height:10px;} QScrollBar::handle:horizontal {background:#354b63;border-radius:4px;min-width:28px;}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;} QSplitter::handle {background:#26394e;width:3px;}
QSlider::groove:horizontal {height:5px;background:#273d54;border-radius:2px;}
QSlider::handle:horizontal {width:14px;margin:-5px 0;background:#53dbbe;border-radius:7px;}
QCheckBox {spacing:6px;} QToolTip {background:#17283b;color:#edf5ff;border:1px solid #36516c;padding:6px;}
'''

def scroll_page(page):
    area=QScrollArea();area.setWidgetResizable(True);area.setWidget(page)
    page.setAutoFillBackground(False);area.viewport().setAutoFillBackground(False)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    return area

def build_shell(w):
    w.setStyleSheet(STYLE)
    central=QWidget();root=QHBoxLayout(central);root.setContentsMargins(0,0,0,0);root.setSpacing(0);w.setCentralWidget(central)
    rail=QFrame();rail.setObjectName('rail');rail.setFixedWidth(154);left=QVBoxLayout(rail);left.setContentsMargins(10,20,10,12)
    brand_row=QHBoxLayout();brand_row.setSpacing(6)
    mascot=QLabel();bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]));mascot.setPixmap(QPixmap(str(bundle/'assets/cream_cat_mascot.png')).scaled(32,32,Qt.KeepAspectRatio,Qt.SmoothTransformation));mascot.setFixedSize(32,32);brand_row.addWidget(mascot)
    brand=QLabel('RC BOAT');brand.setObjectName('brand');brand_row.addWidget(brand,1);left.addLayout(brand_row)
    eyebrow=QLabel('MISSION CONTROL');eyebrow.setObjectName('eyebrow');left.addWidget(eyebrow);left.addSpacing(12)
    w.sidebar=QListWidget();w.sidebar.setObjectName('navigation');left.addWidget(w.sidebar,1)
    footer=QLabel('ROS NOETIC\nJETSON • RC • GNSS');footer.setObjectName('appSubtitle');left.addWidget(footer);root.addWidget(rail)
    body=QWidget();outer=QVBoxLayout(body);outer.setContentsMargins(18,12,18,12);outer.setSpacing(9);root.addWidget(body,1)
    header=QHBoxLayout();titles=QVBoxLayout();titles.setSpacing(2)
    title=QLabel('보트 운항 관제');title.setObjectName('appTitle');titles.addWidget(title)
    version=w.windowTitle().split('v')[-1]
    sub=QLabel('실시간 항로 · GNSS · 붉은 풍선 추적   /   v'+version);sub.setObjectName('appSubtitle');titles.addWidget(sub)
    header.addLayout(titles);header.addStretch()
    w.simulation_badge=QLabel('SIMULATION');w.simulation_badge.setObjectName('simulationBadge');w.simulation_badge.hide();header.addWidget(w.simulation_badge)
    safety=QLabel('출력 상태 확인 전');safety.setObjectName('safetyBadge');w.safety_badge=safety;header.addWidget(safety);outer.addLayout(header)
    w.estop_banner=QFrame();w.estop_banner.setObjectName('estopBanner')
    w.estop_banner.setStyleSheet('QFrame#estopBanner {background:#8b2034;border:2px solid #ff7c89;border-radius:8px;}')
    emergency_row=QHBoxLayout(w.estop_banner);emergency_row.setContentsMargins(12,9,12,9)
    w.estop_banner_text=QLabel('■ 비상정지 작동 중 · ESC·서보 출력 잠금');w.estop_banner_text.setWordWrap(True)
    w.estop_banner_text.setStyleSheet('color:#ffffff;font-size:12pt;font-weight:800;');emergency_row.addWidget(w.estop_banner_text,1)
    w.estop_banner_clear=QPushButton('비상정지 해제');w.estop_banner_clear.clicked.connect(w.clear_estop);emergency_row.addWidget(w.estop_banner_clear)
    w.estop_banner.hide();outer.addWidget(w.estop_banner)
    connect=QGroupBox('장치 연결');grid=QGridLayout(connect);grid.setContentsMargins(10,8,10,8)
    w.host=QLineEdit();w.port=QSpinBox();w.port.setRange(1,65535);w.port.setValue(22);w.port.setMaximumWidth(85)
    w.username=QLineEdit('jetson');w.password=QLineEdit();w.password.setEchoMode(QLineEdit.Password)
    for col,(label,widget) in enumerate((('Jetson 주소',w.host),('SSH 포트',w.port),('사용자',w.username),('비밀번호',w.password))):
        grid.addWidget(QLabel(label),0,col);grid.addWidget(widget,1,col)
    w.remember=QCheckBox('비밀번호 안전 저장');w.simulation=QCheckBox('시뮬레이션')
    w.connect_button=QPushButton('연결');w.connect_button.clicked.connect(w.toggle_connection)
    extras=QHBoxLayout();extras.addWidget(w.remember);extras.addWidget(w.simulation);extras.addStretch();header.addWidget(w.connect_button)
    grid.addLayout(extras,2,0,1,4);grid.setColumnStretch(0,3);grid.setColumnStretch(2,1);grid.setColumnStretch(3,2);outer.addWidget(connect)
    w.connection_settings=connect;w.connection_toggle=QPushButton('연결 설정');header.addWidget(w.connection_toggle);w.connection_toggle.setCheckable(True);w.connection_toggle.toggled.connect(connect.setVisible);connect.hide()
    status=QGridLayout();status.setSpacing(6)
    w.cards={key:StatusCard(label,default) for key,label,default in [
        ('ssh','SSH','disconnected'),('ros_master','ROS master','offline'),('backend','ROS gateway','확인 전'),
        ('logger','LOGGER','idle'),('mode','운항 모드','자동 대기'),('arduino','RC 입력','-'),('pca','PCA9685','-'),
        ('gps','GPS','no_data'),('rtk','RTK','no_data'),('armed','항법 출력','대기'),('estop','비상정지','정상')]}
    primary=['ssh','ros_master','backend','gps','rtk','mode']
    for i,key in enumerate(primary):status.addWidget(w.cards[key],0,i)
    detail=QGroupBox('상세 장치 상태');detail_grid=QGridLayout(detail)
    for i,key in enumerate(['logger','arduino','pca','armed','estop']):detail_grid.addWidget(w.cards[key],0,i)
    grid.addWidget(detail,3,0,1,4)
    outer.addLayout(status)
    controls=QGridLayout();controls.setHorizontalSpacing(8)
    w.mode_combo=QComboBox()
    for label,value in [('자동 대기','AUTO'),('수동 조종','MANUAL'),('GPS 항법','NAVIGATION'),('PC 원격 조종','REMOTE'),('풍선 추적','BALLOON')]:w.mode_combo.addItem(label,value)
    w.mode_combo.currentIndexChanged.connect(w._on_mode_selected)
    w.mode_button=QPushButton('모드 적용');w.mode_button.clicked.connect(w.set_mode)
    controls.addWidget(w.mode_combo,0,0);controls.addWidget(w.mode_button,0,1)
    w.estop_button=QPushButton('비상 정지');w.estop_button.setObjectName('danger');w.estop_button.clicked.connect(lambda:w.command('EMERGENCY_STOP'))
    w.clear_estop_button=QPushButton('비상정지 해제');w.clear_estop_button.setObjectName('safe');w.clear_estop_button.clicked.connect(w.clear_estop)
    controls.addWidget(w.clear_estop_button,0,5);controls.addWidget(w.estop_button,0,6)
    w.auto_speed_slider=QSlider(Qt.Horizontal);w.auto_speed_slider.setRange(0,len(CRUISE_SLIDER_VALUES)-1);w.auto_speed_slider.setSingleStep(1);w.auto_speed_slider.setPageStep(5);w.auto_speed_slider.setValue(CRUISE_SLIDER_VALUES.index(CRUISE_DEFAULT))
    w.auto_speed_spin=CruiseSpinBox();w.auto_speed_spin.setRange(CRUISE_MIN,CRUISE_MAX);w.auto_speed_spin.setValue(CRUISE_DEFAULT);w.auto_speed_spin.setSuffix(' PWM');w.auto_speed_spin.setKeyboardTracking(False)
    w.auto_speed_spin.lineEdit().textEdited.connect(lambda _text:w._mark_cruise_dirty())
    w.auto_speed_slider.valueChanged.connect(w._auto_speed_from_slider);w.auto_speed_spin.valueChanged.connect(w._auto_speed_from_spin)
    w.auto_speed_status=QLabel('적용 목표: 확인 전');w.auto_speed_status.setWordWrap(True)
    w.auto_speed_apply=QPushButton('적용');w.auto_speed_apply.clicked.connect(w.apply_auto_speed)
    w.auto_speed_reset=QPushButton('기본값');w.auto_speed_reset.clicked.connect(w.reset_auto_speed)
    w.curve_slowdown=QCheckBox('커브 감속');w.curve_slowdown.setChecked(True)
    w.curve_slowdown.clicked.connect(w.set_curve_slowdown)
    w.curve_slowdown.setToolTip('항로 주행 중 일반 커브에서 감속합니다. 다른 항법 보호는 계속 적용됩니다.')
    controls.addWidget(QLabel('GPS 항법 순항 PWM'),1,0);controls.addWidget(w.auto_speed_slider,1,1,1,2)
    controls.addWidget(w.auto_speed_spin,1,3);controls.addWidget(w.auto_speed_status,1,4)
    controls.addWidget(w.auto_speed_apply,1,5);controls.addWidget(w.auto_speed_reset,1,6)
    controls.addWidget(w.curve_slowdown,2,0,1,3);controls.setColumnStretch(2,1);outer.addLayout(controls)
    w.tabs=QTabWidget();w.tabs.tabBar().hide()
    pages=[('실시간 관제',w._dashboard_tab()),('GPS · RTK',w._gps_rtk_tab()),('항로 · Multi-Path',w._route_tab()),('도보 테스트',w._ground_test_tab())]
    w.balloon_panel=BalloonPanel();w.balloon_panel.request.connect(w.vision_request)
    w.balloon_panel.start_tracking.connect(lambda:w._request_mode('BALLOON'))
    w.balloon_panel.stop_tracking.connect(lambda:w._request_mode('AUTO'))
    pages.extend([('풍선 추적',w.balloon_panel),('PC 원격 조종',w._remote_tab()),('SSH 터미널',w._terminal_tab()),('운항 기록',w._logs_tab())])
    for i,(label,page) in enumerate(pages):w.sidebar.addItem(label);w.tabs.addTab(page if i in (0,1,2,4) else scroll_page(page),label)
    w.terminal_tab_index=6;w.sidebar.currentRowChanged.connect(w.tabs.setCurrentIndex);w.tabs.currentChanged.connect(w.sidebar.setCurrentRow);w.sidebar.setCurrentRow(0)
    outer.addWidget(w.tabs,1)
    update_dashboard_quality(w,{})

def build_dashboard(w):
    page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,4,0,0)
    row=QHBoxLayout();title=QLabel('LIVE MISSION');title.setObjectName('eyebrow');row.addWidget(title);row.addStretch()
    w.map_background=QCheckBox('거리 지도 배경');w.map_background.setToolTip('OpenStreetMap 온라인 타일 · 네트워크가 없으면 좌표 지도로 계속 표시')
    fit=QPushButton('전체 항로');row.addWidget(w.map_background);row.addWidget(fit);layout.addLayout(row)
    split=QSplitter(Qt.Horizontal);split.setChildrenCollapsible(False);w.live_map=RoutePlot();split.addWidget(w.live_map)
    w.map_background.toggled.connect(w.live_map.set_basemap_enabled);fit.clicked.connect(w.live_map.fit_to_data)
    panel=QWidget();panel.setMinimumWidth(300);right=QVBoxLayout(panel);right.setContentsMargins(6,0,0,0)
    details=QTabWidget();w.dashboard_detail_tabs=details
    primary=QWidget();secondary=QWidget();values=QGridLayout(primary);extra=QGridLayout(secondary);w.value_labels={}
    for i,(title,key) in enumerate([('GNSS 속도','speed'),('진행 방향','course'),('최종 ESC 출력','pca_throttle'),('서보 CH0','pca_steering'),
        ('항법 램프 PWM','ramp_throttle'),('안전 전환 사유','failsafe'),('위도','lat'),('경도','lon'),('RC 조향 µs','rc_steering'),
        ('RC 스로틀 µs','rc_throttle'),('HDOP 참고값','hdop'),('유효 FIX 경과','last_fix_age'),('수신 위성','satellites'),('고도','altitude')]):
        card=StatusCard(title);w.value_labels[key]=card
        target,index=(values,i) if i<6 else (extra,i-6);target.addWidget(card,index//2,index%2)
    details.addTab(scroll_page(primary),'운항');details.addTab(scroll_page(secondary),'GPS · RC 입력')
    right.addWidget(details);split.addWidget(panel);split.setSizes([850,330]);w.dashboard_map_scroll=scroll_page(split);layout.addWidget(w.dashboard_map_scroll,1)
    graphs=QTabWidget();w.rc_graph=TelemetryGraph('RC 입력 (조향 / 스로틀, µs)',1000,2100,('#66d7ed','#f2c16d'))
    w.pwm_graph=TelemetryGraph('최종 출력 (조향 / 스로틀)',4800,7500,('#43d6b4','#f08eaa'))
    graphs.addTab(w.rc_graph,'RC 입력');graphs.addTab(w.pwm_graph,'PCA 출력');graphs.setMaximumHeight(200);w.dashboard_charts=graphs;w.chart_toggle=QPushButton('출력 차트 보기');row.addWidget(w.chart_toggle);w.chart_toggle.setCheckable(True);w.chart_toggle.toggled.connect(graphs.setVisible);graphs.hide();layout.addWidget(graphs)
    return page

def grouped_pages(items):
    tabs=QTabWidget()
    for title,widget in items:tabs.addTab(scroll_page(widget),title)
    return tabs

def build_route_workspace(w,operation,record,layers,multipath,settings,reload_button):
    page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,4,0,0);layout.setSpacing(8)
    # These primary actions are outside every scroll area, above the map.
    w.route_execution_tabs=QTabWidget()
    for title,combo,select,start in [('대루트 주행',w.multipath_combo,w.multipath_select_button,w.multipath_start_button),
                                  ('소루트 주행',w.route_combo,w.route_select_button,w.route_start_button)]:
        pane=QWidget();row=QHBoxLayout(pane);row.setContentsMargins(6,8,6,8)
        combo.setMinimumWidth(120);row.addWidget(combo,1);row.addWidget(select);row.addWidget(start)
        stop=QPushButton('주행 정지');stop.clicked.connect(lambda:w._request_mode('AUTO'));row.addWidget(stop)
        w.route_execution_tabs.addTab(pane,title)
    layout.addWidget(w.route_execution_tabs)
    edit=QWidget();ed=QVBoxLayout(edit)
    for title,buttons in [('소루트 편집',[w.route_add_button,w.route_edit_button,w.route_export_button,w.route_delete_button,reload_button]),
                          ('대루트 편집',[w.multipath_add_button,w.multipath_edit_button,w.multipath_delete_button])]:
        box=QGroupBox(title);grid=QGridLayout(box)
        for i,button in enumerate(buttons):grid.addWidget(button,i,0)
        ed.addWidget(box)
    for label in (w.multipath_group_status,w.route_storage_status,w.route_status):
        label.setMinimumWidth(0);label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);ed.addWidget(label)
    ed.addStretch()
    advanced=QWidget();ad=QVBoxLayout(advanced);ad.addWidget(layers);ad.addWidget(settings);ad.addStretch()
    w.multipath_status.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
    record_panel=QWidget();rp=QVBoxLayout(record_panel);rf=QFormLayout();rf.setRowWrapPolicy(QFormLayout.WrapLongRows)
    w.route_record_name.setMinimumWidth(0)
    for title,widget in [('항로 이름',w.route_record_name),('최소 이동 간격',w.route_record_spacing),
                         ('최소 기록 시간',w.route_record_interval),('도착 반경',w.route_arrival_radius)]:rf.addRow(title,widget)
    rp.addLayout(rf)
    for button in (w.route_record_start,w.route_record_save,w.route_record_cancel):rp.addWidget(button)
    w.route_record_status.setWordWrap(True);rp.addWidget(w.route_record_status);rp.addStretch()
    w.route_detail_tabs=grouped_pages([('편집',edit),('항로 기록',record_panel),('표시·설정',advanced)])
    w.route_detail_tabs.setMinimumWidth(300)
    map_page=QWidget();mp=QVBoxLayout(map_page);mp.setContentsMargins(0,0,0,0);bar=QHBoxLayout()
    hint=QLabel('휠: 확대/축소 · Shift+휠: 화면 스크롤');hint.setObjectName('sectionHint');hint.setWordWrap(True);hint.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);bar.addWidget(hint,1)
    background=QCheckBox('지도 배경');background.toggled.connect(w.route_plot.set_basemap_enabled);bar.addWidget(background)
    for label,factor in [('+',1.25),('−',.8)]:
        button=QPushButton(label);button.setMaximumWidth(35);button.clicked.connect(lambda checked=False,f=factor:w.route_plot.zoom_by(f));bar.addWidget(button)
    fit=QPushButton('전체 항로');fit.clicked.connect(w.route_plot_fit);bar.addWidget(fit);mp.addLayout(bar);mp.addWidget(w.route_plot,1)
    split=QSplitter(Qt.Horizontal);split.setChildrenCollapsible(False);split.addWidget(map_page);split.addWidget(w.route_detail_tabs);split.setSizes([800,350]);w.route_map_scroll=scroll_page(split);layout.addWidget(w.route_map_scroll,1)
    # Old group shells no longer own any visible controls. Their buttons were reparented above.
    operation.hide();multipath.hide();record.hide()
    return page

def tidy_ntrip(w,disable,refresh):
    page=QWidget();layout=QVBoxLayout(page)
    cards=QGridLayout()
    for i,card in enumerate((w.ntrip_link_card,w.ntrip_solution_card,w.ntrip_bytes_card,w.ntrip_age_card)):cards.addWidget(card,i//2,i%2)
    layout.addLayout(cards);w.ntrip_profile_summary=QLabel('Jetson 저장 설정: 연결 후 자동으로 불러옵니다');w.ntrip_profile_summary.setWordWrap(True);layout.addWidget(w.ntrip_profile_summary)
    toolbar=QHBoxLayout();w.ntrip_settings_toggle=QPushButton('Jetson 저장 설정 보기 · 수정');w.ntrip_settings_toggle.setCheckable(True)
    refresh.setText('Jetson 설정 불러오기');refresh.clicked.disconnect();refresh.clicked.connect(w.reload_ntrip_profile)
    toolbar.addWidget(w.ntrip_settings_toggle);toolbar.addWidget(refresh);toolbar.addWidget(disable);layout.addLayout(toolbar)
    box=QGroupBox('Jetson 로컬 NTRIP 설정');settings=QVBoxLayout(box);form=QFormLayout();form.setRowWrapPolicy(QFormLayout.WrapLongRows);settings.addWidget(w.ntrip_enabled)
    for title,widget in [('Host',w.ntrip_host),('Port',w.ntrip_port),('Mount Point',w.ntrip_mountpoint),
                         ('Username',w.ntrip_username),('Password',w.ntrip_password)]:form.addRow(title,widget)
    settings.addLayout(form);settings.addWidget(w.ntrip_tls)
    buttons=QHBoxLayout()
    for button in (w.ntrip_apply,w.ntrip_mount_fix):buttons.addWidget(button)
    settings.addLayout(buttons);layout.addWidget(box);w.ntrip_settings_toggle.toggled.connect(box.setVisible);box.hide()
    layout.addWidget(w.ntrip_status);layout.addStretch();return page

def update_dashboard_quality(w,state):
    gps=state.get('gps') or {};rc=state.get('rc') or {};pca=state.get('pca') or {};settings=state.get('gps_settings') or {}
    try:ref=float(settings.get('navigation_max_hdop',3.0))
    except (ValueError,TypeError):ref=3.0
    if not __import__('math').isfinite(ref):ref=3.0
    throttle_limit = CRUISE_MAX if state.get('mode') == 'NAVIGATION' else THROTTLE_FORWARD_MAX
    hints={'speed':'m/s','course':'0–360°','pca_throttle':f'정지 6450 | 항법 {CRUISE_MAX} · 기타 {THROTTLE_FORWARD_MAX}','pca_steering':'4900–7300 | 중앙 6000',
        'ramp_throttle':'6650 → 목표','failsafe':'','lat':'WGS84','lon':'WGS84','altitude':'m',
        'rc_steering':'1004 / 1620 / 1985 µs','rc_throttle':'1118 / 1499 / 1881 µs',
        'hdop':f'정상 ≤2 | 참고 ≤{ref:g}','last_fix_age':'정상 ≤2 s','satellites':'정상 ≥8 | 주의 6–7'}
    for key,hint in hints.items():w.value_labels[key].set_hint(hint)
    def level(value,good,warn):
        try:value=float(value)
        except (ValueError,TypeError):return 'NO_DATA'
        if not __import__('math').isfinite(value):return 'NO_DATA'
        return 'GOOD' if good(value) else 'WARNING' if warn(value) else 'BAD'
    criteria={'hdop':(gps.get('hdop'),lambda n:n<=2,lambda n:n<=ref),
        'satellites':(gps.get('satellites'),lambda n:n>=8,lambda n:n>=6),
        'last_fix_age':(gps.get('last_fix_age_s'),lambda n:n<=2,lambda n:False),
        'pca_throttle':(pca.get('throttle_pwm'),lambda n:5800<=n<=throttle_limit,lambda n:False),
        'pca_steering':(pca.get('steering_pwm'),lambda n:4900<=n<=7300,lambda n:False),
        'rc_steering':(rc.get('steering_us'),lambda n:970<=n<=2011,lambda n:False),
        'rc_throttle':(rc.get('throttle_us'),lambda n:1090<=n<=1908,lambda n:False)}
    colours={'GOOD':'#38d996','WARNING':'#f8bd58','BAD':'#ff6474','NO_DATA':'#7f93ac'}
    for key,args in criteria.items():w.value_labels[key].value_label.setStyleSheet('color:'+colours[level(*args)])
    if state.get('mock'):w.cards['ssh'].set_value('SIMULATION','INFO')
