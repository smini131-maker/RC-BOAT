"""Optional vision-node lifecycle, preview and camera fallback; fake ROS/device only."""
import json,sys,tempfile,types,urllib.request,urllib.error,unittest,base64,hashlib,io,zipfile,http.client
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import validate_config
import test_ground_continuity_v2111 as harness
from test_balloon_tracking import detection
from test_balloon_completion_v243 import near_box

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

class VisionNodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.m=harness.load_node('balloon_vision_node',root)
        self.m.rospy.Timer=lambda *a:None;self.m.rospy.Duration=lambda v:v
        original=self.m.os.path.expanduser
        with patch.object(self.m.os.path,'expanduser',side_effect=lambda p:str(root/p[2:]) if p.startswith('~/') else original(p)), \
             patch.object(self.m.Vision,'start_preview'),patch.object(self.m.threading,'Thread'):
            self.v=self.m.Vision()
        self.v.server=None;self.addCleanup(self.v.close);self.now=self.m.time.monotonic()
    def execute(self,action,**kwargs):return self.v.execute(types.SimpleNamespace(action=action,arguments_json=json.dumps(kwargs)))
    def test_mode_and_camera_reset_discard_prediction_and_in_flight_frames(self):
        vision = self.v
        self.assertTrue(self.execute('vision_enable', enabled=True).success)

        def mode(name, session):
            vision.on_safety(types.SimpleNamespace(data=json.dumps(
                dict(mode=name, armed=name == 'BALLOON', mode_since_monotonic=session))))

        def frame(stamp, detections):
            return vision.track_frame(detections, (480, 640), stamp, stamp, vision.config)

        mode('BALLOON', 100)
        started = vision.tracking_reset_at
        for index in range(1, 4):
            target, _ = frame(started + index * .33, [detection(.2)])
        self.assertEqual(target['phase'], 'TRACKING')
        vision.detail, vision.desired = frame(started + 1.2, [])
        self.assertEqual(vision.detail['phase'], 'PREDICTING')
        vision.preview = b'previous-overlay'

        mode('MANUAL', 102)
        self.assertEqual((vision.detail, vision.desired, vision.preview), ({}, {}, b''))
        self.assertEqual(frame(started + 2, [detection()]), ({}, {}))
        mode('BALLOON', 103)
        self.assertEqual(frame(started - .1, [detection()]), ({}, {}))
        self.assertEqual(frame(vision.tracking_reset_at + .1, [detection(-.2)])[0]['phase'], 'ACQUIRING')

        self.assertTrue(self.execute('vision_enable', enabled=False).success)
        mode('MANUAL', 104)
        self.assertTrue(self.execute('vision_enable', enabled=True).success)
        self.assertEqual(frame(vision.tracking_reset_at + .1, [detection()]), ({}, {}))
        mode('BALLOON', 105)
        self.assertEqual(frame(vision.tracking_reset_at + .1, [detection()])[0]['phase'], 'ACQUIRING')

    @unittest.skipUnless(cv2 is not None, 'OpenCV and NumPy required')
    def test_near_colour_support_requires_live_fresh_frames_in_same_session(self):
        vision = self.v
        vision.live_source = True
        vision.detector = types.SimpleNamespace(cv2=cv2, config=dict(vision.config, target_colour='red'))
        vision.tracking_session = 99.
        vision.tracking_reset_at = 100.
        box = near_box()
        frame = np.full((1080, 1920, 3), (15, 20, 170), dtype=np.uint8)
        for stamp in (100., 100.1, 100.2):
            vision.track_frame([box], frame.shape, stamp, stamp, vision.config)
        self.assertFalse(vision.near_support(frame, 99.9, 100.3, vision.config))
        self.assertFalse(vision.near_support(frame, 100.3, 102., vision.config))
        vision.live_source = False
        self.assertFalse(vision.near_support(frame, 100.3, 100.3, vision.config))
        vision.live_source = True
        support = vision.near_support(frame, 100.3, 100.3, vision.config)
        self.assertTrue(support)
        target, desired = vision.track_frame([], frame.shape, 100.3, 100.3, vision.config,
                                             near_visual_support=support)
        self.assertEqual(target['phase'], 'NEAR_APPROACH')
        self.assertEqual(desired['desired_throttle_pwm'], 6650)
        frame[:] = 0
        support = vision.near_support(frame, 100.4, 100.4, vision.config)
        self.assertFalse(support)
        target, desired = vision.track_frame([], frame.shape, 100.4, 100.4, vision.config,
                                             near_visual_support=support)
        self.assertEqual(target['phase'], 'NEAR_WAIT')
        self.assertEqual(desired['desired_throttle_pwm'], 6450)
        vision.on_safety(types.SimpleNamespace(data=json.dumps(dict(mode='MANUAL'))))
        frame[:] = (15, 20, 170)
        self.assertFalse(vision.near_support(frame, 100.5, 100.5, vision.config))

    @unittest.skipUnless(cv2 is not None, 'OpenCV and NumPy required')
    def test_unrelated_confirmed_detection_does_not_suppress_near_colour_support(self):
        vision = self.v
        vision.enabled = True
        vision.live_source = True
        vision.tracking_session = 99.
        vision.tracking_reset_at = 100.
        vision.frame = np.full((1080, 1920, 3), (15, 20, 170), dtype=np.uint8)
        vision.frame_at = 100.3
        original = near_box()
        for stamp in (100., 100.1, 100.2):
            vision.track_frame([original], vision.frame.shape, stamp, stamp, vision.config)

        unrelated = dict(confidence=.99, pink_confirmed=True, bbox=[1810, 530, 1880, 600])
        detector = Mock(cv2=cv2, config=dict(vision.config, target_colour='red'),
                        backend_name='fixture', last_view={})
        detector.detect.return_value = [unrelated]
        with patch('rcboat_ros.balloon_detector.BalloonDetector', return_value=detector), \
             patch.object(self.m.rospy, 'is_shutdown', side_effect=[False, True], create=True), \
             patch.object(self.m.time, 'monotonic', return_value=100.3), \
             patch.object(self.m.time, 'sleep'):
            vision.run()

        self.assertEqual(vision.detail['detections'], [unrelated])
        self.assertEqual(vision.detail['target']['bbox'], original['bbox'])
        self.assertEqual(vision.detail['reason'], 'NEAR_APPROACH')
        self.assertEqual(vision.desired['desired_throttle_pwm'], 6650)

    def test_disabled_model_missing_and_camera_stale_cannot_drive(self):
        self.v.desired=dict(valid=True,monotonic=self.now,desired_steering_pwm=4900,desired_throttle_pwm=7397)
        self.v.publish(None)
        out=json.loads(self.v.desired_pub.messages[-1]);self.assertFalse(out['valid']);self.assertEqual(out['desired_throttle_pwm'],6450)
        self.v.enabled=True;self.v.model_ready=True;self.v.frame_at=self.now-4;self.v.publish(None)
        self.assertFalse(json.loads(self.v.desired_pub.messages[-1])['valid'])
    def test_configuration_validation_persistence_and_secret_redaction(self):
        self.assertFalse(self.execute('vision_configure',search_timeout_s=-1).success)
        self.assertTrue(self.execute('vision_configure',camera_type='rtsp',camera_source='rtsp://name:secret@camera/live?token=secret').success)
        public=self.m.public_config(self.v.config);self.assertNotIn('secret',json.dumps(public));self.assertEqual(public['camera_source'],'rtsp://camera/live')
        self.assertTrue(self.v.config_path.is_file())
        self.v.enabled=True;self.assertFalse(self.execute('vision_configure',confidence=.5).success)
        self.assertFalse(self.execute('vision_enable',enabled='yes').success)
    def test_publish_samples_clock_after_frame_snapshot_is_available(self):
        clock=[100.]
        self.v.enabled=True;self.v.model_ready=True
        def parameter(key,default=None):
            clock[0]=100.02;self.v.frame_at=100.01
            self.v.desired=dict(valid=True,monotonic=100.01,desired_steering_pwm=6200,desired_throttle_pwm=6650)
            return default
        with patch.object(self.m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(self.m.rospy,'get_param',side_effect=parameter):self.v.publish(None)
        self.assertTrue(json.loads(self.v.status_pub.messages[-1])['camera_online'])
        self.assertTrue(json.loads(self.v.desired_pub.messages[-1])['valid'])
    def test_authenticated_preview_and_stale_image_rejection(self):
        self.v.config['preview_port']=0
        with patch.dict(self.m.os.environ,{'RCBOAT_GATEWAY_TOKEN':'test-token'}):self.v.start_preview()
        self.assertIsNotNone(self.v.server);url='http://127.0.0.1:%d/frame.jpg'%self.v.server.server_port
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url,timeout=2)
        self.assertEqual(error.exception.code,401)
        req=urllib.request.Request(url,headers={'X-RCBoat-Token':'test-token'})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req,timeout=2)
        self.assertEqual(error.exception.code,503)
        self.v.enabled=True;self.v.preview=b'fixture-jpeg';self.v.preview_at=self.m.time.monotonic()
        with urllib.request.urlopen(req,timeout=2) as response:
            self.assertEqual(response.read(),b'fixture-jpeg');self.assertEqual(response.headers['Cache-Control'],'no-store')
            etag=response.headers['ETag'];self.assertEqual(response.headers['X-Frame-Sequence'],'0')
        duplicate=urllib.request.Request(url,headers={'X-RCBoat-Token':'test-token','If-None-Match':etag})
        with self.assertRaises(urllib.error.HTTPError) as unchanged:urllib.request.urlopen(duplicate,timeout=2)
        self.assertEqual(unchanged.exception.code,304);self.assertEqual(unchanged.exception.read(),b'')
        self.v.preview=b'new-frame';self.v.preview_sequence+=1
        with urllib.request.urlopen(duplicate,timeout=2) as response:self.assertEqual(response.read(),b'new-frame')
        client=http.client.HTTPConnection('127.0.0.1',self.v.server.server_port,timeout=2)
        try:
            client.request('GET','/frame.jpg',headers={'X-RCBoat-Token':'test-token'})
            response=client.getresponse();self.assertEqual(response.version,11);self.assertEqual(response.read(),b'new-frame')
            current=response.getheader('ETag');endpoint=client.sock.getsockname()
            client.request('GET','/frame.jpg',headers={'X-RCBoat-Token':'test-token','If-None-Match':current})
            response=client.getresponse();self.assertEqual(response.status,304);self.assertEqual(response.read(),b'')
            self.assertEqual(client.sock.getsockname(),endpoint)
        finally:client.close()
        self.v.preview_at-=3
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req,timeout=2)
        self.assertEqual(error.exception.code,503)

    def test_stream_reuses_jpeg_and_sends_only_new_frames(self):
        self.v.config['preview_port']=0
        self.v.start_preview()
        with self.v.lock:
            self.v.enabled=True
            self.v.preview=b'first'
            self.v.preview_at=self.m.time.monotonic()
        client=http.client.HTTPConnection('127.0.0.1',self.v.server.server_port,timeout=2)
        try:
            client.request('GET','/stream/12')
            response=client.getresponse()
            self.assertEqual(response.status,200)
            header=self.m.PREVIEW_STREAM_HEADER
            size,age=header.unpack(response.read(header.size))
            self.assertLess(age,500)
            self.assertEqual(response.read(size),b'first')
            with self.v.lock:
                self.v.preview=b'second'
                self.v.preview_at=self.m.time.monotonic()
                self.v.preview_sequence+=1
            size,_=header.unpack(response.read(header.size))
            self.assertEqual(response.read(size),b'second')
        finally:
            with self.v.lock:self.v.enabled=False
            client.close()


