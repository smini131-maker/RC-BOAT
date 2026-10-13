#!/usr/bin/env python3
"""Actual 4Hz GNSS experiment logger, deliberately not hardware-owning."""
import csv
import datetime as dt
import json
import math
import os
import pathlib
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.srv import Execute,ExecuteResponse
from rcboat_ros.common import pack,unpack

FIELDS=['index','timestamp','elapsed_time_s','latitude','longitude','utm_easting_m','utm_northing_m',
        'heading_deg','target_heading_deg','heading_error_deg','speed_mps',
        'controller_mode','lookahead_m','cte_correction_deg','lookahead_target_lat','lookahead_target_lon',
        'desired_steering_pwm','desired_rudder_angle_deg','desired_throttle_pwm',
        'actual_steering_pwm','actual_throttle_pwm','selected_route_id','active_route_id',
        'target_waypoint_index','distance_to_waypoint_m','cross_track_error_m',
        'multipath_candidate_id','multipath_switch','gps_fix','rtk_state',
        'satellites','hdop','hacc_m','cno_dbhz','gps_update_monotonic',
        'previous_route_id','new_route_id','switch_event_timestamp']

class Logger:
    def __init__(self):
        self.cache={};self.folder=None;self.writer=None;self.f=None;self.events=None;self.count=0
        self.start_clock=0;self.last_switch=False;self.switch_count=0;self.previous_route='';self.pending_switch=False;self.pending_switch_event=None
        self.experiments=pathlib.Path(os.path.expanduser('~/rcboat_ros_data/experiments'))
        self.experiments.mkdir(parents=True,exist_ok=True)
        for topic,key in [('/rcboat/gps/status','gps'),('/rcboat/navigation/desired','nav'),('/rcboat/route/state','route'),
                          ('/rcboat/safety/state','safety'),('/rcboat/actuator/status','actuator'),('/rcboat/ntrip/status','ntrip')]:
            rospy.Subscriber(topic,String,lambda m,k=key:self.cache.__setitem__(k,unpack(m)))
        rospy.Subscriber('/rcboat/events',String,self.on_event)
        self.pub=rospy.Publisher('/rcboat/ground_test/status',String,queue_size=4)
        rospy.Service('/rcboat/logger/execute',Execute,self.execute)
        rospy.on_shutdown(self.close)
    def on_event(self,msg):
        event=unpack(msg)
        if self.events:
            event['wall_timestamp']=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='milliseconds')
            event['TimeStep']=round(time.monotonic()-self.start_clock,3)
            self.events.write(json.dumps(event,ensure_ascii=False)+'\n');self.events.flush()
            if event.get('type')=='ROUTE_SWITCH':
                self.switch_count+=1;self.pending_switch=True;self.pending_switch_event=dict(event)
    def execute(self,req):
        try:
            if req.action=='start':
                if self.folder:raise RuntimeError('ground test already recording')
                if self.cache.get('safety',{}).get('mode')!='GROUND_TEST':raise RuntimeError('GROUND_TEST safety mode must activate first')
                if not self.cache.get('safety',{}).get('actuator_locked',False):raise RuntimeError('GROUND_TEST safety lock not confirmed')
                # Command-applied telemetry is NOT physical motor feedback. It must be fresh and neutral.
                actuator=self.cache.get('actuator',{})
                if not (actuator.get('command_applied') is True and
                        actuator.get('actual_steering_pwm')==6000 and
                        actuator.get('actual_throttle_pwm')==6450 and
                        actuator.get('status') in ('LOCKED','BETA_LOCK') and
                        0 <= time.monotonic()-float(actuator.get('monotonic',0)) <= 1.0):
                    raise RuntimeError('actuator neutral command confirmation missing or stale; keep ESC power disconnected')
                if not self.cache.get('gps',{}).get('healthy',False):raise RuntimeError('real GPS FIX/health required to start walking test')
                self.start()
                result={'folder':str(self.folder)}
            elif req.action=='stop':
                if not self.folder:raise RuntimeError('not recording')
                folder=str(self.folder);self.close();result={'folder':folder,'samples':self.count}
            elif req.action=='status':result={'active':bool(self.folder),'folder':str(self.folder or ''),'samples':self.count}
            else:raise ValueError('unknown logger action')
            return ExecuteResponse(True,pack(**result))
        except Exception as exc:return ExecuteResponse(False,pack(error=str(exc)))
    def start(self):
        stamp=dt.datetime.now(dt.timezone.utc).astimezone().strftime('%Y%m%d_%H%M%S')
        folder=self.experiments/('experiment_'+stamp)
        suffix=1
        while folder.exists():suffix+=1;folder=self.experiments/('experiment_'+stamp+'_'+str(suffix))
        (folder/'raw').mkdir(parents=True)
        (folder/'qgis').mkdir()
        (folder/'plots').mkdir()
        self.folder=folder;self.start_clock=time.monotonic();self.count=0;self.switch_count=0;self.pending_switch=False;self.pending_switch_event=None
        self.f=(folder/'raw/path_tracking.csv').open('w',newline='',encoding='utf-8')
        self.writer=csv.DictWriter(self.f,fieldnames=FIELDS);self.writer.writeheader()
        self.events=(folder/'raw/events.jsonl').open('w',encoding='utf-8')
        (folder/'experiment_info.json').write_text(json.dumps({'version':'2.0.0-beta.2','source':'real GNSS only',
           'time_origin':dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),'units':'SI','hardware_lock':True},indent=2),encoding='utf-8')
        self.previous_route=self.cache.get('route',{}).get('active_route_id','')
    def sample(self):
        if not self.folder:return
        if self.cache.get('safety',{}).get('mode')!='GROUND_TEST' or not self.cache.get('safety',{}).get('actuator_locked',False):
            rospy.logerr('Logger forced stop: safety mode or lock lost');self.close();return
        act_state=self.cache.get('actuator',{})
        if not (act_state.get('command_applied') is True and
                act_state.get('actual_steering_pwm')==6000 and
                act_state.get('actual_throttle_pwm')==6450 and
                0 <= time.monotonic()-float(act_state.get('monotonic',0)) <= 1.0):
            rospy.logerr('Logger forced stop: actuator neutral command confirmation lost');self.close();return
        gps=self.cache.get('gps',{});nav=self.cache.get('nav',{});route=self.cache.get('route',{});act=self.cache.get('actuator',{})
        if not gps:return
        lat=gps.get('latitude');lon=gps.get('longitude')
        easting=northing=''
        if lat is not None and lon is not None:
            try:
                from pyproj import Transformer
                zone=max(1,min(60,int((float(lon)+180)//6+1)))
                epsg=(32600 if float(lat)>=0 else 32700)+zone
                easting,northing=Transformer.from_crs(4326,epsg,always_xy=True).transform(float(lon),float(lat))
            except Exception:pass
        now=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='milliseconds')
        self.count+=1
        r=dict(index=self.count,timestamp=now,elapsed_time_s=round(time.monotonic()-self.start_clock,3),
               latitude=lat,longitude=lon,utm_easting_m=easting,utm_northing_m=northing,
               heading_deg=gps.get('heading_deg'),target_heading_deg=nav.get('target_heading_deg'),heading_error_deg=nav.get('heading_error_deg'),
               speed_mps=gps.get('speed_mps'),controller_mode=nav.get('controller_mode','HEADING'),
               lookahead_m=nav.get('lookahead_m'),cte_correction_deg=nav.get('cte_correction_deg'),
               lookahead_target_lat=nav.get('lookahead_target_lat'),lookahead_target_lon=nav.get('lookahead_target_lon'),
               desired_steering_pwm=nav.get('desired_steering_pwm'),
               desired_rudder_angle_deg=nav.get('desired_rudder_angle_deg'),desired_throttle_pwm=nav.get('desired_throttle_pwm'),
               actual_steering_pwm=act.get('actual_steering_pwm'),actual_throttle_pwm=act.get('actual_throttle_pwm'),
               selected_route_id=route.get('selected_route_id'),active_route_id=route.get('active_route_id'),
               target_waypoint_index=route.get('target_waypoint_index'),distance_to_waypoint_m=route.get('distance_to_waypoint_m'),
               cross_track_error_m=route.get('cross_track_error_m'),multipath_candidate_id=route.get('candidate_route_id'),
               multipath_switch=bool(route.get('multipath_switch')) or self.pending_switch,
               gps_fix=bool(gps.get('fix')),rtk_state=gps.get('rtk_state'),satellites=gps.get('satellites'),
               hdop=gps.get('hdop'),hacc_m=gps.get('hacc_m'),cno_dbhz=gps.get('cno_dbhz'),gps_update_monotonic=gps.get('last_update_monotonic'),
               previous_route_id=(self.pending_switch_event or {}).get('previous_route',''),
               new_route_id=(self.pending_switch_event or {}).get('new_route',''),
               switch_event_timestamp=(self.pending_switch_event or {}).get('wall_timestamp',''))
        self.writer.writerow(r);self.f.flush()
        self.pending_switch=False;self.pending_switch_event=None
        self.pub.publish(pack(active=True,folder=str(self.folder),samples=self.count,actual_steering_pwm=act.get('actual_steering_pwm'),
                              actual_throttle_pwm=act.get('actual_throttle_pwm'),actuator_locked=self.cache.get('safety',{}).get('actuator_locked')))
    def close(self):
        if not self.folder:return
        folder=self.folder
        if self.f:self.f.close();self.f=None
        if self.events:self.events.close();self.events=None
        try:
            from rcboat_ros.export import export_experiment
            route=self.cache.get('route',{})
            matlab_src=os.path.expanduser('~/rcboat_ros_ws/matlab/analyze_path_tracking.m')
            export_experiment(folder,route.get('routes',[]),matlab_src)
            try:
                import subprocess
                analyzer=os.path.expanduser('~/rcboat_ros_ws/tools/analyze_csv.py')
                subprocess.run(['python3',analyzer,str(folder/'raw/path_tracking.csv')],timeout=60,check=True)
            except Exception as plot_error:rospy.logwarn('Optional PNG plot export skipped: %s',plot_error)
        except Exception as exc:rospy.logerr('experiment export failed: %s',exc)
        self.folder=None;self.writer=None
    def run(self):
        rate=rospy.Rate(rospy.get_param('/rcboat/log_rate_hz',4))
        while not rospy.is_shutdown():self.sample();rate.sleep()
if __name__=='__main__':rospy.init_node('ground_test_logger_node');Logger().run()
