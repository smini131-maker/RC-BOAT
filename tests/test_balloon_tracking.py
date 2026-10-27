import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"catkin_ws/src/rcboat_ros/src"))
from rcboat_ros.balloon_tracking import validate_config, TargetSelector, tracking_command, safe_balloon_output

def detection(center=.5, size=.1, confidence=.9):
    x, y = center*640, 240
    width, height = size*640, size*480
    return {"class_id": 0, "confidence": confidence,
            "bbox": [x-width/2, y-height/2, x+width/2, y+height/2]}

def supervisor_class():
    fake_ros = types.ModuleType("rospy")
    fake_ros.get_param = lambda _name, default=None: default
    messages = types.ModuleType("rcboat_ros.msg")
    messages.ControlCommand = type("ControlCommand", (), {})
    services = types.ModuleType("rcboat_ros.srv")
    services.Execute = object
    services.ExecuteResponse = lambda success, data: types.SimpleNamespace(success=success, response_json=data)
    std_messages = types.ModuleType("std_msgs.msg")
    std_messages.String = object
    modules = {"rospy": fake_ros, "rcboat_ros.msg": messages, "rcboat_ros.srv": services,
               "std_msgs": types.ModuleType("std_msgs"), "std_msgs.msg": std_messages}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("balloon_test_supervisor",
            ROOT/"catkin_ws/src/rcboat_ros/nodes/safety_supervisor_node.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.Supervisor

def vision_class():
    fake_ros = types.ModuleType("rospy")
    messages = types.ModuleType("std_msgs.msg"); messages.String = object
    services = types.ModuleType("rcboat_ros.srv")
    services.Execute = object; services.ExecuteResponse = object
    with patch.dict(sys.modules, {"rospy": fake_ros, "std_msgs": types.ModuleType("std_msgs"),
                                  "std_msgs.msg": messages, "rcboat_ros.srv": services}):
        spec = importlib.util.spec_from_file_location("balloon_test_vision",
            ROOT/"catkin_ws/src/rcboat_ros/nodes/balloon_vision_node.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.Vision

class BalloonTests(unittest.TestCase):
    def setUp(self):
        self.config = validate_config({})
        self.selector = TargetSelector()

    def target(self, center=.5, size=.1):
        item, acquired = None, False
        for _ in range(3):
            item, acquired = self.selector.update([detection(center, size)], 640, 480, self.config)
        return item, acquired

    def test_three_distinct_frames_are_required(self):
        for index in range(3):
            _, acquired = self.selector.update([detection()], 640, 480, self.config)
            self.assertEqual(acquired, index == 2)

    def test_left_and_right_commands_follow_calibration(self):
        left, acquired = self.target(.35)
        command = tracking_command(left, acquired, 100, 100.1, self.config)
        self.assertGreater(command["desired_steering_pwm"], 6000)
        self.selector.reset()
        right, acquired = self.target(.65)
        command = tracking_command(right, acquired, 100, 100.1, self.config)
        self.assertLess(command["desired_steering_pwm"], 6000)

    def test_steering_inversion_is_configurable(self):
        target, acquired = self.target(.65)
        config = dict(self.config, steering_right_sign=1)
        self.assertGreater(tracking_command(target, acquired, 100, 100.1, config)["desired_steering_pwm"], 6000)

    def test_centered_target_forward_command_is_capped(self):
        target, acquired = self.target()
        command = tracking_command(target, acquired, 100, 100.1, self.config)
        self.assertTrue(command["valid"])
        self.assertEqual(command["desired_steering_pwm"], 6000)
        self.assertEqual(command["desired_throttle_pwm"], 6550)

    def test_off_center_target_holds_forward_output(self):
        target, acquired = self.target(.95)
        command = tracking_command(target, acquired, 100, 100.1, self.config)
        self.assertEqual(command["desired_throttle_pwm"], 6450)

    def test_loss_stale_and_close_target_are_neutral(self):
        target, acquired = self.target()
        cases = [
            tracking_command(None, False, 100, 100.1, self.config),
            tracking_command(target, acquired, 100, 101.2, self.config),
            tracking_command(dict(target, area_ratio=.3), acquired, 100, 100.1, self.config),
        ]
        self.assertEqual([case["reason"] for case in cases],
                         ["NO_TARGET", "STALE_FRAME", "TARGET_CLOSE_STOP"])
        for case in cases:
            self.assertFalse(case["valid"])
            self.assertEqual((case["desired_steering_pwm"], case["desired_throttle_pwm"]), (6000, 6450))

    def test_different_target_needs_reacquisition(self):
        self.target(.2)
        item, acquired = self.selector.update([detection(.8)], 640, 480, self.config)
        self.assertIsNone(item)
        self.assertFalse(acquired)

    def test_invalid_settings_rejected(self):
        for setting in ({"cruise_pwm": 7000}, {"input_size": 300},
                        {"camera_source": "file.mp4"}, {"confidence": float("nan")}):
            with self.assertRaises(ValueError):
                validate_config(setting)

    def test_safety_rejects_model_camera_loss_and_stale_inference(self):
        vision = {"enabled": True, "model_ready": True, "camera_online": True, "max_frame_age_s": 1}
        desired = {"valid": True, "monotonic": 100, "desired_steering_pwm": 5900, "desired_throttle_pwm": 6550}
        self.assertEqual(safe_balloon_output(vision, desired, 100.1), (5900, 6550))
        for key in ("enabled", "model_ready", "camera_online"):
            self.assertIsNone(safe_balloon_output(dict(vision, **{key: False}), desired, 100.1))
        self.assertIsNone(safe_balloon_output(vision, desired, 102))
        self.assertIsNone(safe_balloon_output(vision, dict(desired, desired_throttle_pwm=7000), 100.1))
        self.assertIsNone(safe_balloon_output(vision, dict(desired, monotonic="invalid"), 100.1))

    def test_fresh_camera_cannot_make_old_inference_fresh(self):
        Vision = vision_class()
        instance = Vision.__new__(Vision)
        instance.lock = threading.RLock(); instance.config = dict(self.config)
        instance.detail = {"reason": "TRACKING"}
        instance.enabled = True; instance.model_ready = True
        instance.frame_at = 101.9; instance.error = ""; instance.log_file = None
        instance.desired = {"valid": True, "monotonic": 100,
                            "desired_steering_pwm": 5800, "desired_throttle_pwm": 6550}
        instance.status_pub = Mock(); instance.desired_pub = Mock()
        with patch("time.monotonic", return_value=102):
            instance.publish(None)
        published = json.loads(instance.desired_pub.publish.call_args.args[0])
        status = json.loads(instance.status_pub.publish.call_args.args[0])
        self.assertTrue(status["camera_online"])
        self.assertFalse(published["valid"])
        self.assertEqual(published["monotonic"], 100)
        self.assertEqual(published["desired_throttle_pwm"], 6450)

    def test_supervisor_latches_loss_until_explicit_rearm(self):
        Supervisor = supervisor_class()
        instance = Supervisor.__new__(Supervisor)
        instance.mode = "BALLOON"; instance.armed = True; instance.estop = False
        instance.rc = {}; instance.gps = {}; instance.nav = {}
        instance.events = Mock()
        instance.vision = {"enabled": True, "model_ready": True, "camera_online": True, "max_frame_age_s": 1}
        instance.vision_desired = {"valid": True, "monotonic": 100, "desired_steering_pwm": 5900,
                                   "desired_throttle_pwm": 6550}
        with patch("time.monotonic", return_value=100.1):
            self.assertEqual(instance._command(), ("BALLOON", 5900, 6550, False))
            instance.vision_desired["valid"] = False
            self.assertEqual(instance._command(), ("BALLOON_WAITING_REARM", 6000, 6450, True))
            self.assertFalse(instance.armed)
            instance.vision_desired["valid"] = True
            self.assertEqual(instance._command(), ("BALLOON_WAITING_REARM", 6000, 6450, True))
            instance.estop = True
            self.assertEqual(instance._command(), ("ESTOP", 6000, 6450, True))

    def test_onnx_decoder_and_manifest_integrity(self):
        import cv2
        import numpy as np
        from rcboat_ros.balloon_detector import decode_predictions, verify_model
        predictions = np.array([[[160, 160, 100, 80, .9, .9], [161, 160, 100, 80, .85, .9],
                                 [50, 50, 20, 20, .1, .9]]], dtype=np.float32)
        boxes = decode_predictions(predictions, (480, 640, 3), 320, .5, (0, 40), .45, .45, cv2)
        self.assertEqual(len(boxes), 1)
        self.assertAlmostEqual(boxes[0]["bbox"][0], 220)
        with tempfile.TemporaryDirectory() as directory:
            model, manifest = Path(directory)/"model.onnx", Path(directory)/"model.json"
            model.write_bytes(b"test model")
            manifest.write_text(json.dumps({"classes": ["balloon"], "output_format": "yolov5",
                                            "input_size": 320, "sha256": "wrong"}))
            with self.assertRaisesRegex(ValueError, "MODEL_HASH_MISMATCH"):
                verify_model(model, manifest, 320)

if __name__ == "__main__":
    unittest.main()
