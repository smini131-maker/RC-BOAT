"""Completion is estimated from fresh camera observations; never latches E-STOP."""
import unittest
import test_balloon_tracking as base
from rcboat_ros.balloon_tracking import TargetTracker,TrackingController,validate_config


def near_box(edge=False):
    return dict(confidence=.95,pink_confirmed=True,bbox=[490,90,1430,990] if not edge else [1630,90,1910,990])


class CompletionTests(unittest.TestCase):
    def setUp(self):self.c=validate_config({});self.t=TargetTracker()
    def acquire(self,edge=False):
        for i in range(3):result=self.t.update([near_box(edge)],1920,1080,100+i*.1,self.c)
        self.assertTrue(result['acquired'])

    def test_near_disappearance_holds_then_estimates_pop_with_neutral_command(self):
        self.acquire()
        for at in [100.3,100.45]:
            target=self.t.update([],1920,1080,at,self.c)
            self.assertEqual(target['phase'],'POP_PENDING')
            command=TrackingController().command(target,at,at,self.c,7397,99.)
            self.assertTrue(command['valid']);self.assertEqual(command['desired_throttle_pwm'],6450)
            self.assertIsNone(command['completion_reason'])
        target=self.t.update([],1920,1080,100.61,self.c)
        self.assertEqual(target['phase'],'POP_ESTIMATED')
        command=TrackingController().command(target,100.61,100.61,self.c,7397,99.)
        self.assertEqual(command['completion_reason'],'BALLOON_POP_ESTIMATED')
        self.assertEqual((command['desired_steering_pwm'],command['desired_throttle_pwm']),(6000,6450))

    def test_reappearance_cancels_pending_pop_and_edge_departure_still_turns_back(self):
        self.acquire();self.t.update([],1920,1080,100.3,self.c)
        result=self.t.update([near_box()],1920,1080,100.4,self.c)
        self.assertEqual(result['phase'],'TRACKING');self.assertNotIn('completion_reason',result)
        self.t.reset();self.acquire(edge=True)
        result=self.t.update([],1920,1080,100.9,self.c)
        self.assertEqual(result['phase'],'TURN_BACK');self.assertNotIn('completion_reason',result)

    def test_stale_camera_cannot_request_completion_or_motion(self):
        self.acquire()
        for at in [100.3,100.45,100.61]:target=self.t.update([],1920,1080,at,self.c)
        command=TrackingController().command(target,100.61,103,self.c,7397,99.)
        self.assertFalse(command['valid']);self.assertNotIn('completion_reason',command)


class CompletionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=base.base.load_supervisor()
    setUp=base.BalloonSafetyTests.setUp
    refresh=base.BalloonSafetyTests.refresh
    request=base.BalloonSafetyTests.request
    assert_manual_stop=base.BalloonSafetyTests.assert_manual_stop
    ready=base.BalloonSafetyTests.ready
    def test_completion_requests_manual_without_latching_estop(self):
        self.ready();self.s.vision_desired.update(completion_reason='BALLOON_POP_ESTIMATED',desired_steering_pwm=6000,desired_throttle_pwm=6450)
        self.assert_manual_stop('BALLOON_POP_ESTIMATED');self.assertFalse(self.s.estop)

    def test_completion_from_old_session_or_non_neutral_output_is_rejected(self):
        self.ready();self.s.mode_since=self.now-3
        self.s.vision_desired.update(completion_reason='BALLOON_POP_ESTIMATED',tracking_session=self.now-4,desired_steering_pwm=6000,desired_throttle_pwm=6450)
        self.assertEqual(self.s._command()[1:], (6000,6450,True))
        self.assertEqual(self.s.mode, 'BALLOON');self.assertFalse(self.s.estop)
        self.refresh();self.ready();self.s.vision_desired.update(completion_reason='BALLOON_POP_ESTIMATED',desired_throttle_pwm=6650)
        self.assertEqual(self.s._command()[0],'BALLOON')

    def test_only_explicit_estop_latches_and_records_origin_time(self):
        self.assertTrue(self.request('estop',reason='MAINTENANCE_CHECK',origin='maintenance').success)
        self.assertTrue(self.s.estop);self.assertEqual(self.s.mode,'MANUAL')
        self.assertEqual(self.s.estop_reason,'MAINTENANCE_CHECK');self.assertEqual(self.s.estop_origin,'maintenance')
        self.assertTrue(self.s.estop_time_utc.endswith('Z'))
        self.assertFalse(self.request('set_mode',mode='BALLOON',armed=True).success)
        self.assertTrue(self.request('reset_estop').success);self.assertFalse(self.s.estop)
        self.assertEqual(self.s.mode,'MANUAL');self.assertFalse(self.s.armed)


if __name__=='__main__':unittest.main()
