"""RCBoat ROS2.0-beta.1 Windows application. Only SSH accesses Jetson."""
import csv
import json
import math
import pathlib
import sys
import time
from PySide6.QtCore import QObject,QThread,Qt,Signal,Slot,QTimer,QPointF
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QPlainTextEdit,QTabWidget,QGridLayout,QGroupBox,
    QMessageBox,QFileDialog,QSlider,QGraphicsScene,QGraphicsView,QGraphicsEllipseItem,QGraphicsPathItem)
import paramiko

CLIENT='python3 /home/jetson/rcboat_ros_ws/deployment/jetson/bridge_client.py'

class TrackMap(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene=QGraphicsScene(self);self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMinimumHeight(320)
    def wheelEvent(self,event):
        self.scale(1.2 if event.angleDelta().y()>0 else 1/1.2,1.2 if event.angleDelta().y()>0 else 1/1.2)
    def draw_routes(self,routes,lat=None,lon=None):
        self.scene.clear()
        colors={'left':QColor('#3478ff'),'center':QColor('#888888'),'right':QColor('#e33b3b')}
        allpoints=[p for r in routes for p in r.get('waypoints',[])]
        if lat is not None and lon is not None:allpoints.append({'lat':lat,'lon':lon})
        if not allpoints:return
        minlat=sum(float(p['lat']) for p in allpoints)/len(allpoints)
        minlon=sum(float(p['lon']) for p in allpoints)/len(allpoints)
        def xy(p):return ((float(p['lon'])-minlon)*111000*math.cos(math.radians(minlat))*4,
                           -(float(p['lat'])-minlat)*111000*4)
        for route in routes:
            pts=route.get('waypoints',[])
            col=next((v for k,v in colors.items() if k in (route.get('id','')+route.get('name','')).lower()),QColor('#aa55cc'))
            for a,b in zip(pts,pts[1:]):
                x1,y1=xy(a);x2,y2=xy(b)
                self.scene.addLine(x1,y1,x2,y2,QPen(col,2))
            for p in pts:
                x,y=xy(p);self.scene.addEllipse(x-2,y-2,4,4,QPen(col),col)
        if lat is not None and lon is not None:
            x,y=xy({'lat':lat,'lon':lon})
            self.scene.addEllipse(x-6,y-6,12,12,QPen(QColor('#17995c'),3))
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-15,-15,15,15))
        if not getattr(self,'already_fitted',False):
            self.fitInView(self.scene.sceneRect(),Qt.KeepAspectRatio)
            self.already_fitted=True

