"""Continuous image tracking and target position estimation; no ROS or CV dependency."""
import math
from collections import deque
from .common import clamp,fresh,SAFE_STEERING,SAFE_THROTTLE,finite_coordinate
from .control_config import number,validate_cruise,NavigationThrottleRamp,THROTTLE_FORWARD_MAX,output_in_range

DEFAULTS={
    'camera_type':'auto','camera_source':'/dev/video0','csi_sensor_id':0,
    'width':640,'height':480,'camera_fps':15,'input_size':320,
    'model_path':'~/rcboat_ros_ws/models/balloon_yolov8n.onnx',
    'model_manifest':'~/rcboat_ros_ws/models/model_manifest.json','backend':'auto',
    'confidence':.35,'nms_iou':.45,'pink_min_fraction':.12,'pink_hue_low':140,'pink_hue_high':179,
    'pink_min_saturation':45,'pink_min_value':55,'inference_hz':5.,'max_frame_age_s':1.5,
    'acquire_frames':3,'steering_gain':.85,'steering_deadband':.04,'steering_right_sign':-1,
    'predict_s':2.0,'search_timeout_s':15.0,'search_period_s':5.0,'search_turn_strength':.8,
    'camera_hfov_deg':62.0,'camera_yaw_deg':0.0,'preview_port':8766,'preview_hz':5.,
    'preview_width':640,'preview_jpeg_quality':55,
}

def validate_config(values):
    if not isinstance(values,dict) or set(values)-set(DEFAULTS):raise ValueError('unknown vision setting')
    c=dict(DEFAULTS,**values)
    if c['camera_type'] not in ('auto','usb','csi','rtsp','file'):raise ValueError('unsupported camera type')
    if c['backend'] not in ('auto','tensorrt','onnxruntime','opencv'):raise ValueError('unsupported inference backend')
    if c['camera_type'] in ('auto','usb') and not str(c['camera_source']).startswith('/dev/video'):
        raise ValueError('USB/auto source must be a local /dev/video device')
    if c['camera_type']=='rtsp' and not str(c['camera_source']).startswith(('rtsp://','rtsps://')):raise ValueError('RTSP URL required')
    limits={'width':(160,1920),'height':(120,1080),'camera_fps':(1,60),'input_size':(160,640),
        'confidence':(.05,.99),'nms_iou':(.05,.9),'pink_min_fraction':(.01,.9),
        'pink_hue_low':(0,179),'pink_hue_high':(0,179),'pink_min_saturation':(0,255),'pink_min_value':(0,255),
        'inference_hz':(.5,10),'max_frame_age_s':(.3,2),'acquire_frames':(1,12),
        'steering_gain':(.05,1.5),'steering_deadband':(0,.3),'predict_s':(.2,4),
        'search_timeout_s':(3,30),'search_period_s':(2,12),'search_turn_strength':(.2,1),
        'camera_hfov_deg':(20,150),'camera_yaw_deg':(-180,180),'csi_sensor_id':(0,3),
        'preview_port':(1024,65535),'preview_hz':(.5,5),'preview_width':(160,640),'preview_jpeg_quality':(30,80)}
    integers={'width','height','camera_fps','input_size','acquire_frames','pink_hue_low','pink_hue_high',
        'pink_min_saturation','pink_min_value','csi_sensor_id','preview_port','preview_width','preview_jpeg_quality'}
    for key,(lo,hi) in limits.items():
        value=number(c[key])
        if not lo<=value<=hi or (key in integers and not value.is_integer()):raise ValueError(key+' outside supported range')
        c[key]=int(value) if key in integers else value
    if c['steering_right_sign'] not in (-1,1) or isinstance(c['steering_right_sign'],bool):raise ValueError('steering sign must be -1 or 1')
    if c['pink_hue_low']>c['pink_hue_high'] or c['input_size']%32 or c['search_timeout_s']<=c['predict_s']:raise ValueError('invalid vision configuration ordering')
    for key in ('model_path','model_manifest','camera_source'):
        if not isinstance(c[key],str) or not c[key].strip() or len(c[key])>1000:raise ValueError('invalid '+key)
    return c

def angle_error(target,current):return (target-current+180)%360-180

