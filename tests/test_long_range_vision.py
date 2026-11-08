"""Range geometry, small-target continuity and bounded native-pixel inference.

The numeric tests use artificial images/a fake network, never measured 100m data.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.long_range import expected_diameter_px, square_crop, RegionPlanner
from rcboat_ros.balloon_tracking import validate_config, TargetTracker, BearingEstimator

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None


class GeometryAndContinuityTests(unittest.TestCase):
    def test_pixel_budget_is_an_assumption_not_a_distance_measurement(self):
        native = expected_diameter_px(.5, 100, 1920, 62.2)
        self.assertAlmostEqual(native, 7.96, delta=.03)
        self.assertAlmostEqual(expected_diameter_px(.5,100,320,62.2),native/6)
        self.assertAlmostEqual(expected_diameter_px(1,100,1920,62.2),native*2)
        for bad in (0, -1, float('nan'), True, None):
            with self.assertRaises(ValueError):
                expected_diameter_px(bad,100,1920,62.2)

    def test_crops_are_bounded_at_all_corners(self):
        for box in ([0,0,8,8],[1912,1072,1920,1080],[960,530,968,538]):
            left,top,right,bottom=square_crop(box,(1080,1920,3),96,4)
            self.assertTrue(0<=left<right<=1920 and 0<=top<bottom<=1080)
            self.assertEqual(right-left,96);self.assertEqual(bottom-top,96)

    def test_unrelated_tiny_candidates_cannot_build_acquisition(self):
        c=validate_config({});tracker=TargetTracker()
        def detection(x):return dict(bbox=[x,200,x+8,208],confidence=.9,pink_confirmed=True)
        for i,x in enumerate((100,500,900,1300)):
            out=tracker.update([detection(x)],1920,1080,100+i*.25,c)
            self.assertFalse(out['acquired'])
        for i in range(3):out=tracker.update([detection(1300)],1920,1080,101+i*.25,c)
        self.assertTrue(out['acquired'])
        self.assertEqual(tracker.update([],1920,1080,102,c)['phase'],'PREDICTING')
        self.assertFalse(tracker.update([],1920,1080,120,c)['acquired'])

    def test_well_conditioned_estimate_over_80m_and_weak_geometry_rejected(self):
        c=validate_config({});estimator=BearingEstimator()
        for i,y in enumerate(range(0,51,5)):
            now=100+i
            gps=dict(fix=True,latitude=35+math.degrees(y/6371000),longitude=129,heading_deg=0,
                     speed_mps=1,last_valid_monotonic=now)
            image_x=(25/(150-y))/math.tan(math.radians(c['camera_hfov_deg']/2))
            estimator.observe(dict(center_x_normalized=image_x),gps,now,c)
        self.assertIsNotNone(estimator.estimate)
        self.assertAlmostEqual(estimator.estimate[0],25,places=3)
        self.assertAlmostEqual(estimator.estimate[1],150,places=3)
        self.assertGreater(estimator.relative(gps,now)['distance_m'],100)
        weak=BearingEstimator()
        for i in range(3):weak.observe(dict(center_x_normalized=.1),gps,200+i,c)
        self.assertIsNone(weak.estimate)

    def test_new_configuration_bounds(self):
        for config in ({'long_range_enabled':'true'},{'roi_max_candidates':25},{'roi_full_interval':1},
                       {'roi_min_size':10},{'max_target_distance_m':float('inf')}):
            with self.assertRaises(ValueError):validate_config(config)


class ProfileMigrationTests(unittest.TestCase):
    def test_backup_preservation_and_no_repeated_overwrite(self):
        spec=importlib.util.spec_from_file_location('vision_profile_upgrade',ROOT/'deployment/jetson/upgrade_vision_profile.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'vision.json'
            old=dict(camera_type='csi',camera_source='/dev/video0',csi_sensor_id=1,width=640,height=480,confidence=.6)
            original=json.dumps(old).encode();p.write_bytes(original)
            self.assertTrue(module.upgrade(p));new=json.loads(p.read_text())
            self.assertEqual((new['width'],new['height']),(1920,1080))
            self.assertEqual(new['csi_sensor_id'],1);self.assertEqual(new['confidence'],.6)
            self.assertEqual(next(Path(tmp).glob('*.before_*')).read_bytes(),original)
            new.update(width=1280,height=720,long_range_enabled=False);p.write_text(json.dumps(new))
            self.assertFalse(module.upgrade(p));self.assertFalse(json.loads(p.read_text())['long_range_enabled'])
            p.write_text('{invalid');before=p.read_bytes()
            with self.assertRaises(ValueError):module.upgrade(p)
            self.assertEqual(p.read_bytes(),before)

    def test_field_capture_refuses_active_camera_or_unlocked_outputs(self):
        spec=importlib.util.spec_from_file_location('field_capture',ROOT/'deployment/jetson/capture_range_test.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Connection:
            def __init__(self,state):self.raw=(json.dumps(dict(success=True,version='2.4.0',telemetry=state))+'\n').encode();self.sent=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,*args):pass
            def sendall(self,raw):self.sent.append(json.loads(raw))
            def recv(self,*args):return self.raw
        states=[dict(vision={'enabled':True},safety={'actuator_locked':True}),
                dict(vision={'enabled':False},safety={'armed':True,'actuator_locked':False}),
                dict(vision={'enabled':False},safety={})]
        for state in states:
            connection=Connection(state)
            with patch.object(module.socket,'create_connection',return_value=connection),self.assertRaises(ValueError):module.backend_state()
            self.assertEqual([request['action'] for request in connection.sent],['status'])
        connection=Connection(dict(vision={'enabled':False},safety={'armed':False,'actuator_locked':True}))
        with patch.object(module.socket,'create_connection',return_value=connection):self.assertTrue(module.backend_state()['actuator_locked'])
        with patch.object(module.socket,'create_connection',side_effect=OSError('offline')):
            self.assertEqual(module.backend_state()['safety_state'],'unknown')


@unittest.skipIf(cv2 is None,'numpy/OpenCV checked in the vision-numeric CI job')
class NativeCropTests(unittest.TestCase):
    def frame(self,x=1700,y=200):
        image=np.zeros((1080,1920,3),np.uint8)
        cv2.circle(image,(x,y),4,(160,0,255),-1)
        return image

    def test_native_candidates_are_bounded_and_round_robin_searches_distractors(self):
        c=validate_config({});planner=RegionPlanner();frame=self.frame()
        cv2.circle(frame,(300,300),6,(160,0,255),-1)
        selected=[]
        for i in range(8):
            crop,detail=planner.plan(frame,c,cv2,now=100+i*.2)
            self.assertEqual(detail['neural_passes'],1)
            if detail['kind']=='roi':selected.append(crop[0])
        self.assertTrue(any(x<500 for x in selected));self.assertTrue(any(x>1000 for x in selected))
        planner.observe([dict(bbox=[1696,196,1704,204],confidence=.9,pink_confirmed=True)],100)
        for i in range(4):self.assertEqual(planner.plan(frame,c,cv2,100.1+i*.1)[1]['kind'],'roi')

    def fake_detector(self,outputs):
        from rcboat_ros.balloon_detector import BalloonDetector
        class Net:
            def __init__(self):self.calls=0;self.blob=None
            def setInput(self,blob):self.blob=blob
            def forward(self):
                self.calls+=1
                return np.array(outputs[min(self.calls-1,len(outputs)-1)],np.float32)
        d=BalloonDetector.__new__(BalloonDetector)
        d.cv2=cv2;d.config=validate_config({});d.planner=RegionPlanner();d.last_view={};d.backend_name='opencv';d.backend=Net()
        return d

    def test_one_network_pass_mapping_and_pink_uses_original_pixels(self):
        d=self.fake_detector([np.zeros((1,5,0)),[[[160,160,26.6667,26.6667,.9]]]])
        self.assertEqual(d.detect(self.frame()),[])
        result=d.detect(self.frame());self.assertEqual(d.backend.calls,2)
        self.assertEqual(d.backend.blob.shape,(1,3,320,320))
        self.assertEqual(len(result),1);self.assertTrue(result[0]['pink_confirmed'])
        self.assertTrue(np.allclose(result[0]['bbox'],[1696,196,1704,204],atol=1))
        self.assertEqual(d.last_view['kind'],'roi');self.assertTrue(d.last_view['requested_resolution_met'])
        self.assertGreater(result[0]['source_span_px'],7)

    def test_colour_only_or_subpixel_box_never_confirms(self):
        d=self.fake_detector([np.zeros((1,5,0))]);self.assertFalse(d.detect(self.frame()))
        d.detect(self.frame());self.assertEqual(d.backend.calls,2)
        tiny=self.fake_detector([np.zeros((1,5,0)),[[[160,160,6,6,.99]]]])
        tiny.detect(self.frame());out=tiny.detect(self.frame())
        self.assertFalse(out[0]['pink_confirmed'])

    def test_thin_pink_paint_strip_is_not_small_balloon_support(self):
        from rcboat_ros.balloon_detector import small_pink_shape_supported
        frame=np.zeros((80,80,3),np.uint8);frame[30:34,20:50]=(160,0,255)
        self.assertFalse(small_pink_shape_supported(frame,[20,30,50,34],validate_config({}),cv2))
        cv2.circle(frame,(40,60),6,(160,0,255),-1)
        self.assertTrue(small_pink_shape_supported(frame,[34,54,47,67],validate_config({}),cv2))

    def test_wrong_capture_resolution_is_reported_and_close_approach_uses_full_frame(self):
        d=self.fake_detector([np.zeros((1,5,0))]);d.detect(np.zeros((480,640,3),np.uint8))
        self.assertFalse(d.last_view['requested_resolution_met'])
        planner=RegionPlanner();planner.observe([dict(bbox=[300,100,1500,900],pink_confirmed=True,confidence=.9)],100)
        self.assertEqual(planner.plan(self.frame(),validate_config({}),cv2,100.1)[1]['kind'],'full')


if __name__=='__main__':unittest.main()
