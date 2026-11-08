"""Controlled native-pixel benchmark; no image here is a measured-distance test.

Held-out photographic balloon cutouts are downsampled onto procedural backgrounds.
The four combinations isolate model fine-tuning from native-ROI inference. Colour
labels are an HSV proxy. Results cannot establish 100m detection or sea false alarms.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_detector import BalloonDetector,pink_fraction
from rcboat_ros.balloon_tracking import validate_config,TargetTracker


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def sources(dataset,count):
    config=validate_config({});result=[]
    for path in sorted((dataset/'images/test').glob('*.jpg')):
        image=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2]
        labels=dataset/'labels/test'/(path.stem+'.txt')
        for line in labels.read_text().splitlines():
            _,x,y,bw,bh=map(float,line.split());box=[(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h]
            if min(bw*w,bh*h)<24 or pink_fraction(image,box,config,cv2)<.3:continue
            x1,y1=max(0,int(box[0])-3),max(0,int(box[1])-3)
            x2,y2=min(w,math.ceil(box[2])+3),min(h,math.ceil(box[3])+3)
            result.append(dict(source_id=path.stem,patch=image[y1:y2,x1:x2],
                               box=[box[0]-x1,box[1]-y1,box[2]-x1,box[3]-y1]))
            break  # One positive per source image, not many near-identical boxes.
        if len(result)>=count:break
    if len(result)<count:raise ValueError('not enough held-out pink-proxy source images')
    return result


def scene(source,pixels,seed,negative=False):
    rng=random.Random(seed)
    # Explicitly synthetic background; not a substitute for real sea/hull negatives.
    image=np.empty((1080,1920,3),np.uint8)
    image[:430]=(155,139,122);image[430:]=(100,72,50)
    for _ in range(90):
        y=rng.randrange(440,1080);x=rng.randrange(1920)
        cv2.line(image,(x,y),(min(1919,x+rng.randrange(10,100)),y),tuple(rng.randrange(70,155) for _ in range(3)),1)
    for _ in range(3):
        x,y=rng.randrange(30,1850),rng.randrange(50,1000)
        cv2.rectangle(image,(x,y),(x+rng.randrange(8,35),y+rng.randrange(3,7)),(160,0,255),-1)
    if negative:return image,None
    b=source['box'];factor=pixels/min(b[2]-b[0],b[3]-b[1]);patch=source['patch']
    resized=cv2.resize(patch,(max(1,round(patch.shape[1]*factor)),max(1,round(patch.shape[0]*factor))),interpolation=cv2.INTER_AREA)
    x=rng.randrange(20,max(21,1900-resized.shape[1]));y=rng.randrange(450,max(451,1040-resized.shape[0]))
    image[y:y+resized.shape[0],x:x+resized.shape[1]]=resized
    box=[b[0]*factor+x,b[1]*factor+y,b[2]*factor+x,b[3]*factor+y]
    return image,box


def sequence(detector,frame,box,frames):
    detector.reset_search();tracker=TargetTracker();hit=False;acquired=False;first=None;timings=[];false_frames=0
    for i in range(frames):
        start=time.perf_counter();detections=detector.detect(frame);timings.append((time.perf_counter()-start)*1000)
        pink=[d for d in detections if d['pink_confirmed']]
        hit=hit or any(box is not None and iou(d['bbox'],box)>=.3 for d in pink)
        false_frames+=int(any(box is None or iou(d['bbox'],box)<.3 for d in pink))
        target=tracker.update(detections,frame.shape[1],frame.shape[0],100+i*.25,detector.config)
        matches=box is not None and target.get('bbox') and iou(target['bbox'],box)>=.3
        if target.get('acquired') and not target.get('predicted') and (matches or box is None):
            acquired=True
            if first is None:first=i+1
    return dict(detected=bool(hit),acquired=acquired,first_acquisition_frame=first,
                inference_ms=timings,false_pink_frames=false_frames,frames=frames)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sources',type=int,default=40)
    args=p.parse_args();cv2.setNumThreads(2)
    originals=sources(args.dataset,args.sources)
    detectors={}
    for name,folder,roi in [('baseline_global',args.baseline,False),('baseline_roi',args.baseline,True),
                             ('candidate_global',args.candidate,False),('candidate_roi',args.candidate,True)]:
        c=validate_config(dict(model_path=str(folder/'balloon_yolov8n.onnx'),model_manifest=str(folder/'model_manifest.json'),
                               backend='onnxruntime',long_range_enabled=roi))
        detectors[name]=BalloonDetector(c)
    rows=[]
    try:
        for index,source in enumerate(originals):
            for pixels in (8,12,16,24,32):
                image,box=scene(source,pixels,2400+index*100+pixels)
                results={name:sequence(d,image,box,6) for name,d in detectors.items()}
                rows.append(dict(source_id=source['source_id'],source_min_span_px=pixels,negative=False,results=results))
            if index%5==0:print('BENCHMARK %d/%d sources'%(index+1,len(originals)),flush=True)
        for index in range(30):
            image,box=scene(None,0,9900+index,negative=True)
            rows.append(dict(source_id='procedural_negative_%03d'%index,negative=True,
                             results={name:sequence(d,image,box,6) for name,d in detectors.items()}))
    finally:
        for d in detectors.values():d.close()
    summary={}
    for name in detectors:
        positive=[r for r in rows if not r['negative']];negative=[r for r in rows if r['negative']]
        times=[v for r in rows for v in r['results'][name]['inference_ms']]
        summary[name]=dict(detection_sequences=sum(r['results'][name]['detected'] for r in positive),
            acquisition_sequences=sum(r['results'][name]['acquired'] for r in positive),positive_sequences=len(positive),
            negative_acquisitions=sum(r['results'][name]['acquired'] for r in negative),negative_sequences=len(negative),
            mean_inference_ms=round(statistics.mean(times),2),p95_inference_ms=round(sorted(times)[int(.95*len(times))],2),
            bins={str(px):dict(detected=sum(r['results'][name]['detected'] for r in positive if r['source_min_span_px']==px),
                              acquired=sum(r['results'][name]['acquired'] for r in positive if r['source_min_span_px']==px),count=len(originals)) for px in (8,12,16,24,32)})
    report=dict(kind='controlled_native_pixel_scale_benchmark',device='Windows PC CPU; not Jetson',
                source_originals=len(originals),frames_per_sequence=6,association_clock='simulated 4Hz',
                ground_truth_iou=.3,pink_ground_truth='HSV proxy, not human colour labels',summary=summary,cases=rows,
                actual_competition_test=False,measured_distance_validation=False,
                real_100m_images=0,limitation='Photographic held-out cutouts on procedural backgrounds; not a measured 100m or real maritime false-positive benchmark')
    report.update(confirmation_policy='All four variants use the same native-pixel strip veto; baseline denotes old weights, not unmodified old application',
        negative_sequence_role='Procedural development checks used while designing the strip veto; not independent real maritime validation',
        candidate_sha256=hashlib.sha256((args.candidate/'balloon_yolov8n.onnx').read_bytes()).hexdigest(),
        baseline_sha256=hashlib.sha256((args.baseline/'balloon_yolov8n.onnx').read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
