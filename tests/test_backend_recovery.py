from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rcboat.config import RuntimeSettings
from rcboat.controller import BoatController
from rcboat.hardware import (
    MockHardware,
    RealHardware,
    _extract_nmea_sentences,
)
from rcboat.navigation import RouteManager


def nmea(payload: str) -> bytes:
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"${payload}*{checksum:02X}\r\n".encode("ascii")


def route_file(directory: str, routes: list[dict]) -> Path:
    path = Path(directory) / "routes.json"
    path.write_text(json.dumps({"routes": routes}), encoding="utf-8")
    return path


class FailingWriteHardware(MockHardware):
    def write_pwm(self, steering: int, throttle: int) -> None:
        raise OSError("simulated PCA failure")


class BackendRecoveryTests(unittest.TestCase):
    def test_mixed_ubx_nmea_stream_extracts_only_valid_supported_sentences(self) -> None:
        valid_rmc = nmea("GNRMC,095516.50,A,3504.6800,N,12905.1600,E,1.5,42.0,230926,,,A")
        invalid = b"$GNGGA,095516.50,3504.6800,N,12905.1600,E,1,12,0.8,4.2,M,,M,,*00\r\n"
        valid_gga = nmea("GNGGA,095516.50,3504.6800,N,12905.1600,E,1,12,0.8,4.2,M,,M,,")
        buffer = bytearray(b"\xb5\x62\x01\x02garbage" + valid_rmc + b"\xb5\x62" + invalid + valid_gga)

        sentences = _extract_nmea_sentences(buffer)

        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].startswith("$GNRMC"))
        self.assertTrue(sentences[1].startswith("$GNGGA"))

    def test_gps_parser_reports_fix_altitude_hdop_and_last_fix_time(self) -> None:
        hardware = RealHardware(RuntimeSettings())
        hardware._parse_nmea(nmea("GNRMC,095516.50,A,3504.6800,N,12905.1600,E,1.5,42.0,230926,,,A").decode().strip())
        hardware._parse_nmea(nmea("GNGGA,095516.50,3504.6800,N,12905.1600,E,1,12,0.8,4.2,M,,M,,").decode().strip())

        snap = hardware.snapshot()
        self.assertTrue(snap.gps_fix)
        self.assertAlmostEqual(snap.gps_altitude_m or 0.0, 4.2)
        self.assertAlmostEqual(snap.gps_hdop or 0.0, 0.8)
        self.assertGreater(snap.gps_last_fix, 0.0)

    def test_empty_route_file_keeps_navigation_safely_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            routes = RouteManager(route_file(temp, []))
            hardware = MockHardware()
            hardware.start()
            controller = BoatController(hardware, routes, RuntimeSettings())
            controller.set_mode("NAVIGATION")
            controller.step()

            self.assertEqual(controller.operation_state, "NAVIGATION_WAITING_ROUTE")
            self.assertEqual((hardware.last_steering, hardware.last_throttle), (6000, 6450))
            self.assertTrue(routes.load_error)

    def test_multipath_switch_targets_next_point_of_nearest_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            routes = RouteManager(
                route_file(
                    temp,
                    [
                        {"id": "a", "waypoints": [{"lat": 35.0, "lon": 129.0}, {"lat": 35.0006, "lon": 129.0}]},
                        {
                            "id": "b",
                            "waypoints": [
                                {"lat": 35.0, "lon": 129.0},
                                {"lat": 35.0002, "lon": 129.0003},
                                {"lat": 35.0004, "lon": 129.0003},
                                {"lat": 35.0006, "lon": 129.0},
                            ],
                        },
                    ],
                )
            )
            point = (35.0003, 129.0003)
            routes.update_position(point, now=10.0)
            result = routes.update_position(point, now=13.1)

            self.assertTrue(result["switched_route"])
            self.assertEqual(result["active_route_id"], "b")
            self.assertEqual(result["waypoint_index"], 2)
            self.assertEqual(routes.selected.route_id, "a")

    def test_final_waypoint_latches_safe_route_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = MockHardware()
            hardware.start()
            snap = hardware.snapshot()
            routes = RouteManager(
                route_file(
                    temp,
                    [{"id": "goal", "arrival_radius_m": 5.0, "waypoints": [{"lat": snap.gps_lat, "lon": snap.gps_lon}]}],
                )
            )
            controller = BoatController(hardware, routes, RuntimeSettings())
            controller.set_mode("NAVIGATION")
            controller.step()

            self.assertEqual(controller.operation_state, "NAVIGATION_ROUTE_COMPLETE")
            self.assertEqual((hardware.last_steering, hardware.last_throttle), (6000, 6450))
            self.assertTrue(controller.state()["route"]["route_complete"])

    def test_safe_write_failure_does_not_escape_control_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = FailingWriteHardware()
            hardware.start()
            routes = RouteManager(
                route_file(temp, [{"id": "a", "waypoints": [{"lat": 35.0, "lon": 129.0}]}])
            )
            controller = BoatController(hardware, routes, RuntimeSettings())

            controller.step()

            self.assertEqual(controller.mode, "AUTO")
            self.assertTrue(controller.failsafe_reason.startswith("CONTROL_EXCEPTION"))


if __name__ == "__main__":
    unittest.main()
