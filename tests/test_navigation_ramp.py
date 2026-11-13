"""Navigation demand ramp and real safety arbitration; virtual time, no motor I/O."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_failsafe_v218 as base
import test_ground_continuity_v2111 as harness
from rcboat_ros.control_config import CRUISE_MAX,NavigationThrottleRamp,NAV_RAMP_RATE


class RampMathTests(unittest.TestCase):
    def test_120_pwm_per_second_and_7842_ceiling(self):
        self.assertEqual(NAV_RAMP_RATE,120.0)
        ramp=NavigationThrottleRamp()
        self.assertEqual(ramp.update(CRUISE_MAX,100),6650)
        self.assertEqual(ramp.update(CRUISE_MAX,101),6770)
        self.assertLess(ramp.update(CRUISE_MAX,104.25),CRUISE_MAX)
        self.assertEqual(ramp.update(CRUISE_MAX,100+(CRUISE_MAX-6650)/NAV_RAMP_RATE),CRUISE_MAX)
        self.assertEqual(ramp.update(CRUISE_MAX,110),CRUISE_MAX)

    def test_6900_at_2_083_seconds_and_4hz_ticks(self):
        ramp=NavigationThrottleRamp()
        values=[ramp.update(6900,100+i*.25) for i in range(10)]
        self.assertEqual(values,[6650,6680,6710,6740,6770,6800,6830,6860,6890,6900])
        self.assertEqual(ramp.update(6900,110),6900)

    def test_elapsed_time_not_loop_count(self):
        ramp=NavigationThrottleRamp();self.assertEqual(ramp.update(6900,100),6650)
        self.assertEqual(ramp.update(6900,100),6650)
        self.assertEqual(ramp.update(6900,100.9),6758)
        self.assertEqual(ramp.update(6900,100+250/120),6900)

    def test_targets_low_default_intermediate_and_maximum(self):
        for target in (6480,6650,6750,7397,7840,CRUISE_MAX):
            ramp=NavigationThrottleRamp()
            self.assertEqual(ramp.update(target,100),min(6650,target))
            duration=max(0,(target-6650)/NAV_RAMP_RATE)
            self.assertEqual(ramp.update(target,100+duration),target)
            self.assertEqual(ramp.update(target,110),target)
        with self.assertRaises(ValueError):ramp.update(CRUISE_MAX+1,111)

    def test_raise_from_current_lower_immediately_and_no_turn_rebound(self):
        ramp=NavigationThrottleRamp();ramp.update(7000,100)
        self.assertEqual(ramp.update(7000,100.6),6722)
        self.assertEqual(ramp.update(6900,100.9),6758)
        self.assertEqual(ramp.update(6680,100.9),6680)
        self.assertEqual(ramp.update(6450,101),6450)
        self.assertEqual(ramp.update(7000,101.25),6480)
        self.assertLessEqual(ramp.current,6450+NAV_RAMP_RATE*.25+1e-8)
        ramp.reset();self.assertEqual(ramp.update(7000,102),6650)

    def test_increase_target_after_reaching_old_target(self):
        ramp=NavigationThrottleRamp();ramp.update(6750,100)
        self.assertEqual(ramp.update(6750,101),6750)
        self.assertEqual(ramp.update(7000,101),6750)
        self.assertEqual(ramp.update(7000,101.25),6780)
        self.assertEqual(ramp.update(6700,101.25),6700)


class NavigationRampTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.module=harness.load_node('navigation_node',Path(self.tmp.name))
        self.module.rospy.set_param=lambda k,v:None
        self.module.rospy.logwarn=lambda *args:None
        self.now=100.0
        self.clock=patch.object(self.module.time,'monotonic',side_effect=lambda:self.now)
        self.clock.start();self.addCleanup(self.clock.stop)
        self.nav=self.module.Navigation()
        self.state=dict(mode='NAVIGATION',armed=True,estop=False,gps_grace_active=False,mode_since_monotonic=100)
        self.nav.update_safety(json.dumps(self.state))

    def output(self,demand=6900,**updates):
        self.nav.update_safety(json.dumps(self.state))
        return self.nav.apply_throttle_ramp(dict(valid=True,route_complete=False,
            desired_throttle_pwm=demand,**updates),self.now)

    def test_nav_only_and_start_reset_without_subroute_reset(self):
        self.assertEqual(self.output()['desired_throttle_pwm'],6650)
        self.now=100.75
        self.nav.route={'active_route_id':'other_subroute'}
        self.assertEqual(self.output()['desired_throttle_pwm'],6740)
        self.state['mode']='MANUAL';self.nav.update_safety(json.dumps(self.state))
        self.state.update(mode='NAVIGATION',mode_since_monotonic=100.8)
        self.now=100.8
        self.assertEqual(self.output()['desired_throttle_pwm'],6650)
        for mode in ('MANUAL','AUTO','AUTO_SAFE','GROUND_TEST','REMOTE'):
            self.state['mode']=mode
            out=self.output(7000)
            self.assertFalse(out['ramp_active']);self.assertIsNone(out['ramp_throttle_pwm'])
            self.assertEqual(out['desired_throttle_pwm'],7000)

    def test_fresh_safety_armed_valid_and_no_grace_required(self):
        for update in (dict(armed=False),dict(estop=True),dict(gps_grace_active=True)):
            self.state.update(update)
            self.assertFalse(self.output()['ramp_active'])
            self.state.update(armed=True,estop=False,gps_grace_active=False)
        self.now+=1
        out=self.nav.apply_throttle_ramp(dict(valid=True,route_complete=False,desired_throttle_pwm=6900),self.now)
        self.assertFalse(out['ramp_active'])
        self.assertIsNone(self.nav.throttle_ramp.current)

    def test_real_navigation_loop_preserves_turn_reduction_before_ramp(self):
        self.nav.config['cruise_pwm']=6900
        self.nav.gps=dict(healthy=True,heading_deg=0,last_valid_monotonic=100)
        self.nav.route=dict(monotonic=100,target_lat=35,active_route_id='center')
        demands=iter((6900,6600,6900))
        def calc(*args):
            return dict(heading_error_deg=40,initial_turn_pause_requested=False,
                        desired_throttle_pwm=next(demands),desired_steering_pwm=6000)
        def advance():
            self.now+=.25
            self.nav.route['monotonic']=self.now
            self.nav.update_safety(json.dumps(self.state))
        with patch.object(self.module,'navigation_command',side_effect=calc), \
             patch.object(self.module.rospy,'Rate',return_value=types.SimpleNamespace(sleep=advance),create=True), \
             patch.object(self.module.rospy,'is_shutdown',side_effect=[False,False,False,True],create=True):
            self.nav.run()
        rows=[json.loads(item) for item in self.nav.pub.messages]
        self.assertEqual([row['desired_throttle_pwm'] for row in rows],[6650,6600,6630])
        self.assertTrue(all(row['ramp_active'] for row in rows))
        self.assertEqual(rows[-1]['auto_cruise_pwm'],6900)


class RampSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=base.load_supervisor()
    setUp=base.SupervisorTests.setUp
    refresh=base.SupervisorTests.refresh
    request=base.SupervisorTests.request
    assert_manual_stop=base.SupervisorTests.assert_manual_stop

    def test_reapplying_navigation_while_armed_keeps_applied_pwm(self):
        session=self.s.mode_since
        self.now+=3
        self.refresh()
        self.s.nav.update(route_id='new_route',desired_throttle_pwm=7000)
        self.assertTrue(self.request('set_mode',mode='NAVIGATION',armed=True).success)
        self.assertEqual(self.s.mode_since,session)
        self.assertEqual(self.s._command(),('NAVIGATION',6100,7000,False))
        self.assertTrue(self.request('set_mode',mode='AUTO_SAFE').success)
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.now+=.1
        self.refresh()
        self.assertTrue(self.request('set_mode',mode='NAVIGATION',armed=True).success)
        self.assertNotEqual(self.s.mode_since,session)
        self.assertEqual(self.s._command()[1:],(6000,6450,True))

    def test_pre_start_or_previous_session_high_command_is_locked(self):
        self.s.nav.update(desired_throttle_pwm=7000,ramp_active=False)
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.s.nav.update(ramp_active=True,ramp_session_monotonic=99)
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.s.nav.update(ramp_session_monotonic=self.s.mode_since,desired_throttle_pwm=6650)
        self.assertEqual(self.s._command(),('NAVIGATION',6100,6650,False))

    def test_fault_stop_is_immediate_even_while_ramp_high(self):
        for field,key,value,reason in [('gps','transport_connected',False,'GPS_DISCONNECTED'),
                ('gps','fix',False,'GPS_INVALID_OR_STALE'),('link','ssh_connected',False,'SSH_DISCONNECTED'),
                ('nav','route_complete',True,'TARGET_ARRIVED'),('rc','monotonic',99,'RC_INPUT_LOST')]:
            self.s.mode='NAVIGATION';self.s.armed=True;self.refresh()
            self.s.nav['desired_throttle_pwm']=6900
            getattr(self.s,field)[key]=value
            self.assert_manual_stop(reason)
        self.s.mode='NAVIGATION';self.s.armed=True;self.refresh();self.s.estop=True
        self.assertEqual(self.s._command()[1:],(6000,6450,True))


if __name__=='__main__':unittest.main()