class BearingEstimator:
    """Stationary balloon position from GPS motion and camera bearings; reject weak geometry."""
    def __init__(self):self.origin=None;self.observations=deque(maxlen=20);self.estimate=None;self.updated_at=0
    def reset(self):self.__init__()
    def pose(self,gps,now):
        try:
            if (not gps.get('fix') or not fresh(float(gps.get('last_valid_monotonic') or 0),2,now)
                    or not finite_coordinate(gps.get('latitude'),gps.get('longitude'))):return None
            speed=number(gps.get('speed_mps'));heading=number(gps.get('heading_deg'))
            if speed<.35:return None
            lat=number(gps['latitude']);lon=number(gps['longitude'])
            if self.origin is None:self.origin=(lat,lon)
            x=math.radians(lon-self.origin[1])*6371000*math.cos(math.radians(self.origin[0]))
            y=math.radians(lat-self.origin[0])*6371000
            return x,y,heading,speed
        except (ValueError,TypeError):return None
    def observe(self,target,gps,now,config):
        pose=self.pose(gps,now)
        if pose is None:return
        x,y,heading,_=pose
        if self.observations and math.hypot(x-self.observations[-1][0],y-self.observations[-1][1])<.35:return
        bearing=math.radians(heading+config['camera_yaw_deg']+math.degrees(math.atan(target['center_x_normalized']*math.tan(math.radians(config['camera_hfov_deg']/2)))))
        self.observations.append((x,y,math.sin(bearing),math.cos(bearing),now))
        obs=[o for o in self.observations if now-o[4]<15]
        if len(obs)<3 or max(math.hypot(o[0]-x,o[1]-y) for o in obs)<1:return
        a=b=d=u=v=0
        for px,py,dx,dy,_ in obs:
            nx,ny=-dy,dx;q=nx*px+ny*py;a+=nx*nx;b+=nx*ny;d+=ny*ny;u+=nx*q;v+=ny*q
        det=a*d-b*b
        if det<.02:return
        tx,ty=(d*u-b*v)/det,(a*v-b*u)/det
        distances=[abs(-dy*(tx-px)+dx*(ty-py)) for px,py,dx,dy,_ in obs]
        forward=sum((tx-px)*dx+(ty-py)*dy>0 for px,py,dx,dy,_ in obs)
        if forward<len(obs)*.8 or max(distances)>2 or not .5<math.hypot(tx-x,ty-y)<80:return
        self.estimate=(tx,ty);self.updated_at=now
    def relative(self,gps,now):
        pose=self.pose(gps,now)
        if self.estimate is None or pose is None or now-self.updated_at>20:return None
        x,y,heading,_=pose;dx=self.estimate[0]-x;dy=self.estimate[1]-y
        lat=self.origin[0]+math.degrees(self.estimate[1]/6371000)
        lon=self.origin[1]+math.degrees(self.estimate[0]/(6371000*math.cos(math.radians(self.origin[0]))))
        return dict(heading_error_deg=angle_error(math.degrees(math.atan2(dx,dy)),heading),distance_m=math.hypot(dx,dy),
            latitude=lat,longitude=lon,source='bearing_triangulation',age_s=now-self.updated_at,calibration_assumed=True)

