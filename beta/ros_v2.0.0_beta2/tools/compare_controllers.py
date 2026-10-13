#!/usr/bin/env python3
"""Replay commands from one recorded GNSS track. NOT an actual tracking performance test."""
import sys,pathlib,argparse,csv
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.path_tracking import RouteManager,navigation_command,TRACKING_MODES
def replay(csvfile,routesfile,outfile):
    with open(csvfile,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    manager=RouteManager(routesfile)
    config=dict(steering_low=4900,steering_center=6000,steering_high=7300,
                throttle_stop=6450,cruise_pwm=6650,nav_invert_steering=True)
    out=[]
    for sample in rows:
        if str(sample.get('gps_fix','')).lower() not in ('true','1'):continue
        try:
            lat,lon,heading=float(sample['latitude']),float(sample['longitude']),float(sample['heading_deg'])
            speed=float(sample.get('speed_mps') or 0)
            t=float(sample['elapsed_time_s'])
        except (ValueError,TypeError,KeyError):continue
        selected=sample.get('active_route_id')
        if selected in manager.routes and selected!=manager.active:
            manager.active=selected;manager.next_index=0
        route=manager.update((lat,lon),now=100000+t)
        for mode in TRACKING_MODES:
            res=navigation_command(dict(latitude=lat,longitude=lon,heading_deg=heading,speed_mps=speed),
                                   route,{**config,'tracking_mode':mode},stopped_once=True)
            out.append(dict(elapsed_time_s=t,controller_mode=mode,
                            heading_error_deg=res['heading_error_deg'],
                            desired_steering_pwm=res['desired_steering_pwm'],
                            desired_throttle_pwm=res['desired_throttle_pwm'],
                            cross_track_error_m=res['cross_track_error_m'],
                            lookahead_m=res['lookahead_m']))
    if not out:raise ValueError('No valid samples')
    with open(outfile,'w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(out[0]));writer.writeheader();writer.writerows(out)
    return len(out)
if __name__=='__main__':
    a=argparse.ArgumentParser()
    for name in ('raw_csv','routes_json','output_csv'):a.add_argument(name)
    args=a.parse_args()
    print('Command replay rows:',replay(args.raw_csv,args.routes_json,args.output_csv))
    print('NOT an empirical navigation performance comparison.')
