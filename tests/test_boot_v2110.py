import importlib.util
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.direct_pca import DirectLinuxPCA9685


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class BootTests(unittest.TestCase):
    def test_i2c_initialization_failure_closes_descriptor(self):
        bus=MagicMock();bus.write_byte_data.side_effect=OSError('NACK')
        module=types.ModuleType('smbus2');module.SMBus=lambda n:bus
        with patch.dict(sys.modules,{'smbus2':module}):
            with self.assertRaises(OSError):DirectLinuxPCA9685()
        bus.close.assert_called_once()

    def test_successful_i2c_preserves_calibration(self):
        bus=MagicMock();bus.read_byte_data.return_value=0
        module=types.ModuleType('smbus2');module.SMBus=lambda n:bus
        with patch.dict(sys.modules,{'smbus2':module}):
            pca=DirectLinuxPCA9685();pca.set_duty_cycle(6,6450)
            call=bus.write_i2c_block_data.call_args
            self.assertEqual(call.args[0:2],(0x40,0x06+4*6))
            off=round(6450*4095/65535)
            self.assertEqual(call.args[2],[0,0,off&255,off>>8])
            pca.close()

    def test_safe_pwm_does_not_open_i2c_when_actuator_owns_it(self):
        helper=load('safe_pwm',Path('deployment/jetson/set_safe_pwm.py'))
        fake=types.ModuleType('fcntl');fake.LOCK_EX=2;fake.LOCK_NB=4
        fake.flock=MagicMock(side_effect=BlockingIOError('owned'))
        with patch.dict(sys.modules,{'fcntl':fake}),patch('builtins.open',MagicMock()),patch.object(helper,'DirectLinuxPCA9685') as pca:
            helper.main();pca.assert_not_called()

    def test_boot_retry_rate_is_bounded(self):
        text=(ROOT/'systemd/rcboat_ros.service').read_text()
        self.assertIn('StartLimitIntervalSec=120',text)
        self.assertIn('StartLimitBurst=3',text)
        self.assertIn('RestartSec=10',text)
        self.assertIn('ExecStopPost=/usr/bin/timeout 5s',text)
        self.assertNotIn('FailureAction=reboot',text)

    def test_diagnostics_redacts_credentials(self):
        diagnostic=load('diag',Path('deployment/jetson/collect_diagnostics.py'))
        data='PASSWORD=do-not-publish\nAuthorization: Basic abc123\nI2C error -121\n'
        text=diagnostic.redact(data)
        self.assertNotIn('do-not-publish',text);self.assertNotIn('abc123',text)
        self.assertIn('I2C error -121',text)

    def test_diagnostics_command_timeout_is_reported(self):
        diagnostic=load('diag',Path('deployment/jetson/collect_diagnostics.py'))
        with patch.object(diagnostic.subprocess,'run',side_effect=subprocess.TimeoutExpired('journalctl',8)):
            self.assertIn('unavailable',diagnostic.read_command(['journalctl']))


if __name__=='__main__':unittest.main()
