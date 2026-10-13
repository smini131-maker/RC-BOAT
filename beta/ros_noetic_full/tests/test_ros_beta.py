from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "catkin_ws" / "src" / "rcboat_core" / "src"
sys.path.insert(0, str(CORE_SRC))

from rcboat_core.constants import VALUES  # noqa: E402
from rcboat_core.controller_logic import ControllerLogic, GpsSample, RcSample  # noqa: E402
from rcboat_core.navigation import RouteManager, position_along_route  # noqa: E402
from rcboat_core.ntrip_protocol import build_gga, nmea_coordinate, pop_rtcm_frames  # noqa: E402


def make_routes(directory: str) -> Path:
    path = Path(directory) / "routes.json"
    path.write_text(
        json.dumps(
            {
                "selected_route_id": "a",
                "routes": [
                    {
                        "id": "a",
                        "name": "A",
                        "arrival_radius_m": 3.0,
                        "waypoints": [
                            {"lat": 35.0, "lon": 129.0},
                            {"lat": 35.0002, "lon": 129.0},
                        ],
                    },
                    {
                        "id": "b",
                        "name": "B",
                        "arrival_radius_m": 3.0,
                        "waypoints": [
                            {"lat": 35.0, "lon": 129.0},
                            {"lat": 35.0001, "lon": 129.0003},
                            {"lat": 35.0002, "lon": 129.0},
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class ControllerLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        multipath = {
            "enabled": True,
            "endpoint_tolerance_m": 0.75,
            "off_route_distance_m": 8.0,
            "off_route_hold_s": 3.0,
            "closer_advantage_m": 2.0,
            "switch_cooldown_s": 5.0,
        }
        self.routes = RouteManager(make_routes(self.temp.name), multipath)
        self.settings = {
            "auto_cruise_pwm": 6650,
            "gps_stale_s": 2.0,
            "navigation_max_hdop": 3.0,
            "rtk_required_for_navigation": False,
            "rtk_fallback_to_gps": True,
            "rtk_correction_max_age_s": 10.0,
        }
        self.logic = ControllerLogic(self.routes, self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_boot_is_manual_and_safe(self) -> None:
        self.assertEqual(self.logic.mode, "MANUAL")
        self.assertEqual(self.logic.step(10.0), (6000, 6450))
        self.assertEqual(self.logic.operation_state, "MANUAL_WAITING_RC")

    def test_manual_neutral_rearm_and_mapping(self) -> None:
        self.logic.update_rc(RcSample(True, 1640, 1500, 10.0))
        self.logic.step(10.0)
        self.logic.step(10.31)
        self.assertEqual(self.logic.operation_state, "MANUAL_ACTIVE")
        self.logic.update_rc(RcSample(True, 2000, 1786, 10.32))
        steering, throttle = self.logic.step(10.32)
        self.assertEqual(steering, 7300)
        self.assertEqual(throttle, 7000)

    def test_manual_rc_loss_stays_manual_and_safe(self) -> None:
        self.logic.update_rc(RcSample(True, 1640, 1500, 10.0))
        self.logic.step(11.0)
        self.assertEqual(self.logic.mode, "MANUAL")
        self.assertEqual(self.logic.operation_state, "MANUAL_WAITING_RC")
        self.assertEqual((self.logic.steering_pwm, self.logic.throttle_pwm), (6000, 6450))

    def test_remote_timeout_returns_auto_safe(self) -> None:
        self.logic.set_mode("REMOTE", 10.0)
        self.logic.set_remote_pwm(7300, 5800)
        self.assertEqual(self.logic.step(10.6), (7300, 5800))
        self.assertEqual(self.logic.step(10.71), (6000, 6450))
        self.assertEqual(self.logic.mode, "AUTO")
        self.assertEqual(self.logic.failsafe_reason, "REMOTE_HEARTBEAT_TIMEOUT")

    def test_navigation_allows_ordinary_gps_fallback(self) -> None:
        self.settings["rtk_required_for_navigation"] = True
        self.settings["rtk_fallback_to_gps"] = True
        self.logic.set_mode("NAVIGATION", 10.0)
        self.logic.update_gps(
            GpsSample(True, True, 35.0, 129.0, 0.0, 0.8, "GOOD", "NO_RTK", math.inf, 10.0)
        )
        _, throttle = self.logic.step(10.1)
        self.assertEqual(throttle, 6650)
        self.assertEqual(self.logic.operation_state, "NAVIGATION_ACTIVE")

    def test_navigation_can_require_fresh_rtk(self) -> None:
        self.settings["rtk_required_for_navigation"] = True
        self.settings["rtk_fallback_to_gps"] = False
        self.logic.set_mode("NAVIGATION", 10.0)
        self.logic.update_gps(
            GpsSample(True, True, 35.0, 129.0, 0.0, 0.8, "GOOD", "NO_RTK", math.inf, 10.0)
        )
        self.assertEqual(self.logic.step(10.1), (6000, 6450))
        self.assertEqual(self.logic.failsafe_reason, "RTK_REQUIRED")

    def test_estop_latches_safe_output(self) -> None:
        self.logic.set_mode("REMOTE", 10.0)
        self.logic.set_remote_pwm(7300, 7000)
        self.logic.emergency_stop()
        self.assertEqual(self.logic.step(10.1), (6000, 6450))
        self.assertTrue(self.logic.estop)
        with self.assertRaises(RuntimeError):
            self.logic.set_mode("MANUAL", 10.2)


class NtripProtocolTests(unittest.TestCase):
    def test_gga_coordinates_and_checksum(self) -> None:
        self.assertEqual(nmea_coordinate(35.5, True), ("3530.0000", "N"))
        self.assertEqual(nmea_coordinate(-129.25, False), ("12915.0000", "W"))
        sentence = build_gga(35.5, 129.25)
        body, checksum = sentence.strip()[1:].split(b"*")
        calculated = 0
        for byte in body:
            calculated ^= byte
        self.assertEqual(int(checksum, 16), calculated)

    def test_rtcm_fragment_reassembly(self) -> None:
        frame = b"\xd3\x00\x03abcXYZ"
        buffer = bytearray(b"noise" + frame[:5])
        self.assertEqual(pop_rtcm_frames(buffer), [])
        buffer.extend(frame[5:] + frame)
        self.assertEqual(pop_rtcm_frames(buffer), [frame, frame])
        self.assertEqual(buffer, bytearray())


class HilGeometryTests(unittest.TestCase):
    def test_position_along_route_interpolates_and_stops_at_destination(self) -> None:
        points = [(35.0, 129.0), (35.0001, 129.0)]
        midpoint, course = position_along_route(points, 5.5)
        self.assertGreater(midpoint[0], points[0][0])
        self.assertLess(midpoint[0], points[1][0])
        self.assertAlmostEqual(course, 0.0, delta=0.1)
        end, _course = position_along_route(points, 1000.0)
        self.assertEqual(end, points[-1])


class ConfigurationTests(unittest.TestCase):
    def test_safety_constants_match_production_contract(self) -> None:
        self.assertEqual((VALUES.steering_channel, VALUES.throttle_channel), (0, 6))
        self.assertEqual(
            (VALUES.steering_low_pwm, VALUES.steering_center_pwm, VALUES.steering_high_pwm),
            (4900, 6000, 7300),
        )
        self.assertEqual(
            (VALUES.throttle_reverse_pwm, VALUES.throttle_stop_pwm, VALUES.throttle_forward_pwm),
            (5800, 6450, 7000),
        )
        self.assertEqual(VALUES.remote_heartbeat_timeout_s, 0.7)

    def test_windows_gui_uses_ros_gateway_tree_only(self) -> None:
        gui_root = ROOT / "windows_gui_source"
        worker = (
            gui_root / "windows_app" / "rcboat_gui" / "ssh_worker.py"
        ).read_text(encoding="utf-8")
        gateway = (
            ROOT
            / "catkin_ws"
            / "src"
            / "rcboat_core"
            / "scripts"
            / "gui_gateway_node.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ROS_GUI_GATEWAY_PORT = 8876", worker)
        self.assertNotIn("127.0.0.1\", 8765", worker)
        self.assertIn('{"127.0.0.1", "::1", "localhost"}', gateway)
        self.assertNotIn("rcboat_daemon", gateway)
        for command in (
            "SET_MODE",
            "EMERGENCY_STOP",
            "REMOTE_CONTROL",
            "SELECT_ROUTE",
            "CONFIGURE_NTRIP",
            "START_GPS_LOGGING",
        ):
            self.assertIn(f'"{command}"', gateway)


if __name__ == "__main__":
    unittest.main()