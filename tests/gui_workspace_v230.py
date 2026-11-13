"""Qt layout, route-record placement, wheel routing and edit ACK regression; no boat I/O."""
from pathlib import Path
import sys,json,time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'windows_gui'),str(ROOT/'catkin_ws/src/rcboat_ros/src')]
from PySide6.QtCore import Qt,QPoint,QPointF,QRectF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QPushButton,QScrollArea
from rcboat_gui.main_window import MainWindow
from rcboat_gui.ui_shell import update_dashboard_quality
from rcboat_ros.balloon_tracking import DEFAULTS
from rcboat_gui.ssh_worker import SSHWorker
app=QApplication([])
with patch.object(MainWindow,'_load_settings',lambda self:None):w=MainWindow()
w.show();w.tabs.setCurrentIndex(2);app.processEvents()
required=['connect_button','mode_button','estop_button','clear_estop_button','auto_speed_apply','auto_speed_reset',
    'gps_log_start','gps_log_stop','ntrip_apply','ntrip_mount_fix','gps_settings_save','route_select_button',
    'route_start_button','route_export_button','route_delete_button','route_add_button','route_edit_button',
    'route_record_start','route_record_save','route_record_cancel','multipath_select_button','multipath_start_button',
    'multipath_add_button','multipath_edit_button','multipath_delete_button','multipath_apply','ground_start_button',
    'ground_stop_button','ground_resume_button','ground_download_button','sim_heartbeat_loss','sim_multipath',
    'terminal_send','terminal_interrupt']
assert all(isinstance(getattr(w,key),QPushButton) for key in required)
assert w.tabs.count()==8 and w.tabs.tabText(2)=='항로 · Multi-Path'
assert w.route_detail_tabs.tabText(1)=='항로 기록'
for width,height in [(1440,900),(1280,800),(1024,768)]:
    w.resize(width,height);w.route_execution_tabs.setCurrentIndex(0);app.processEvents()
    for b in (w.multipath_select_button,w.multipath_start_button):
        pos=b.mapTo(w,b.rect().topLeft())
        assert b.isVisible() and pos.y()+b.height()<height-30,(width,height,b.text(),pos,w.size())
        assert pos.x()+b.width()<=w.width(),(width,b.text(),pos,w.size())
    assert w.route_plot.height()>=520
    assert w.route_map_scroll.horizontalScrollBar().maximum()==0
    if height<=800:
        assert w.route_map_scroll.verticalScrollBar().maximum()>0
        w.route_map_scroll.verticalScrollBar().setValue(w.route_map_scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert w.multipath_start_button.isVisible()
    for index in range(w.route_detail_tabs.count()):
        w.route_detail_tabs.setCurrentIndex(index);app.processEvents()
        area=w.route_detail_tabs.currentWidget();area.verticalScrollBar().setValue(area.verticalScrollBar().maximum());app.processEvents()
        assert w.multipath_start_button.isVisible()
w.resize(1440,900);w.route_detail_tabs.setCurrentIndex(0);app.processEvents()
edit_area=w.route_detail_tabs.currentWidget()
assert edit_area.horizontalScrollBar().maximum()==0,edit_area.horizontalScrollBar().maximum()
w.route_detail_tabs.setCurrentIndex(1);app.processEvents()
assert w.route_record_start.isVisible() and w.route_record_save.isVisible()
plot=w.route_plot;scale=plot._pixels_per_meter
def wheel(mod=Qt.NoModifier,angle=120,pixel=0):
    ev=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(0,pixel),QPoint(0,angle),Qt.NoButton,mod,Qt.NoScrollPhase,False)
    QApplication.sendEvent(plot,ev);return ev
anchor=plot._screen_point(QPointF(7,11),plot.rect().adjusted(36,34,-26,-38))
area=QRectF(plot.rect()).adjusted(36,34,-26,-38)
cursor_world=QPointF(plot._center_m.x()+(100-area.center().x())/scale,
                    plot._center_m.y()-(100-area.center().y())/scale)
