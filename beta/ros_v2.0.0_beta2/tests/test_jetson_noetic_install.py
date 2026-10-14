"""ROS Noetic Jetson installer: static guards for recurrent failures."""
import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ROSJetsonRegression(unittest.TestCase):
    def test_cmake_order(self):
        c=(ROOT/'catkin_ws/src/rcboat_ros/CMakeLists.txt').read_text(encoding='utf-8')
        self.assertEqual(c.count('catkin_python_setup()'),1)
        self.assertLess(c.index('catkin_python_setup()'),c.index('generate_messages('))
        self.assertLess(c.index('catkin_python_setup()'),c.index('add_message_files('))
        self.assertLess(c.index('generate_messages('),c.index('catkin_package('))
    def test_catkin_package_xml_declares_all_cmake_components_at_build_time(self):
        from xml.etree import ElementTree as ET
        package=ET.fromstring((ROOT/'catkin_ws/src/rcboat_ros/package.xml').read_text(encoding='utf-8'))
        cmake=(ROOT/'catkin_ws/src/rcboat_ros/CMakeLists.txt').read_text(encoding='utf-8')
        import re
        found=re.search(r'find_package\(catkin\s+REQUIRED\s+COMPONENTS\s+([^\)]+)\)',cmake)
        self.assertIsNotNone(found,'CMakeLists must have find_package(catkin REQUIRED COMPONENTS ...)')
        required=set(found.group(1).split())
        build=set()
        execute=set()
        for x in package:
            if x.tag in ('depend','build_depend','build_export_depend'):
                build.add(x.text.strip())
            if x.tag in ('depend','exec_depend'):
                execute.add(x.text.strip())
        self.assertEqual(package.findtext('name'),'rcboat_ros')
        self.assertFalse(required-build,'Missing build dependencies in package.xml: '+repr(required-build))
        self.assertTrue({'rospy','std_msgs'}.issubset(execute),'Runtime package dependencies missing')
        self.assertIn('message_generation',build)
        self.assertIn('message_runtime',execute)
        self.assertEqual(ET.tostring(package).count(b'<depend>rospy</depend>'),1)

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
