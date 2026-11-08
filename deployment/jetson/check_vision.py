#!/usr/bin/env python3
"""Model/camera diagnostic; does not publish commands or open any actuator."""
import argparse,json,platform,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import validate_config
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--camera-type',choices=['auto','usb','csi'],default='auto')
    parser.add_argument('--source',default='/dev/video0');parser.add_argument('--sensor-id',type=int,default=0)
    parser.add_argument('--backend',choices=['auto','onnxruntime','opencv','tensorrt'],default='auto');args=parser.parse_args()
    import cv2,numpy as np
    from rcboat_ros.balloon_detector import BalloonDetector
    from rcboat_ros.camera_io import open_camera
    c=validate_config(dict(camera_type=args.camera_type,camera_source=args.source,csi_sensor_id=args.sensor_id,backend=args.backend,
        model_path=str(ROOT/'models/balloon_yolov8n.onnx'),model_manifest=str(ROOT/'models/model_manifest.json')))
    detector=BalloonDetector(c);cap=None;timings=[];count=0
    try:
        if args.live:cap,source,live=open_camera(c,cv2)
        else:source='zero-frame benchmark (not a detection accuracy test)';live=False
        actual_shape=None
        for i in range(20):
            if cap is not None:
                ok,frame=cap.read()
                if not ok:raise RuntimeError('camera read failed')
            else:frame=np.zeros((c['height'],c['width'],3),np.uint8)
            actual_shape=list(frame.shape[:2])
            start=time.monotonic();detections=detector.detect(frame);timings.append((time.monotonic()-start)*1000)
            count+=sum(d['pink_confirmed'] for d in detections)
        report=dict(python=platform.python_version(),machine=platform.machine(),opencv=cv2.__version__,backend=detector.backend_name,
            numpy=np.__version__,source=source,live_source=live,frames=len(timings),mean_inference_ms=round(statistics.mean(timings),2),
            p95_inference_ms=round(sorted(timings)[-2],2),pink_detections=count,actuator_access=False,
            actual_frame_height_width=actual_shape,requested_frame_height_width=[c['height'],c['width']],
            requested_resolution_met=actual_shape==[c['height'],c['width']],detector_view=detector.last_view,
            range_validation='not_field_validated')
        print(json.dumps(report,indent=2))
    finally:
        if cap is not None:cap.release()
        detector.close()
if __name__=='__main__':main()