assert wheel().isAccepted() and abs(plot._pixels_per_meter-scale*1.25)<1e-8
assert (plot._screen_point(cursor_world,area)-QPointF(100,100)).manhattanLength()<1e-6
assert wheel(angle=-120).isAccepted() and abs(plot._pixels_per_meter-scale)<1e-8
after=plot._screen_point(QPointF(7,11),plot.rect().adjusted(36,34,-26,-38))
assert (anchor-after).manhattanLength()<1e-6  # Cursor-anchored zoom returns to the same position.
wheel(Qt.ControlModifier);assert plot._pixels_per_meter>scale
scale=plot._pixels_per_meter;assert wheel(angle=0,pixel=15).isAccepted() and plot._pixels_per_meter>scale
scale=plot._pixels_per_meter;assert not wheel(angle=0).isAccepted() and plot._pixels_per_meter==scale
scale=plot._pixels_per_meter
assert not wheel(Qt.ShiftModifier).isAccepted() and plot._pixels_per_meter==scale
# Routes panned beyond the map must not paint across the coordinate footer.
from PySide6.QtGui import QImage,QPainter,QColor
from rcboat_gui.widgets import RoutePlot
isolated=RoutePlot();isolated.resize(660,520)
isolated.update_data([dict(id='sample',name='경로 이름',waypoints=[dict(lat=35,lon=129),dict(lat=35.001,lon=129)])],{},'sample')
isolated._auto_fit_pending=False;isolated._pixels_per_meter=2
map_area=QRectF(isolated.rect()).adjusted(36,34,-26,-38)
isolated._center_m=QPointF(0,(20-map_area.center().y())/2)
image=QImage(isolated.size(),QImage.Format_ARGB32);image.fill(QColor('#000000'))
isolated.render(image)
assert image.pixelColor(int(map_area.center().x()),20).name()=='#0b1423'
isolated.close()
update_dashboard_quality(w,dict(gps=dict(hdop=1.1,satellites=9,last_fix_age_s=.2),gps_settings={'navigation_max_hdop':None}))
assert '#38d996' in w.value_labels['hdop'].value_label.styleSheet()
update_dashboard_quality(w,dict(gps=dict(hdop=4,satellites=6,last_fix_age_s=3),gps_settings={'navigation_max_hdop':5}))
assert '#f8bd58' in w.value_labels['hdop'].value_label.styleSheet()
assert '#ff6474' in w.value_labels['last_fix_age'].value_label.styleSheet()
update_dashboard_quality(w,dict(gps={}))
assert '#7f93ac' in w.value_labels['hdop'].value_label.styleSheet()
assert all(card.hint_label.text() for key,card in w.value_labels.items() if key!='failsafe')
# Jetson's persisted profile supplies the public fields; disconnects do not clear it.
state=SSHWorker._normalize(dict(success=True,version='2.3.1',gateway_online=True,master_online=True,telemetry={
    'ntrip':dict(host='caster.example.invalid',port=2101,mountpoint='SAVED',username='fixture-user',credentials_saved=True,enabled=True),
    'gps':dict(fix=True,healthy=True,latitude=35,longitude=129,utc_time='2026-11-03T12:34:56.000Z',utm_zone='52N',utm_easting_m=508000.123,utm_northing_m=3882000.456)}))
w.update_telemetry(state)
assert w.ntrip_host.text()=='caster.example.invalid' and w.ntrip_username.text()=='fixture-user'
assert not w.ntrip_password.text() and '저장됨' in w.ntrip_password.placeholderText()
w.update_telemetry(SSHWorker._normalize(dict(success=True,telemetry={})))
assert w.ntrip_host.text()=='caster.example.invalid' and w.ntrip_mountpoint.text()=='SAVED'
w.ntrip_host.setText('edited.example.invalid');w._mark_ntrip_dirty();w.update_telemetry(state)
assert w.ntrip_host.text()=='edited.example.invalid'
sent=[];w.command=lambda command,**args:sent.append((command,args)) or 'fixture-request'
w.reload_ntrip_profile();w.update_telemetry(state)
assert sent[-1][0]=='REFRESH_NTRIP' and w.ntrip_host.text()=='caster.example.invalid'
w.apply_ntrip();assert sent[-1][0]=='CONFIGURE_NTRIP' and 'password' not in sent[-1][1]
assert w.gps_workspace_tabs.count()==2
w.gps_details_toggle.setChecked(True);w.ntrip_settings_toggle.setChecked(True)
for width,height in [(1440,900),(1280,800),(1024,768)]:
    w.resize(width,height);app.processEvents()
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i);app.processEvents();page=w.tabs.currentWidget()
        from PySide6.QtWidgets import QTabWidget
        nested=[(g,j) for g in page.findChildren(QTabWidget) for j in range(g.count())]
        for group,index in [(None,0)]+nested:
            if group:group.setCurrentIndex(index);app.processEvents()
            for area in page.findChildren(QScrollArea)+([page] if isinstance(page,QScrollArea) else []):
                if area.isVisible():assert area.horizontalScrollBar().maximum()==0,(width,w.tabs.tabText(i),group.tabText(index) if group else '',area.horizontalScrollBar().maximum())
