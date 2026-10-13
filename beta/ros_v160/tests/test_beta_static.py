from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "catkin_ws" / "src" / "rcboat_ros"
sys.path.insert(0, str(PACKAGE / "src"))

from rcboat_ros.gps_parser import MixedGpsParser  # noqa: E402
from rcboat_ros.navigation import RouteManager, angle_error_deg, bearing_deg  # noqa: E402
from rcboat_ros.ros_utils import piecewise_map  # noqa: E402


def nmea(payload: str) -> bytes:
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"${payload}*{checksum:02X}\r\n".encode("ascii")


class LaunchAndOwnershipTests(unittest.TestCase):
    def node_types(self, name: str) -> list[str]:
        root = ET.parse(PACKAGE / "launch" / name).getroot()
        return [node.attrib["type"] for node in root.findall("node")]

    def test_hil_has_no_physical_owner_nodes(self) -> None:
        nodes = self.node_types("rcboat_hil.launch")
        for forbidden in ("actuator_node.py", "gps_node.py", "rc_input_node.py", "ntrip_node.py"):
            self.assertNotIn(forbidden, nodes)
        self.assertIn("mock_hardware_node.py", nodes)

    def test_real_has_exactly_one_hardware_owner_each(self) -> None:
        nodes = self.node_types("rcboat_real.launch")
        for owner in ("actuator_node.py", "gps_node.py", "rc_input_node.py"):
            self.assertEqual(nodes.count(owner), 1)
        self.assertNotIn("mock_hardware_node.py", nodes)

    def test_only_safety_publishes_final_command(self) -> None:
        publishers = []
        marker = 'Publisher("/rcboat/safety/actuator_command"'
        for path in (PACKAGE / "scripts").glob("*.py"):
            if marker in path.read_text(encoding="utf-8"):
                publishers.append(path.name)
        self.assertEqual(publishers, ["safety_supervisor_node.py"])

    def test_systemd_units_conflict(self) -> None:
        real = (ROOT / "systemd" / "rcboat_ros.service").read_text(encoding="utf-8")
        hil = (ROOT / "systemd" / "rcboat_ros_hil.service").read_text(encoding="utf-8")
        self.assertIn("Conflicts=rcboat.service rcboat_ros_hil.service", real)
        self.assertIn("Conflicts=rcboat.service rcboat_ros.service", hil)


class RegressionValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hardware = (PACKAGE / "config" / "hardware.yaml").read_text(encoding="utf-8")

    def test_verified_hardware_values(self) -> None:
        for value in (
            "arduino_baudrate: 9600", "gps_baudrate: 115200", "i2c_bus: 1",
            "pca_address: 64", "pca_frequency_hz: 60", "steering_channel: 0",
            "throttle_channel: 6", "steering_center_pwm: 6000",
            "throttle_reverse_pwm: 5800", "throttle_stop_pwm: 6450",
            "throttle_forward_pwm: 7000", "command_timeout_s: 0.30",
        ):
            self.assertIn(value, self.hardware)

    def test_stable_by_id_paths(self) -> None:
        self.assertIn("/dev/serial/by-id/usb-Arduino__", self.hardware)
        self.assertIn("/dev/serial/by-id/usb-u-blox_AG_", self.hardware)
        self.assertNotIn("/dev/ttyACM", self.hardware)

    def test_manual_mapping_keeps_v160_direction(self) -> None:
        self.assertEqual(piecewise_map(1106, 1106, 1500, 1786, 5800, 6450, 7000), 5800)
        self.assertEqual(piecewise_map(1500, 1106, 1500, 1786, 5800, 6450, 7000), 6450)
        self.assertEqual(piecewise_map(1786, 1106, 1500, 1786, 5800, 6450, 7000), 7000)


class ReusedLogicTests(unittest.TestCase):
    def test_gps_parser_accepts_rtk_gga(self) -> None:
        parser = MixedGpsParser()
        parser.feed(nmea("GNGGA,123456.00,3504.6800,N,12905.1600,E,4,18,0.8,4.2,M,0.0,M,,"), 10.0)
        self.assertTrue(parser.data.fix)
        self.assertEqual(parser.data.fix_quality, 4)
        self.assertEqual(parser.data.rtk_state, "RTK_FIXED")

    def test_bearing_and_wrapped_error(self) -> None:
        self.assertAlmostEqual(bearing_deg((35.0, 129.0), (35.001, 129.0)), 0.0, places=3)
        self.assertEqual(angle_error_deg(5.0, 355.0), 10.0)

    def test_route_manager_reads_legacy_and_record_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            path.write_text(json.dumps({
                "selected_route_id": "legacy",
                "routes": [
                    {"id": "legacy", "name": "legacy", "waypoints": [
                        {"lat": 35.0, "lon": 129.0},
                        {"lat": 35.0001, "lon": 129.0001},
                    ]},
                    {"id": "timed", "name": "timed", "waypoints": [
                        {"lat": 35.0, "lon": 129.0, "timestamp": "2026-10-13T00:00:00+00:00", "heading_deg": 270.5},
                        {"lat": 35.0001, "lon": 129.0001},
                    ]},
                ],
            }), encoding="utf-8")
            manager = RouteManager(path)
            self.assertEqual(manager.selected.route_id, "legacy")
            manager.select("timed")
            self.assertEqual(manager.selected.waypoint_records[0]["heading_deg"], 270.5)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["selected_route_id"], "timed")


class DeliveryTests(unittest.TestCase):
    def test_required_windows_wrappers_exist(self) -> None:
        folder = ROOT / "deployment" / "windows"
        for name in (
            "INSTALL_ROS.cmd", "DEPLOY_ROS.cmd", "USE_ROS.cmd", "USE_DAEMON.cmd",
            "USE_ROS_HIL.cmd", "CHECK_ROS.cmd", "UNINSTALL_ROS_BETA.cmd",
        ):
            self.assertTrue((folder / name).is_file(), name)

    def test_required_documents_exist(self) -> None:
        for name in ("README_KO.md", "ARCHITECTURE.md", "TOPICS_AND_SERVICES.md", "CHANGED_FILES.md", "TEST_REPORT.md", "ROLLBACK.md"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_gui_has_both_backend_ports_and_safe_hil_wording(self) -> None:
        gui = (ROOT / "windows_gui_source" / "windows_app" / "rcboat_gui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn('addItem("ROS Beta", 8876)', gui)
        self.assertIn('addItem("Daemon v1.6", 8765)', gui)
        self.assertNotIn("HIL은 실제 조향·ESC 출력을 발생시킬 수 있습니다", gui)


if __name__ == "__main__":
    unittest.main(verbosity=2)
