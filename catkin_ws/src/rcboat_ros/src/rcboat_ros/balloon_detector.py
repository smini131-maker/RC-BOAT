"""Static YOLOv8n inference without PyTorch on Jetson; neural shape AND pink colour."""
import hashlib,json
from pathlib import Path
import numpy as np

def verify_model(path,manifest_path,input_size):
    model=Path(path).expanduser();meta=Path(manifest_path).expanduser()
    if not model.is_file() or not meta.is_file():raise ValueError('MODEL_MISSING: install trained ONNX and manifest')
    data=json.loads(meta.read_text(encoding='utf-8'))
    if data.get('classes')!=['balloon'] or data.get('output_format')!='yolov8':raise ValueError('trained YOLOv8 balloon model required')
    if data.get('input_size')!=input_size:raise ValueError('model input size mismatch')
    if hashlib.sha256(model.read_bytes()).hexdigest()!=data.get('sha256'):raise ValueError('model SHA-256 mismatch')
    return data

def decode_predictions(prediction,shape,size,scale,padding,confidence,nms,cv2):
    rows=np.asarray(prediction)
    if rows.ndim==3 and rows.shape[0]==1:rows=rows[0]
    if rows.ndim==2 and rows.shape[0]==5:rows=rows.T
    if rows.ndim!=2 or rows.shape[1]!=5:raise ValueError('YOLOv8 single class [1,5,N] expected')
    height,width=shape[:2];boxes=[];scores=[]
    for row in rows[np.isfinite(rows).all(axis=1)]:
        if row[4]<confidence or row[2]<=0 or row[3]<=0:continue
        x,y,w,h=[float(v) for v in row[:4]]
        x1=max(0,min(width,(x-w/2-padding[0])/scale));x2=max(0,min(width,(x+w/2-padding[0])/scale))
        y1=max(0,min(height,(y-h/2-padding[1])/scale));y2=max(0,min(height,(y+h/2-padding[1])/scale))
        if x2<=x1 or y2<=y1:continue
        boxes.append([x1,y1,x2-x1,y2-y1]);scores.append(float(row[4]))
    indices=cv2.dnn.NMSBoxes(boxes,scores,confidence,nms) if boxes else []
    return [dict(class_id=0,label='balloon',confidence=scores[int(i)],
        bbox=[boxes[int(i)][0],boxes[int(i)][1],boxes[int(i)][0]+boxes[int(i)][2],boxes[int(i)][1]+boxes[int(i)][3]])
        for i in np.asarray(indices).reshape(-1)]

def pink_fraction(frame,bbox,config,cv2):
    x1,y1,x2,y2=[int(v) for v in bbox];roi=frame[y1:y2,x1:x2]
    if not roi.size:return 0.
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([config['pink_hue_low'],config['pink_min_saturation'],config['pink_min_value']],np.uint8),
        np.array([config['pink_hue_high'],255,255],np.uint8))
    yy,xx=np.ogrid[:roi.shape[0],:roi.shape[1]]
    ellipse=((xx-roi.shape[1]/2)/max(1,roi.shape[1]/2))**2+((yy-roi.shape[0]/2)/max(1,roi.shape[0]/2))**2<=1
    return float(np.count_nonzero(mask[ellipse]))/max(1,int(np.count_nonzero(ellipse)))

