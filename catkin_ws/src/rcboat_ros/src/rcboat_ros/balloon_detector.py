"""Static YOLOv8n inference without PyTorch on Jetson; neural shape AND target colour."""
import hashlib,json
import time
from pathlib import Path
import numpy as np
from .long_range import RegionPlanner, target_colour_mask

def verify_model(path,manifest_path,input_size):
    model=Path(path).expanduser();meta=Path(manifest_path).expanduser()
    if not model.is_file() or not meta.is_file():raise ValueError('MODEL_MISSING: install trained ONNX and manifest')
    data=json.loads(meta.read_text(encoding='utf-8'))
    if data.get('classes')!=['balloon'] or data.get('output_format')!='yolov8':raise ValueError('trained YOLOv8 balloon model required')
    if data.get('input_size')!=input_size:raise ValueError('model input size mismatch')
    if hashlib.sha256(model.read_bytes()).hexdigest()!=data.get('sha256'):raise ValueError('model SHA-256 mismatch')
    if data.get('target_colour', 'pink') not in ('pink', 'red'):raise ValueError('unsupported model target colour')
    return data

def decode_predictions(prediction,shape,size,scale,padding,confidence,nms,cv2):
    rows=np.asarray(prediction)
    if rows.ndim==3 and rows.shape[0]==1:rows=rows[0]
    if rows.ndim==2 and rows.shape[0]==5:rows=rows.T
    if rows.ndim!=2 or rows.shape[1]!=5:raise ValueError('YOLOv8 single class [1,5,N] expected')
    height,width=shape[:2];boxes=[];scores=[]
    candidates=rows[np.isfinite(rows).all(axis=1)&(rows[:,4]>=confidence)&(rows[:,2]>0)&(rows[:,3]>0)]
    for row in candidates:
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
    mask=target_colour_mask(hsv,config,cv2)
    yy,xx=np.ogrid[:roi.shape[0],:roi.shape[1]]
    ellipse=((xx-roi.shape[1]/2)/max(1,roi.shape[1]/2))**2+((yy-roi.shape[0]/2)/max(1,roi.shape[0]/2))**2<=1
    return float(np.count_nonzero(mask[ellipse]))/max(1,int(np.count_nonzero(ellipse)))

def small_pink_shape_supported(frame,bbox,config,cv2):
    """Reject thin colour strips when a target has few native pixels.

    This is only a confirmation veto after neural inference, never a detector.
    At this scale the largest target-colour component must occupy both image axes;
    elongated hull edges/paint lines are not enough evidence to acquire a target.
    """
    x1,y1,x2,y2=[int(v) for v in bbox];roi=frame[y1:y2,x1:x2]
    if not roi.size:return False
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    mask=target_colour_mask(hsv,config,cv2)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=8)
    if len(stats)<2:return False
    component=max(stats[1:],key=lambda row:row[4])
    w,h,area=int(component[2]),int(component[3]),int(component[4])
    return min(w,h)>=3 and min(w,h)/max(w,h)>=.5 and area/(w*h)>=.3

def roi_contains_red_box(box,crop,frame_shape):
    """Reject detections cut by an artificial crop edge; full frames remain usable."""
    x1,y1,x2,y2=box
    left,top,right,bottom=crop
    height,width=frame_shape[:2]
    margin=max(2.,.015*min(right-left,bottom-top))
    return ((left==0 or x1-left>margin) and (top==0 or y1-top>margin)
            and (right==width or right-x2>margin) and (bottom==height or bottom-y2>margin))


def large_red_shape_supported(frame,bbox,config,cv2):
    """Reject a narrow patch of red inside a large neural detection."""
    x1,y1,x2,y2=map(int,bbox)
    roi=frame[y1:y2,x1:x2]
    height,width=roi.shape[:2]
    if not height or not width:
        return False
    scale=min(1.,192/max(height,width))
    view=cv2.resize(roi,(max(1,round(width*scale)),max(1,round(height*scale))),
                    interpolation=cv2.INTER_AREA) if scale<1. else roi
    mask=target_colour_mask(cv2.cvtColor(view,cv2.COLOR_BGR2HSV),config,cv2)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=8)
    if len(stats)<2:
        return False
    _,_,w,h,_=map(int,max(stats[1:],key=lambda row:row[4]))
    return (min(w,h)>=.27*max(w,h)
            and w>=.24*view.shape[1] and h>=.24*view.shape[0])