# A polling response or old ACK cannot discard a new camera configuration edit.
p=w.balloon_panel;p.set_connected(True);p.sync_config(DEFAULTS,1)
p.source.setText('/dev/video1');p.edited();p.sync_config(dict(DEFAULTS,camera_source='/dev/video2'),2)
assert p.source.text()=='/dev/video1' and p.dirty
p.request_sent('VISION_CONFIGURE','one',{});p.on_ack(dict(request_id='old',ok=True));assert p.pending
p.source.setText('/dev/video3');p.edited();p.on_ack(dict(request_id='one',ok=True,configuration=dict(DEFAULTS,camera_source='/dev/video1'),applied_monotonic=3))
assert p.source.text()=='/dev/video3' and p.dirty
p.request_sent('VISION_CONFIGURE','two',{});p.timeout('two');assert p.pending is None and p.dirty
# Native resolution and range selection share the existing dirty/ACK lifecycle.
p.dirty=False;p.sync_config(DEFAULTS,4,force=True)
assert p.resolution.currentData()=='1920x1080' and p.long_range.isChecked()
p.resolution.setCurrentIndex(p.resolution.findData('1280x720'));p.long_range.setChecked(False)
configs=[];p.request.connect(lambda command,args:configs.append((command,args)))
p.save_config();assert configs[-1][1]['width']==1280 and configs[-1][1]['height']==720
assert configs[-1][1]['long_range_enabled'] is False
p.sync_config(DEFAULTS,5);assert p.resolution.currentData()=='1280x720'
p.request_sent('VISION_CONFIGURE','range',configs[-1][1])
p.on_ack(dict(request_id='range',ok=True,configuration=dict(DEFAULTS,width=1280,height=720,long_range_enabled=False),applied_monotonic=6))
assert not p.dirty and p.resolution.currentData()=='1280x720' and not p.long_range.isChecked()
# Explicit start waits for the live camera. A stale target is hidden in MANUAL.
p.set_connected(True);p.camera_enabled=False;requests=[];starts=[]
p.request.connect(lambda command,args:requests.append(command));p.start_tracking.connect(lambda:starts.append(True))
p.begin_tracking();assert requests==['VISION_ENABLE'] and not starts
ready=dict(backend={'gateway_online':True},mode='MANUAL',mode_since_monotonic=100,
           vision={'enabled':True,'live_source':True,'camera_online':True,'model_ready':True,
                   'tracking_session':90,'target':{'phase':'TURN_BACK','acquired':True,'predicted':True}})
