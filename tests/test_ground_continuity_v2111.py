"""Real logger/supervisor lifecycle with injected sensor faults; no motor writes."""
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import test_failsafe_v218 as failsafe_tests

Publisher = failsafe_tests.Publisher
Response = failsafe_tests.Response

ROOT = Path(__file__).resolve().parents[1]


def load_node(name, root):
    ros = types.ModuleType('rospy')
    ros.Publisher = Publisher
    ros.Subscriber = ros.Service = ros.on_shutdown = lambda *a, **k: None
    ros.get_param = lambda key, default=None: str(root) if key == '/rcboat/ground_test_log_root' else default
    ros.logerr = lambda *a: None
    modules = {'rospy': ros}
    for key in ('std_msgs', 'std_msgs.msg', 'rcboat_ros.srv'):
        modules[key] = types.ModuleType(key)
    modules['std_msgs.msg'].String = str
    modules['rcboat_ros.srv'].Execute = object
    modules['rcboat_ros.srv'].ExecuteResponse = Response
    path = ROOT / 'catkin_ws/src/rcboat_ros/nodes' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class GroundSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = failsafe_tests.load_supervisor()

    setUp = failsafe_tests.SupervisorTests.setUp
    refresh = failsafe_tests.SupervisorTests.refresh
    request = failsafe_tests.SupervisorTests.request
    assert_manual_stop = failsafe_tests.SupervisorTests.assert_manual_stop

    def test_ground_ssh_loss_with_fresh_gateway_continues(self):
        self.s.mode = 'GROUND_TEST'; self.s.ground_test_actuation_enabled = True
        self.s.link['ssh_connected'] = False
        self.assertEqual(self.s._command(), ('GROUND_TEST_NAVIGATION', 6100, 6650, False))

    def test_ground_can_start_with_ssh_offline_and_gateway_alive(self):
        self.s.link['ssh_connected'] = False
        self.assertTrue(self.request('set_mode', mode='GROUND_TEST', ground_test_actuation_enabled=True).success)
        self.assertEqual(self.s._command()[0], 'GROUND_TEST_NAVIGATION')

    def test_ground_actual_gateway_loss_still_stops_and_never_auto_resumes(self):
        self.s.mode = 'GROUND_TEST'; self.s.ground_test_actuation_enabled = True
        self.s.link['monotonic'] = self.now - 5.1
        self.assert_manual_stop('GUI_LINK_TIMEOUT')
        self.refresh()
        self.assertNotEqual(self.s._command()[0], 'GROUND_TEST_NAVIGATION')
        self.assertTrue(self.request('set_mode', mode='GROUND_TEST', ground_test_actuation_enabled=True).success)
        self.assertEqual(self.s._command()[0], 'GROUND_TEST_NAVIGATION')

    def test_failure_event_contains_original_gps_and_lease_evidence(self):
        self.s.gps['fix'] = False
        self.assert_manual_stop('GPS_INVALID_OR_STALE')
        event = json.loads(self.s.events.messages[-1])
        self.assertFalse(event['gps_snapshot']['fix'])
        self.assertTrue(event['link_snapshot']['ssh_connected'])

    def test_estop_or_completed_route_cannot_resume(self):
        self.s.nav['route_complete'] = True
        self.assertFalse(self.request('set_mode', mode='GROUND_TEST', ground_test_actuation_enabled=True).success)
        self.s.nav['route_complete'] = False
        self.request('estop')
        self.assertFalse(self.request('set_mode', mode='GROUND_TEST', ground_test_actuation_enabled=True).success)


class LoggerContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module = load_node('ground_test_logger_node', self.root)
        self.now = 100.0
        clock = patch.object(self.module.time, 'monotonic', side_effect=lambda: self.now)
        clock.start(); self.addCleanup(clock.stop)
        self.logger = self.module.Logger()
        self.addCleanup(self.logger.close)
        self.logger.cache = {
            'route': {'routes': [{'id': 'c', 'name': 'C', 'waypoints': [
                {'lat': 35, 'lon': 129}, {'lat': 35.001, 'lon': 129}]}]},
            'gps': dict(healthy=True, fix=True, latitude=35, longitude=129,
                        last_valid_monotonic=self.now, last_update_monotonic=self.now),
            'safety': dict(mode='GROUND_TEST', ground_test_actuation_enabled=True,
                           actuator_locked=False, steering_pwm=6100, throttle_pwm=6650),
            'actuator': dict(command_applied=True, actual_steering_pwm=6100,
                             actual_throttle_pwm=6650, monotonic=self.now),
            'link': dict(ssh_connected=True, monotonic=self.now)}
        self.logger.start(['c'], 'single_route', 'c', True)
        self.folder = self.logger.folder

    def test_gps_fault_records_pause_and_explicit_resume_in_same_folder(self):
        self.logger.sample()
        self.logger.cache['safety'].update(mode='MANUAL', reason='GPS_INVALID_OR_STALE',
                                          ground_test_actuation_enabled=False)
        for index in range(1, 181):
            self.now = 100 + index * .25
            self.logger.cache['actuator'].update(monotonic=self.now,
                actual_steering_pwm=6000, actual_throttle_pwm=6450)
            self.logger.sample()
        self.assertEqual(self.logger.count, 181)
        self.assertEqual(self.logger.state, 'recording')
        self.assertEqual(self.logger.folder, self.folder)
        self.assertTrue(self.logger.output_paused)
        self.logger.cache['gps'].update(last_valid_monotonic=self.now, last_update_monotonic=self.now)
        self.logger.cache['safety'].update(mode='GROUND_TEST', reason='', ground_test_actuation_enabled=True)
        self.logger.sample()
        self.assertFalse(self.logger.output_paused)
        self.logger.close()
        with (self.folder / 'ground_test.csv').open(encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 182)
        self.assertEqual(rows[-2]['gps_healthy'], 'False')
        self.assertEqual(rows[-2]['gps_validity'], 'stale')
        self.assertEqual(rows[-2]['test_pause_reason'], 'GPS_INVALID_OR_STALE')
        events = [json.loads(line) for line in (self.folder / 'events.jsonl').read_text().splitlines()]
        kinds = [event['type'] for event in events]
        self.assertEqual(kinds.count('GROUND_TEST_OUTPUT_PAUSED'), 1)
        self.assertEqual(kinds.count('GROUND_TEST_OUTPUT_RESUMED'), 1)
        self.assertTrue((self.folder / 'export_manifest.json').exists())
        metadata = json.loads((self.folder / 'test_metadata.json').read_text())
        self.assertEqual(metadata['sample_count'], 182)
        self.assertEqual(metadata['final_state'], 'complete')

    def test_estop_arrival_link_loss_and_output_fault_remain_recordable(self):
        for reason in ('EMERGENCY_STOP', 'TARGET_ARRIVED', 'GUI_LINK_TIMEOUT', 'ACTUATOR_ERROR'):
            self.now += .25
            self.logger.cache['safety'].update(mode='MANUAL', reason=reason, ground_test_actuation_enabled=False)
            self.logger.cache['actuator']['command_applied'] = False
            self.logger.sample()
            self.assertTrue(self.logger.output_paused)
            self.assertEqual(self.logger.state, 'recording')
            self.assertEqual(self.logger.folder, self.folder)
        self.assertEqual(self.logger.count, 4)

    def test_gateway_resume_does_not_restart_route_or_logger(self):
        module = load_node('gui_bridge_node', self.root)
        bridge = module.Bridge.__new__(module.Bridge)
        bridge.cache = {'ground_test': dict(active=True, actuation_enabled=True, folder=str(self.folder))}
        calls = []
        bridge.service = lambda *args: calls.append(args) or {'mode': 'GROUND_TEST'}
        bridge.events = Publisher()
        bridge.ground_resume()
        self.assertEqual(calls, [('/rcboat/safety/execute', 'set_mode', {
            'mode': 'GROUND_TEST', 'ground_test_actuation_enabled': True})])
        bridge.cache['ground_test']['active'] = False
        with self.assertRaisesRegex(ValueError, 'no active'):
            bridge.ground_resume()


if __name__ == '__main__':
    unittest.main()
