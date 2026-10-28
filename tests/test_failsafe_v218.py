"""Exercise the real supervisor without ROS or physical motor writes."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.failsafe import ProgressMonitor


class Publisher:
    def __init__(self, *args, **kwargs):
        self.messages = []

    def publish(self, value):
        self.messages.append(value)


class Response:
    def __init__(self, success, response_json):
        self.success, self.response_json = success, response_json


def load_supervisor():
    rospy = types.ModuleType('rospy')
    rospy.Publisher = Publisher
    rospy.Subscriber = rospy.Service = lambda *a, **k: None
    rospy.get_param = lambda name, default=None: default
    modules = {'rospy': rospy}
    for name in ('std_msgs', 'std_msgs.msg', 'rcboat_ros.msg', 'rcboat_ros.srv'):
        modules[name] = types.ModuleType(name)
    modules['std_msgs.msg'].String = str
    modules['rcboat_ros.msg'].ControlCommand = object
    modules['rcboat_ros.srv'].Execute = object
    modules['rcboat_ros.srv'].ExecuteResponse = Response
    spec = importlib.util.spec_from_file_location('tested_supervisor', ROOT / 'catkin_ws/src/rcboat_ros/nodes/safety_supervisor_node.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class SupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_supervisor()

    def setUp(self):
        self.now = 100.0
        self.clock = patch.object(self.module.time, 'monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.s = self.module.Supervisor()
        self.s.mode = 'NAVIGATION'; self.s.armed = True
        self.refresh()

    def refresh(self):
        self.s.gps = dict(healthy=True, fix=True, latitude=35.0, longitude=129.0,
                          speed_mps=.6, last_valid_monotonic=self.now)
        self.s.link = dict(ssh_connected=True, monotonic=self.now)
        self.s.nav = dict(valid=True, monotonic=self.now, route_monotonic=self.now, desired_steering_pwm=6100,
                          desired_throttle_pwm=6650, route_complete=False)
        self.s.rc = dict(monotonic=self.now, steering_us=1640, throttle_us=1500)
        self.s.actuator = dict(command_applied=True, monotonic=self.now)

    def request(self, action, **args):
        return self.s.execute(types.SimpleNamespace(action=action, arguments_json=json.dumps(args)))

    def assert_manual_stop(self, reason):
        source, steer, throttle, locked = self.s._command()
        self.assertEqual(self.s.mode, 'MANUAL')
        self.assertFalse(self.s.armed)
        self.assertEqual((steer, throttle, locked), (6000, 6450, True))
        self.assertEqual(self.s.reason, reason)
        self.assertTrue(self.s.manual_rearm_pending)

    def test_healthy_navigation(self):
        self.assertEqual(self.s._command(), ('NAVIGATION', 6100, 6650, False))

    def test_ssh_loss_with_live_ros(self):
        self.s.link['ssh_connected'] = False
        self.assert_manual_stop('SSH_DISCONNECTED')

    def test_gui_crash_or_wifi_lease_expiry(self):
        self.s.link['monotonic'] = self.now - 5.01
        self.assert_manual_stop('GUI_LINK_TIMEOUT')

    def test_gps_receiver_loses_fix(self):
        self.s.gps['fix'] = False
        self.assert_manual_stop('GPS_INVALID_OR_STALE')

    def test_gps_publisher_dies_with_cached_healthy_true(self):
        self.s.gps['last_valid_monotonic'] = self.now - 2.01
        self.assert_manual_stop('GPS_INVALID_OR_STALE')

    def test_goal_arrival(self):
        self.s.nav['route_complete'] = True
        self.assert_manual_stop('TARGET_ARRIVED')

    def test_navigation_dies(self):
        self.s.nav['monotonic'] = self.now - .8
        self.assert_manual_stop('NAVIGATION_TIMEOUT')

    def test_actuator_fault_and_missing_status(self):
        self.s.actuator['command_applied'] = False
        self.assert_manual_stop('ACTUATOR_ERROR')
        self.s.mode = "NAVIGATION"; self.s.armed = True
        self.now += 2
        self.refresh(); self.s.actuator = {}
        self.assert_manual_stop('ACTUATOR_TIMEOUT')

    def test_route_publisher_dies(self):
        self.s.nav['route_monotonic'] = self.now - 1.1
        self.assert_manual_stop('ROUTE_TIMEOUT')

    def test_rc_input_lost_during_autonomy(self):
        self.s.rc['monotonic'] = self.now - 1
        self.assert_manual_stop('RC_INPUT_LOST')

    def test_gps_or_navigation_crash_does_not_kill_manual_nodes(self):
        import xml.etree.ElementTree as ET
        launch = ET.parse(ROOT / 'catkin_ws/src/rcboat_ros/launch/rcboat.launch')
        for node in launch.findall('node'):
            if node.get('name') in ('gps_node', 'route_manager_node', 'navigation_node', 'rc_input_node'):
                self.assertEqual(node.get('respawn'), 'true')
                self.assertNotEqual(node.get('required'), 'true')

    def test_explicit_propulsion_sensor_fault(self):
        self.s.propulsion = {'blocked': True}
        self.assert_manual_stop('PROPULSION_FAULT')

    def test_no_progress_dwell(self):
        self.s.gps['speed_mps'] = .01
        self.assertEqual(self.s._command()[0], 'NAVIGATION')
        self.now += 15.1
        self.refresh(); self.s.gps['speed_mps'] = .01
        self.assert_manual_stop('PROPULSION_NO_PROGRESS_SUSPECTED')

    def test_walking_test_excludes_no_progress_monitor(self):
        self.s.mode = 'GROUND_TEST'; self.s.ground_test_actuation_enabled = True
        for delta in (0, 20, 40):
            self.now = 100 + delta; self.refresh(); self.s.gps['speed_mps'] = 0
            self.assertEqual(self.s._command()[0], 'GROUND_TEST_NAVIGATION')

    def test_ground_test_fault_disables_output_opt_in(self):
        self.s.mode = 'GROUND_TEST'; self.s.ground_test_actuation_enabled = True
        self.s.gps['healthy'] = False
        self.assert_manual_stop('GPS_INVALID_OR_STALE')
        self.assertFalse(self.s.ground_test_actuation_enabled)

    def test_no_auto_resume_and_neutral_dwell_required(self):
        self.s.rc['throttle_us'] = 1800
        self.s.link['ssh_connected'] = False
        self.assert_manual_stop('SSH_DISCONNECTED')
        self.s.link['ssh_connected'] = True
        self.assertEqual(self.s._command()[2:], (6450, True))
        self.s.rc['throttle_us'] = 1500
        self.s._command()
        self.now += .31; self.s.rc['monotonic'] = self.now
        self.assertEqual(self.s._command()[0], 'MANUAL')
        self.s.rc['throttle_us'] = 1700
        self.assertGreater(self.s._command()[2], 6450)
        self.assertEqual(self.s.mode, 'MANUAL')

    def test_manual_works_without_gps_ssh_or_gateway(self):
        self.request('set_mode', mode='MANUAL')
        self.s.gps = {}; self.s.link = {}
        self.s._command(); self.now += .31; self.s.rc['monotonic'] = self.now
        self.s._command(); self.s.rc['throttle_us'] = 1700
        self.assertEqual(self.s._command()[0], 'MANUAL')

    def test_estop_never_allows_manual_throttle(self):
        self.assertTrue(self.request('estop').success)
        self.assertEqual(self.s.mode, 'MANUAL')
        self.s.rc['throttle_us'] = 1800
        self.assertEqual(self.s._command(), ('ESTOP', 6000, 6450, True))
        self.assertFalse(self.request('set_mode', mode='NAVIGATION', armed=True).success)
        self.assertTrue(self.request('reset_estop').success)
        self.assertTrue(self.s.manual_rearm_pending)
        self.assertEqual(self.s._command()[2:], (6450, True))

    def test_explicit_auto_arm_rejected_when_disconnected(self):
        self.s.link = {}
        self.assertFalse(self.request('set_mode', mode='NAVIGATION', armed=True).success)

    def test_remote_timeout_becomes_manual(self):
        self.s.mode = 'REMOTE'; self.s.remote_stamp = 0
        self.assert_manual_stop('REMOTE_TIMEOUT')

    def test_rc_gap_requires_neutral_again(self):
        self.request('set_mode', mode='MANUAL')
        self.s._command(); self.now += .31; self.s.rc['monotonic'] = self.now
        self.s._command()
        self.now += 1
        self.assertEqual(self.s._command()[2:], (6450, True))
        self.s.rc.update(monotonic=self.now, throttle_us=1800)
        self.assertEqual(self.s._command()[2:], (6450, True))


class ProgressTests(unittest.TestCase):
    def test_progress_or_speed_or_neutral_resets_the_timer(self):
        gps = dict(latitude=35, longitude=129, speed_mps=0)
        for change in ({'latitude': 35.0001}, {'speed_mps': .3}):
            monitor = ProgressMonitor()
            self.assertFalse(monitor.update(100, gps, 6650))
            self.assertFalse(monitor.update(116, dict(gps, **change), 6650))
        monitor = ProgressMonitor(); monitor.update(100, gps, 6650)
        self.assertFalse(monitor.update(116, gps, 6450))

    def test_unknown_speed_is_not_fabricated_zero(self):
        monitor = ProgressMonitor()
        for now in (100, 200):
            self.assertFalse(monitor.update(now, dict(latitude=35, longitude=129), 6650))


if __name__ == '__main__':
    unittest.main()
