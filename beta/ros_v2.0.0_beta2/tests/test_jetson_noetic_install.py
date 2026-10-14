"""ROS Noetic Jetson installer: static guards for recurrent failures."""
import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ROSJetsonRegression(unittest.TestCase):
    def test_cmake_order(self):
        c=(ROOT/'catkin_ws/src/rcboat_ros/CMakeLists.txt').read_text(encoding='utf-8')
        self.assertEqual(c.count('catkin_python_setup()'),1)
        self.assertLess(c.index('catkin_python_setup()'),c.index('generate_messages('))
        self.assertLess(c.index('generate_messages('),c.index('catkin_package('))
    def test_no_nounset_while_sourcing_noetic(self):
        for p in ['install_jetson_ros.sh','preflight.sh','check_ros.sh']:
            data=(ROOT/'deployment/jetson'/p).read_bytes()
            with self.subTest(script=p):
                self.assertIn(b'set -Eeo pipefail',data)
                self.assertNotIn(b'set -Eeuo pipefail',data)
                self.assertNotIn(b'\r',data)
    def test_no_old_daemon_stop(self):
        s=(ROOT/'deployment/jetson/install_jetson_ros.sh').read_text()
        self.assertNotIn('systemctl stop rcboat.service',s)
        self.assertNotIn('systemctl start rcboat_ros.service',s)
        self.assertIn('systemctl disable rcboat_ros.service',s)
if __name__=='__main__':unittest.main()
