"""Interleaved ROS callbacks must not fabricate stale/future control inputs.

Virtual clocks and real node methods; no PCA, servo or ESC is opened.
"""
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

import test_failsafe_v218 as base
from rcboat_ros.control_config import OUTPUT_DEFAULTS

ROOT=Path(__file__).resolve().parents[1]

class SupervisorSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.module=base.load_supervisor();self.now=100.
        self.clock=patch.object(self.module.time,'monotonic',side_effect=lambda:self.now)
        self.clock.start();self.addCleanup(self.clock.stop)
        self.callbacks={}
        self.module.rospy.Subscriber=lambda topic,kind,callback,**kwargs:self.callbacks.setdefault(topic,callback)
        self.s=self.module.Supervisor();self.s.mode='BALLOON';self.s.mode_since=98.;self.s.armed=True
        self.s.gps=dict(healthy=True,fix=True,latitude=35,longitude=129,speed_mps=.6,last_valid_monotonic=100.)
        self.s.rc=dict(monotonic=100.,steering_us=1620,throttle_us=1499)
        self.s.link=dict(ssh_connected=True,monotonic=100.)
        self.s.actuator=dict(command_applied=True,monotonic=100.)
        self.s.vision=dict(enabled=True,model_ready=True,camera_online=True,live_source=True,monotonic=100.,max_frame_age_s=1.5)
        self.s.vision_desired=dict(valid=True,monotonic=100.,tracking_session=98.,desired_steering_pwm=6350,desired_throttle_pwm=6650)

    def test_actuator_callback_during_decision_does_not_force_manual(self):
        self._interleave('/rcboat/actuator/status',dict(command_applied=True,monotonic=100.01))

    def test_rc_and_link_updates_during_decision_do_not_create_false_loss(self):
        for topic,payload in [('/rcboat/rc/input',dict(monotonic=100.01,steering_us=1620,throttle_us=1499)),
                              ('/rcboat/gui/link',dict(ssh_connected=True,monotonic=100.01))]:
            self.setUp_interleave_state()
            self._interleave(topic,payload)

    def test_gps_and_vision_updates_do_not_create_false_grace_or_target_loss(self):
        for topic,payload in [('/rcboat/gps/status',dict(self.s.gps,last_valid_monotonic=100.01)),
                              ('/rcboat/vision/status',dict(self.s.vision,monotonic=100.01)),
                              ('/rcboat/vision/desired',dict(self.s.vision_desired,monotonic=100.01))]:
            self.setUp_interleave_state()
            self.s.gps['last_valid_monotonic']=self.s.vision['monotonic']=self.s.vision_desired['monotonic']=100.
            self._interleave(topic,payload)

    def setUp_interleave_state(self):
        self.s.mode='BALLOON';self.s.armed=True;self.now=100.
        self.s.actuator['monotonic']=self.s.rc['monotonic']=self.s.link['monotonic']=100.

    def _interleave(self,topic,payload):
        # get_param occurs after the command cycle samples its clock. A ROS
        # callback then arrives with a perfectly valid, slightly newer timestamp.
        started=threading.Event();completed=threading.Event();workers=[];first=[True]
        def receive():
            started.set()
            self.callbacks[topic](types.SimpleNamespace(data=json.dumps(payload)))
            completed.set()
        def parameter(name,default=None):
            if first[0]:
                first[0]=False;t=threading.Thread(target=receive);workers.append(t);t.start()
                if not started.wait(1):raise RuntimeError('callback did not start')
                completed.wait(.05)
            return default
        with patch.object(self.module.rospy,'get_param',side_effect=parameter):result=self.s._command()
        for worker in workers:worker.join(1);self.assertFalse(worker.is_alive())
        self.assertTrue(completed.is_set())
        self.assertEqual(result,('BALLOON',6350,6650,False))
        self.assertEqual(self.s.mode,'BALLOON')
        self.assertEqual(self.s.reason,'')
        self.assertIsNone(self.s.balloon_gps_gap_since)
        self.now=100.1
        self.assertEqual(self.s._command(),('BALLOON',6350,6650,False))

    def test_real_actuator_loss_still_latches_manual_and_records_evidence(self):
        self.s.actuator['monotonic']=98.9
        self.assertEqual(self.s._command(),('FAILSAFE_MANUAL',6000,6450,True))
        self.assertEqual(self.s.reason,'ACTUATOR_TIMEOUT')
        event=json.loads(self.s.events.messages[-1])
        self.assertEqual(event['actuator_snapshot']['monotonic'],98.9)
        self.assertGreater(event['decision_snapshot']['actuator_age_s'],1.)

    def test_genuinely_future_timestamps_are_still_rejected(self):
        self.s.actuator['monotonic']=101.
        self.assertEqual(self.s._command(),('FAILSAFE_MANUAL',6000,6450,True))
        self.assertEqual(self.s.reason,'ACTUATOR_TIMEOUT')