class TargetTracker:
    def __init__(self):self.reset()
    def reset(self):
        self.target=None;self.streak=0;self.observed_at=None;self.velocity=0.;self.scale_velocity=0.;self.side=1
        self.estimator=BearingEstimator();self.acquired=False;self.was_close=False
    def update(self,detections,width,height,now,config,gps=None):
        candidates=[]
        for item in detections:
            try:
                box=[number(v) for v in item['bbox']];score=number(item['confidence'])
                if (not item.get('pink_confirmed') or score<config['confidence'] or len(box)!=4 or
                        not 0<=box[0]<box[2]<=width or not 0<=box[1]<box[3]<=height):continue
                candidates.append(dict(item,bbox=box,center_x_normalized=(box[0]+box[2])/width-1,
                    center_y_normalized=(box[1]+box[3])/height-1,area_ratio=(box[2]-box[0])*(box[3]-box[1])/(width*height),
                    box_height_ratio=(box[3]-box[1])/height))
            except (KeyError,TypeError,ValueError):continue
        age=now-self.observed_at if self.observed_at is not None else 1e9
        if candidates:
            if self.target is not None and age<config['search_timeout_s']:
                predicted=self.target['center_x_normalized']+self.velocity*min(age,config['predict_s'])
                target=min(candidates,key=lambda t:abs(t['center_x_normalized']-predicted)+.12*abs(math.log(max(t['area_ratio'],1e-6)/max(self.target['area_ratio'],1e-6))))
                if age<1.5 and abs(target['center_x_normalized']-predicted)>.8:candidates=[]
            else:target=max(candidates,key=lambda t:t['confidence']*math.sqrt(t['area_ratio']))
        if candidates:
            if age>=config['search_timeout_s']:self.acquired=False;self.was_close=False;self.estimator.reset()
            if self.target is not None and .02<age<1.5:
                residual=target['center_x_normalized']-(self.target['center_x_normalized']+self.velocity*age)
                self.velocity=clamp(self.velocity+.12*residual/age,-1.5,1.5)
                self.scale_velocity=clamp((target['area_ratio']-self.target['area_ratio'])/age,-.5,.5)
            else:self.velocity=0;self.scale_velocity=0
            if age>1.5:self.streak=0
            self.target=target;self.observed_at=now;self.streak+=1;self.acquired=self.acquired or self.streak>=config['acquire_frames']
            self.side=1 if target['center_x_normalized']>=.03 else -1 if target['center_x_normalized']<=-.03 else self.side
            self.was_close=self.was_close or target['area_ratio']>.12 or target['box_height_ratio']>.55
            self.estimator.observe(target,gps or {},now,config)
            return dict(target,phase='TRACKING' if self.acquired else 'ACQUIRING',acquired=self.acquired,
                predicted=False,lost_age_s=0.,velocity_x=self.velocity,world_estimate=self.estimator.relative(gps or {},now))
        if self.target is None or not self.acquired:return dict(phase='NO_TARGET',acquired=False,predicted=False,lost_age_s=None)
        if age>=config['search_timeout_s']:return dict(self.target,phase='LOST_TIMEOUT',acquired=False,predicted=True,lost_age_s=age)
        target=dict(self.target);world=self.estimator.relative(gps or {},now)
        predicted=clamp(target['center_x_normalized']+self.velocity*min(age,config['predict_s']),-1.5,1.5)
        if world is not None:
            predicted=clamp(world['heading_error_deg']/(config['camera_hfov_deg']/2),-1.5,1.5)
            phase='TURN_BACK' if abs(world['heading_error_deg'])>100 else 'POSITION_REACQUIRE'
        elif self.was_close and age>.5:predicted=self.side*config['search_turn_strength'];phase='TURN_BACK'
        elif age<config['predict_s']:phase='PREDICTING'
        else:
            predicted=self.side*config['search_turn_strength']*math.cos((age-config['predict_s'])*math.pi/config['search_period_s']);phase='SEARCHING'
        return dict(target,center_x_normalized=predicted,phase=phase,acquired=True,predicted=True,
                    lost_age_s=age,velocity_x=self.velocity,world_estimate=world)

class TrackingController:
    def __init__(self):self.ramp=NavigationThrottleRamp();self.session=None
    def command(self,target,frame_time,now,config,cruise_pwm=6650,session=None):
        cruise=validate_cruise(cruise_pwm)
        out=dict(valid=False,desired_steering_pwm=SAFE_STEERING,desired_throttle_pwm=SAFE_THROTTLE,
            monotonic=frame_time,reason=target.get('phase','NO_TARGET'),phase=target.get('phase','NO_TARGET'),
            target_pwm=cruise,tracking_session=session,predicted=bool(target.get('predicted')))
        if not fresh(frame_time,config['max_frame_age_s'],now) or not target.get('acquired'):
            self.ramp.reset();return out
        if self.session!=session:self.ramp.reset();self.session=session
        error=number(target['center_x_normalized']);demand=0 if abs(error)<config['steering_deadband'] else clamp(config['steering_right_sign']*error*config['steering_gain'],-1,1)
        if target['phase']=='TURN_BACK':demand=config['steering_right_sign']*(1 if error>=0 else -1)*config['search_turn_strength']
        steer=round(SAFE_STEERING+demand*(1300 if demand>=0 else 1100))
        # Straight approach uses the shared navigation target. Turns retain reduced thrust.
        fraction=1.0 if abs(error)<.25 else max(.65,1-.35*abs(error))
        throttle=round(SAFE_THROTTLE+(cruise-SAFE_THROTTLE)*fraction)
        if target.get('predicted'):throttle=min(throttle,6650)
        throttle=self.ramp.update(throttle,now)
        out.update(valid=True,desired_steering_pwm=steer,desired_throttle_pwm=throttle,
                   horizontal_error=error,area_ratio=target.get('area_ratio'),world_estimate=target.get('world_estimate'))
        return out

def safe_balloon_output(vision,desired,now,session=None):
    try:
        limit=number(vision.get('max_frame_age_s',1.5))
        if not .3<=limit<=2:return None
        if (not vision.get('enabled') or not vision.get('model_ready') or not vision.get('camera_online') or
                not vision.get('live_source') or not fresh(number(vision.get('monotonic')),min(2,limit),now) or
                not desired.get('valid') or not fresh(number(desired.get('monotonic')),min(2,limit),now)):return None
        if session is not None and desired.get('tracking_session')!=session:return None
        s,t=desired.get('desired_steering_pwm'),desired.get('desired_throttle_pwm')
        if not output_in_range(s,t) or t<SAFE_THROTTLE:return None
        return s,t
    except (TypeError,ValueError,KeyError):return None
