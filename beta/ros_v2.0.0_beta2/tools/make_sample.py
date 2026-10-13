#!/usr/bin/env python3
"""SYNTHETIC sample fixture generation. NOT a measured ground test."""
import csv
import datetime as dt
import json
import pathlib
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.export import export_experiment
from rcboat_ros.path_tracking import RouteManager,navigation_command,meters
from rcboat_ros.common import SAFE_STEERING,SAFE_THROTTLE
from rcboat_ros.gps_mix import MixedGpsParser

p=ROOT/'samples/synthetic_experiment_20261013_212000'
(p/'raw').mkdir(parents=True,exist_ok=True)
routes_file=ROOT/'catkin_ws/src/rcboat_ros/config/routes.json'
route=p/'routes.json';route.write_text(routes_file.read_text(),encoding='utf-8')
rm=RouteManager(route);rm.select('training_right')
start=dt.datetime(2026,10,13,12,20,tzinfo=dt.timezone.utc)
config={'steering_center':6000,'steering_low':4900,'steering_high':7300,'throttle_stop':6450,'cruise_pwm':6650,'nav_invert_steering':True}
files=[
'index','timestamp','elapsed_time_s','latitude','longitude','utm_easting_m','utm_northing_m',
'heading_deg','target_heading_deg','heading_error_deg','speed_mps','desired_steering_pwm','desired_rudder_angle_deg',
'desired_throttle_pwm','actual_steering_pwm','actual_throttle_pwm','selected_route_id','active_route_id',
'target_waypoint_index','distance_to_waypoint_m','cross_track_error_m','multipath_candidate_id','multipath_switch',
'gps_fix','rtk_state','satellites','hdop','hacc_m','cno_dbhz','gps_update_monotonic',
'previous_route_id','new_route_id','switch_event_timestamp']
events=[]
with (p/'raw/path_tracking.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=files);writer.writeheader()
    for i in range(220):
        t=i*.25
        # Trip: initially follow RIGHT then gradually cross to CENTER, then remain nearby.
        if t<=15:
            lat=35.00005+.00010*t/15
            lon=129.0+.0003*t/15
        elif t<=36:
            lat=35.00015
            lon=129.0+.0003*(1-(t-15)/21)
        else:
            lat=35.00015+.00010*min((t-36)/18,1)
            lon=129.0
        lat+=.0000004*__import__('math').sin(t*.25)
        lon+=.0000004*__import__('math').sin(t*.33)
        heading=120 if t<16 else 265 if t<36 else 0
        gps={'latitude':lat,'longitude':lon,'heading_deg':heading}
        stat=rm.update((lat,lon),now=500+t)
        out=navigation_command(gps,stat,config,stopped_once=True)
        if stat['multipath_switch']:
            events.append({'type':'ROUTE_SWITCH','TimeStep':t,'previous_route':stat['previous_route'],
                           'candidate_route':stat['candidate_route_id'],'new_route':stat['active_route_id']})
        row=dict(index=i+1,timestamp=(start+dt.timedelta(seconds=t)).isoformat(timespec='milliseconds'),elapsed_time_s=t,
           latitude=lat,longitude=lon,utm_easting_m='',utm_northing_m='',heading_deg=heading,
           target_heading_deg=out['target_heading_deg'],heading_error_deg=out['heading_error_deg'],speed_mps=.75,
           desired_steering_pwm=out['desired_steering_pwm'],desired_rudder_angle_deg=out['desired_rudder_angle_deg'],
           desired_throttle_pwm=out['desired_throttle_pwm'],actual_steering_pwm=SAFE_STEERING,
           actual_throttle_pwm=SAFE_THROTTLE,selected_route_id=rm.selected,active_route_id=rm.active,
           target_waypoint_index=stat['target_waypoint_index'],distance_to_waypoint_m=stat['distance_to_waypoint_m'],
           cross_track_error_m=stat['cross_track_error_m'],multipath_candidate_id=stat['candidate_route_id'],
           multipath_switch=str(stat['multipath_switch']),gps_fix='True',rtk_state='RTK_FIXED' if t>=4 else 'RTK_FLOAT',
           satellites=18,hdop=1.1,hacc_m=.05,cno_dbhz=34,gps_update_monotonic=10000+t,
           previous_route_id=stat['previous_route'] if stat['multipath_switch'] else '',
           new_route_id=stat['active_route_id'] if stat['multipath_switch'] else '',
           switch_event_timestamp=(start+dt.timedelta(seconds=t)).isoformat(timespec='milliseconds') if stat['multipath_switch'] else '')
        writer.writerow(row)
(p/'raw/events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
info={'synthetic':True,'real_gps':False,'purpose':'CSV/QGIS/MATLAB schema verification only','version':'2.0.0-beta.2'}
(p/'experiment_info.json').write_text(json.dumps(info,indent=2))
summary=export_experiment(p,list(rm.routes.values()),ROOT/'matlab/analyze_path_tracking.m')
print('Synthetic fixture:',p,'events=',len(events),'summary=',summary)