def near_red_visual_support(frame, previous_box, config, cv2):
    """Check if a previously verified close red target still covers its last box."""
    if config.get('target_colour') != 'red' or previous_box is None:
        return False
    height, width = frame.shape[:2]
    left, top, right, bottom = previous_box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        return False
    box_width, box_height = right - left, bottom - top
    fills_view = box_height / height >= .8 or box_width * box_height / (width * height) >= .4
    if not fills_view or abs((left + right) / width - 1) >= .45:
        return False

    region = frame[int(top):int(bottom), int(left):int(right)]
    box_height, box_width = region.shape[:2]
    if not region.size:
        return False
    scale = min(1., 96 / max(box_height, box_width))
    if scale < 1.:
        region = cv2.resize(region, (max(1, round(box_width * scale)),
                                     max(1, round(box_height * scale))), interpolation=cv2.INTER_AREA)
    # A close balloon can shift toward magenta under the camera's automatic
    # exposure and white balance. Only broaden colour after neural acquisition.
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    warm = cv2.inRange(hsv, (0, 50, 35), (16, 255, 255))
    cool = cv2.inRange(hsv, (160, 50, 35), (179, 255, 255))
    mask = cv2.bitwise_or(warm, cool)
    rows, columns = mask.shape
    if cv2.countNonZero(mask) < .30 * mask.size:
        return False
    _, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    label = 1 + int(np.argmax(stats[1:, 4]))
    _, _, patch_width, patch_height, patch_area = stats[label]
    if (patch_width < .35 * columns or patch_height < .35 * rows
            or min(patch_width, patch_height) < .27 * max(patch_width, patch_height)):
        return False
    core = labels[rows//4:rows-rows//4, columns//4:columns-columns//4]
    coverage = patch_area / mask.size
    core_coverage = np.count_nonzero(core == label) / core.size
    if coverage >= .30 and core_coverage >= .65:
        return True
    # A shifted patch must still have substantial overlap with the old box
    # and its core. A patch only at the old box edge cannot sustain motion.
    center_x, center_y = centroids[label]
    return (coverage >= .40 and core_coverage >= .30
            and abs(center_x - (columns - 1) / 2) <= .32 * columns
            and abs(center_y - (rows - 1) / 2) <= .32 * rows)


class TensorRTBackend:
    """TensorRT 8 binding API (JetPack 4/5), optional and target-device generated."""
    def __init__(self,path,onnx_hash):
        self.buffers=[];self.stream=None
        try:self.initialize(path,onnx_hash)
        except Exception:
            self.close();raise
    def initialize(self,path,onnx_hash):
        import tensorrt as trt
        from .cuda_runtime import CudaRuntime
        engine_path=Path(path).with_suffix('.engine');manifest=engine_path.with_suffix('.engine.json')
        meta=json.loads(manifest.read_text())
        if meta.get('onnx_sha256')!=onnx_hash or meta.get('engine_sha256')!=hashlib.sha256(engine_path.read_bytes()).hexdigest():
            raise ValueError('TensorRT engine does not match this model')
        self.cuda=CudaRuntime()
        self.logger=trt.Logger(trt.Logger.WARNING);self.runtime=trt.Runtime(self.logger);self.engine=self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:raise ValueError('engine incompatible with this TensorRT/device')
        if not hasattr(self.engine,'num_bindings'):raise ValueError('TensorRT 8 engine API required; use ONNX fallback')
        self.context=self.engine.create_execution_context();self.stream=self.cuda.stream();self.bindings=[];self.buffers=[]
        if self.engine.num_bindings!=2:raise ValueError('one static image input and one YOLO output required')
        for i in range(self.engine.num_bindings):
            shape=tuple(self.context.get_binding_shape(i))
            if any(s<=0 for s in shape):raise ValueError('static engine required')
            host,dev,pinned=self.cuda.allocate(shape,trt.nptype(self.engine.get_binding_dtype(i)))
            self.bindings.append(dev.value);self.buffers.append((host,dev,shape,self.engine.binding_is_input(i),pinned))
        if sum(item[3] for item in self.buffers)!=1:raise ValueError('single input/output engine required')
    def run(self,blob):
        for host,dev,shape,is_input,pinned in self.buffers:
            if is_input:
                if tuple(blob.shape)!=shape:raise ValueError('TensorRT input shape mismatch')
                np.copyto(host,blob.reshape(-1),casting='same_kind')
                self.cuda.copy(dev,pinned,host.nbytes,1,self.stream)
        if not self.context.execute_async_v2(self.bindings,self.stream.value):raise RuntimeError('TensorRT inference failed')
        for host,dev,shape,is_input,pinned in self.buffers:
            if not is_input:self.cuda.copy(pinned,dev,host.nbytes,2,self.stream)
        self.cuda.call('cudaStreamSynchronize',self.stream)
        return next(host.reshape(shape).copy() for host,dev,shape,is_input,pinned in self.buffers if not is_input)
    def close(self):
        cuda=getattr(self,'cuda',None)
        if cuda:
            if self.stream:cuda.call('cudaStreamSynchronize',self.stream)
            for host,dev,shape,is_input,pinned in self.buffers:
                cuda.call('cudaFree',dev);cuda.call('cudaFreeHost',pinned)
            self.buffers=[]
            if self.stream:cuda.call('cudaStreamDestroy',self.stream);self.stream=None
        self.context=None;self.engine=None;self.runtime=None;self.logger=None

class BalloonDetector:
    def __init__(self,config):
        import cv2
        self.cv2=cv2;cv2.setNumThreads(2)
        self.planner=RegionPlanner();self.last_view={}
        self.manifest=verify_model(config['model_path'],config['model_manifest'],config['input_size'])
        self.target_colour=self.manifest.get('target_colour','pink')
        self.config=dict(config,target_colour=self.target_colour)
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
        if not isinstance(frame,np.ndarray) or frame.ndim!=3 or frame.shape[2]!=3 or not frame.size or frame.dtype!=np.uint8:
            raise ValueError('nonempty uint8 BGR frame required')
        cv2=self.cv2;size=self.config['input_size']
        start = time.monotonic()
        crop,detail=self.planner.plan(frame,self.config,cv2)
        planned = time.monotonic()
        x0,y0,xend,yend=crop;view=frame[y0:yend,x0:xend];h,w=view.shape[:2];scale=min(size/w,size/h)
        rw,rh=round(w*scale),round(h*scale);left,top=(size-rw)//2,(size-rh)//2
        padded=np.full((size,size,3),114,np.uint8);padded[top:top+rh,left:left+rw]=cv2.resize(view,(rw,rh))
        blob=cv2.dnn.blobFromImage(padded,1/255.,(size,size),swapRB=True,crop=False)
        prepared = time.monotonic()
        if self.backend_name=='onnxruntime':prediction=self.backend.run(None,{self.backend.get_inputs()[0].name:blob})[0]
        elif self.backend_name=='tensorrt':prediction=self.backend.run(blob)
        else:self.backend.setInput(blob);prediction=self.backend.forward()
        inferred = time.monotonic()
        detections=decode_predictions(prediction,view.shape,size,scale,(left,top),self.config['confidence'],self.config['nms_iou'],cv2)
        target_colour=self.config.get('target_colour','pink')
        for item in detections:
            b=item['bbox'];item['bbox']=[b[0]+x0,b[1]+y0,b[2]+x0,b[3]+y0]
            fraction=pink_fraction(frame,item['bbox'],self.config,cv2)
            span=min(b[2]-b[0],b[3]-b[1])
            supported=span>=self.config.get('min_source_span_px',4.0)
            shape_supported=span>=40 or small_pink_shape_supported(frame,item['bbox'],self.config,cv2)
            colour_confirmed=fraction>=self.config['pink_min_fraction'] and supported and shape_supported
            if colour_confirmed and target_colour=='red':
                colour_confirmed=roi_contains_red_box(item['bbox'],crop,frame.shape)
                if colour_confirmed and span>=40:
                    colour_confirmed=large_red_shape_supported(frame,item['bbox'],self.config,cv2)
            item.update(pink_fraction=round(fraction,4),pink_confirmed=colour_confirmed,
                        small_shape_supported=shape_supported,
                        source_span_px=round(span,2),pixel_support='limited' if span<8 else 'adequate',detector_view=detail['kind'])
            # The pink_* telemetry fields are retained for existing tracker and log readers.
            item['target_colour']=target_colour
            if item['pink_confirmed']:item['label']=target_colour+'_balloon'
        self.planner.observe(detections)
        detail['model_input']=size;detail['requested_resolution_met']=frame.shape[1]>=self.config['width'] and frame.shape[0]>=self.config['height']
        detail.setdefault('timing_ms', {}).update(
            roi_plan=round((planned-start)*1000, 2),
            input_prep=round((prepared-planned)*1000, 2),
            model_run=round((inferred-prepared)*1000, 2),
            postprocess=round((time.monotonic()-inferred)*1000, 2))
        self.last_view=detail
        return detections
    def reset_search(self):
        self.planner=RegionPlanner()
    def close(self):
        if hasattr(self.backend,'close'):self.backend.close()