class CameraAdapterTests(unittest.TestCase):
    def test_usb_failure_falls_back_to_csi_and_files_cannot_control(self):
        from rcboat_ros.camera_io import open_camera
        class Cap:
            def __init__(self,opened):self.opened=opened;self.released=False
            def set(self,*a):pass
            def isOpened(self):return self.opened
            def release(self):self.released=True
            def read(self):return True,types.SimpleNamespace(ndim=3,shape=(1080,1920,3))
        caps=[]
        def capture(source,backend):
            cap=Cap(backend!=1);caps.append(cap);return cap
        cv=types.SimpleNamespace(VideoCapture=capture,CAP_V4L2=1,CAP_GSTREAMER=2,CAP_FFMPEG=3,CAP_ANY=4,
            CAP_PROP_FRAME_WIDTH=5,CAP_PROP_FRAME_HEIGHT=6,CAP_PROP_FPS=7,CAP_PROP_BUFFERSIZE=8)
        with patch('pathlib.Path.exists',return_value=True):cap,kind,live=open_camera(validate_config({}),cv)
        self.assertEqual(kind,'csi');self.assertTrue(live);self.assertTrue(caps[0].released)
        cap,kind,live=open_camera(validate_config(dict(camera_type='file',camera_source='fixture.mp4')),cv)
        self.assertEqual(kind,'file');self.assertFalse(live)
    def test_open_but_unreadable_usb_releases_and_falls_back_without_dropping_probe(self):
        from rcboat_ros.camera_io import open_camera
        frame=types.SimpleNamespace(ndim=3,shape=(1080,1920,3))
        captures=[];sources=[]
        class Cap:
            def __init__(self,good):self.good=good;self.released=False;self.reads=0
            def set(self,*a):pass
            def isOpened(self):return True
            def read(self):self.reads+=1;return (True,frame) if self.good else (False,None)
            def release(self):self.released=True
        def capture(source,backend):
            cap=Cap(backend==2);captures.append(cap);sources.append(source);return cap
        cv=types.SimpleNamespace(VideoCapture=capture,CAP_V4L2=1,CAP_GSTREAMER=2,CAP_FFMPEG=3,CAP_ANY=4,
            CAP_PROP_FRAME_WIDTH=5,CAP_PROP_FRAME_HEIGHT=6,CAP_PROP_FPS=7,CAP_PROP_BUFFERSIZE=8)
        with patch('pathlib.Path.exists',return_value=True):cap,kind,live=open_camera(validate_config({}),cv)
        self.assertTrue(captures[0].released);self.assertEqual(kind,'csi');self.assertTrue(live)
        self.assertIn('width=1920,height=1080',sources[1])
        self.assertIs(cap.read()[1],frame);self.assertEqual(captures[1].reads,1)
        cap.release();self.assertTrue(captures[1].released)

