#!/usr/bin/env python3
"""Capture native camera evidence only; never publish or send actuator commands."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import validate_config
from rcboat_ros.camera_io import open_camera
from rcboat_ros.long_range import expected_diameter_px


def backend_state():
    try:
        request={'action':'status','arguments':{}}
        token=os.getenv('RCBOAT_GATEWAY_TOKEN','')
        if token:request['token']=token
        with socket.create_connection(('127.0.0.1',8765),timeout=2) as connection:
            connection.settimeout(2);connection.sendall((json.dumps(request)+'\n').encode())
            raw=b''
            while not raw.endswith(b'\n') and len(raw)<8_000_000:
                block=connection.recv(65536)
                if not block:break
                raw+=block
        response=json.loads(raw)
        if not response.get('success'):raise ValueError(response.get('error','gateway rejected status'))
        telemetry=response.get('telemetry',{})
        if telemetry.get('vision',{}).get('enabled'):raise ValueError('GUI에서 카메라를 끈 뒤 원본 녹화를 실행하세요')
        safety=telemetry.get('safety',{})
        if safety.get('armed') or safety.get('actuator_locked') is not True:
            raise ValueError('GUI에서 비상정지로 출력을 잠근 뒤 원본 녹화를 실행하세요')
        return dict(backend_online=True,version=response.get('version'),actuator_locked=True)
    except (OSError,ValueError) as exc:
        if isinstance(exc,ValueError):raise
        return dict(backend_online=False,safety_state='unknown',note='Camera-only tool; no actuator access')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--distance-m',type=float,required=True)
    p.add_argument('--diameter-m',type=float)
    p.add_argument('--seconds',type=float,default=20)
    p.add_argument('--camera-type',choices=['auto','usb','csi'])
    p.add_argument('--source')
    p.add_argument('--sensor-id',type=int)
    p.add_argument('--output',type=Path,default=Path('~/rcboat_ros_data/vision_validation'))
    args=p.parse_args()
    if not 1<=args.distance_m<=500 or not 1<=args.seconds<=120 or args.diameter_m is not None and not .05<=args.diameter_m<=5:
        p.error('distance 1..500m; duration 1..120s; optional diameter .05..5m')
    import cv2
    path=Path('~/.rcboat/vision.json').expanduser()
    local=json.loads(path.read_text()) if path.is_file() else {}
    for arg,key in [('camera_type','camera_type'),('source','camera_source'),('sensor_id','csi_sensor_id')]:
        value=getattr(args,arg)
        if value is not None:local[key]=value
    c=validate_config(local)
    if c['camera_type'] not in ('auto','usb','csi'):raise ValueError('Field recording requires a local live USB/CSI camera')
    checked=backend_state()
    folder=args.output.expanduser()/('range_'+str(round(args.distance_m))+'m_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True,exist_ok=False)
    cap,kind,live=open_camera(c,cv2);frames=[];start=time.monotonic();last=0
    try:
        while time.monotonic()-start<args.seconds:
            ok,frame=cap.read()
            if not ok or frame is None:raise RuntimeError('camera read failed')
            now=time.monotonic()
            if now-last<.5:continue
            last=now;name='frame_%04d.jpg'%len(frames)
            ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,95])
            if not ok:raise RuntimeError('JPEG encoding failed')
            raw=encoded.tobytes();(folder/name).write_bytes(raw)
            frames.append(dict(file=name,utc=dt.datetime.now(dt.timezone.utc).isoformat(),elapsed_s=round(now-start,3),
                               width=frame.shape[1],height=frame.shape[0],sha256=hashlib.sha256(raw).hexdigest()))
    finally:cap.release()
    if not frames:raise RuntimeError('No frame captured')
    width=frames[0]['width']
    meta=dict(version=(ROOT/'VERSION').read_text().strip(),distance_m=args.distance_m,distance_source='operator_declared_not_sensor_measured',
              balloon_diameter_m=args.diameter_m,hfov_assumed_deg=c['camera_hfov_deg'],source=kind,live_source=live,
              expected_diameter_px=expected_diameter_px(args.diameter_m,args.distance_m,width,c['camera_hfov_deg']) if args.diameter_m else None,
              backend=checked,frames=frames,actuator_access=False,detection_accuracy_validated=False,
              instructions='Annotate the real balloon boxes before calculating detection recall or accepting 100m tracking.')
    (folder/'capture_metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    archive=folder.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):z.writestr(folder.name+'/'+f.name,f.read_bytes())
    print('CAMERA EVIDENCE SAVED '+str(archive))
    print('No motor commands were issued. Distance is operator-declared; accuracy not yet validated.')


if __name__=='__main__':main()
