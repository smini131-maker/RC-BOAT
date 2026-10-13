import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class StaticAudit(unittest.TestCase):
    def test_safe_ground_override_independent(self):
        s=(ROOT/'catkin_ws/src/rcboat_ros/nodes/safety_supervisor_node.py').read_text(encoding='utf-8')
        a=(ROOT/'catkin_ws/src/rcboat_ros/nodes/actuator_node.py').read_text(encoding='utf-8')
        self.assertIn("if self.mode=='GROUND_TEST':return 'GROUND_TEST',s,t,True",s)
        self.assertIn("msg.mode=='GROUND_TEST'",a)
        self.assertIn("msg.actuator_locked",a)
        self.assertIn("self.safe_write()",a)
        self.assertIn("propulsion_allowed',False",s)
        self.assertIn("propulsion_allowed',False",a)
    def test_no_legacy_change_in_package(self):
        self.assertFalse((ROOT/'jetson_backend').exists())
        self.assertFalse((ROOT/'rcboat.service').exists())
        config=(ROOT/'catkin_ws/src/rcboat_ros/config/boat.yaml').read_text(encoding='utf-8')
        self.assertIn('propulsion_allowed: false',config)
        self.assertIn('throttle_stop: 6450',config)
        self.assertIn('steering_center: 6000',config)
    def test_no_legacy_test_ui_files_in_new_package(self):
        pkg=ROOT/'catkin_ws/src/rcboat_ros'
        names='\n'.join(x.name.lower() for x in pkg.rglob('*'))
        self.assertNotIn('mock_hardware_node',names)
        self.assertNotIn('hil',names)
    def test_backend_unit_has_conflict(self):
        u=(ROOT/'systemd/rcboat_ros.service').read_text(encoding='utf-8')
        self.assertIn('Conflicts=rcboat.service',u)
        self.assertNotIn('WantedBy=graphical.target',u)
    def test_all_ground_columns(self):
        src=(ROOT/'catkin_ws/src/rcboat_ros/nodes/ground_test_logger_node.py').read_text(encoding='utf-8')
        for x in ('elapsed_time_s','utm_easting_m','multipath_candidate_id','hacc_m','cno_dbhz',
                  'actual_steering_pwm','desired_steering_pwm'):
            self.assertIn(x,src)

if __name__=='__main__':unittest.main()
