"""Windows-to-Jetson deployment normalization regression tests."""
import importlib.util
import pathlib
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]

class LinuxDeploy(unittest.TestCase):
    def test_lf(self):
        files=list((ROOT/'deployment/jetson').glob('*.sh'))
        files+=list((ROOT/'deployment/jetson').glob('*.py'))
        files+=list((ROOT/'catkin_ws/src/rcboat_ros/nodes').glob('*.py'))
        files+=list((ROOT/'systemd').glob('*.service'))
        self.assertGreaterEqual(len(files),19)
        for path in files:
            with self.subTest(file=path.name):
                self.assertNotIn(b'\r\n',path.read_bytes(),str(path))
    def test_normalizer(self):
        spec=importlib.util.spec_from_file_location('ros_lf_fix',ROOT/'deployment/jetson/normalize_line_endings.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            for rel in ('deployment/jetson','catkin_ws/src/rcboat_ros/nodes','systemd'):
                (root/rel).mkdir(parents=True)
            sh=root/'deployment/jetson/start.sh'
            sh.write_bytes(b'#!/bin/bash\r\nset -Eeuo pipefail\r\n')
            node=root/'catkin_ws/src/rcboat_ros/nodes/gps_node.py'
            node.write_bytes(b'#!/usr/bin/env python3\r\nprint(1)\r\n')
            self.assertEqual(module.normalize(root),(2,1))
            self.assertNotIn(b'\r',sh.read_bytes())
            # Windows chmod does not expose POSIX executable bits; Linux CI checks these.
            if __import__('os').name != 'nt':
                self.assertTrue(node.stat().st_mode & 0o100)
    def test_installer_calls_normalizer(self):
        script=(ROOT/'tools/windows/runner.ps1').read_text(encoding='utf-8')
        self.assertLess(script.index('normalize_line_endings.py'),script.index('install_jetson_ros.sh'))

if __name__=='__main__': unittest.main()
