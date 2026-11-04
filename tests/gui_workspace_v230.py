"""Qt layout, route-record placement, wheel routing and edit ACK regression; no boat I/O."""
from pathlib import Path
import sys,json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'windows_gui'),str(ROOT/'catkin_ws/src/rcboat_ros/src')]
from PySide6.QtCore import Qt,QPoint,QPointF
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
def wheel(mod):
    ev=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(0,0),QPoint(0,120),Qt.NoButton,mod,Qt.NoScrollPhase,False)
    QApplication.sendEvent(plot,ev);return ev
assert not wheel(Qt.NoModifier).isAccepted() and plot._pixels_per_meter==scale
wheel(Qt.ControlModifier);assert plot._pixels_per_meter>scale
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
# Explicit start turns on the camera, waits for fresh actual detection, and arms once.
p.set_connected(True);p.camera_enabled=False;requests=[];starts=[]
p.request.connect(lambda command,args:requests.append(command));p.start_tracking.connect(lambda:starts.append(True))
p.begin_tracking();assert requests==['VISION_ENABLE'] and not starts
ready=dict(backend={'gateway_online':True},mode='AUTO',vision={'enabled':True,'live_source':True,'target':{'acquired':True,'predicted':False}},vision_desired={'valid':True})
p.update_state(ready,'127.0.0.1');p.update_state(ready,'127.0.0.1');assert len(starts)==1
p.begin_tracking();p.stop();p.update_state(ready,'127.0.0.1');assert len(starts)==1
p.set_connected(False);assert not p.start_button.isEnabled()
# Camera settings consume their own right-hand width; the image is never overlaid.
w.tabs.setCurrentIndex(4);p.settings_toggle.setChecked(True)
from PySide6.QtTest import QTest
QTest.qWait(220);app.processEvents()
assert p.camera_drawer.isVisible() and p.camera_drawer.width()==280
assert p.image.geometry().right()<p.camera_drawer.geometry().left()
assert p.camera_drawer.horizontalScrollBar().maximum()==0
p.settings_toggle.setChecked(False);QTest.qWait(220);app.processEvents()
assert not p.camera_drawer.isVisible()
w.rc_graph.append(None,None);assert w.rc_graph.series[0][-1] is None
w.close();app.processEvents()
print('PASS: 34 existing button attributes; pinned group execution at 1440/1280/1024; route recording remains with map; no horizontal edit clipping; wheel routing; threshold hints/colours/no-data; camera edit ACK lifecycle')
