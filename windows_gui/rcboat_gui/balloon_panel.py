"""Live balloon detection and one-click tracking; camera settings stay collapsed."""
import logging
import os,time
from collections import deque
from PySide6.QtCore import Qt,QTimer,QUrl,Signal,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkProxy,QNetworkRequest,QNetworkReply
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QComboBox,QPushButton,QSpinBox,QCheckBox,QFileDialog,QSizePolicy,QScrollArea)
from rcboat_ros.balloon_tracking import DEFAULTS

logger = logging.getLogger('rcboat.preview')

class BalloonPanel(QWidget):
    request=Signal(str,dict);start_tracking=Signal();stop_tracking=Signal()
    def __init__(self):
        super().__init__();self.network=self._preview_network();self.reply=None;self.host='';self.port=8766
        self.preview_request_at=0.;self.preview_retry_at=0.;self.preview_failure=None
        self.remote_enabled=False;self.camera_enabled=False;self.mock=False;self.last_image=0;self.samples=deque(maxlen=60);self.etag=''
        self.dirty=False;self.synced=False;self.syncing=False;self.generation=0;self.pending=None;self.stamp=0;self.waiting_start=False
        self.tracking_session=None;self.mode_since=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,4,0,0)
        bar=QHBoxLayout();self.summary=QLabel('카메라 연결 대기');self.summary.setObjectName('healthHeadline');bar.addWidget(self.summary,1)
        self.enable_button=QPushButton('카메라 켜기');self.disable_button=QPushButton('카메라 끄기')
        self.start_button=QPushButton('풍선 추적 시작');self.start_button.setObjectName('safe')
        self.stop_button=QPushButton('정지');self.stop_button.setObjectName('danger');self.download_button=QPushButton('로그 가져오기')
        self.enable_button.clicked.connect(lambda:self.request.emit('VISION_ENABLE',{'enabled':True}))
        self.disable_button.clicked.connect(self.disable_camera);self.start_button.clicked.connect(self.begin_tracking)
        self.stop_button.clicked.connect(self.stop);self.download_button.clicked.connect(self.download_log)
        for b in (self.enable_button,self.disable_button,self.start_button,self.stop_button,self.download_button):bar.addWidget(b)
        layout.addLayout(bar)
        options=QHBoxLayout();self.show_preview=QCheckBox('실시간 영상');self.show_preview.setChecked(True);options.addWidget(self.show_preview)
        self.metrics=QLabel('감지 대기');options.addWidget(self.metrics,1);self.bandwidth=QLabel('');options.addWidget(self.bandwidth)
        self.settings_toggle=QPushButton('카메라 설정');self.settings_toggle.setCheckable(True);options.addWidget(self.settings_toggle);layout.addLayout(options)
        settings=QWidget();form=QFormLayout(settings);form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.camera=QComboBox()
        for label,value in [('자동 (USB → CSI)','auto'),('USB','usb'),('Pi CSI','csi'),('RTSP · 보기 전용','rtsp'),('파일 · 보기 전용','file')]:self.camera.addItem(label,value)
        self.source=QLineEdit('/dev/video0');self.sensor=QSpinBox();self.sensor.setRange(0,3)
        self.resolution=QComboBox()
        for label,value in [('1920×1080 · 원거리','1920x1080'),('1280×720','1280x720'),('640×480','640x480')]:self.resolution.addItem(label,value)
        self.long_range=QCheckBox('작은 풍선 원거리 감지');self.long_range.setChecked(True)
        self.save_button=QPushButton('카메라 설정 저장');self.save_button.clicked.connect(self.save_config)
        for label,widget in [('연결 방식',self.camera),('장치 주소',self.source),('CSI 번호',self.sensor)]:form.addRow(label,widget)
        form.addRow('촬영 해상도',self.resolution);form.addRow(self.long_range)
        form.addRow(self.save_button);self.config_status=QLabel('');self.config_status.setWordWrap(True);self.config_status.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);form.addRow(self.config_status)
        self.image=QLabel('카메라를 켜면 실시간 감지 화면이 표시됩니다');self.image.setAlignment(Qt.AlignCenter);self.image.setMinimumSize(280,180)
        self.image.setStyleSheet('background:#060e18;border:1px solid #30465f;border-radius:10px;color:#92a9c1;')
        self.camera_drawer=QScrollArea();self.camera_drawer.setWidgetResizable(True);self.camera_drawer.setWidget(settings)
        self.camera_drawer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.camera_drawer.setFixedWidth(0);self.camera_drawer.hide()
        preview_row=QHBoxLayout();preview_row.addWidget(self.image,1);preview_row.addWidget(self.camera_drawer);layout.addLayout(preview_row,1)
        self.drawer_animation=QVariantAnimation(self);self.drawer_animation.setDuration(180);self.drawer_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.drawer_animation.valueChanged.connect(lambda value:self.camera_drawer.setFixedWidth(int(value)))
        self.drawer_animation.finished.connect(lambda:self.camera_drawer.hide() if not self.settings_toggle.isChecked() else None)
        self.settings_toggle.toggled.connect(self.toggle_camera_settings)
        self.shared_speed=QLabel('목표 PWM — · 최종 출력 —');layout.addWidget(self.shared_speed)
        self.editors=(self.camera,self.source,self.sensor,self.resolution,self.long_range)
        self.camera.currentIndexChanged.connect(self.edited);self.source.textEdited.connect(self.edited);self.sensor.valueChanged.connect(self.edited)
        self.resolution.currentIndexChanged.connect(self.edited);self.long_range.toggled.connect(self.edited)
        self.timer=QTimer(self);self.timer.setInterval(60);self.timer.timeout.connect(self.fetch_frame);self.timer.start();self.set_connected(False)
    def toggle_camera_settings(self,opened):
        self.drawer_animation.stop();start=self.camera_drawer.width() if self.camera_drawer.isVisible() else 0
        if opened:self.camera_drawer.show()
        self.drawer_animation.setStartValue(start);self.drawer_animation.setEndValue(280 if opened else 0);self.drawer_animation.start()
    def edited(self,*args):
        if not self.syncing:self.dirty=True;self.generation+=1;self.config_status.setText('수정 중 · 저장 전')
    def set_connected(self,connected):
        was_connected=self.remote_enabled
        self.remote_enabled=bool(connected)
        for b in (self.enable_button,self.disable_button,self.stop_button,self.download_button,self.start_button):b.setEnabled(connected)
        self.save_button.setEnabled(connected)
        if not connected:
            self.waiting_start=False;self.synced=False;self.pending=None;self.image.clear();self.image.setText('ROS 연결 대기');self.summary.setText('카메라 연결 대기');self.last_image=0
            self.etag='';self.samples.clear()
            self.bandwidth.clear()
        if self.remote_enabled!=was_connected:
            self._reset_preview_connection()
    def begin_tracking(self):
        if not self.remote_enabled or self.waiting_start or self.tracking_session is not None:return
        self.waiting_start=True;self.start_button.setEnabled(False);self.summary.setText('카메라 준비 대기')
        if not self.camera_enabled:self.request.emit('VISION_ENABLE',{'enabled':True})
    def stop(self):
        self.waiting_start=False;self.stop_tracking.emit()
    def disable_camera(self):
        self.stop();self.request.emit('VISION_ENABLE',{'enabled':False})
    def download_log(self):
        folder=QFileDialog.getExistingDirectory(self,'풍선 추적 로그 저장')
        if folder:self.request.emit('DOWNLOAD_VISION_LOG',{'destination':folder})
    def save_config(self):
        width,height=map(int,self.resolution.currentData().split('x'))
        self.request.emit('VISION_CONFIGURE',dict(camera_type=self.camera.currentData(),camera_source=self.source.text().strip(),csi_sensor_id=self.sensor.value(),
            width=width,height=height,long_range_enabled=self.long_range.isChecked()))
    def request_sent(self,command,request,args):
        if command=='VISION_CONFIGURE' and request:
            self.pending=(request,self.generation);self.save_button.setEnabled(False);self.config_status.setText('저장 확인 중')
            QTimer.singleShot(6000,lambda:self.timeout(request))
    def timeout(self,request):
        if self.pending and self.pending[0]==request:self.pending=None;self.save_button.setEnabled(True);self.dirty=True;self.config_status.setText('응답 없음 · 다시 저장')
    def on_ack(self,ack):
        if ack.get('command')=='VISION_ENABLE' and not ack.get('ok'):
            self.waiting_start=False;self.summary.setText('카메라 연결 실패')
        if not self.pending or ack.get('request_id')!=self.pending[0]:return
        _,generation=self.pending;self.pending=None;self.save_button.setEnabled(True)
        if ack.get('ok'):
            if generation==self.generation:self.dirty=False;self.sync_config(ack.get('configuration') or {},ack.get('applied_monotonic',0),force=True)
            self.config_status.setText('저장됨' if not self.dirty else '새 수정값 저장 필요')
        else:self.dirty=True;self.config_status.setText('저장 실패: '+str(ack.get('error','unknown')))
    def sync_config(self,c,stamp,force=False):
        if not c or self.pending or self.dirty and not force or stamp<self.stamp:return
        self.syncing=True
        try:
            self.camera.setCurrentIndex(max(0,self.camera.findData(c.get('camera_type'))));self.source.setText(str(c.get('camera_source',DEFAULTS['camera_source'])))
            self.sensor.setValue(c.get('csi_sensor_id',0));self.synced=True;self.stamp=stamp
            resolution=str(c.get('width',DEFAULTS['width']))+'x'+str(c.get('height',DEFAULTS['height']))
            if self.resolution.findData(resolution)<0:self.resolution.addItem(resolution,resolution)
            self.resolution.setCurrentIndex(self.resolution.findData(resolution));self.long_range.setChecked(c.get('long_range_enabled',True))
        finally:self.syncing=False
    def update_state(self,state,host):
        previous_endpoint=(self.host,self.port)
        was_connected=self.remote_enabled
        v=state.get('vision') or {};self.host=host;self.port=int(v.get('preview_port') or 8766)
        camera_was_enabled=self.camera_enabled
        self.mock=bool(state.get('mock'));self.remote_enabled=bool((state.get('backend') or {}).get('gateway_online'));self.camera_enabled=bool(v.get('enabled'))
        mode_since=state.get('mode_since_monotonic')
        if not self.remote_enabled or state.get('estop') or (self.mode_since is not None and mode_since!=self.mode_since):
            self.waiting_start=False
        self.mode_since=mode_since
        active=state.get('mode')=='BALLOON' and state.get('balloon_armed') and not state.get('estop')
        session=mode_since if active else None
        if (session!=self.tracking_session or camera_was_enabled!=self.camera_enabled or
                previous_endpoint!=(self.host,self.port) or was_connected!=self.remote_enabled):
            self.tracking_session=session
            self._reset_preview_connection()
            self.last_image=0
            self.samples.clear();self.bandwidth.clear()
            self.image.clear()
            self.image.setText('새 영상 수신 대기')
        t=(v.get('target') or {}) if session is not None and v.get('tracking_session')==session else {}
        visible=bool(t.get('acquired')) and not t.get('predicted')
        if self.waiting_start and all(v.get(key) for key in ('enabled','camera_online','model_ready','live_source')):
            self.waiting_start=False;self.start_tracking.emit()
        phase_labels = {
            'TRACKING':'풍선 추적 중', 'ACQUIRING':'풍선 감지 확인 중',
            'TURN_BACK':'되돌아가기', 'POSITION_REACQUIRE':'추정 위치 접근',
            'PREDICTING':'위치 예측', 'SEARCHING':'예측 추적',
            'POP_PENDING':'근접 풍선 소실 확인 중 · 정지', 'POP_ESTIMATED':'파열 추정',
        }
        text=phase_labels.get(t.get('phase'),'풍선 감지 대기') if self.camera_enabled else '카메라 꺼짐'
        if self.waiting_start:text='카메라 준비 대기'
        if active and state.get('failsafe_reason')=='BALLOON_CAMERA_DELAY':
            text='카메라 응답 대기 · 출력 정지'
        elif active and v.get('error'):
            text='카메라 응답 지연 · 추적 유지'
        elif v.get('error'):
            text='카메라 / 모델 확인 필요'
        self.summary.setToolTip(str(v.get('error') or ''))
        if state.get('estop'):text='■ 비상정지 · 풍선 추적 출력 잠금'
        self.summary.setText(text);self.summary.setStyleSheet('color:' + ('#ff788a' if state.get('estop') else '#61dfad' if visible else '#edbd66' if self.camera_enabled else '#9bacc0'))
        self.enable_button.setVisible(not self.camera_enabled);self.disable_button.setVisible(self.camera_enabled)
        self.enable_button.setEnabled(self.remote_enabled);self.disable_button.setEnabled(self.remote_enabled)
        self.start_button.setEnabled(self.remote_enabled and not active and not self.waiting_start and not state.get('estop'))
        self.stop_button.setEnabled(self.remote_enabled);self.download_button.setEnabled(self.remote_enabled and not self.mock)
        self.save_button.setEnabled(self.remote_enabled and not self.camera_enabled and not self.pending)
        for editor in self.editors:editor.setEnabled(not self.camera_enabled)
        self.sync_config(v.get('configuration') or {},v.get('applied_monotonic') or 0)
        def fmt(value,suffix=''):return '—' if value is None else f'{float(value):.1f}{suffix}'
        self.metrics.setText(('풍선 감지' if visible else '추적 유지' if active and t.get('predicted') else '감지 대기')+
            ' · '+fmt(v.get('processed_fps'),' fps')+' · '+fmt(v.get('inference_ms'),' ms'))
        view=v.get('detector_view') or {}
        if view.get('native_width'):
            text=f" · {view['native_width']}×{view['native_height']}"
            if view.get('requested_resolution_met') is False:text+=' 해상도 확인 필요'
            elif t.get('source_span_px') is not None:text+=' · '+fmt(t['source_span_px'],' px')
            self.metrics.setText(self.metrics.text()+text)
        self.shared_speed.setText('목표 PWM '+str(state.get('auto_cruise_pwm') or v.get('shared_cruise_pwm') or '—')+' · 최종 출력 '+str((state.get('pca') or {}).get('throttle_pwm','—')))
        if self.mock:self.image.setPixmap(QPixmap());self.image.setText('SIMULATION · 모의 감지 상태\n실제 카메라 영상 아님')
        elif not self.camera_enabled:self.image.setPixmap(QPixmap());self.image.setText('카메라 꺼짐')

    def _preview_network(self):
        network=QNetworkAccessManager(self)
        network.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        return network

    def _reset_preview_connection(self):
        reply,self.reply=self.reply,None
        if reply is not None:
            reply.abort()
        previous,self.network=self.network,self._preview_network()
        previous.deleteLater()
        self.etag=''
        self.preview_retry_at=0.

    def _preview_transport_failed(self,error):
        if self.preview_failure is None:
            logger.warning('Preview connection interrupted: %s',error)
        self.preview_failure=error
        self._reset_preview_connection()
        self.preview_retry_at=time.monotonic()+.25
        if not self.last_image:
            self.image.setText('영상 연결 지연 · 재연결 중')

    def fetch_frame(self):
        if (not self.isVisible() or not self.show_preview.isChecked() or
                not self.remote_enabled or not self.camera_enabled or not self.host or self.mock):
            if self.reply is not None:self._reset_preview_connection()
            return
        now=time.monotonic()
        if self.last_image and now-self.last_image>2:
            self.last_image=0;self.etag='';self.samples.clear();self.bandwidth.clear()
            self.image.clear();self.image.setText('새 영상 수신 대기 · 이전 영상 만료')
        if self.reply is not None:
            if now-self.preview_request_at>1.8:self._preview_transport_failed('request timeout')
            return
        if now<self.preview_retry_at:return
        host='['+self.host+']' if ':' in self.host else self.host;req=QNetworkRequest(QUrl(f'http://{host}:{self.port}/frame.jpg'));req.setTransferTimeout(1500)
        token=os.getenv('RCBOAT_GATEWAY_TOKEN','')
        if token:req.setRawHeader(b'X-RCBoat-Token',token.encode())
        if self.etag:req.setRawHeader(b'If-None-Match',self.etag.encode())
        reply=self.network.get(req)
        self.reply=reply
        self.preview_request_at=now
        reply.finished.connect(lambda:self.frame_finished(reply))
        reply.downloadProgress.connect(lambda received,total:reply.abort() if self.reply is reply and received>200000 else None)

    def frame_finished(self,reply):
        try:
            if reply is not self.reply:
                return
            self.reply=None
            if not self.remote_enabled or not self.camera_enabled or not self.show_preview.isChecked():
                return
            status=reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status==304:
                return
            if reply.error()!=QNetworkReply.NoError:
                if status is None:
                    self._preview_transport_failed(reply.error().name)
                    return
                self.preview_retry_at=time.monotonic()+(.15 if status==503 else .5)
                if not self.last_image or time.monotonic()-self.last_image>2:
                    self.image.clear()
                    self.image.setText({
                        401:'영상 인증 필요', 503:'Jetson 영상 준비 중 · 다시 수신 중',
                    }.get(status, '영상 연결 지연 · 다시 수신 중'))
                return
            raw=bytes(reply.readAll());pix=QPixmap()
            if len(raw)>150000 or not pix.loadFromData(raw,'JPG'):
                if not self.last_image:self.image.setText('영상 형식 오류 · 다시 수신 중')
                return
            # Header pairs work with both Qt 6.6 and the Qt 6.12 str-only reader.
            self.etag=next((bytes(value).decode('ascii',errors='ignore')
                            for key,value in reply.rawHeaderPairs() if bytes(key).lower()==b'etag'),'')
            self.image.setPixmap(pix.scaled(self.image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.last_image=time.monotonic();self.samples.append((self.last_image,len(raw)))
            if self.preview_failure is not None:
                logger.info('Preview connection recovered')
                self.preview_failure=None
            if len(self.samples)>1:
                elapsed=max(.1,self.samples[-1][0]-self.samples[0][0])
                self.bandwidth.setText(f'미리보기 {(len(self.samples)-1)/elapsed:.1f} fps · {sum(n for _,n in list(self.samples)[1:])/elapsed/1024:.1f} KiB/s')
        finally:
            reply.deleteLater()
    def shutdown(self):
        self.timer.stop();self.remote_enabled=False
        reply,self.reply=self.reply,None
        if reply is not None:reply.abort()
