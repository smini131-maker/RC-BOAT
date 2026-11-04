"""Optional vision-node lifecycle, preview and camera fallback; fake ROS/device only."""
import json,sys,tempfile,types,urllib.request,urllib.error,unittest,base64,hashlib,io,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import validate_config
import test_ground_continuity_v2111 as harness

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
        self.v.preview_at-=3
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req,timeout=2)
        self.assertEqual(error.exception.code,503)

class CameraAdapterTests(unittest.TestCase):
    def test_usb_failure_falls_back_to_csi_and_files_cannot_control(self):
        from rcboat_ros.camera_io import open_camera
        class Cap:
            def __init__(self,opened):self.opened=opened;self.released=False
            def set(self,*a):pass
            def isOpened(self):return self.opened
            def release(self):self.released=True
        caps=[]
        def capture(source,backend):
            cap=Cap(backend!=1);caps.append(cap);return cap
        cv=types.SimpleNamespace(VideoCapture=capture,CAP_V4L2=1,CAP_GSTREAMER=2,CAP_FFMPEG=3,CAP_ANY=4,
            CAP_PROP_FRAME_WIDTH=5,CAP_PROP_FRAME_HEIGHT=6,CAP_PROP_FPS=7,CAP_PROP_BUFFERSIZE=8)
        with patch('pathlib.Path.exists',return_value=True):cap,kind,live=open_camera(validate_config({}),cv)
        self.assertEqual(kind,'csi');self.assertTrue(live);self.assertTrue(caps[0].released)
        cap,kind,live=open_camera(validate_config(dict(camera_type='file',camera_source='fixture.mp4')),cv)
        self.assertEqual(kind,'file');self.assertFalse(live)

class VisionGatewayTests(unittest.TestCase):
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
