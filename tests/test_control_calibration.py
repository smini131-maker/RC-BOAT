"""Real conversion/service/safety code with virtual clocks, no ROS or motor I/O."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.control_config import (RC_DEFAULTS,OUTPUT_DEFAULTS,validate_rc,validate_cruise,
    load_output,map_axis,normalized,rc_valid,neutral)
import test_failsafe_v218 as base
import test_ground_continuity_v2111 as harness


class MappingTests(unittest.TestCase):
    def test_exact_requested_integer_references(self):
        for value,expected in ((1004,4900),(1620,6000),(1985,7300)):
            self.assertEqual(map_axis(value,RC_DEFAULTS['steering'],4900,6000,7300),expected)
        for value,expected in ((1118,5800),(1499,6450),(1881,7397)):
            self.assertEqual(map_axis(value,RC_DEFAULTS['throttle'],5800,6450,7397),expected)

    def test_yaml_and_shared_defaults_do_not_drift(self):
        import re
        source=(ROOT/'catkin_ws/src/rcboat_ros/config/boat.yaml').read_text(encoding='utf-8')
        section=source.split('rc_input_calibration:\n',1)[1].split('cruise_pwm:',1)[0]
        for name,axis in RC_DEFAULTS.items():
            block=section.split('  '+name+':\n',1)[1].split('\n  throttle:',1)[0]
            for key,value in axis.items():
                actual=float(re.search(r'^    '+key+r':\s*([0-9.]+)',block,re.M).group(1))
                self.assertEqual(actual,value,(name,key))
        import xml.etree.ElementTree as ET
        version=(ROOT/'VERSION').read_text().strip()
        self.assertEqual(ET.parse(ROOT/'catkin_ws/src/rcboat_ros/package.xml').findtext('version'),version)
        gui_versions=(ROOT/'windows_gui/rcboat_gui/__init__.py').read_text(encoding='utf-8')
        self.assertIn(f'JETSON_VERSION = "{version}"',gui_versions)
        for filename in ['catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py',
                         'catkin_ws/src/rcboat_ros/nodes/ground_test_logger_node.py']:
            self.assertIn('"'+version+'"',(ROOT/filename).read_text(encoding='utf-8'))

    def test_measured_neutral_jitter_is_exactly_output_neutral(self):
        for name,band,out in [('steering',range(1616,1625),(4900,6000,7300)),
                              ('throttle',range(1496,1503),(5800,6450,7397))]:
            for value in band:self.assertEqual(map_axis(value,RC_DEFAULTS[name],*out),out[1])
        for value in range(1470,1531):
            self.assertTrue(neutral(value,RC_DEFAULTS['throttle']))

    def test_asymmetric_halves_and_measured_endpoint_jitter(self):
        for name,limits,bands in [('steering',(4900,6000,7300),[range(995,1014),range(1983,1987)]),
                                   ('throttle',(5800,6450,7397),[range(1115,1121),range(1879,1884)])]:
            axis=RC_DEFAULTS[name];low,center,high=limits
            self.assertEqual(map_axis(axis['min_us'],axis,*limits),low)
            self.assertEqual(map_axis(axis['max_us'],axis,*limits),high)
            for samples in bands:
                for value in samples:self.assertTrue(low<=map_axis(value,axis,*limits)<=high)
            left_edge=axis['center_us']-axis['deadband_us']
            right_edge=axis['center_us']+axis['deadband_us']
            self.assertEqual(map_axis((axis['min_us']+left_edge)/2,axis,*limits),round((low+center)/2))
            self.assertEqual(map_axis((axis['max_us']+right_edge)/2,axis,*limits),round((high+center)/2))
            # Whole envelope sweep catches sign reversals, overshoot and edge jumps.
            inputs=[axis['valid_min_us']+i/10 for i in range(int((axis['valid_max_us']-axis['valid_min_us'])*10)+1)]
            outputs=[map_axis(value,axis,*limits) for value in inputs]
            self.assertEqual(outputs,sorted(outputs))
            for edge in (left_edge,right_edge):
                self.assertAlmostEqual(normalized(edge-1e-6,axis),normalized(edge+1e-6,axis),places=7)
                self.assertLessEqual(abs(map_axis(edge-.001,axis,*limits)-map_axis(edge+.001,axis,*limits)),1)

    def test_invalid_config_and_signal_are_never_endpoint_saturation(self):
        for key,value in [('min_us',1620),('max_us',1620),('deadband_us',-1),
                          ('deadband_us',500),('valid_min_us',1100),('center_us',float('nan'))]:
            config=deepcopy(RC_DEFAULTS);config['steering'][key]=value
            with self.assertRaises(ValueError):validate_rc(config)
        with self.assertRaises(ValueError):load_output(lambda k,d: 2000 if k.endswith('steering_high') else d)
        for old_or_excessive in (7000,7398,7800):
            with self.assertRaises(ValueError):
                load_output(lambda k,d:old_or_excessive if k.endswith('throttle_forward_max') else d)
        good=dict(steering_us=1620,throttle_us=1499,monotonic=100)
        for update in [dict(steering_us=0),dict(throttle_us=2300),dict(steering_us=None),
                       dict(throttle_us=float('inf')),dict(monotonic=99.24),dict(monotonic=101),
                       dict(monotonic='100'),dict(valid=False),dict(valid='true')]:
            self.assertFalse(rc_valid(dict(good,**update),RC_DEFAULTS,100),update)
        self.assertFalse(rc_valid({'monotonic':100},RC_DEFAULTS,100))
        with self.assertRaises(ValueError):map_axis(2300,RC_DEFAULTS['throttle'],5800,6450,7397)


class ManualAndGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=base.load_supervisor()
    setUp=base.SupervisorTests.setUp
    refresh=base.SupervisorTests.refresh
    request=base.SupervisorTests.request
    assert_manual_stop=base.SupervisorTests.assert_manual_stop
    def test_manual_signal_loss_locks_then_requires_neutral_again(self):
        self.request('set_mode',mode='MANUAL')
        self.s._command();self.now+=.31;self.s.rc['monotonic']=self.now
        self.assertEqual(self.s._command(),('MANUAL',6000,6450,False))
        self.s.rc['throttle_us']=1883
        self.assertEqual(self.s._command()[2],7397)
        self.s.rc['throttle_us']=2300
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.s.rc['throttle_us']=1499
        self.assertTrue(self.s.manual_rearm_pending)
        self.s._command();self.now+=.31;self.s.rc['monotonic']=self.now
        self.assertEqual(self.s._command(),('MANUAL',6000,6450,False))

    def test_gestures_reachable_with_preserved_dwell_times(self):
        self.request('set_mode',mode='MANUAL')
        self.s.rc.update(steering_us=1983,throttle_us=1502)
        self.s._gestures(self.now)
        self.now+=2.99;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertEqual(self.s.mode,'MANUAL')
        self.now+=.02;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertEqual(self.s.mode,'AUTO_SAFE')
        self.s.rc['throttle_us']=1879;self.s._gestures(self.now)
        self.now+=.49;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertEqual(self.s.mode,'AUTO_SAFE')
        self.now+=.02;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertEqual(self.s.mode,'MANUAL');self.assertTrue(self.s.manual_rearm_pending)
        self.s.rc['throttle_us']=1496;self.s._gestures(self.now)
        self.now+=.29;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertTrue(self.s.manual_rearm_pending)
        self.now+=.02;self.s.rc['monotonic']=self.now;self.s._gestures(self.now)
        self.assertFalse(self.s.manual_rearm_pending)

    def test_bad_cruise_parameter_fails_safe(self):
        with patch.object(self.module.rospy,'get_param',side_effect=lambda k,d=None: 7800 if k.endswith('/cruise_pwm') else d):
            self.assert_manual_stop('CRUISE_PWM_INVALID')

    def test_mapping_does_not_use_nav_inversion(self):
        self.request('set_mode',mode='MANUAL');self.s.manual_rearm_pending=False
        self.s.rc.update(steering_us=1004,throttle_us=1115)
        self.assertEqual(self.s._command(),('MANUAL',4900,5800,False))
        self.s.rc.update(steering_us=1986,throttle_us=1883)
        self.assertEqual(self.s._command(),('MANUAL',7300,7397,False))

    def test_remote_navigation_and_ground_allow_max_and_reject_excess(self):
        self.assertTrue(self.request('set_mode',mode='REMOTE').success)
        self.assertTrue(self.request('set_remote_pwm',steering_pwm=6000,throttle_pwm=7397).success)
        self.assertEqual(self.s._command(),('REMOTE',6000,7397,False))
        for bad in (7398,7800,7397.1,True):
            self.assertFalse(self.request('set_remote_pwm',steering_pwm=6000,throttle_pwm=bad).success)
            self.assertEqual(self.s.remote['throttle_pwm'],7397)
        for mode in ('NAVIGATION','GROUND_TEST'):
            self.s.mode=mode;self.s.armed=True;self.s.ground_test_actuation_enabled=True
            self.refresh();self.s.nav['desired_throttle_pwm']=7397
            self.assertEqual(self.s._command()[2:],(7397,False))
            self.s.nav['desired_throttle_pwm']=7398
            self.assert_manual_stop('NAVIGATION_PWM_OUT_OF_RANGE')


class CruiseServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.module=harness.load_node('navigation_node',Path(self.tmp.name))
        self.module.rospy.set_param=lambda k,v:None
        self.nav=self.module.Navigation()

    def request(self,value):
        return self.nav.execute(types.SimpleNamespace(action='set_auto_cruise_pwm',arguments_json=json.dumps({'value':value})))

    def test_all_grid_values_and_rejections_without_partial_mutation(self):
        for value in list(range(6480,7391,10))+[7397]:
            answer=self.request(value);self.assertTrue(answer.success)
            self.assertEqual(json.loads(answer.response_json)['value'],value)
        for value in (True,None,'6650',6650.0,6470,7398,7800,6651,float('nan')):
            before=dict(self.nav.config)
            with patch.object(self.module.rospy,'set_param') as mutate:
                self.assertFalse(self.request(value).success,value)
                mutate.assert_not_called()
            self.assertEqual(before,self.nav.config)

    def test_acknowledgement_and_event_preserve_previous_setting(self):
        answer=self.request(6660);ack=json.loads(answer.response_json)
        self.assertGreater(ack['cruise_applied_monotonic'],0)
        event=json.loads(self.nav.events.messages[-1])
        self.assertEqual(event['before'],{'value':6650})
        self.assertEqual(event['after']['value'],6660)

    def test_gateway_rejects_bad_value_before_service(self):
        bridge_module=harness.load_node('gui_bridge_node',Path(self.tmp.name))
        bridge=bridge_module.Bridge.__new__(bridge_module.Bridge);bridge.token=''
        with patch.object(bridge,'service') as call:
            for value in (7398,7800,6470,6651,True,'6650'):
                result=bridge.dispatch({'action':'set_auto_cruise_pwm','arguments':{'value':value}})
                self.assertFalse(result['success'])
            call.assert_not_called()

    def test_final_actuator_gate_preserves_lock_and_output_modes(self):
        # Loading the real actuator module does not construct/open an I2C driver.
        import importlib.util
        ros=self.module.rospy
        modules={'rospy':ros,'fcntl':types.ModuleType('fcntl'),
                 'std_msgs.msg':types.SimpleNamespace(String=str),
                 'rcboat_ros.msg':types.SimpleNamespace(ControlCommand=object)}
        spec=importlib.util.spec_from_file_location('test_actuator',ROOT/'catkin_ws/src/rcboat_ros/nodes/actuator_node.py')
        actuator_module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,modules):spec.loader.exec_module(actuator_module)
        actuator=actuator_module.Actuator.__new__(actuator_module.Actuator)
        actuator.lock=threading.RLock()
        actuator.last_at=100;actuator.output_calibration=dict(OUTPUT_DEFAULTS)
        for mode,source in [('MANUAL','MANUAL'),('AUTO','AUTO'),('NAVIGATION','NAVIGATION'),
                            ('GROUND_TEST','GROUND_TEST_NAVIGATION'),('BALLOON','BALLOON')]:
            actuator.last_message=types.SimpleNamespace(mode=mode,source=source,actuator_locked=True,
                                                        steering_pwm=6100,throttle_pwm=6660)
            self.assertEqual(actuator.resolve(100)[:2],(6000,6450))
            actuator.last_message.actuator_locked=False
            self.assertEqual(actuator.resolve(100)[:2],(6100,6660))
            self.assertEqual(actuator.resolve(100.76)[:2],(6000,6450))
            actuator.last_message.throttle_pwm=7397
            self.assertEqual(actuator.resolve(100)[:2],(6100,7397))
            for bad in (7398,7800):
                actuator.last_message.throttle_pwm=bad
                self.assertEqual(actuator.resolve(100)[:2],(6000,6450))
        actuator.last_message.mode='AUTO';actuator.last_message.source='AUTO'
        actuator.last_message.throttle_pwm=7398  # exceeds both cruise and physical bounds
        self.assertEqual(actuator.resolve(100)[:2],(6000,6450))
        actuator.last_message.throttle_pwm=6999  # in physical range, invalid cruise grid
        self.assertEqual(actuator.resolve(100),(6000,6450,'CRUISE_REJECTED'))
        actuator.last_message.throttle_pwm=6660
        with patch.object(ros,'get_param',side_effect=lambda k,d=None:7800 if k.endswith('/cruise_pwm') else d):
            self.assertEqual(actuator.resolve(100),(6000,6450,'CRUISE_REJECTED'))
        actuator.last_message.mode='NAVIGATION';actuator.last_message.source='NAVIGATION_GPS_GRACE'
        actuator.last_message.steering_pwm=6000;actuator.last_message.throttle_pwm=6650
        self.assertEqual(actuator.resolve(100),(6000,6650,'NAVIGATION_GPS_GRACE'))
        actuator.last_message.actuator_locked=True
        self.assertEqual(actuator.resolve(100)[:2],(6000,6450))
        actuator.last_message.actuator_locked=False;actuator.last_message.steering_pwm=6100
        self.assertEqual(actuator.resolve(100)[:2],(6000,6450))

    def test_logger_metadata_keeps_effective_input_and_output_separate(self):
        # Use the established logger fixture, which starts and samples a real logger.
        fixture=harness.LoggerContinuityTests()
        fixture.setUp()
        try:
            metadata=json.loads((fixture.logger.folder/'test_metadata.json').read_text())
            self.assertEqual(metadata['rc_input_calibration'],RC_DEFAULTS)
            self.assertEqual(metadata['pca_output_calibration'],OUTPUT_DEFAULTS)
        finally:fixture.doCleanups()

    def test_ground_logger_accepts_7397_and_invalidates_7398(self):
        fixture=harness.LoggerContinuityTests();fixture.setUp()
        try:
            fixture.logger.cache['actuator']['actual_throttle_pwm']=7397
            fixture.logger.sample()
            fixture.logger.cache['actuator']['actual_throttle_pwm']=7398
            fixture.logger.sample()
            fixture.logger.close()
            import csv
            with (fixture.folder/'ground_test.csv').open(encoding='utf-8-sig') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual([r['output_confirmation_valid'] for r in rows],['True','False'])
            # The same range is checked when a new ground recording starts.
            fixture.logger.cache['actuator']['actual_throttle_pwm']=7398
            with self.assertRaisesRegex(RuntimeError,'actuator command confirmation'):
                fixture.logger.start(['c'],'single_route','c',True)
            fixture.logger.cache['actuator']['actual_throttle_pwm']=7397
            fixture.logger.start(['c'],'single_route','c',True)
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