p.update_state(ready,'127.0.0.1');p.update_state(ready,'127.0.0.1');assert len(starts)==1
assert '풍선 감지 대기' in p.summary.text()
active=dict(ready,mode='BALLOON',mode_since_monotonic=101,balloon_armed=True)
p.update_state(active,'127.0.0.1');assert '풍선 감지 대기' in p.summary.text()
active['vision']=dict(ready['vision'],tracking_session=101)
p.update_state(active,'127.0.0.1');assert '되돌아가기' in p.summary.text()
p.update_state(dict(active,failsafe_reason='BALLOON_CAMERA_DELAY'),'127.0.0.1')
assert '카메라 응답 대기' in p.summary.text()
p.update_state(dict(ready,mode_since_monotonic=102),'127.0.0.1')
assert '풍선 감지 대기' in p.summary.text()
p.update_state(dict(ready,vision={'enabled':False}),'127.0.0.1')
assert '카메라 꺼짐' in p.summary.text()
p.begin_tracking();p.stop();p.update_state(ready,'127.0.0.1');assert len(starts)==1
p.set_connected(False);assert not p.start_button.isEnabled()
# Camera settings consume their own right-hand width; the image is never overlaid.
w.tabs.setCurrentIndex(4);p.settings_toggle.setChecked(True)
from PySide6.QtTest import QTest
QTest.qWait(220);app.processEvents()
assert p.camera_drawer.isVisible() and p.camera_drawer.width()==280
assert p.preview_scroll.geometry().right()<p.camera_drawer.geometry().left()
assert p.camera_drawer.horizontalScrollBar().maximum()==0
p.settings_toggle.setChecked(False);QTest.qWait(220);app.processEvents()
assert not p.camera_drawer.isVisible()
# Exercise real QNetworkReply header parsing and recovery after a warm-up 503.
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QPixmap
from rcboat_gui.balloon_panel import BalloonPanel, is_vpn_endpoint, vpn_preview_interval, stream_frame_rate

assert stream_frame_rate([180,200,900])==14
assert stream_frame_rate([480,460,200])==8
assert stream_frame_rate([900,870,120])==5
assert is_vpn_endpoint('100.74.153.81') and is_vpn_endpoint('rcboat-jetson.example.ts.net')
assert not is_vpn_endpoint('10.16.147.215') and not is_vpn_endpoint('')
assert vpn_preview_interval(.04, 1024, 30) == 1/12
assert vpn_preview_interval(.04, 32*1024, 30) == .2
assert vpn_preview_interval(.05, 1024, 250) == .4
assert vpn_preview_interval(.25, 1024, 30) == .5

picture=QPixmap(32,18);picture.fill(Qt.magenta)
buffer=QBuffer();buffer.open(QIODevice.WriteOnly);assert picture.save(buffer,'JPEG')
jpeg=bytes(buffer.data())
# Drag the video to reveal the lower frame without changing scale or the controls.
from PySide6.QtCore import QPoint
panel=BalloonPanel()
panel.timer.stop()
panel.resize(960,600)
panel.show()
assert panel.display_frame(jpeg)
QTest.qWait(80)
bar=panel.preview_scroll.verticalScrollBar()
assert bar.maximum()==0, 'A normal-height window must show the entire video'
rect=panel.image.frame_rect(panel.image.pixmap())
assert rect.width()<panel.image.width(), 'Video should fit the height instead of forcing full width'
assert abs(rect.center().x()-panel.image.width()/2)<1
assert rect.height()<=panel.image.height()
panel.resize(960,325)
QTest.qWait(80)
assert bar.maximum()>50
assert panel.preview_scroll.horizontalScrollBar().maximum()==0
original_size=panel.image.pixmap().size()
original_controls=panel.start_button.geometry()
QTest.mousePress(panel.image,Qt.LeftButton,pos=QPoint(250,170))
QTest.mouseMove(panel.image,QPoint(250,65))
QTest.mouseRelease(panel.image,Qt.LeftButton,pos=QPoint(250,65))
assert bar.value()>0
assert panel.image.pixmap().size()==original_size
assert panel.image.frame_rect(panel.image.pixmap()).height()<=panel.image.height()
assert panel.start_button.geometry()==original_controls
assert panel.display_frame(jpeg)
assert bar.value()>0, 'new camera frame reset the scroll position'
panel.shutdown()
panel.close()

requests=[]
release_stalled_request=Event()
class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        previous=self.headers.get('If-None-Match')
        requests.append(previous)
        if len(requests)==4:
            release_stalled_request.wait(4)
            return
        status=503 if len(requests)==1 else 304 if previous=='"frame-1"' else 200
        body=jpeg if status==200 else b''
        self.send_response(status)
        self.send_header('ETag','"frame-1"')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Frame-Age','1.3' if len(requests)==5 else '.05')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):pass

