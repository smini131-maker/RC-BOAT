import csv
import json
import pathlib
import struct
import sys
import tempfile
import time
import unittest

BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'catkin_ws/src/rcboat_ros/src'))
sys.path.insert(0,str(BASE/'tools'))
from rcboat_ros.common import SAFE_STEERING,SAFE_THROTTLE,gps_is_healthy,cno_quality
from rcboat_ros.path_tracking import RouteManager,navigation_command,meters,bearing,angle_error
from rcboat_ros.gps_mix import MixedGpsParser
from rcboat_ros.export import export_experiment
from resample_route import resample

class Tests(unittest.TestCase):
    def test_safe_constants(self):
        self.assertEqual((SAFE_STEERING,SAFE_THROTTLE),(6000,6450))
    def test_gps_health(self):
        now=time.monotonic()
        a={'fix':True,'latitude':35,'longitude':129,'last_valid_monotonic':now,'hdop':2}
        self.assertTrue(gps_is_healthy(a,now))
        for d in ({**a,'last_valid_monotonic':now-3},{**a,'hdop':4},{**a,'fix':False},
                  {**a,'latitude':float('nan')}):
            self.assertFalse(gps_is_healthy(d,now))
        self.assertEqual(cno_quality(32),'GOOD')
        self.assertEqual(cno_quality(26),'WARNING')
        self.assertEqual(cno_quality(24),'BAD')
    def test_angle_and_distance(self):
        self.assertEqual(angle_error(1,359),2)
        self.assertEqual(angle_error(359,1),-2)
        self.assertGreater(meters((35,129),(35.00001,129)),1)
    def _manager(self,t):
        f=pathlib.Path(t)/'routes.json'
        f.write_text((BASE/'catkin_ws/src/rcboat_ros/config/routes.json').read_text(),encoding='utf-8')
        return RouteManager(f)
    def test_route_group_endpoints_and_persist(self):
        with tempfile.TemporaryDirectory() as t:
            r=self._manager(t)
            self.assertEqual(set(r.group()),{'training_left','training_center','training_right'})
            r.select('training_right')
            fresh=RouteManager(r.filename)
            self.assertEqual(fresh.selected,'training_right')
            fresh.routes['training_left']['waypoints'][0]['lon']+=0.001
            self.assertNotIn('training_left',fresh.group())
    def test_multipath_switch_requires_offroute_hold(self):
        with tempfile.TemporaryDirectory() as t:
            r=self._manager(t);r.select('training_right')
            center=(35.00015,129.0)
            before=r.update(center,now=100)
            self.assertFalse(before['multipath_switch'])
            middle=r.update(center,now=102)
            self.assertFalse(middle['multipath_switch'])
            after=r.update(center,now=103.1)
            self.assertTrue(after['multipath_switch'])
            self.assertEqual(after['active_route_id'],'training_center')
            self.assertEqual(r.event['previous_route'],'training_right')
            self.assertEqual(r.event['new_route'],'training_center')
    def test_record_metadata(self):
        with tempfile.TemporaryDirectory() as t:
            r=self._manager(t);r.record_start('Walking')
            self.assertTrue(r.record_point(35,129,heading=278.5,timestamp='2026-10-13T19:20:00.123+09:00'))
            self.assertTrue(r.record_point(35.00003,129,heading=279.0,timestamp='2026-10-13T19:20:03.123+09:00'))
            name=r.record_stop()
            saved=json.loads(r.filename.read_text())
            pts=next(x for x in saved['routes'] if x['id']==name)['waypoints']
            self.assertEqual(pts[0]['timestamp'],'2026-10-13T19:20:00.123+09:00')
            self.assertEqual(pts[0]['heading_deg'],278.5)
    def test_navigation_neutral_and_turn_band(self):
        c={'steering_center':6000,'steering_low':4900,'steering_high':7300,'throttle_stop':6450,'cruise_pwm':6650,'nav_invert_steering':True}
        a={'latitude':35,'longitude':129,'heading_deg':0}
        route={'target_lat':35.001,'target_lon':129,'route_complete':False}
        good=navigation_command(a,route,c)
        self.assertAlmostEqual(good['heading_error_deg'],0,places=1)
        self.assertEqual(good['desired_steering_pwm'],6000)
        self.assertEqual(good['desired_throttle_pwm'],6650)
        a['heading_deg']=180
        turn=navigation_command(a,route,c,stopped_once=False)
        self.assertEqual(turn['desired_throttle_pwm'],6450)
        turn2=navigation_command(a,route,c,stopped_once=True)
        self.assertEqual(turn2['desired_throttle_pwm'],6580)
    def test_resample(self):
        pts=[{'lat':35,'lon':129},{'lat':35.0001,'lon':129}]
        out=resample(pts,1)
        self.assertGreater(len(out),10)
        self.assertEqual(out[0],pts[0]);self.assertEqual(out[-1],pts[-1])
        self.assertTrue(all(.75<meters((a['lat'],a['lon']),(b['lat'],b['lon']))<1.1 for a,b in zip(out,out[1:-1])))
    def test_ubx_nav_pvt(self):
        parser=MixedGpsParser()
        data=bytearray(92)
        data[20]=3
        data[21]=1 | (2<<6)
        data[23]=15
        struct.pack_into('<i',data,24,1290000000)
        struct.pack_into('<i',data,28,350000000)
        struct.pack_into('<I',data,40,250) # 250 mm -> .25 m
        struct.pack_into('<i',data,60,500)
        struct.pack_into('<i',data,64,9000000)
        struct.pack_into('<H',data,76,110)
        body=b'\x01\x07'+len(data).to_bytes(2,'little')+data
        x=y=0
        for byte in body:x=(x+byte)&255;y=(y+x)&255
        parser.feed(b'\xb5\x62'+body+bytes([x,y]))
        v=parser.state
        self.assertEqual(v['rtk_state'],'RTK_FIXED')
        self.assertEqual(v['hacc_m'],.25)
        self.assertAlmostEqual(v['latitude'],35)
        self.assertAlmostEqual(v['longitude'],129)
    def test_export_csv(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t);(p/'raw').mkdir()
            with (p/'raw/path_tracking.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['index','elapsed_time_s','timestamp','latitude','longitude','heading_deg','active_route_id','gps_fix','speed_mps','heading_error_deg','cross_track_error_m','rtk_state','multipath_switch'])
                w.writeheader()
                for i in range(5):w.writerow(dict(index=i+1,elapsed_time_s=i/4,timestamp='2026-10-13T00:00:00+09:00',latitude=35+i*.00001,longitude=129,heading_deg=0,active_route_id='CENTER',gps_fix=True,speed_mps=.5,heading_error_deg=4,cross_track_error_m=.1,rtk_state='RTK_FIXED',multipath_switch='True' if i==3 else 'False'))
            rows=[{'id':'training_center','waypoints':[{'lat':35,'lon':129},{'lat':35.001,'lon':129}]}]
            res=export_experiment(p,rows)
            self.assertEqual(res['Samples'],5)
            self.assertEqual(res['Multi_Path_Switch_Count'],1)
            self.assertEqual(res['RTK_Fixed_Ratio'],1)
            with (p/'qgis/actual_track.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),5)
            with (p/'qgis/target_center.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)

if __name__=='__main__':unittest.main()
