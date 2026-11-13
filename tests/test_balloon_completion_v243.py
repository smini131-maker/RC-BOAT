"""Exercise close visual tracking and manual handoff without physical outputs."""
import unittest

import test_balloon_tracking as base
from rcboat_ros.balloon_tracking import TargetTracker, TrackingController, validate_config


def near_box(error=0.0):
    center_x = 960 * (1 + error)
    half_width = 140 if abs(error) > .45 else 470
    return dict(confidence=.95, pink_confirmed=True,
                bbox=[center_x-half_width, 90, center_x+half_width, 990])


class NearApproachTests(unittest.TestCase):
    def setUp(self):
        self.config = validate_config({})
        self.tracker = TargetTracker()
        self.controller = TrackingController()

    def update(self, detections, now, support=False):
        return self.tracker.update(detections, 1920, 1080, now, self.config,
                                   near_visual_support=support)

    def acquire(self, error=0.0):
        for i in range(3):
            result = self.update([near_box(error)], 100+i*.1)
        self.assertEqual(result['phase'], 'TRACKING')
        self.assertTrue(result['acquired'])
        return result

    def command(self, target, now, cruise_pwm=7397, frame_time=None):
        return self.controller.command(target, now if frame_time is None else frame_time,
                                       now, self.config, cruise_pwm, session=99.)

    def test_verified_close_colour_continues_with_last_direction_and_speed_limit(self):
        self.acquire(error=.2)
        for now in (100.3, 100.45, 100.61):
            with self.subTest(now=now):
                target = self.update([], now, support=True)
                self.assertEqual(target['phase'], 'NEAR_APPROACH')
                self.assertTrue(target['acquired'])
                self.assertAlmostEqual(target['center_x_normalized'], .2)
                command = self.command(target, now)
                self.assertTrue(command['valid'])
                self.assertLess(command['desired_steering_pwm'], 6000)
                self.assertGreater(command['desired_throttle_pwm'], 6450)
                self.assertLessEqual(command['desired_throttle_pwm'], 6650)
                self.assertIsNone(command.get('completion_reason'))
        self.assertEqual(self.command(target, 100.65, cruise_pwm=6480)['desired_throttle_pwm'], 6480)

    def test_close_fallback_reduces_fast_cruise_then_reacquisition_ramps(self):
        self.acquire()
        self.command(self.update([near_box()], 100.3), 100.3)
        for now in range(101, 108):
            tracking = self.update([near_box()], now)
            high = self.command(tracking, now)['desired_throttle_pwm']
        self.assertEqual(high, 7397)
        supported = self.update([], 107.1, support=True)
        self.assertEqual(self.command(supported, 107.1)['desired_throttle_pwm'], 6650)
        reacquired = self.update([near_box()], 107.2)
        self.assertEqual(reacquired['phase'], 'TRACKING')
        self.assertEqual(self.command(reacquired, 107.2)['desired_throttle_pwm'], 6662)

    def test_loss_of_colour_waits_in_neutral_without_estimating_a_pop(self):
        self.acquire()
        self.update([], 100.3, support=True)
        for now in (100.45, 100.61, 100.9, 101.1):
            with self.subTest(now=now):
                target = self.update([], now)
                self.assertEqual(target['phase'], 'NEAR_WAIT')
                command = self.command(target, now)
                self.assertEqual((command['desired_steering_pwm'], command['desired_throttle_pwm']), (6000, 6450))
                self.assertIsNone(command.get('completion_reason'))
        result = self.update([near_box()], 101.2)
        self.assertEqual(result['phase'], 'TRACKING')
        self.assertFalse(result['predicted'])

    def test_colour_alone_cannot_acquire_or_override_normal_edge_departure(self):
        target = self.update([], 100, support=True)
        self.assertEqual(target['phase'], 'NO_TARGET')
        self.assertFalse(self.command(target, 100)['valid'])
        self.acquire(error=.85)
        target = self.update([], 100.9, support=True)
        self.assertEqual(target['phase'], 'TURN_BACK')

    def test_near_colour_continuity_expires_without_a_new_neural_detection(self):
        self.acquire()
        for now in (100.5, 101.5, 102.5):
            self.assertIsNotNone(self.tracker.near_reference_box(now, self.config))
            self.assertEqual(self.update([], now, support=True)['phase'], 'NEAR_APPROACH')
        now = 102.5 + self.config['max_frame_age_s'] + .01
        self.assertIsNone(self.tracker.near_reference_box(now, self.config))
        self.assertEqual(self.update([], now, support=True)['phase'], 'NEAR_WAIT')
        self.assertEqual(self.update([near_box()], now+.1)['phase'], 'TRACKING')

    def test_stale_camera_cannot_keep_close_motion(self):
        self.acquire()
        target = self.update([], 100.3, support=True)
        command = self.command(target, 103, frame_time=100.3)
        self.assertFalse(command['valid'])
        self.assertEqual((command['desired_steering_pwm'], command['desired_throttle_pwm']), (6000, 6450))


class NearApproachSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = base.base.load_supervisor()

    setUp = base.BalloonSafetyTests.setUp
    refresh = base.BalloonSafetyTests.refresh
    request = base.BalloonSafetyTests.request
    assert_manual_stop = base.BalloonSafetyTests.assert_manual_stop
    ready = base.BalloonSafetyTests.ready

    def test_visual_wait_preserves_the_balloon_session_until_manual(self):
        self.ready()
        session = self.s.mode_since
        self.s.vision_desired.update(phase='NEAR_WAIT', desired_steering_pwm=6000, desired_throttle_pwm=6450)
        self.assertEqual(self.s._command()[1:3], (6000, 6450))
        self.assertEqual((self.s.mode, self.s.mode_since), ('BALLOON', session))
        self.assertTrue(self.request('set_mode', mode='MANUAL').success)
        self.assertEqual(self.s._command()[1:3], (6000, 6450))
        self.assertEqual(self.s.mode, 'MANUAL')
        self.assertFalse(self.s.estop)

    def test_confirmed_camera_loss_overrides_close_approach(self):
        self.ready()
        self.s.vision_desired.update(phase='NEAR_APPROACH')
        self.assertEqual(self.s._command(), ('BALLOON', 5900, 6650, False))
        self.s.vision.update(enabled=False)
        self.assert_manual_stop('BALLOON_TARGET_OR_CAMERA_LOST')

    def test_legacy_pop_metadata_does_not_force_manual(self):
        self.ready()
        self.s.vision_desired.update(completion_reason='BALLOON_POP_ESTIMATED',
                                     desired_steering_pwm=6000, desired_throttle_pwm=6450)
        self.assertEqual(self.s._command()[1:3], (6000, 6450))
        self.assertEqual(self.s.mode, 'BALLOON')
        self.assertFalse(self.s.estop)

    def test_only_explicit_estop_latches_and_records_origin_time(self):
        self.ready()
        self.s.vision_desired.update(phase='NEAR_APPROACH')
        self.assertTrue(self.request('estop', reason='MAINTENANCE_CHECK', origin='maintenance').success)
        self.assertEqual(self.s._command()[1:], (6000, 6450, True))
        self.assertTrue(self.s.estop)
        self.assertEqual(self.s.mode, 'MANUAL')
        self.assertEqual(self.s.estop_reason, 'MAINTENANCE_CHECK')
        self.assertEqual(self.s.estop_origin, 'maintenance')
        self.assertTrue(self.s.estop_time_utc.endswith('Z'))
        self.assertFalse(self.request('set_mode', mode='BALLOON', armed=True).success)
        self.assertTrue(self.request('reset_estop').success)
        self.assertFalse(self.s.estop)
        self.assertEqual(self.s.mode, 'MANUAL')
        self.assertFalse(self.s.armed)


if __name__ == '__main__':
    unittest.main()
