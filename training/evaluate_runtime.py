"""Evaluate shipped ONNX and colour postprocessing on held-out images; never on a boat."""
import argparse,hashlib,json,statistics,sys,tempfile,time
from pathlib import Path
import cv2,numpy as np,yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_detector import BalloonDetector,decode_predictions,pink_fraction,verify_model
from rcboat_ros.balloon_tracking import validate_config
def iou(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return inter/max(1e-6,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('dataset',type=Path)
    parser.add_argument('--model-dir',type=Path,default=ROOT/'models');parser.add_argument('--output',type=Path,default=ROOT/'models/runtime_evaluation.json');args=parser.parse_args()
    c=validate_config(dict(model_path=str(args.model_dir/'balloon_yolov8n.onnx'),model_manifest=str(args.model_dir/'model_manifest.json'),backend='onnxruntime',long_range_enabled=False))
    # Known decoder geometry, invalid shapes and pink/green colour boundaries.
    pred=np.array([[[160,160,80,80,.9],[160,160,80,80,.8],[100,100,-1,20,.99]]],np.float32)
    decoded=decode_predictions(pred,(480,640,3),320,.5,(0,40),.35,.45,cv2)
    assert len(decoded)==1 and np.allclose(decoded[0]['bbox'],[240,160,400,320])
    pink=np.zeros((40,40,3),np.uint8);pink[:]=(160,0,255)
    green=pink.copy();green[:]=(0,255,0)
    assert pink_fraction(pink,[0,0,40,40],c,cv2)>.99 and pink_fraction(green,[0,0,40,40],c,cv2)==0
    with tempfile.TemporaryDirectory() as tmp:
        fake=Path(tmp)/'fake.onnx';fake.write_bytes(b'corrupted')
        try:verify_model(fake,c['model_manifest'],320)
        except ValueError:pass
        else:raise AssertionError('model hash was not enforced')
    detector=BalloonDetector(c);timings=[];tp=fp=total=large_total=large_found=pink_total=pink_found=pink_pred=0;examples=[]
    paths=sorted((args.dataset/'images/test').glob('*.jpg'))
    for image_path in paths:
        frame=cv2.imdecode(np.fromfile(str(image_path),np.uint8),cv2.IMREAD_COLOR);h,w=frame.shape[:2];boxes=[]
        for row in (args.dataset/'labels/test'/(image_path.stem+'.txt')).read_text().splitlines():
            _,x,y,bw,bh=map(float,row.split());boxes.append([(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h])
        start=time.perf_counter();detections=detector.detect(frame);timings.append((time.perf_counter()-start)*1000)
        used=set();matches={}
        for d in sorted(detections,key=lambda a:-a['confidence']):
            candidates=[(iou(d['bbox'],box),i) for i,box in enumerate(boxes) if i not in used]
            score,index=max(candidates,default=(0,-1))
            if score>=.5:used.add(index);matches[index]=d;tp+=1
            else:fp+=1
            pink_pred+=int(d['pink_confirmed'])
        for i,box in enumerate(boxes):
            large=(box[2]-box[0])*(box[3]-box[1])/(w*h)>=.01;large_total+=int(large);large_found+=int(large and i in matches)
            is_pink=pink_fraction(frame,box,c,cv2)>=c['pink_min_fraction'];pink_total+=int(is_pink)
            pink_found+=int(is_pink and i in matches and matches[i]['pink_confirmed'])
        total+=len(boxes)
        if len(examples)<12:examples.append(dict(image_id=image_path.stem,ground_truth_boxes=len(boxes),detected=len(detections),pink_detected=sum(d['pink_confirmed'] for d in detections)))
    detector.close()
    # Same actual shipped model also loads through the CPU OpenCV fallback.
    cv_detector=BalloonDetector(dict(c,backend='opencv'));sample=cv2.imdecode(np.fromfile(str(paths[0]),np.uint8),cv2.IMREAD_COLOR);cv_detector.detect(sample);cv_detector.close()
    report=dict(model_sha256=hashlib.sha256(Path(c['model_path']).read_bytes()).hexdigest(),backend='ONNX Runtime CPU, 2 threads',
        device='Windows PC; not Jetson Nano',input_size=320,test_images=len(paths),ground_truth_boxes=total,
        confidence=.35,iou_threshold=.5,true_positive_boxes=tp,false_positive_boxes=fp,
        precision=tp/max(1,tp+fp),recall=tp/max(1,total),large_boxes_area_at_least_1pct=large_total,large_box_recall=large_found/max(1,large_total),
        pink_colour_proxy_ground_truth_boxes=pink_total,pink_colour_proxy_matches=pink_found,pink_detections=pink_pred,
        mean_inference_ms=round(statistics.mean(timings[5:]),2),p95_inference_ms=round(sorted(timings[5:])[int(.95*len(timings[5:]))],2),
        checks=dict(decoder_geometry=True,nms=True,pink_green_filter=True,model_hash=True,opencv_fallback_loaded=True),
        examples=examples,actual_competition_test=False,jetson_benchmark=False,
        limitation='Public balloon images. Pink subset is an HSV proxy, not independent human colour labels. No no-balloon marine negative set; false-positive rate in water scenes is not established.')
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
