#!/usr/bin/env python3
"""Resample WGS84 v1.6.0 JSON route at ~1m intervals; preserve raw original."""
import argparse
import json
import math
import pathlib
from copy import deepcopy
from datetime import datetime

R=6371000.0

def interp(a,b,f):
    point={'lat': a['lat']+(b['lat']-a['lat'])*f,'lon':a['lon']+(b['lon']-a['lon'])*f}
    ha,hb=a.get('heading_deg'),b.get('heading_deg')
    if ha is not None and hb is not None:
        delta=(float(hb)-float(ha)+180)%360-180
        point['heading_deg']=(float(ha)+f*delta)%360
    if a.get('timestamp') and b.get('timestamp'):
        try:
            ta=datetime.fromisoformat(a['timestamp']); tb=datetime.fromisoformat(b['timestamp'])
            point['timestamp']=(ta+(tb-ta)*f).isoformat(timespec='milliseconds')
        except (ValueError,TypeError):
            pass  # Never fabricate a date from malformed legacy data
    return point

def meters(a,b):
    p,q=math.radians(a['lat']),math.radians(b['lat'])
    dp=q-p;dq=math.radians(b['lon']-a['lon'])
    return 2*R*math.asin(math.sqrt(min(1,math.sin(dp/2)**2+math.cos(p)*math.cos(q)*math.sin(dq/2)**2)))

def resample(points,spacing=1.0):
    if len(points)<2 or spacing<=0:raise ValueError('at least two waypoints and positive spacing required')
    cumulative=[0]
    for a,b in zip(points,points[1:]):cumulative.append(cumulative[-1]+meters(a,b))
    if cumulative[-1]==0:raise ValueError('zero route length')
    positions=[k*spacing for k in range(int(cumulative[-1]/spacing)+1)]
    if cumulative[-1]-positions[-1]>1e-6:positions.append(cumulative[-1])
    new=[];j=0
    for distance in positions:
        while j<len(points)-2 and distance>cumulative[j+1]:j+=1
        seg=cumulative[j+1]-cumulative[j]
        f=(distance-cumulative[j])/seg if seg else 0
        new.append(interp(points[j],points[j+1],min(1,max(0,f))))
    return new

def main():
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--spacing',type=float,default=1.0)
    args=p.parse_args()
    if pathlib.Path(args.input).resolve()==pathlib.Path(args.output).resolve():raise SystemExit('Output must be different from original input')
    source=json.loads(pathlib.Path(args.input).read_text(encoding='utf-8'))
    target=deepcopy(source)
    for r in target['routes']:
        r['waypoints']=resample(r['waypoints'],args.spacing)
        r['resampled_spacing_m']=args.spacing
    pathlib.Path(args.output).write_text(json.dumps(target,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