with ThreadingHTTPServer(('127.0.0.1',0),PreviewHandler) as server:
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    preview=BalloonPanel();preview.timer.stop();preview.show()
    preview.update_state(dict(ready,vision=dict(ready['vision'],preview_port=server.server_port)),'127.0.0.1')
    preview.set_status_unavailable()
    assert preview.video_requested and not preview.start_button.isEnabled()
    assert '상태 응답 대기' in preview.summary.text()
    def fetch_preview():
        for _ in range(60):
            if time.monotonic()>=preview.preview_retry_at:break
            QTest.qWait(10)
        preview.fetch_frame()
        for _ in range(260):
            if preview.reply is None:return
            preview.fetch_frame()
            QTest.qWait(10)
        raise AssertionError('Preview request did not complete')
    try:
        fetch_preview()
        assert '영상 준비 중' in preview.image.text()
        fetch_preview()
        assert not preview.image.pixmap().isNull() and preview.etag=='"frame-1"'
        fetch_preview()
        assert requests==[None,None,'"frame-1"'] and len(preview.samples)==1
        assert not preview.image.pixmap().isNull()
        first_connection=preview.network
        last_displayed=preview.last_image
        fetch_preview()
        assert preview.network is not first_connection
        fetch_preview()
        assert requests[3:]==['"frame-1"',None]
        assert preview.etag=='' and preview.last_image in (0,last_displayed), 'Old frame displayed'
        fetch_preview()
        assert not preview.image.pixmap().isNull() and preview.preview_failure is None
        preview.stream_supported=True
        preview._preview_transport_failed('simulated stream timeout',stream=True)
        preview._preview_transport_failed('simulated stream timeout',stream=True)
        assert preview.snapshot_until>time.monotonic()
        fetch_preview()
        assert not preview.image.pixmap().isNull()
        assert preview.video_requested

    finally:
        release_stalled_request.set()
        preview.shutdown();preview.close()
        server.shutdown();thread.join(timeout=2)

w.rc_graph.append(None,None);assert w.rc_graph.series[0][-1] is None
locked=SSHWorker._normalize(dict(success=True,version='2.4.18',gateway_online=True,master_online=True,telemetry={
    'safety':dict(mode='MANUAL',estop=True,actuator_locked=True,estop_reason='MAINTENANCE_CHECK',estop_time_utc='2026-11-10T10:00:00Z'),
    'vision':dict(enabled=True,model_ready=True,camera_online=True,target={'acquired':True,'predicted':False})}))
w.update_telemetry(locked);app.processEvents()
assert w.estop_banner.isVisible() and '점검 중' in w.estop_banner_text.text() and '19:00:00 KST' in w.estop_banner_text.text()
assert '비상정지' in w.balloon_panel.summary.text() and not w.balloon_panel.start_button.isEnabled()
w.update_telemetry({'backend':{'status_unavailable':True,'ssh_connected':True,'ssh_state':'delayed'}})
assert w.cards['ros_master'].value_label.text()=='상태 확인 불가'
assert '재시도' in w.cards['backend'].value_label.text()
assert w._last_estop and '마지막 확인' in w.estop_banner_text.text()
w.update_telemetry(locked)
assert w.cards['ros_master'].value_label.text()=='online'
master_down=SSHWorker._normalize(dict(success=True,version='2.4.18',gateway_online=True,master_online=False))
w.update_telemetry(master_down)
assert w.cards['ros_master'].value_label.text()=='offline'
w.update_telemetry(locked)

for index in range(w.tabs.count()):
    w.tabs.setCurrentIndex(index);app.processEvents();assert w.estop_banner.isVisible()
w._set_connected(False);assert w.estop_banner.isVisible() and '현재 출력 확인 불가' in w.estop_banner_text.text()
assert not w.estop_banner_clear.isEnabled()
locked['estop']=False;w.update_telemetry(locked);app.processEvents();assert not w.estop_banner.isVisible()
w.close();app.processEvents()
print('PASS: 34 existing button attributes; pinned group execution at 1440/1280/1024; route recording remains with map; no horizontal edit clipping; wheel routing; threshold hints/colours/no-data; camera edit ACK lifecycle')
