import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.corrections import crc24q,Rtcm3Stream,HttpChunkedStream,reception_status,refresh_transport_status,refresh_receiver_status
from rcboat_ros.gps_mix import MixedGpsParser


def frame(payload=b'\x43\x20\x01\xd3\x00\x04'):
    data=b'\xd3'+len(payload).to_bytes(2,'big')+payload
    return data+crc24q(data).to_bytes(3,'big')


def gga(age):
    payload='GPGGA,005111.00,3504.5,N,12905.0,E,1,09,1.0,0,M,0,M,%s,'%age
    checksum=0
    for char in payload:checksum^=ord(char)
    return ('$'+payload+'*%02X\r\n'%checksum).encode()


class CorrectionTests(unittest.TestCase):
    def test_crc_reference_vector(self):
        self.assertEqual(crc24q(b'123456789'),0xCDE703)

    def test_partial_frames_do_not_refresh_correction_age(self):
        stream=Rtcm3Stream(); packet=frame()
        self.assertEqual(stream.feed(packet[:5]),[])
        self.assertEqual(stream.frames,0)
        self.assertEqual(stream.feed(packet[5:]),[packet])

    def test_bad_crc_and_noise_do_not_count_as_corrections(self):
        stream=Rtcm3Stream(); bad=bytearray(frame());bad[-1]^=1
        self.assertEqual(stream.feed(b'HTTP error body\r\n'+bytes(bad)+frame()),[frame()])
        self.assertGreaterEqual(stream.crc_errors,1)

    def test_multiple_frames(self):
        stream=Rtcm3Stream()
        self.assertEqual(stream.feed(frame()+frame()),[frame(),frame()])

    def test_chunked_http_decodes_before_crc_validation(self):
        data=frame(); wire=(b'5;tag=x\r\n'+data[:5]+b'\r\n'+
                          ('%X\r\n'%(len(data)-5)).encode()+data[5:]+b'\r\n0\r\n\r\n')
        decoder=HttpChunkedStream();stream=Rtcm3Stream();packets=[]
        for byte in wire:
            packets+=stream.feed(decoder.feed(bytes([byte])))
        self.assertEqual(packets,[data]);self.assertTrue(decoder.done)

    def test_age_grows_without_more_data(self):
        self.assertEqual(reception_status(None,100),(None,'no_data'))
        self.assertEqual(reception_status(100,100.25),(.25,'valid'))
        self.assertEqual(reception_status(100,107.5),(7.5,'stale'))
        self.assertEqual(reception_status(110,100),(None,'invalid'))

    def test_gateway_refreshes_age_if_publisher_dies(self):
        data=dict(correction_age_source='JETSON_RTCM3_CRC_RECEPTION',last_rtcm_monotonic=100,last_correction_age_s=0)
        self.assertEqual(refresh_transport_status(data,108)['last_correction_age_s'],8)
        self.assertEqual(data['last_correction_age_s'],0)

    def test_old_backend_hardcoded_zero_is_unsupported(self):
        data=refresh_transport_status({'last_correction_age_s':0},108)
        self.assertIsNone(data['last_correction_age_s'])
        self.assertEqual(data['correction_age_status'],'unsupported')

    def test_receiver_value_is_stale_when_reports_stop(self):
        gps=dict(receiver_correction_age_s=2.5,receiver_correction_age_monotonic=100,
                 receiver_correction_age_status='valid')
        self.assertEqual(refresh_receiver_status(gps,101)['receiver_correction_age_status'],'valid')
        self.assertEqual(refresh_receiver_status(gps,103)['receiver_correction_age_status'],'stale')
        self.assertEqual(gps['receiver_correction_age_status'],'valid')

    def test_empty_payload_cannot_count_as_corrections(self):
        self.assertEqual(Rtcm3Stream().feed(frame(b'')),[])

    def test_receiver_reported_age_is_preserved_separately(self):
        parser=MixedGpsParser();parser.feed(gga('2.5'))
        self.assertEqual(parser.state['receiver_correction_age_s'],2.5)
        parser.feed(gga('0'))
        self.assertEqual(parser.state['receiver_correction_age_s'],0)
        self.assertEqual(parser.state['receiver_correction_age_status'],'valid')

    def test_missing_receiver_age_never_becomes_zero(self):
        parser=MixedGpsParser()
        self.assertEqual(parser.state['receiver_correction_age_status'],'unsupported')
        parser.feed(gga(''))
        self.assertIsNone(parser.state['receiver_correction_age_s'])
        self.assertEqual(parser.state['receiver_correction_age_status'],'no_data')

    def test_invalid_receiver_age(self):
        for value in ('-1','nan','oops'):
            parser=MixedGpsParser();parser.feed(gga(value))
            self.assertIsNone(parser.state['receiver_correction_age_s'])
            self.assertEqual(parser.state['receiver_correction_age_status'],'invalid')


