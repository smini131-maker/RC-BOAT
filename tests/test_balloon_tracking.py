"""Virtual camera/GNSS trajectories and actual supervisor arbitration; no hardware writes."""
import math,json,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import (validate_config,TargetTracker,TrackingController,BearingEstimator,safe_balloon_output)
from rcboat_ros.control_config import NAV_RAMP_RATE
import test_failsafe_v218 as base

def detection(error=0,close=False,pink=True):
    cx=320*(1+error);w=200 if close else 80;h=300 if close else 100
    return dict(class_id=0,label='pink_balloon',confidence=.9,pink_fraction=.7,pink_confirmed=pink,bbox=[cx-w/2,240-h/2,cx+w/2,240+h/2])

class TrackerTests(unittest.TestCase):
    def setUp(self):self.c=validate_config({});self.t=TargetTracker()
    def acquire(self,close=False):
        for i in range(3):target=self.t.update([detection(.2,close)],640,480,100+i*.33,self.c)
        self.assertTrue(target['acquired']);return target
    def test_shape_and_pink_both_required_and_continuous_acquisition(self):
        target=self.t.update([detection(pink=False)],640,480,100,self.c)
        self.assertEqual(target['phase'],'NO_TARGET')
        self.assertFalse(self.t.update([detection()],640,480,100.1,self.c)['acquired'])
        self.acquire()
    def test_occlusion_predicts_without_stopping_then_reacquires(self):
        self.acquire();target=self.t.update([],640,480,101,self.c)
        self.assertEqual(target['phase'],'PREDICTING');self.assertTrue(target['acquired'])
        command=TrackingController().command(target,101,101,self.c)
        self.assertTrue(command['valid']);self.assertGreater(command['desired_throttle_pwm'],6450)
        target=self.t.update([detection(.3)],640,480,101.2,self.c)
        self.assertEqual(target['phase'],'TRACKING');self.assertFalse(target['predicted'])
    def test_passed_close_balloon_turns_back_and_timeout_is_bounded(self):
        self.acquire(close=True);target=self.t.update([],640,480,101.4,self.c)
        self.assertEqual(target['phase'],'TURN_BACK')
        command=TrackingController().command(target,101.4,101.4,self.c)
        self.assertLess(command['desired_steering_pwm'],6000);self.assertGreater(command['desired_throttle_pwm'],6450)
        target=self.t.update([],640,480,117,self.c)
        self.assertEqual(target['phase'],'LOST_TIMEOUT');self.assertFalse(target['acquired'])
    def test_far_target_predicts_then_tracks_departure_direction(self):
        self.acquire();target=self.t.update([],640,480,104,self.c)
        self.assertEqual(target['phase'],'SEARCHING');self.assertTrue(target['predicted'])
    def test_shared_speed_ramp_deceleration_reacceleration_and_restart(self):
        controller=TrackingController();target=self.acquire()
        target['center_x_normalized']=0
        self.assertEqual(controller.command(target,100,100,self.c,7397,100)['desired_throttle_pwm'],6650)
        self.assertEqual(controller.command(target,104.5,104.5,self.c,7397,100)['desired_throttle_pwm'],7397)
        target['center_x_normalized']=.9
        reduced=controller.command(target,104.6,104.6,self.c,7397,100)['desired_throttle_pwm']
        self.assertLess(reduced,7397)
        target['center_x_normalized']=0
        value=controller.command(target,104.85,104.85,self.c,7397,100)['desired_throttle_pwm']
        self.assertLessEqual(value,reduced+math.ceil(NAV_RAMP_RATE*.25)+1)
        self.assertEqual(controller.command(target,105,105,self.c,6480,100)['desired_throttle_pwm'],6480)
        self.assertEqual(controller.command(target,106,106,self.c,7397,106)['desired_throttle_pwm'],6650)
    def test_stale_camera_never_becomes_motion_prediction(self):
        target=self.acquire();out=TrackingController().command(target,100,103,self.c)
        self.assertFalse(out['valid']);self.assertEqual(out['desired_throttle_pwm'],6450)
    def test_bearing_triangulation_and_behind_target(self):
        estimator=BearingEstimator();c=self.c
        for i,y in enumerate((0,1,2,3,4)):
            now=100+i;gps=dict(fix=True,latitude=35+math.degrees(y/6371000),longitude=129,heading_deg=0,speed_mps=1,last_valid_monotonic=now)
            error=(5/(12-y))/math.tan(math.radians(c['camera_hfov_deg']/2))
            estimator.observe(dict(center_x_normalized=error),gps,now,c)
        self.assertIsNotNone(estimator.estimate)
        self.assertAlmostEqual(estimator.estimate[0],5,places=3);self.assertAlmostEqual(estimator.estimate[1],12,places=3)
        gps.update(latitude=35+math.degrees(16/6371000),last_valid_monotonic=105)
        relative=estimator.relative(gps,105);self.assertGreater(abs(relative['heading_error_deg']),100)
        target=self.acquire();self.t.estimator=estimator
        target=self.t.update([],640,480,105,c,gps)
        self.assertEqual(target['phase'],'TURN_BACK');self.assertIsNotNone(target['world_estimate'])
        gps['speed_mps']=.1;self.assertIsNone(estimator.relative(gps,105))
    def test_automatic_left_right_and_navigation_direction_configuration(self):
        for error in (-.5,.5):
            for sign in (-1,1):
                target=dict(phase='TRACKING',center_x_normalized=error,acquired=True,predicted=False)
                result=TrackingController().command(target,100,100,dict(self.c,steering_right_sign=sign))
                self.assertTrue(result['valid']);self.assertGreater((result['desired_steering_pwm']-6000)*error*sign,0)
    def test_configuration_validation(self):
        for args in (dict(confidence=-1),dict(pink_min_fraction=1),dict(inference_hz=float('nan')),dict(camera_type='bad'),dict(width=320.5)):
            with self.assertRaises(ValueError):validate_config(args)

class BalloonSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=base.load_supervisor()
    setUp=base.SupervisorTests.setUp
    refresh=base.SupervisorTests.refresh
    request=base.SupervisorTests.request
    assert_manual_stop=base.SupervisorTests.assert_manual_stop
    def ready(self):
        self.s.mode='BALLOON';self.s.armed=True
        self.s.vision=dict(enabled=True,model_ready=True,camera_online=True,live_source=True,max_frame_age_s=1.5,monotonic=self.now)
        self.s.vision_desired=dict(valid=True,monotonic=self.now,tracking_session=self.s.mode_since,desired_steering_pwm=5900,desired_throttle_pwm=6650)
    def test_arm_requires_real_camera_and_target_and_session(self):
        self.assertFalse(self.request('set_mode',mode='BALLOON',armed=True).success)
        self.ready();self.s.vision_desired['tracking_session']=99
        self.assertEqual(self.s._command()[1:],(6000,6450,True))
        self.s.vision_desired['tracking_session']=self.s.mode_since
        self.assertEqual(self.s._command(),('BALLOON',5900,6650,False))
        self.s.vision['live_source']=False
        self.assert_manual_stop('BALLOON_TARGET_OR_CAMERA_LOST')
    def test_gps_ssh_delay_keep_mode_and_recover_without_rearming(self):
        self.ready();session=self.s.mode_since
        for delta in (0,1,4.9):
            self.now=100+delta;self.refresh();self.ready();self.s.gps.update(healthy=False,fix=False,data_validity='stale')
            self.s.link.update(ssh_state='delayed',ssh_connected=True)
            self.assertEqual(self.s._command()[0],'BALLOON')
        self.now=104.95;self.refresh();self.ready();self.assertEqual(self.s._command()[0],'BALLOON')
        self.assertEqual(self.s.mode_since,session);self.assertIsNone(self.s.balloon_gps_gap_since)
    def test_camera_fault_estop_rc_loss_confirmed_disconnect_and_gps_expiry(self):
        for source,key,value,reason in [('vision','camera_online',False,'BALLOON_TARGET_OR_CAMERA_LOST'),
            ('link','ssh_connected',False,'SSH_DISCONNECTED'),('rc','monotonic',99,'RC_INPUT_LOST'),
            ('gps','transport_connected',False,'GPS_DISCONNECTED')]:
            self.refresh();self.ready();self.s.estop=False;getattr(self.s,source)[key]=value;self.assert_manual_stop(reason)
        self.refresh();self.ready();self.s.estop=True;self.assertEqual(self.s._command()[1:],(6000,6450,True));self.s.estop=False
        self.refresh();self.ready();self.s.gps.update(healthy=False,fix=False,data_validity='stale');self.s._command()
        self.now+=5.1;self.refresh();self.ready();self.s.gps.update(healthy=False,fix=False,data_validity='stale');self.assert_manual_stop('GPS_INVALID_OR_STALE')

if __name__=='__main__':unittest.main()
