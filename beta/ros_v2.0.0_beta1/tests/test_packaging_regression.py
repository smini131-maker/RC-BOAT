import ast
import csv
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.path_tracking import navigation_command

class PackagingRegression(unittest.TestCase):
    def test_legacy_untouched(self):
        self.assertFalse((ROOT/'jetson_backend').exists())
        self.assertFalse((ROOT/'rcboat.service').exists())
        self.assertTrue((ROOT/'systemd/rcboat_ros.service').exists())
        self.assertIn('Conflicts=rcboat.service',(ROOT/'systemd/rcboat_ros.service').read_text())
    def test_no_hil_files(self):
        pkg=ROOT/'catkin_ws/src/rcboat_ros'
        files=[x.as_posix().lower() for x in pkg.rglob('*') if x.is_file()]
        self.assertFalse(any('hil' in x for x in files))
    def test_cmd_always_pauses(self):
        for n in ('BUILD_ROS_GUI.cmd','UPLOAD_GITHUB.cmd','DEPLOY_ROS.cmd','INSTALL_ROS.cmd','USE_ROS.cmd','USE_DAEMON.cmd','CHECK_ROS.cmd','CHECK_BACKEND.cmd'):
            d=(ROOT/n).read_text()
            self.assertIn('pause',d,n)
            self.assertIn('runner.ps1',d,n)
            self.assertIn('RCBOAT_NO_PAUSE',d,n)
    def test_runner_logs(self):
        text=(ROOT/'tools/windows/runner.ps1').read_text()
        for required in ('Start-Transcript','Stop-Transcript','BUILD_GUI','UPLOAD_GITHUB','Get-FileHash','PyInstaller','--smoke-test','git','clone','push'):
            self.assertIn(required,text)
        self.assertIn('logs',text)
    def test_client_path_deployed(self):
        gui=(ROOT/'windows_gui/app.py').read_text()
        self.assertIn('/home/jetson/rcboat_ros_ws/deployment/jetson/bridge_client.py',gui)
        self.assertTrue((ROOT/'deployment/jetson/bridge_client.py').exists())
        self.assertIn('--smoke-test',gui)
    def test_python_parse(self):
        for p in list((ROOT/'catkin_ws').rglob('*.py'))+list((ROOT/'deployment').rglob('*.py'))+list((ROOT/'windows_gui').rglob('*.py'))+list((ROOT/'tools').rglob('*.py')):
            ast.parse(p.read_text(encoding='utf-8'),filename=str(p),feature_version=(3,8) if 'catkin_ws' in str(p) else None)
    def test_ros_check_nonzero_on_missing_topic(self):
        script=(ROOT/'deployment/jetson/check_ros.sh').read_text()
        self.assertIn('ROS HEALTH CHECK FAILED',script)
        self.assertIn('exit 1',script)
        self.assertIn('fail=1',script)
    def test_rudder_physical_sign_inverted_navigation(self):
        c=dict(steering_center=6000,steering_low=4900,steering_high=7300,throttle_stop=6450,cruise_pwm=6650,nav_invert_steering=True)
        a=dict(latitude=35.0,longitude=129.0,heading_deg=0)
        right={'target_lat':35.0001,'target_lon':129.0001,'route_complete':False}
        left={'target_lat':35.0001,'target_lon':128.9999,'route_complete':False}
        to_right=navigation_command(a,right,c)
        to_left=navigation_command(a,left,c)
        self.assertGreater(to_right['desired_rudder_angle_deg'],0)
        self.assertLess(to_left['desired_rudder_angle_deg'],0)
        self.assertLess(to_right['desired_steering_pwm'],6000) # calibration inverted for NAV only
    def test_ground_data_csv_has_lock_separate(self):
        with (ROOT/'sample_ground_test.csv').open(encoding='utf-8') as f:
            rows=list(csv.DictReader(f))
        self.assertGreater(len(rows),30)
        self.assertTrue(all(r['actual_steering_pwm']=='6000' and r['actual_throttle_pwm']=='6450' for r in rows))
        self.assertTrue(any(r['desired_steering_pwm'] not in ('','6000') for r in rows))
    def test_package_manual_contains_restrictions(self):
        t=(ROOT/'VIDEO_GROUND_TEST_따라하기_설명서.md').read_text()
        for x in ('TimeStep','VWorld','RTK_FIXED','Non-Disturbance','Disturbance','5300','6620','영상의 제목은 확인'):
            self.assertIn(x,t)
    def test_archive_workflow_root(self):
        workflow=(ROOT/'github_workflow/build-ros-v2-windows.yml').read_text()
        self.assertIn('setup-python@v5',workflow)
        self.assertIn('app.py --smoke-test',workflow)
        self.assertIn('windows-latest',workflow)

if __name__=='__main__':unittest.main()