class TensorRTBackend:
    """TensorRT 8 binding API (JetPack 4/5), optional and target-device generated."""
    def __init__(self,path,onnx_hash):
        self.device_context=None;self.buffers=[]
        try:self.initialize(path,onnx_hash)
        except Exception:
            self.close();raise
    def initialize(self,path,onnx_hash):
        import tensorrt as trt
        import pycuda.driver as cuda
        engine_path=Path(path).with_suffix('.engine');manifest=engine_path.with_suffix('.engine.json')
        meta=json.loads(manifest.read_text())
        if meta.get('onnx_sha256')!=onnx_hash or meta.get('engine_sha256')!=hashlib.sha256(engine_path.read_bytes()).hexdigest():
            raise ValueError('TensorRT engine does not match this model')
        cuda.init();self.cuda=cuda;self.device_context=cuda.Device(0).make_context()
        self.runtime=trt.Runtime(trt.Logger(trt.Logger.WARNING));self.engine=self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:raise ValueError('engine incompatible with this TensorRT/device')
        if not hasattr(self.engine,'num_bindings'):raise ValueError('TensorRT 8 engine API required; use ONNX fallback')
        self.context=self.engine.create_execution_context();self.stream=cuda.Stream();self.bindings=[];self.buffers=[]
        for i in range(self.engine.num_bindings):
            shape=tuple(self.context.get_binding_shape(i))
            if any(s<=0 for s in shape):raise ValueError('static engine required')
            host=cuda.pagelocked_empty(int(np.prod(shape)),trt.nptype(self.engine.get_binding_dtype(i)))
            dev=cuda.mem_alloc(host.nbytes);self.bindings.append(int(dev));self.buffers.append((host,dev,shape,self.engine.binding_is_input(i)))
    def run(self,blob):
        for host,dev,shape,is_input in self.buffers:
            if is_input:np.copyto(host,blob.astype(host.dtype).reshape(-1));self.cuda.memcpy_htod_async(dev,host,self.stream)
        if not self.context.execute_async_v2(self.bindings,self.stream.handle):raise RuntimeError('TensorRT inference failed')
        for host,dev,shape,is_input in self.buffers:
            if not is_input:self.cuda.memcpy_dtoh_async(host,dev,self.stream)
        self.stream.synchronize()
        return next(host.reshape(shape).copy() for host,dev,shape,is_input in self.buffers if not is_input)
    def close(self):
        if getattr(self,'device_context',None):
            for host,dev,shape,is_input in self.buffers:dev.free()
            self.buffers=[];self.stream=None;self.context=None;self.engine=None;self.runtime=None
            self.device_context.pop();self.device_context.detach();self.device_context=None

class BalloonDetector:
    def __init__(self,config):
        import cv2
        self.cv2=cv2;self.config=config;cv2.setNumThreads(2)
        self.manifest=verify_model(config['model_path'],config['model_manifest'],config['input_size'])
        path=str(Path(config['model_path']).expanduser());self.backend=None;self.backend_name='';self.fallback=[]
        choices=['tensorrt','onnxruntime','opencv'] if config['backend']=='auto' else [config['backend']]
        for name in choices:
            try:
                if name=='tensorrt':self.backend=TensorRTBackend(path,self.manifest['sha256'])
                elif name=='onnxruntime':
                    import onnxruntime as ort
                    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
                    self.backend=ort.InferenceSession(path,sess_options=options,providers=['CPUExecutionProvider'])
                else:
                    self.backend=cv2.dnn.readNetFromONNX(np.frombuffer(Path(path).read_bytes(),np.uint8))
                    self.backend.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV);self.backend.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.backend_name=name;self.detect(np.zeros((config['input_size'],config['input_size'],3),np.uint8));break
            except Exception as exc:
                if hasattr(self.backend,'close'):self.backend.close()
                self.backend=None;self.fallback.append(name+': '+str(exc)[:160])
        if self.backend is None:raise RuntimeError('No usable inference backend: '+'; '.join(self.fallback))
    def detect(self,frame):
        cv2=self.cv2;size=self.config['input_size'];h,w=frame.shape[:2];scale=min(size/w,size/h)
        rw,rh=round(w*scale),round(h*scale);left,top=(size-rw)//2,(size-rh)//2
        padded=np.full((size,size,3),114,np.uint8);padded[top:top+rh,left:left+rw]=cv2.resize(frame,(rw,rh))
        blob=cv2.dnn.blobFromImage(padded,1/255.,(size,size),swapRB=True,crop=False)
        if self.backend_name=='onnxruntime':prediction=self.backend.run(None,{self.backend.get_inputs()[0].name:blob})[0]
        elif self.backend_name=='tensorrt':prediction=self.backend.run(blob)
        else:self.backend.setInput(blob);prediction=self.backend.forward()
        detections=decode_predictions(prediction,frame.shape,size,scale,(left,top),self.config['confidence'],self.config['nms_iou'],cv2)
        for item in detections:
            fraction=pink_fraction(frame,item['bbox'],self.config,cv2)
            item.update(pink_fraction=round(fraction,4),pink_confirmed=fraction>=self.config['pink_min_fraction'])
            if item['pink_confirmed']:item['label']='pink_balloon'
        return detections
    def close(self):
        if hasattr(self.backend,'close'):self.backend.close()