class Worker(QThread):
    result=Signal(dict)
    connection_state=Signal(str)
    def __init__(self,host,user,password):
        super().__init__();self.host=host;self.user=user;self.password=password
        self.queue=[];self.running=True;self.client=None
    def enqueue(self,req):self.queue.append(req)
    def shell(self,req):
        stdin,stdout,stderr=self.client.exec_command(req.get('command',''),timeout=8)
        return {'success':True,'output':stdout.read(100000).decode(errors='replace'),
                'stderr':stderr.read(100000).decode(errors='replace')}
    def execute(self,req):
        if not self.client:raise RuntimeError('SSH not connected')
        stdin,stdout,stderr=self.client.exec_command(CLIENT,timeout=7)
        stdin.write(json.dumps(req)+'\n');stdin.flush();stdin.channel.shutdown_write()
        data=stdout.read(1200000).decode(errors='replace')
        try:return json.loads(data)
        except json.JSONDecodeError:raise RuntimeError(data[:250] or stderr.read(500).decode())
    def download_files(self,req):
        import stat
        base='/home/jetson/rcboat_ros_data/experiments'
        sftp=self.client.open_sftp()
        try:
            options=[x for x in sftp.listdir_attr(base) if stat.S_ISDIR(x.st_mode) and x.filename.startswith('experiment_')]
            if not options:raise RuntimeError('No experiment directory found')
            latest=max(options,key=lambda x:x.st_mtime).filename
            source=base+'/'+latest;dest=pathlib.Path(req['dest'])/latest
            wanted=req.get('kind')
            prefixes=['raw','qgis','matlab','plots'] if wanted=='all' else ['raw'] if wanted=='csv' else ['matlab','raw'] if wanted=='matlab' else ['qgis']
            total=0
            def recurse(remote,local):
                nonlocal total
                local.mkdir(parents=True,exist_ok=True)
                for item in sftp.listdir_attr(remote):
                    rp=remote+'/'+item.filename;lp=local/item.filename
                    if stat.S_ISDIR(item.st_mode):recurse(rp,lp)
                    else:sftp.get(rp,str(lp));total+=1
            for sub in prefixes:
                try:
                    st=sftp.stat(source+'/'+sub)
                    if stat.S_ISDIR(st.st_mode):recurse(source+'/'+sub,dest/sub)
                except FileNotFoundError:continue
            dest.mkdir(parents=True,exist_ok=True)
            for name in ('summary.txt','experiment_info.json','summary.json'):
                try: sftp.get(source+'/'+name,str(dest/name));total+=1
                except FileNotFoundError:pass
            return {'success':True,'downloaded_files':total,'folder':str(dest)}
        finally:sftp.close()
    def run(self):
        try:
            s=paramiko.SSHClient();s.load_system_host_keys();s.set_missing_host_key_policy(paramiko.RejectPolicy())
            s.connect(self.host,username=self.user,password=self.password or None,timeout=8,auth_timeout=8,look_for_keys=True)
            self.client=s;self.connection_state.emit('SSH 연결됨 · Backend: ROS')
            last=0
            while self.running:
                req=self.queue.pop(0) if self.queue else {'action':'status'} if time.monotonic()-last>1 else None
                if req is not None:
                    last=time.monotonic()
                    try:
                        ans=self.download_files(req) if req.get('action')=='__download' else self.shell(req) if req.get('action')=='__shell' else self.execute(req)
                        ans['_request']=req;self.result.emit(ans)
                    except Exception as e:self.result.emit({'success':False,'error':str(e),'_request':req})
                self.msleep(100)
        except Exception as e:self.connection_state.emit('SSH 연결 실패: '+str(e))
        finally:
            if self.client:self.client.close();self.client=None
    def stop(self):self.running=False;self.wait(6000)

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('RCBoatControl ROS v2.0.0-beta.2')
        self.resize(1200,820);self.worker=None;self.telemetry={}
        center=QWidget();self.setCentralWidget(center);body=QVBoxLayout(center)
        connect=QHBoxLayout();body.addLayout(connect)
        self.host=QLineEdit('10.85.226.215');self.host.setPlaceholderText('Jetson IP')
        self.user=QLineEdit('jetson');self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('SSH password (not saved)')
        for title,obj in [('호스트',self.host),('계정',self.user),('비밀번호',self.password)]:connect.addWidget(QLabel(title));connect.addWidget(obj)
        self.connect_btn=QPushButton('SSH 연결');connect.addWidget(self.connect_btn);self.connect_btn.clicked.connect(self.connect_ssh)
        self.status=QLabel('Backend: ROS · 연결 대기');body.addWidget(self.status)
        self.node_status=QLabel('ROS Master · GPS · RC · Navigation · Safety · Actuator · NTRIP · Logger: 연결 대기')
        body.addWidget(self.node_status)
        tabs=QTabWidget();body.addWidget(tabs)
        overview=QWidget();tabs.addTab(overview,'운항·GPS')
        over=QVBoxLayout(overview);modes=QHBoxLayout();over.addLayout(modes)
        for mode,label in [('AUTO_SAFE','AUTO SAFE'),('MANUAL','MANUAL'),('REMOTE','REMOTE'),('NAVIGATION','NAVIGATION')]:
            b=QPushButton(label);modes.addWidget(b);b.clicked.connect(lambda checked=False,m=mode:self.command('set_mode',mode=m,armed=False))
        estop=QPushButton('E-STOP');estop.setStyleSheet('background:#bd2d38;color:white;font-weight:bold;padding:8px')
        modes.addWidget(estop);estop.clicked.connect(lambda:self.command('estop'))
        reset=QPushButton('비상정지 해제');modes.addWidget(reset);reset.clicked.connect(lambda:self.command('reset_estop'))
        rmt=QHBoxLayout();over.addLayout(rmt)
        self.steering_pwm=QSlider(Qt.Horizontal);self.steering_pwm.setRange(4900,7300);self.steering_pwm.setValue(6000)
        self.throttle_pwm=QSlider(Qt.Horizontal);self.throttle_pwm.setRange(5800,7000);self.throttle_pwm.setValue(6450)
        rmt.addWidget(QLabel('REMOTE Steering'));rmt.addWidget(self.steering_pwm)
        rmt.addWidget(QLabel('Throttle'));rmt.addWidget(self.throttle_pwm)
        ssend=QPushButton('REMOTE PWM 적용');rmt.addWidget(ssend)
        ssend.clicked.connect(self.send_remote)
        self.remote_timer=QTimer(self)
        self.remote_timer.timeout.connect(self.remote_heartbeat)
        self.remote_timer.start(300)
        self.grid=QGridLayout();over.addLayout(self.grid)
        labels=['mode','fix','rtk_state','latitude','longitude','heading_deg','speed_mps','hdop','hacc_m',
                'cno_dbhz','active_route_id','controller_mode','lookahead_m','cte_correction_deg','target_heading_deg','heading_error_deg','cross_track_error_m',
                'desired_steering_pwm','desired_throttle_pwm','actual_steering_pwm','actual_throttle_pwm']
        self.indicators={}
        for i,key in enumerate(labels):
            k=QLabel(key);v=QLabel('—');v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(k,i//3,2*(i%3));self.grid.addWidget(v,i//3,2*(i%3)+1)
            self.indicators[key]=v
        self.map=TrackMap();over.addWidget(self.map)
        ground=QWidget();tabs.addTab(ground,'GROUND TEST')
        g=QVBoxLayout(ground)
        groundactions=QHBoxLayout();g.addLayout(groundactions)
        for label,action in [('지상 실험 시작','ground_start'),('지상 실험 종료','ground_stop')]:
            btn=QPushButton(label);groundactions.addWidget(btn);btn.clicked.connect(lambda checked=False,a=action:self.command(a))
        algo=QHBoxLayout();g.addLayout(algo)
        algo.addWidget(QLabel('Path-Tracking 알고리즘 (지상 비교 실험)'))
        self.trackingbox=QComboBox();self.trackingbox.addItems(['HEADING','HEADING_CTE','LOS','PURE_PURSUIT'])
        algo.addWidget(self.trackingbox)
        abtn=QPushButton('알고리즘 적용');algo.addWidget(abtn)
        abtn.clicked.connect(lambda:self.command('set_tracking_mode',tracking_mode=self.trackingbox.currentText()))
        algo.addWidget(QLabel('실제 추진은 별도 안전승인 전까지 차단'))
        self.groundstatus=QLabel('GROUND TEST INACTIVE · ACTUATOR LOCKED');g.addWidget(self.groundstatus)
        self.groundlogs=QPlainTextEdit();self.groundlogs.setReadOnly(True);g.addWidget(self.groundlogs)
        for label,kind in [('CSV 다운로드','csv'),('MATLAB 분석용 파일 저장','matlab'),('QGIS 파일 저장','qgis')]:
            btn=QPushButton(label);groundactions.addWidget(btn);btn.clicked.connect(lambda checked=False,k=kind:self.download(k))
        routes=QWidget();tabs.addTab(routes,'항로 관리');rl=QVBoxLayout(routes)
        rcontrols=QHBoxLayout();rl.addLayout(rcontrols)
        self.routebox=QComboBox();rcontrols.addWidget(self.routebox)
        for label,action in [('항로 선택','select_route'),('항로 삭제','delete_route'),('항로 목록 갱신','list_routes')]:
            btn=QPushButton(label);rcontrols.addWidget(btn)
            btn.clicked.connect(lambda checked=False,a=action:self.command(a,route_id=self.routebox.currentData()))
        nearest=QPushButton('현재 위치에서 가장 가까운 그룹 항로로 시작')
        nearest.clicked.connect(lambda:self.command('choose_nearest_group_route'))
        rl.addWidget(nearest)
        rrecord=QHBoxLayout();rl.addLayout(rrecord)
        self.recordname=QLineEdit('Ground recorded route');rrecord.addWidget(self.recordname)
        for label,action in [('GPS 경로 기록 시작','record_start'),('GPS 경로 기록 종료','record_stop')]:
            btn=QPushButton(label);rrecord.addWidget(btn)
            btn.clicked.connect(lambda checked=False,a=action:self.command(a,name=self.recordname.text()))
        export=QHBoxLayout();rl.addLayout(export)
        for fmt in ('json','csv','gpx'):
            b=QPushButton(fmt.upper()+' 내보내기');export.addWidget(b);b.clicked.connect(lambda checked=False,f=fmt:self.export_routes(f))
        multipath=QHBoxLayout();rl.addLayout(multipath)
        self.multipath_inputs={}
        for key,default in [('endpoint_tolerance_m','0.75'),('off_route_distance_m','8'),('off_route_hold_s','3'),
                            ('closer_advantage_m','2'),('switch_cooldown_s','5')]:
            box=QLineEdit(default);box.setMaximumWidth(72)
            multipath.addWidget(QLabel(key));multipath.addWidget(box)
            self.multipath_inputs[key]=box
        msave=QPushButton('Multi-Path 설정 저장');multipath.addWidget(msave)
        msave.clicked.connect(self.save_multipath)
        self.routesinfo=QPlainTextEdit();rl.addWidget(self.routesinfo)
        nt=QWidget();tabs.addTab(nt,'RTK / NTRIP')
        nl=QGridLayout(nt)
        self.ntrip_inputs={}
        for i,(label,key,initial) in enumerate([('Caster 주소','host',''),('포트','port','2101'),('Mountpoint','mountpoint',''),
                ('사용자','username',''),('비밀번호','password','')]):
            inp=QLineEdit(initial)
            if key=='password':inp.setEchoMode(QLineEdit.Password)
            self.ntrip_inputs[key]=inp;nl.addWidget(QLabel(label),i,0);nl.addWidget(inp,i,1)
        self.ntrip_tls=QComboBox();self.ntrip_tls.addItems(['TLS 사용','TLS 사용 안함'])
        self.ntrip_enable=QComboBox();self.ntrip_enable.addItems(['연결 사용','연결 안함'])
        nl.addWidget(self.ntrip_tls,5,1);nl.addWidget(self.ntrip_enable,6,1)
        nsave=QPushButton('Jetson에 NTRIP 설정 저장');nl.addWidget(nsave,7,1)
        nsave.clicked.connect(self.configure_ntrip)
        self.ntripview=QPlainTextEdit();self.ntripview.setReadOnly(True);nl.addWidget(self.ntripview,8,0,1,2)
        logs=QWidget();tabs.addTab(logs,'로그·SSH 터미널');ll=QVBoxLayout(logs)
        self.eventlog=QPlainTextEdit();self.eventlog.setReadOnly(True);ll.addWidget(self.eventlog)
        term=QHBoxLayout();ll.addLayout(term)
        self.shellcmd=QLineEdit();self.shellcmd.setPlaceholderText('SSH command (serial/I2C를 직접 열지 마세요)')
        term.addWidget(self.shellcmd)
        cmd_btn=QPushButton('SSH 명령 실행');term.addWidget(cmd_btn)
        cmd_btn.clicked.connect(self.send_shell)
        self.setStyleSheet('QLabel{font-size:12px}QPushButton{padding:5px 9px}')
    def connect_ssh(self):
        if self.worker:self.worker.stop()
        self.worker=Worker(self.host.text().strip(),self.user.text().strip(),self.password.text())
        self.password.clear();self.worker.connection_state.connect(self.status.setText)
        self.worker.result.connect(self.on_result);self.worker.start()
    def send_remote(self):
        self.command('set_remote_pwm',steering_pwm=self.steering_pwm.value(),throttle_pwm=self.throttle_pwm.value())
    def remote_heartbeat(self):
        if self.telemetry.get('safety',{}).get('mode')=='REMOTE' and self.worker and self.worker.isRunning():
            self.command('heartbeat')
    def send_shell(self):
        if self.shellcmd.text().strip() and self.worker and self.worker.isRunning():
            self.worker.enqueue({'action':'__shell','command':self.shellcmd.text().strip()})
    def save_multipath(self):
        try:self.command('set_multipath',**{k:float(w.text()) for k,w in self.multipath_inputs.items()})
        except ValueError:QMessageBox.warning(self,'Multi-Path','설정값은 숫자여야 합니다')
    def command(self,action,**arguments):
        if not self.worker or not self.worker.isRunning():return self.eventlog.appendPlainText('SSH 연결 필요')
        self.worker.enqueue({'action':action,'arguments':arguments})
    def on_result(self,result):
        if not result.get('success'):
            self.eventlog.appendPlainText('오류: '+str(result.get('error',result.get('response'))))
            return
        if result.get('telemetry'):
            t=result['telemetry'];self.telemetry=t
            active=result.get('nodes',[])
            expected=['rc_input_node','gps_node','ntrip_node','route_manager_node','navigation_node','safety_supervisor_node',
                      'actuator_node','ground_test_logger_node','gui_bridge_node']
            self.node_status.setText('ROS Node Health: '+' | '.join(k+(': OK' if '/'+k in active else ': MISSING') for k in expected))
            gps=t.get('gps',{});nav=t.get('navigation',{});route=t.get('route',{});act=t.get('actuator',{});saf=t.get('safety',{})
            values={**gps,**nav,**route,**act,**saf}
            for k,v in self.indicators.items():v.setText(str(values.get(k,'—')))
            locked=saf.get('actuator_locked',True)
            self.groundstatus.setText(('GROUND TEST ACTIVE' if saf.get('mode')=='GROUND_TEST' else 'GROUND TEST INACTIVE')+
                (' · ACTUATOR LOCKED' if locked else ' · ACTUATOR UNLOCKED')+
                f" · Steering actual={act.get('actual_steering_pwm','—')} Throttle actual={act.get('actual_throttle_pwm','—')}")
            self.ntripview.setPlainText(json.dumps(t.get('ntrip',{}),ensure_ascii=False,indent=2))
            gtest=t.get('ground_test',{})
            self.groundlogs.setPlainText(json.dumps(gtest,ensure_ascii=False,indent=2))
            newroutes=route.get('routes',[])
            if newroutes:
                self.routesinfo.setPlainText(json.dumps({'selected':route.get('selected_route_id'),'active':route.get('active_route_id'),
                    'candidate':route.get('candidate_route_id'),'group':route.get('group_routes'),
                    'off_route_time_s':route.get('off_route_time_s'), 'gaps':route.get('endpoint_gaps')},ensure_ascii=False,indent=2))
                prev=self.routebox.currentData()
                self.routebox.blockSignals(True);self.routebox.clear()
                for r in newroutes:self.routebox.addItem(r.get('name',r['id']),r['id'])
                n=self.routebox.findData(prev)
                if n>=0:self.routebox.setCurrentIndex(n)
                self.routebox.blockSignals(False)
                if gps.get('latitude') is not None:self.map.draw_routes(newroutes,gps.get('latitude'),gps.get('longitude'))
        else:
            if result.get('output') is not None:self.eventlog.appendPlainText(result['output']+'\n'+result.get('stderr',''))
            else:self.eventlog.appendPlainText(json.dumps(result,ensure_ascii=False))
    def configure_ntrip(self):
        args={k:v.text().strip() for k,v in self.ntrip_inputs.items()}
        try:args['port']=int(args['port'])
        except ValueError:
            QMessageBox.warning(self,'NTRIP','포트는 정수여야 합니다');return
        args['enabled']=self.ntrip_enable.currentIndex()==0
        args['tls']=self.ntrip_tls.currentIndex()==0
        self.command('configure',**args)
        self.ntrip_inputs['password'].clear()
    def download(self,kind):
        if not self.worker or not self.worker.isRunning():
            QMessageBox.warning(self,'SSH','먼저 Jetson에 연결하세요');return
        folder=QFileDialog.getExistingDirectory(self,'실험 파일 저장 위치')
        if folder:self.worker.enqueue({'action':'__download','dest':folder,'kind':kind})
    def export_routes(self,fmt):
        routes=self.telemetry.get('route',{}).get('routes',[])
        if not routes:return
        path,_=QFileDialog.getSaveFileName(self,'항로 저장','routes.'+fmt,'*.'+fmt)
        if not path:return
        if fmt=='json':pathlib.Path(path).write_text(json.dumps({'selected_route_id':self.telemetry.get('route',{}).get('selected_route_id'),'routes':routes},ensure_ascii=False,indent=2),encoding='utf-8');return
        points=[(r,p) for r in routes for p in r.get('waypoints',[])]
        if fmt=='csv':
            with open(path,'w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(['route_id','timestamp','lat','lon','heading_deg'])
                for r,p in points:w.writerow([r['id'],p.get('timestamp'),p.get('lat'),p.get('lon'),p.get('heading_deg')])
        else:
            import xml.etree.ElementTree as ET
            ns='http://www.topografix.com/GPX/1/1'
            doc=ET.Element('gpx',attrib={'version':'1.1','creator':'RCBoatROS','xmlns':ns})
            for r in routes:
                trk=ET.SubElement(doc,'trk');ET.SubElement(trk,'name').text=r.get('name',r['id']);seg=ET.SubElement(trk,'trkseg')
                for p in r.get('waypoints',[]):
                    pt=ET.SubElement(seg,'trkpt',attrib={'lat':str(p['lat']),'lon':str(p['lon'])})
                    if p.get('timestamp'):ET.SubElement(pt,'time').text=p['timestamp']
                    if p.get('heading_deg') is not None:
                        ext=ET.SubElement(pt,'extensions');ET.SubElement(ext,'heading_deg').text=str(p['heading_deg'])
            ET.ElementTree(doc).write(path,encoding='utf-8',xml_declaration=True)
    def closeEvent(self,event):
        if self.worker:self.worker.stop()
        event.accept()

def run_gui_smoke():
    """Headless widget creation check; does not connect to hardware."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    window=Window()
    assert 'ROS' in window.windowTitle()
    assert window.centralWidget() is not None
    assert window.findChild(QTabWidget) is not None
    window.close()
    print('GUI_SMOKE_OK: widgets created without SSH or hardware')
    return 0

if __name__=='__main__':
    if '--smoke-test' in sys.argv:sys.exit(run_gui_smoke())
    a=QApplication(sys.argv);w=Window();w.show();sys.exit(a.exec())
