#!/usr/bin/env python3
"""Optional camera node; no actuator ownership. Latest frame only and on-demand JPEG."""
import datetime as dt
import json,os,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,urlunsplit
import rospy
from std_msgs.msg import String
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.common import pack,unpack,fresh
from rcboat_ros.control_config import validate_cruise
from rcboat_ros.balloon_tracking import validate_config,TargetTracker,TrackingController

VERSION='2.3.2'
def public_config(c):
    c=dict(c)
    if c['camera_type']=='rtsp':
        u=urlsplit(c['camera_source']);c['camera_source']=urlunsplit((u.scheme,u.netloc.rsplit('@',1)[-1],u.path,'',''))
    return c

class Vision:
    def __init__(self):
        self.lock=threading.RLock();self.stopping=False;self.enabled=False;self.revision=0
        self.config_path=Path(os.path.expanduser('~/.rcboat/vision.json'))
        try:local=json.loads(self.config_path.read_text()) if self.config_path.is_file() else {}
        except (ValueError,OSError):local={}
        self.config=validate_config(dict(rospy.get_param('/rcboat/vision',{}),**local));self.applied_at=time.monotonic()
        self.frame=None;self.frame_at=0.;self.frame_id=0;self.live_source=False;self.source_type='none'
        self.preview=b'';self.preview_at=0.;self.preview_requested_at=0.;self.preview_bytes=0;self.preview_count=0
        self.error='';self.preview_error='';self.model_ready=False;self.detector=None;self.desired={};self.detail={}
        self.tracker=TargetTracker();self.controller=TrackingController();self.safety={};self.gps={};self.actuator={};self.log_file=None
        self.status_pub=rospy.Publisher('/rcboat/vision/status',String,queue_size=1)
        self.desired_pub=rospy.Publisher('/rcboat/vision/desired',String,queue_size=1)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        rospy.Subscriber('/rcboat/safety/state',String,lambda m:setattr(self,'safety',unpack(m)))
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
        rospy.Subscriber('/rcboat/actuator/status',String,lambda m:setattr(self,'actuator',unpack(m)))
        rospy.Service('/rcboat/vision/execute',Execute,self.execute);rospy.on_shutdown(self.close)
        self.start_preview();threading.Thread(target=self.capture,daemon=True).start()
        self.timer=rospy.Timer(rospy.Duration(.2),self.publish)
    def execute(self,request):
        try:
            args=json.loads(request.arguments_json or '{}')
            if not isinstance(args,dict):raise ValueError('arguments must be an object')
            with self.lock:
                if request.action=='vision_enable':
                    if type(args.get('enabled')) is not bool:raise ValueError('enabled must be boolean')
                    self.enabled=args['enabled'];self.revision+=1;self.model_ready=False;self.desired={};self.frame=None;self.frame_at=0
                    self.preview=b'';self.tracker.reset();self.controller=TrackingController();self.error=''
                    if self.log_file:self.log_file.close();self.log_file=None
                    if self.enabled:
                        folder=Path(os.path.expanduser('~/rcboat_ros_data/logs/vision'));folder.mkdir(parents=True,exist_ok=True)
                        self.log_file=(folder/('vision_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.jsonl')).open('w',encoding='utf-8')
                elif request.action=='vision_configure':
                    if self.enabled:raise ValueError('turn camera off before changing configuration')
                    if 'preview_port' in args:raise ValueError('preview port is startup-only')
                    values=dict(self.config,**args)
                    if values.get('camera_type')=='rtsp' and values.get('camera_source')==public_config(self.config)['camera_source']:values['camera_source']=self.config['camera_source']
                    c=validate_config(values);self.config_path.parent.mkdir(parents=True,exist_ok=True)
                    tmp=self.config_path.with_suffix('.tmp');tmp.write_text(json.dumps(c,indent=2));os.chmod(str(tmp),0o600);tmp.replace(self.config_path)
                    self.config=c;self.revision+=1;self.applied_at=time.monotonic()
                elif request.action=='vision_reset_tracking':self.tracker.reset();self.controller=TrackingController();self.desired={}
                elif request.action!='vision_status':raise ValueError('unknown vision action')
                result=dict(enabled=self.enabled,configuration=public_config(self.config),applied_monotonic=self.applied_at)
            self.events.publish(pack(type='VISION_CHANGE',action=request.action,at=time.time(),configuration=result['configuration']))
            return ExecuteResponse(True,pack(**result))
        except Exception as exc:return ExecuteResponse(False,pack(error=str(exc)))
    def capture(self):
        cap=None;revision=-1
        while not self.stopping and not rospy.is_shutdown():
            if not self.enabled:
                if cap is not None:cap.release();cap=None
                time.sleep(.1);continue
            try:
                import cv2
                if cap is None or revision!=self.revision:
                    from rcboat_ros.camera_io import open_camera
                    if cap is not None:cap.release()
                    revision=self.revision;cap,kind,live=open_camera(dict(self.config),cv2)
                    with self.lock:self.source_type=kind;self.live_source=live
                ok,frame=cap.read();stamp=time.monotonic()
                if not ok or frame is None or frame.ndim!=3:raise RuntimeError('CAMERA_READ_FAILED')
                with self.lock:
                    if self.enabled and revision==self.revision:self.frame=frame;self.frame_at=stamp;self.frame_id+=1
                time.sleep(.002)
            except Exception as exc:
                with self.lock:self.frame_at=0;self.desired={};self.error=str(exc)
                if cap is not None:cap.release()
                cap=None;time.sleep(.8)
        if cap is not None:cap.release()
    def start_preview(self):
        owner=self;token=os.getenv('RCBOAT_GATEWAY_TOKEN','');slots=threading.BoundedSemaphore(4)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.connection.settimeout(1)
                if token and self.headers.get('X-RCBoat-Token','')!=token:self.send_error(401);return
                if self.path!='/frame.jpg':self.send_error(404);return
                if not slots.acquire(False):self.send_error(429);return
                try:
                    with owner.lock:owner.preview_requested_at=time.monotonic();payload=owner.preview;stamp=owner.preview_at
                    if not payload or not owner.enabled or not fresh(stamp,2):self.send_error(503,'no fresh frame');return
                    self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Length',str(len(payload)));self.send_header('X-Frame-Age',str(round(time.monotonic()-stamp,3)));self.end_headers()
                    self.wfile.write(payload);owner.preview_count+=1;owner.preview_bytes+=len(payload)
                except (OSError,TimeoutError):pass
                finally:slots.release()
            def log_message(self,*args):pass
        try:
            self.server=ThreadingHTTPServer(('0.0.0.0',self.config['preview_port']),Handler);self.server.daemon_threads=True
            threading.Thread(target=self.server.serve_forever,daemon=True).start()
        except OSError as exc:self.server=None;self.preview_error=str(exc)
    def publish(self,_event):
        now=time.monotonic()
        with self.lock:
            c=dict(self.config);c['steering_right_sign']=-1 if rospy.get_param('/rcboat/nav_invert_steering',True) else 1;online=self.enabled and fresh(self.frame_at,c['max_frame_age_s'],now);desired=dict(self.desired)
            if not online or not self.model_ready or not fresh(float(desired.get('monotonic') or 0),c['max_frame_age_s'],now):desired.update(valid=False,desired_steering_pwm=6000,desired_throttle_pwm=6450)
            status=dict(self.detail,software_version=VERSION,enabled=self.enabled,model_ready=self.model_ready,camera_online=online,live_source=self.live_source,
                source_type=self.source_type,frame_age_s=round(now-self.frame_at,3) if self.frame_at else None,max_frame_age_s=c['max_frame_age_s'],
                preview_port=c['preview_port'],preview_error=self.preview_error,preview_frames_sent=self.preview_count,preview_bytes_sent=self.preview_bytes,
                configuration=public_config(c),applied_monotonic=self.applied_at,error=self.error,monotonic=now,shared_cruise_pwm=rospy.get_param('/rcboat/cruise_pwm',6650))
            self.status_pub.publish(pack(**status));self.desired_pub.publish(pack(**desired))
            if self.log_file:
                self.log_file.write(json.dumps(dict(utc=dt.datetime.now(dt.timezone.utc).isoformat(),vision=status,desired=desired,
                    gps=self.gps,safety=self.safety,actuator=self.actuator),ensure_ascii=False,allow_nan=False)+'\n');self.log_file.flush()
    def make_preview(self,frame,detections,target,c,stamp):
        import cv2
        image=frame.copy();h,w=image.shape[:2]
        for item in detections:
            colour=(130,235,80) if item['pink_confirmed'] else (155,155,155);x1,y1,x2,y2=[int(v) for v in item['bbox']]
            cv2.rectangle(image,(x1,y1),(x2,y2),colour,2)
            cv2.putText(image,'%s %.2f PINK %.0f%%'%(item['label'],item['confidence'],item['pink_fraction']*100),(x1,max(16,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.43,colour,1)
        if target.get('predicted') and target.get('acquired'):
            x=int(max(0,min(w-1,(target['center_x_normalized']+1)/2*w)));cv2.arrowedLine(image,(w//2,h//2),(x,h//2),(0,210,255),3)
        cv2.line(image,(w//2,0),(w//2,h),(220,220,220),1);cv2.putText(image,target.get('phase','NO_TARGET'),(10,24),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,210,255),2)
        scale=min(c['preview_width']/w,360/h,1);image=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))))
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,c['preview_jpeg_quality']])
        if ok and len(encoded)<=150000:
            with self.lock:self.preview=encoded.tobytes();self.preview_at=stamp
    def run(self):
        revision=-1;processed=-1;last_preview=0;last_load=0;last_end=None
        while not rospy.is_shutdown() and not self.stopping:
            if not self.enabled:
                if self.detector is not None:self.detector.close();self.detector=None
                revision=-1;time.sleep(.1);continue
            start=time.monotonic()
            try:
                c=dict(self.config)
                c['steering_right_sign']=-1 if rospy.get_param('/rcboat/nav_invert_steering',True) else 1
                if revision!=self.revision or self.detector is None and start-last_load>5:
                    if self.detector is not None:self.detector.close()
                    self.detector=None;revision=self.revision;last_load=start
                    from rcboat_ros.balloon_detector import BalloonDetector
                    try:self.detector=BalloonDetector(c)
                    except Exception as exc:
                        with self.lock:self.error='MODEL_NOT_READY: '+str(exc);self.model_ready=False
                    else:
                        with self.lock:self.model_ready=True;self.error=''
                with self.lock:frame=self.frame;stamp=self.frame_at;frame_id=self.frame_id
                if frame is None or frame_id==processed:time.sleep(.02);continue
                processed=frame_id;detections=self.detector.detect(frame) if self.detector else [];end=time.monotonic()
                with self.lock:
                    if not self.enabled or revision!=self.revision:continue
                    target=self.tracker.update(detections,frame.shape[1],frame.shape[0],end,c,self.gps)
                    session=self.safety.get('mode_since_monotonic') if self.safety.get('mode')=='BALLOON' else None
                    desired=self.controller.command(target,stamp,end,c,validate_cruise(rospy.get_param('/rcboat/cruise_pwm',6650)),session)
                    if self.detector is None:desired['valid']=False
                    self.desired=desired;self.detail=dict(reason=target['phase'],target=target,detections=detections,inference_ms=round((end-start)*1000,1),
                        processed_fps=round(1/(end-last_end),2) if last_end and end>last_end else None,backend=self.detector.backend_name if self.detector else 'unavailable',
                        prediction_source='bearing_triangulation' if target.get('world_estimate') else 'image_motion')
                    if self.detector is not None:self.error=''
                last_end=end
                if end-last_preview>=1/c['preview_hz'] and end-self.preview_requested_at<3:last_preview=end;self.make_preview(frame,detections,target,c,stamp)
            except Exception as exc:
                with self.lock:self.desired={};self.error='VISION_ERROR: '+str(exc)
                rospy.logwarn_throttle(5,'Vision: %s',exc)
            time.sleep(max(.01,1/self.config['inference_hz']-(time.monotonic()-start)))
        if self.detector is not None:self.detector.close()
    def close(self):
        self.stopping=True;self.enabled=False
        if self.server:self.server.shutdown();self.server.server_close()
        with self.lock:
            if self.log_file:self.log_file.close();self.log_file=None

if __name__=='__main__':rospy.init_node('balloon_vision_node');Vision().run()
