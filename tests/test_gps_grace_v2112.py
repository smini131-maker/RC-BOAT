"""Bounded GPS grace on the real supervisor; outputs are never sent to hardware."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_failsafe_v218 as base
import test_ground_continuity_v2111 as logger_tests


class GpsGraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = base.load_supervisor()

    setUp = base.SupervisorTests.setUp
    refresh = base.SupervisorTests.refresh
    request = base.SupervisorTests.request
    assert_manual_stop = base.SupervisorTests.assert_manual_stop

    def enter_gap(self):
        self.s.mode = 'GROUND_TEST'; self.s.ground_test_actuation_enabled = True
        self.s.gps.update(healthy=False,fix=False)
        self.s.nav['valid'] = False
        self.assertEqual(self.s._command(), ('GROUND_TEST_GPS_GRACE',6000,6450,True))
        self.assertEqual(self.s.mode, 'GROUND_TEST')

    def advance(self,seconds,gps_ok=False):
        self.now = 100 + seconds
        self.refresh()
        self.s.gps.update(healthy=gps_ok,fix=gps_ok)
        self.s.nav.update(valid=gps_ok,gps_solution_monotonic=self.now if gps_ok else None)

    def test_bad_fix_keeps_ground_mode_and_neutral_for_five_seconds(self):
        self.enter_gap()
        for age in (.1,1,3,4.99):
            self.advance(age)
            self.assertEqual(self.s._command(), ('GROUND_TEST_GPS_GRACE',6000,6450,True))
            self.assertAlmostEqual(self.s.ground_gps_grace_remaining_s,5-age)
            self.assertTrue(self.s.ground_test_actuation_enabled)

    def test_recovery_inside_deadline_resumes_without_a_new_start(self):
        self.enter_gap(); self.advance(2,True)
        self.assertEqual(self.s._command(),('GROUND_TEST_NAVIGATION',6100,6650,False))
        self.assertIsNone(self.s.ground_gps_gap_since)
        self.assertEqual(self.s.reason,'')
        kinds=[json.loads(item)['type'] for item in self.s.events.messages]
        self.assertEqual(kinds,['GROUND_TEST_GPS_GRACE_STARTED','GROUND_TEST_GPS_GRACE_RECOVERED'])

    def test_cached_navigation_cannot_resume_after_recovery(self):
        self.enter_gap(); self.advance(2,True)
        self.s.nav['gps_solution_monotonic']=99.5
        self.assertEqual(self.s._command(),('GROUND_TEST_GPS_GRACE',6000,6450,True))
        self.s.nav['gps_solution_monotonic']=self.now
        self.assertEqual(self.s._command()[0],'GROUND_TEST_NAVIGATION')

    def test_flapping_fix_does_not_extend_the_original_deadline(self):
        self.enter_gap(); self.advance(3,True)
        self.s.nav['valid']=False
        self.s._command()
        self.advance(4,False); self.s._command()
        self.advance(5,False)
        self.assert_manual_stop('GPS_INVALID_OR_STALE')
        self.advance(5.1,True)
        self.assertNotEqual(self.s._command()[0],'GROUND_TEST_NAVIGATION')

    def test_unrecovered_navigation_at_deadline_is_manual(self):
        self.enter_gap();self.advance(5,True);self.s.nav['valid']=False
        self.assert_manual_stop('NAVIGATION_INVALID')

    def test_stale_publisher_also_enters_grace(self):
        self.s.mode='GROUND_TEST';self.s.ground_test_actuation_enabled=True
        self.s.gps['last_valid_monotonic']=self.now-2.01
        self.assertEqual(self.s._command()[0],'GROUND_TEST_GPS_GRACE')

    def test_other_faults_interrupt_grace_immediately(self):
        for fault in ('link','rc','nav','route','actuator','propulsion','goal','estop','manual'):
            with self.subTest(fault=fault):
                self.now=100;self.refresh();self.s.estop=False;self.s.propulsion={}
                self.enter_gap()
                expected={'link':'GUI_LINK_TIMEOUT','rc':'RC_INPUT_LOST','nav':'NAVIGATION_TIMEOUT',
                    'route':'ROUTE_TIMEOUT','actuator':'ACTUATOR_ERROR','propulsion':'PROPULSION_FAULT',
                    'goal':'TARGET_ARRIVED'}
                if fault=='link':self.s.link['monotonic']=94
                elif fault=='rc':self.s.rc['monotonic']=99
                elif fault=='nav':self.s.nav['monotonic']=99
                elif fault=='route':self.s.nav['route_monotonic']=98
                elif fault=='actuator':self.s.actuator['command_applied']=False
                elif fault=='propulsion':self.s.propulsion={'blocked':True}
                elif fault=='goal':self.s.nav['route_complete']=True
                elif fault=='estop':self.request('estop')
                elif fault=='manual':self.request('set_mode',mode='MANUAL')
                if fault in expected:self.assert_manual_stop(expected[fault])
                else:self.assertEqual(self.s.mode,'MANUAL')
                self.assertIsNone(self.s.ground_gps_gap_since)

    def test_grace_is_ground_only_and_requires_a_valid_start(self):
        for mode in ('AUTO','NAVIGATION','REMOTE'):
            self.refresh();self.s.mode=mode;self.s.gps['fix']=False
            self.assert_manual_stop('GPS_INVALID_OR_STALE')
        self.assertFalse(self.request('set_mode',mode='GROUND_TEST').success)

    def test_disabled_grace_and_invalid_configuration(self):
        self.s.ground_gps_grace_s=0
        self.s.mode='GROUND_TEST';self.s.gps['fix']=False
        self.assert_manual_stop('GPS_INVALID_OR_STALE')
        for value in (float('nan'),float('inf'),-1,31):
            with patch.object(self.module.rospy,'get_param',return_value=value):
                with self.assertRaises(ValueError):self.module.Supervisor()


class GraceLoggerTests(unittest.TestCase):
    setUp=logger_tests.LoggerContinuityTests.setUp

    def test_grace_is_logged_as_a_pause_without_closing_recording(self):
        self.logger.cache['safety'].update(gps_grace_active=True,gps_grace_remaining_s=4.8)
        self.logger.sample()
        self.assertTrue(self.logger.output_paused)
        self.assertEqual(self.logger.pause_reason,'GROUND_TEST_GPS_GRACE')
        self.assertEqual(self.logger.state,'recording')
        self.assertEqual(self.logger.folder,self.folder)
        self.logger.cache['safety'].update(gps_grace_active=False,gps_grace_remaining_s=0)
        self.logger.sample()
        self.assertFalse(self.logger.output_paused)
        self.assertEqual(self.logger.count,2)


class NavigationProvenanceTests(unittest.TestCase):
    def test_navigation_result_keeps_the_fix_it_actually_used(self):
        with tempfile.TemporaryDirectory() as directory:
            module=logger_tests.load_node('navigation_node',Path(directory))
        nav=module.Navigation.__new__(module.Navigation)
        nav.config={'tracking_mode':'HEADING','target_speed_mps':.6,'cruise_pwm':6650}
        nav.gps={'healthy':True,'heading_deg':12,'last_valid_monotonic':100.0}
        nav.route={'monotonic':100.0,'target_lat':35,'active_route_id':'C'}
        nav.large_turn_seen=False;nav.paused_until=0;nav.pub=base.Publisher()
        def calculate(gps,route,config,seen):
            nav.gps=dict(gps,last_valid_monotonic=100.1)
            return {'heading_error_deg':0,'initial_turn_pause_requested':False}
        with patch.object(module.time,'monotonic',return_value=100.2), \
             patch.object(module,'navigation_command',side_effect=calculate), \
             patch.object(module.rospy,'Rate',return_value=types.SimpleNamespace(sleep=lambda:None),create=True), \
             patch.object(module.rospy,'is_shutdown',side_effect=[False,True],create=True):
            nav.run()
        result=json.loads(nav.pub.messages[-1])
        self.assertTrue(result['valid'])
        self.assertEqual(result['gps_solution_monotonic'],100.0)


if __name__=='__main__':unittest.main()
