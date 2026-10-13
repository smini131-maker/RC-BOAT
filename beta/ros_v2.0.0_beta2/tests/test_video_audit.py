"""Ground GPS walking experiment/video requirements; offline tests only."""
import csv
import pathlib
import sys
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
sys.path.insert(0,str(ROOT/'tools'))
from rcboat_ros.export import export_experiment
from resample_route import resample
class VideoContract(unittest.TestCase):
    def test_resample_metadata_and_heading_wrap(self):
        p=[{'lat':35,'lon':129,'timestamp':'2026-10-13T19:20:00.000+09:00','heading_deg':350},
           {'lat':35,'lon':129.00003,'timestamp':'2026-10-13T19:20:03.000+09:00','heading_deg':10}]
        r=resample(p,1.0)
        self.assertGreater(len(r),3)
        self.assertTrue(all('timestamp' in x and 'heading_deg' in x for x in r))
        self.assertTrue(all(x['heading_deg']<30 or x['heading_deg']>330 for x in r))
    def test_export_excludes_nofix_and_adds_qgis_script(self):
        with tempfile.TemporaryDirectory() as temp:
            p=pathlib.Path(temp);(p/'raw').mkdir()
            cols=['index','timestamp','elapsed_time_s','latitude','longitude','heading_deg','active_route_id','gps_fix','rtk_state','multipath_switch','speed_mps','cross_track_error_m','heading_error_deg']
            with (p/'raw/path_tracking.csv').open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,cols);w.writeheader()
                for i,fix,route,switch in [(1,True,'RIGHT',False),(2,False,'RIGHT',False),(3,True,'CENTER',True)]:
                    w.writerow(dict(index=i,timestamp='2026-10-14T00:00:00+09:00',elapsed_time_s=(i-1)*.25,latitude=35,longitude=129,heading_deg=0,active_route_id=route,gps_fix=fix,rtk_state='RTK_FIXED',multipath_switch=switch,speed_mps=.6,cross_track_error_m=0,heading_error_deg=0))
            result=export_experiment(p,[{'id':'training_left','name':'LEFT','waypoints':[{'lat':35,'lon':129}]}],ROOT/'matlab/analyze_path_tracking.m')
            with (p/'qgis/actual_track.csv').open(encoding='utf-8',newline='') as f:actual=list(csv.DictReader(f))
            self.assertEqual(len(actual),2)
            self.assertEqual(result['Multi_Path_Switch_Count'],1)
            self.assertTrue((p/'qgis/setup_qgis_layers.py').is_file())
    def test_route_switch_marker_and_lock_are_present(self):
        script=(ROOT/'catkin_ws/src/rcboat_ros/nodes/ground_test_logger_node.py').read_text()
        self.assertIn('or self.pending_switch',script)
        self.assertIn('actuator neutral command confirmation missing or stale',script)
    def test_qgis_helper_deployed_with_ros_package(self):
        runner=(ROOT/'tools/windows/runner.ps1').read_text()
        self.assertIn("'matlab','qgis','tools'",runner)

    def test_plot_and_qgis_specs(self):
        m=(ROOT/'matlab/analyze_path_tracking.m').read_text()
        q=(ROOT/'qgis/setup_qgis_layers.py').read_text()
        for x in ('walkingReference_mps = 0.6','readtable','linkaxes','route_switch_timeline.png'):
            self.assertIn(x,m)
        for x in ('EPSG:4326','TimeStep','Index','target_left.csv','target_center.csv','target_right.csv'):
            self.assertIn(x,q)
if __name__=='__main__':unittest.main()
