"""Bounded navigation delay versus confirmed disconnection; no live I/O."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_failsafe_v218 as base
import test_ground_continuity_v2111 as harness
from rcboat_ros.gps_settings import load_hdop,save_hdop,validate_hdop


class NavigationDelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=base.load_supervisor()
    setUp=base.SupervisorTests.setUp
    refresh=base.SupervisorTests.refresh
    assert_manual_stop=base.SupervisorTests.assert_manual_stop

    def gap(self):
        self.s.gps.update(healthy=False,fix=False,data_validity='stale',transport_connected=True)
        self.s.nav['valid']=False

    def test_delay_runs_6650_until_new_fix_and_new_navigation(self):
        self.gap();original_armed=self.s.armed
        for delta in (0,1,4.9):
            self.now=100+delta;self.refresh();self.gap()
            self.assertEqual(self.s._command(),('NAVIGATION_GPS_GRACE',6000,6650,False))
        self.now=104.95;self.refresh()
        self.s.nav['gps_solution_monotonic']=90
        self.assertEqual(self.s._command()[0],'NAVIGATION_GPS_GRACE')
        self.s.nav['gps_solution_monotonic']=self.now
        self.assertEqual(self.s._command(),('NAVIGATION',6100,6650,False))
        self.assertEqual(self.s.armed,original_armed)
        self.assertIsNone(self.s.ground_gps_gap_since)
        self.assertEqual([json.loads(x)['type'] for x in self.s.events.messages],
                         ['NAVIGATION_GPS_GRACE_STARTED','NAVIGATION_GPS_GRACE_RECOVERED'])

    def test_confirmed_loss_and_other_faults_win_even_during_delay(self):
        for fault,reason in [(dict(transport_connected=False),'GPS_DISCONNECTED'),
                             (dict(data_validity='invalid',fix=False),'GPS_INVALID_OR_STALE')]:
            self.s.mode='NAVIGATION';self.s.armed=True;self.refresh();self.gap();self.s._command()
            self.s.gps.update(**fault)
            self.assert_manual_stop(reason)
        self.s.mode='NAVIGATION';self.s.armed=True;self.refresh();self.gap();self.s._command()
        self.s.link['ssh_connected']=False
        self.assert_manual_stop('SSH_DISCONNECTED')

    def test_expiry_does_not_resume_on_late_gps(self):
        self.gap();self.s._command();self.now+=5
        self.refresh();self.gap();self.assert_manual_stop('GPS_INVALID_OR_STALE')
        self.refresh()
        self.assertNotEqual(self.s._command()[0],'NAVIGATION')

    def test_not_armed_and_estop_cannot_start_grace_propulsion(self):
        self.s.armed=False;self.gap()
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.s.estop=True
        self.assertEqual(self.s._command()[1:],(6000,6450,True))

    def test_delayed_ssh_preserves_navigation_but_explicit_loss_stops(self):
        self.s.link.update(ssh_state='delayed',ssh_connected=True)
        self.assertEqual(self.s._command()[0],'NAVIGATION')
        self.s.link.update(ssh_state='disconnected',ssh_connected=False)
        self.assert_manual_stop('SSH_DISCONNECTED')

    def test_other_faults_and_goal_win_during_6650_grace(self):
        cases=[('rc','monotonic',99,'RC_INPUT_LOST'),
               ('actuator','command_applied',False,'ACTUATOR_ERROR'),
               ('nav','monotonic',99,'NAVIGATION_TIMEOUT'),
               ('nav','route_complete',True,'TARGET_ARRIVED'),
               ('link','monotonic',94,'GUI_LINK_TIMEOUT'),
               ('propulsion','fault',True,'PROPULSION_FAULT')]
        for source,key,value,reason in cases:
            self.s=self.module.Supervisor();self.s.mode='NAVIGATION';self.s.armed=True
            self.refresh();self.gap();self.s._command()
            getattr(self.s,source)[key]=value
            self.assert_manual_stop(reason)

    def test_explicit_nmea_invalid_fix_does_not_look_like_data_delay(self):
        from rcboat_ros.gps_mix import MixedGpsParser
        parser=MixedGpsParser()
        parser.state.update(fix=True,latitude=35,longitude=129,last_valid_monotonic=self.now)
        payload='GNRMC,120000.00,V,,,,,,,031126,,,N'
        checksum=0
        for char in payload:checksum^=ord(char)
        parser.feed(('$'+payload+'*%02X\r\n'%checksum).encode('ascii'))
        self.assertFalse(parser.state['fix'])


class HdopSettingsTests(unittest.TestCase):
    def test_local_persistence_validation_and_gateway_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'gps_settings.json'
            self.assertEqual(load_hdop(path),3.0)
            save_hdop(path,6.5);self.assertEqual(load_hdop(path),6.5)
            original=path.read_bytes()
            for value in (float('nan'),float('inf'),True,'4',None,0.4,20.1):
                with self.assertRaises(ValueError):save_hdop(path,value)
                self.assertEqual(original,path.read_bytes())
            module=harness.load_node('gui_bridge_node',root)
            module.rospy.set_param=lambda *args:None
            bridge=module.Bridge.__new__(module.Bridge)
            bridge.token='';bridge.events=base.Publisher();bridge.gps_settings_path=path
            bridge.gps_settings={'navigation_max_hdop':6.5}
            response=bridge.dispatch(dict(action='set_gps_settings',arguments={'navigation_max_hdop':7.0}))
            self.assertTrue(response['success'])
            self.assertEqual(response['response']['navigation_max_hdop'],7.0)
            self.assertGreater(response['response']['applied_monotonic'],0)
            self.assertEqual(load_hdop(path),7.0)  # restart loads the saved local setting
            for value in (None,False,30):
                self.assertFalse(bridge.dispatch(dict(action='set_gps_settings',arguments={'navigation_max_hdop':value}))['success'])
            self.assertEqual(load_hdop(path),7.0)


if __name__=='__main__':unittest.main()
