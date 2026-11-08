"""USB/CSI capture may control the boat; RTSP/file inputs are preview-only."""
from pathlib import Path

class PrimedCapture:
    """Return the probe frame first; isOpened alone does not prove usable BGR."""
    def __init__(self,capture,frame):self.capture=capture;self.first=frame
    def read(self):
        if self.first is not None:
            frame,self.first=self.first,None
            return True,frame
        return self.capture.read()
    def release(self):self.first=None;self.capture.release()
    def __getattr__(self,name):return getattr(self.capture,name)

def open_camera(c,cv2):
    errors=[]
    for kind in (['usb','csi'] if c['camera_type']=='auto' else [c['camera_type']]):
        cap=None
        try:
            if kind=='csi':
                pipeline=('nvarguscamerasrc sensor-id=%d ! video/x-raw(memory:NVMM),width=%d,height=%d,framerate=%d/1 ! '
                    'nvvidconv ! video/x-raw,width=%d,height=%d,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! '
                    'appsink drop=true max-buffers=1 sync=false')%(c['csi_sensor_id'],max(1280,c['width']),max(720,c['height']),c['camera_fps'],c['width'],c['height'])
                cap=cv2.VideoCapture(pipeline,cv2.CAP_GSTREAMER)
            else:
                if kind=='usb' and not Path(c['camera_source']).exists():raise RuntimeError('device absent')
                cap=cv2.VideoCapture(c['camera_source'],cv2.CAP_V4L2 if kind=='usb' else cv2.CAP_FFMPEG if kind=='rtsp' else cv2.CAP_ANY)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,c['width']);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,c['height'])
                cap.set(cv2.CAP_PROP_FPS,c['camera_fps']);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
            if not cap.isOpened():raise RuntimeError('camera driver did not open')
            frame=None
            for _ in range(3):
                ok,probe=cap.read()
                if ok and probe is not None and getattr(probe,'ndim',0)==3 and probe.shape[2]==3 and min(probe.shape[:2])>0:
                    frame=probe;break
            if frame is None:raise RuntimeError('camera opened without usable BGR frames')
            return PrimedCapture(cap,frame),kind,kind in ('usb','csi')
        except Exception as exc:
            if cap is not None:cap.release()
            errors.append(kind+': '+str(exc)[:100])
    raise RuntimeError('CAMERA_OPEN_FAILED: '+'; '.join(errors))