class VisionGatewayTests(unittest.TestCase):
    def test_compact_status_keeps_route_updates_and_omits_unchanged_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            module=harness.load_node('gui_bridge_node',Path(directory))
            with patch.object(module.rospy,'set_param',create=True):
                bridge=module.Bridge()
            route=dict(routes=[dict(id='one')],multipaths=[dict(id='a')],selected_route_id='one')
            first=dict(route=route)
            revision=bridge.compact_route_status(first,'')
            self.assertEqual(first['route']['routes'],route['routes'])
            compact=dict(route=route)
            self.assertEqual(bridge.compact_route_status(compact,revision),revision)
            self.assertEqual(compact['route'],dict(selected_route_id='one'))
            self.assertIn('routes',route)
            changed=dict(route=dict(route,routes=[dict(id='two')],selected_route_id='two'))
            self.assertNotEqual(bridge.compact_route_status(changed,revision),revision)
            self.assertEqual(changed['route']['routes'],[dict(id='two')])

    def test_gateway_client_cleans_up_lost_and_incomplete_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            module=harness.load_node('gui_bridge_node',Path(directory))
            bridge=module.Bridge.__new__(module.Bridge)
            bridge.dispatch=Mock(return_value={'success':True})
            for error in (ConnectionResetError, TimeoutError):
                with self.subTest(error=error):
                    connection=MagicMock()
                    connection.recv.side_effect=error
                    bridge.client(connection)
                    connection.settimeout.assert_called_once_with(5)
                    connection.sendall.assert_not_called()
                    bridge.dispatch.assert_not_called()
            connection=MagicMock()
            connection.recv.side_effect=[b'{"action":"status"}',b'']
            bridge.client(connection)
            self.assertFalse(json.loads(connection.sendall.call_args.args[0])['success'])
            bridge.dispatch.assert_not_called()
            connection=MagicMock()
            connection.recv.side_effect=[b'{"action":',b'"status"}\n']
            connection.sendall.side_effect=BrokenPipeError
            bridge.client(connection)
            bridge.dispatch.assert_called_once_with({'action':'status'})

    def test_service_routing_and_complete_line_snapshot_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);m=harness.load_node('gui_bridge_node',root)
            bridge=m.Bridge.__new__(m.Bridge);bridge.token='';calls=[]
            bridge.service=lambda ns,action,args:(calls.append((ns,action,args)) or {})
            self.assertTrue(bridge.dispatch({'action':'vision_enable','arguments':{'enabled':True}})['success'])
            self.assertEqual(calls[-1][0],'/rcboat/vision/execute')
            log=root/'vision_fixture.jsonl';log.write_bytes(b'{"phase":"TRACKING"}\n{"partial":')
            with patch.object(m.os.path,'expanduser',return_value=str(root)):result=bridge.download_vision_log()
            raw=base64.b64decode(result['zip_base64']);self.assertEqual(hashlib.sha256(raw).hexdigest(),result['sha256'])
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                snapshot=archive.read(log.name);meta=json.loads(archive.read('export_manifest.json'))
                self.assertEqual(snapshot,b'{"phase":"TRACKING"}\n');self.assertEqual(meta['sha256'],hashlib.sha256(snapshot).hexdigest())
            with log.open('wb') as handle:handle.truncate(32*1024*1024+1)
            with patch.object(m.os.path,'expanduser',return_value=str(root)),self.assertRaises(ValueError):bridge.download_vision_log()

if __name__=='__main__':unittest.main()
