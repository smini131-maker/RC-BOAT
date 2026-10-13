import pathlib,sys,unittest,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.path_tracking import TRACKING_MODES,tracking_heading,navigation_command,RouteManager,angle_error
CFG=dict(steering_low=4900,steering_center=6000,steering_high=7300,throttle_stop=6450,cruise_pwm=6650,nav_invert_steering=True)
ROUTE={'target_lat':35.0002,'target_lon':129,'route_complete':False,'path_waypoints':[{'lat':35,'lon':129},{'lat':35.0002,'lon':129}]}
GPS={'latitude':35.0001,'longitude':129,'heading_deg':0,'speed_mps':.6}
class Beta2(unittest.TestCase):
    def test_version(self):
        self.assertEqual((ROOT/'VERSION').read_text().strip(),'2.0.0-beta.2')
    def test_all_modes(self):
        self.assertEqual(set(TRACKING_MODES),{'HEADING','HEADING_CTE','LOS','PURE_PURSUIT'})
    def test_baseline(self):
        out=navigation_command(GPS,ROUTE,CFG)
        self.assertEqual((out['desired_steering_pwm'],out['desired_throttle_pwm']),(6000,6650))
    def test_lateral_sign(self):
        for mode in TRACKING_MODES[1:]:
            for lon,sign in ((128.99996,1),(129.00004,-1)):
                out=tracking_heading({**GPS,'longitude':lon},ROUTE,{**CFG,'tracking_mode':mode})
                self.assertGreater(sign*out['cross_track_error_m'],0,mode)
                self.assertGreater(sign*angle_error(out['target_heading_deg'],0),0,mode)
    def test_missing_route_fails_safe(self):
        with self.assertRaises(ValueError):
            tracking_heading(GPS,{'target_lat':35.0002,'target_lon':129},{'tracking_mode':'LOS'})
    def test_speed_not_armed(self):
        a=navigation_command({**GPS,'speed_mps':0},ROUTE,CFG)
        b=navigation_command({**GPS,'speed_mps':3},ROUTE,CFG)
        self.assertEqual(a['desired_throttle_pwm'],b['desired_throttle_pwm'])
    def test_bounded_speed(self):
        c={**CFG,'speed_feedback_enabled':True,'target_speed_mps':.6,'speed_kp_pwm_per_mps':1000}
        self.assertEqual(navigation_command({**GPS,'speed_mps':0},ROUTE,c)['desired_throttle_pwm'],6680)
        self.assertEqual(navigation_command({**GPS,'speed_mps':5},ROUTE,c)['desired_throttle_pwm'],6620)
    def test_explicit_nearest(self):
        with tempfile.TemporaryDirectory() as d:
            f=pathlib.Path(d)/'r.json'
            f.write_text((ROOT/'catkin_ws/src/rcboat_ros/config/routes.json').read_text())
            m=RouteManager(f);m.select('training_right')
            self.assertEqual(m.choose_nearest_group_route((35.00015,129)),'training_center')
            self.assertEqual(m.selected,'training_right')
    def test_default_lock(self):
        s=(ROOT/'catkin_ws/src/rcboat_ros/nodes/safety_supervisor_node.py').read_text()
        self.assertIn('EXPERIMENTAL_CONTROLLER_LOCK',s)
        c=(ROOT/'catkin_ws/src/rcboat_ros/config/boat.yaml').read_text()
        self.assertIn('propulsion_allowed: false',c)
        self.assertIn('experimental_nav_actuation_enabled: false',c)
if __name__=='__main__':unittest.main()