class PersistedProfileTests(unittest.TestCase):
    def test_local_profile_public_fields_and_empty_password_retention(self):
        class Publisher:
            def __init__(self,*a,**k):self.messages=[]
            def publish(self,value):self.messages.append(value)
        class Response:
            def __init__(self,success,response_json):self.success=success;self.response_json=response_json
        ros=types.SimpleNamespace(Service=lambda *a:None,Subscriber=lambda *a:None,
            Publisher=Publisher,Timer=lambda *a:None,Duration=lambda v:v)
        modules={'rospy':ros,'std_msgs.msg':types.SimpleNamespace(String=str,UInt8MultiArray=object),
            'rcboat_ros.srv':types.SimpleNamespace(Execute=object,ExecuteResponse=Response)}
        spec=importlib.util.spec_from_file_location('ntrip_profile_test',ROOT/'catkin_ws/src/rcboat_ros/nodes/ntrip_node.py')
        m=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,modules):spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as directory,patch.dict(m.os.environ,{},clear=True):
            path=Path(directory)/'ntrip.env';m.NTRIP_ENV_PATH=path
            values={'ENABLED':'true','HOST':'caster.example.invalid','PORT':'2101','MOUNTPOINT':'SAVED',
                    'USERNAME':'fixture-user','PASSWORD':'fixture-secret'}
            path.write_text(''.join('RCBOAT_NTRIP_'+k+'='+json.dumps(v)+'\n' for k,v in values.items()),encoding='utf-8')
            n=m.Ntrip();n.publish_status();public=json.loads(n.status.messages[-1])
            self.assertEqual(public['username'],'fixture-user');self.assertEqual(public['host'],'caster.example.invalid')
            self.assertTrue(public['credentials_saved']);self.assertNotIn('fixture-secret',n.status.messages[-1])
            answer=n.execute(types.SimpleNamespace(action='configure',arguments_json=json.dumps({'enabled':True})))
            self.assertTrue(answer.success);self.assertEqual(n.password,'fixture-secret')
            self.assertEqual(m.load_local_env(path)['RCBOAT_NTRIP_PASSWORD'],'fixture-secret')
            self.assertNotIn('fixture-secret',''.join(n.events.messages))

class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('verify_release',ROOT/'deployment/jetson/verify_release.py')
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'VERSION').write_text('2.1.10\n')
        source=self.root/'catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py'
        source.parent.mkdir(parents=True);source.write_text('VERSION="2.1.10"\n')
        (source.parents[1]/'package.xml').write_text('<package><version>2.1.10</version></package>')
        self.name=str(source.relative_to(self.root)).replace('\\','/')
        self.manifest={'version':'2.1.10','files':{self.name:self.module.file_hash(source)}}
        (self.root/'deployment_manifest.json').write_text(json.dumps(self.manifest))
        self.result=dict(version='2.1.10',master_online=True,runtime_identity=dict(
            source=str(source),source_sha256=self.manifest['files'][self.name]),
            telemetry={k:{'software_version':'2.1.10'} for k in ('gps','ntrip','safety')})

    def test_source_and_runtime_identity_match(self):
        self.assertEqual(self.module.verify_sources(self.root)[0],'2.1.10')
        self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)

    def test_old_running_gateway_is_rejected(self):
        self.result['version']='2.1.3'
        with self.assertRaisesRegex(RuntimeError,'RUNNING gateway'):
            self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)

    def test_matching_label_but_wrong_source_is_rejected(self):
        self.result['runtime_identity']['source_sha256']='oldhash'
        with self.assertRaisesRegex(RuntimeError,'source hash mismatch'):
            self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)

    def test_old_ntrip_node_is_rejected(self):
        self.result['telemetry']['ntrip']['software_version']='2.1.3'
        with self.assertRaisesRegex(RuntimeError,'ntrip node runtime version'):
            self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)

    def test_camera_release_requires_running_vision_status(self):
        self.manifest['files']['catkin_ws/src/rcboat_ros/nodes/balloon_vision_node.py']='fixture'
        with self.assertRaisesRegex(RuntimeError,'vision node runtime version'):
            self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)
        self.result['telemetry']['vision']={'software_version':'2.1.10'}
        self.module.verify_runtime(self.result,'2.1.10',self.manifest,self.root)

    def test_partial_source_transfer_is_rejected(self):
        (self.root/self.name).write_text('old source')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):
            self.module.verify_sources(self.root)

    def test_generated_cache_cleanup_preserves_routes(self):
        routes=self.root/'catkin_ws/routes.json';routes.write_text('user-owned')
        for name in ('build','devel'):
            path=self.root/'catkin_ws'/name;path.mkdir();(path/'stale').write_text('old cache')
        self.module.clean_build(self.root)
        self.assertEqual(routes.read_text(),'user-owned')
        self.assertFalse((self.root/'catkin_ws/devel').exists())


if __name__=='__main__':unittest.main()