class ActuatorSnapshotTests(unittest.TestCase):
    def setUp(self):
        ros=types.ModuleType('rospy');ros.get_param=lambda name,default=None:default
        modules={'rospy':ros,'fcntl':types.ModuleType('fcntl'),
                 'std_msgs.msg':types.SimpleNamespace(String=str),
                 'rcboat_ros.msg':types.SimpleNamespace(ControlCommand=object)}
        spec=importlib.util.spec_from_file_location('snapshot_actuator',ROOT/'catkin_ws/src/rcboat_ros/nodes/actuator_node.py')
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,modules):spec.loader.exec_module(self.module)
        self.a=self.module.Actuator.__new__(self.module.Actuator);self.a.lock=threading.RLock()
        self.a.output_calibration=dict(OUTPUT_DEFAULTS);self.a.last_at=99.9
        self.a.last_message=self.message(6250)

    def message(self,steer):return types.SimpleNamespace(mode='BALLOON',source='BALLOON',actuator_locked=False,steering_pwm=steer,throttle_pwm=6650)

    def test_callback_between_clock_sample_and_resolution_cannot_insert_neutral(self):
        self.assert_consistent_actuator_command('BALLOON')

    def test_manual_after_ssh_disconnect_also_keeps_consistent_command(self):
        self.assert_consistent_actuator_command('MANUAL')

    def assert_consistent_actuator_command(self,mode):
        self.a.last_message.mode=self.a.last_message.source=mode
        attempted=threading.Event();done=threading.Event();workers=[];first=[True]
        def receive():
            message=self.message(6550);message.mode=message.source=mode
            attempted.set();self.a.command(message);done.set()
        def clock():
            if threading.current_thread() is threading.main_thread() and first[0]:
                first[0]=False;t=threading.Thread(target=receive);workers.append(t);t.start()
                if not attempted.wait(1):raise RuntimeError('callback did not start')
                done.wait(.05)
                return 100.
            return 100.01
        with patch.object(self.module.time,'monotonic',side_effect=clock):
            # The production entrypoint samples time inside the same lock as
            # the command/receive timestamp, instead of sampling in run().
            result=self.a.resolve()
            for t in workers:t.join(1);self.assertFalse(t.is_alive())
        self.assertTrue(done.is_set());self.assertEqual(result,(6250,6650,mode))
        with patch.object(self.module.time,'monotonic',return_value=100.02):
            self.assertEqual(self.a.resolve(),(6550,6650,mode))

    def test_timeout_lock_and_bad_pwm_still_produce_neutral(self):
        self.assertEqual(self.a.resolve(101.)[:2],(6000,6450))
        self.a.last_message.actuator_locked=True
        self.assertEqual(self.a.resolve(100.)[:2],(6000,6450))
        self.a.last_message=self.message(6250);self.a.last_at=100.01
        self.assertEqual(self.a.resolve(100.)[:2],(6000,6450))
        self.a.last_at=99.9
        self.a.last_message.actuator_locked=False;self.a.last_message.throttle_pwm=7398
        self.assertEqual(self.a.resolve(100.)[:2],(6000,6450))

if __name__=='__main__':unittest.main()
