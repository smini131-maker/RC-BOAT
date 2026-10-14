from __future__ import annotations

import csv
import os
import struct
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rcboat.config import RuntimeSettings
from rcboat.controller import BoatController
from rcboat.gps_health import evaluate_gps_health, navigation_gate_reason
from rcboat.gps_logger import GpsCsvLogger
from rcboat.gps_parser import MixedGpsParser, latlon_to_utm
from rcboat.gps_runtime import UBX_NAV_PVT_POLL
from rcboat.hardware import MockHardware
from rcboat.navigation import RouteManager
from rcboat.ntrip import NtripClient, NtripConfig, build_gga, load_ntrip_env, save_ntrip_env


def nmea(payload: str) -> bytes:
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"${payload}*{checksum:02X}\r\n".encode("ascii")


def ubx_nav_pvt() -> bytes:
    payload = bytearray(92)
    payload[4:6] = (2026).to_bytes(2, "little")
    payload[6:12] = bytes((10, 6, 12, 34, 56, 3))
    payload[20] = 3
    payload[21] = 0x81  # valid fix + RTK fixed
    payload[23] = 18
    struct.pack_into("<i", payload, 24, int(129.086 * 1e7))
    struct.pack_into("<i", payload, 28, int(35.078 * 1e7))
    struct.pack_into("<i", payload, 36, 4200)
    payload[40:44] = (20).to_bytes(4, "little")
    struct.pack_into("<i", payload, 60, 1200)
    struct.pack_into("<i", payload, 64, int(42.5 * 1e5))
    payload[76:78] = (85).to_bytes(2, "little")
    body = bytes((0x01, 0x07)) + len(payload).to_bytes(2, "little") + payload
    ck_a = ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return b"\xb5\x62" + body + bytes((ck_a, ck_b))


def routes_file(directory: str) -> Path:
    path = Path(directory) / "routes.json"
    path.write_text('{"routes":[{"id":"a","waypoints":[{"lat":35.078,"lon":129.086},{"lat":35.079,"lon":129.087}]}]}', encoding="utf-8")
    return path


class ParserTests(unittest.TestCase):
    def test_gga_parser(self) -> None:
        parser = MixedGpsParser()
        parser.feed(nmea("GNGGA,123456.00,3504.6800,N,12905.1600,E,4,12,0.8,4.2,M,0.0,M,,"), 10.0)
        self.assertTrue(parser.data.fix)
        self.assertEqual(parser.data.fix_quality, 4)
        self.assertEqual(parser.data.satellites, 12)
        self.assertAlmostEqual(parser.data.altitude_m or 0, 4.2)

    def test_rmc_parser(self) -> None:
        parser = MixedGpsParser()
        parser.feed(nmea("GNRMC,123456.00,A,3504.6800,N,12905.1600,E,2.0,42.0,061026,,,A"), 10.0)
        self.assertTrue(parser.data.fix)
        self.assertAlmostEqual(parser.data.speed_mps, 1.028888)
        self.assertEqual(parser.data.course_deg, 42.0)

    def test_gsa_parser(self) -> None:
        parser = MixedGpsParser()
        parser.feed(nmea("GNGSA,A,3,01,02,03,04,05,06,07,08,,,,,1.2,0.8,0.9"), 10.0)
        self.assertEqual((parser.data.pdop, parser.data.hdop, parser.data.vdop), (1.2, 0.8, 0.9))

    def test_gsv_cno_average(self) -> None:
        parser = MixedGpsParser()
        parser.feed(nmea("GPGSV,1,1,04,01,45,100,40,02,50,120,42,03,30,200,38,04,20,250,44"), 10.0)
        self.assertEqual(parser.data.cno_avg_dbhz, 41.0)

    def test_malformed_nmea_is_counted(self) -> None:
        parser = MixedGpsParser()
        parser.feed(b"$GNGGA,bad*00\r\n")
        self.assertEqual(parser.data.parser_error_count, 1)

    def test_binary_and_nmea_mixed_stream(self) -> None:
        parser = MixedGpsParser()
        stream = b"garbage" + ubx_nav_pvt() + nmea("GNGGA,123456.00,3504.6800,N,12905.1600,E,4,12,0.8,4.2,M,0.0,M,,")
        parser.feed(stream, 10.0)
        self.assertEqual(parser.data.rtk_state, "RTK_FIXED")
        self.assertEqual(parser.data.ubx_message_count, 1)
        self.assertEqual(parser.data.nav_pvt_message_count, 1)
        self.assertEqual(parser.data.nmea_sentence_count, 1)
        self.assertAlmostEqual(parser.data.hacc_m or 0, 0.02)

    def test_nav_pvt_poll_packet(self) -> None:
        self.assertEqual(
            UBX_NAV_PVT_POLL,
            bytes.fromhex("B5 62 01 07 00 00 08 19"),
        )

    def test_utm_helper(self) -> None:
        try:
            easting, northing, zone = latlon_to_utm(35.078, 129.086)
        except ImportError:
            self.skipTest("pyproj not installed in minimal test runtime")
        self.assertEqual(zone, "52N")
        self.assertGreater(easting, 100000)
        self.assertGreater(northing, 1000000)


class HealthTests(unittest.TestCase):
    def source(self, **overrides):
        data = {"fix": True, "latitude": 35.0, "longitude": 129.0, "satellites": 10, "hdop": 0.8, "pdop": 1.2, "vdop": 1.0, "hacc_m": 0.5, "last_update_monotonic": 100.0, "rtk_state": "NO_RTK"}
        data.update(overrides)
        return data

    def test_no_fix(self) -> None:
        self.assertEqual(evaluate_gps_health(self.source(fix=False), connected=True, now=100.1)["status"], "NO_FIX")

    def test_satellite_good_warning_bad(self) -> None:
        self.assertEqual(evaluate_gps_health(self.source(satellites=8), connected=True, now=100.1)["status"], "GOOD")
        self.assertEqual(evaluate_gps_health(self.source(satellites=6), connected=True, now=100.1)["status"], "WARNING")
        self.assertEqual(evaluate_gps_health(self.source(satellites=5), connected=True, now=100.1)["status"], "BAD")

    def test_hdop_good_warning_bad(self) -> None:
        self.assertEqual(evaluate_gps_health(self.source(hdop=1.5), connected=True, now=100.1)["status"], "GOOD")
        self.assertEqual(evaluate_gps_health(self.source(hdop=2.5), connected=True, now=100.1)["status"], "WARNING")
        self.assertEqual(evaluate_gps_health(self.source(hdop=4.0), connected=True, now=100.1)["status"], "BAD")

    def test_pdop_vdop(self) -> None:
        health = evaluate_gps_health(self.source(pdop=4.5, vdop=2.0), connected=True, now=100.1)
        self.assertEqual(health["status"], "BAD")

    def test_stale(self) -> None:
        self.assertEqual(evaluate_gps_health(self.source(), connected=True, now=103.0)["status"], "STALE")

    def test_vdop_is_relaxed_and_does_not_downgrade_navigation_gate(self) -> None:
        health = evaluate_gps_health(
            self.source(vdop=6.0), connected=True, now=100.1
        )
        self.assertEqual(health["status"], "WARNING")
        self.assertEqual(health["navigation_status"], "GOOD")

    def test_cno_good_warning_bad_thresholds(self) -> None:
        self.assertEqual(
            evaluate_gps_health(
                self.source(cno_avg_dbhz=30.0), connected=True, now=100.1
            )["status"],
            "GOOD",
        )
        self.assertEqual(
            evaluate_gps_health(
                self.source(cno_avg_dbhz=25.0), connected=True, now=100.1
            )["status"],
            "WARNING",
        )
        self.assertEqual(
            evaluate_gps_health(
                self.source(cno_avg_dbhz=24.9), connected=True, now=100.1
            )["status"],
            "BAD",
        )

    def test_low_cno_is_diagnostic_not_propulsion_gate(self) -> None:
        source = self.source(cno_avg_dbhz=20.0, hdop=1.0)
        health = evaluate_gps_health(source, connected=True, now=100.1)
        self.assertEqual(health["status"], "BAD")
        self.assertEqual(health["navigation_status"], "GOOD")
        self.assertIsNone(
            navigation_gate_reason(
                source, health, connected=True, hdop_max=3.0,
                rtk_required=False, correction_age_s=None,
            )
        )


    def test_gate_hdop_and_rtk_falls_back_to_gps(self) -> None:
        source = self.source(hdop=4.0)
        health = evaluate_gps_health(source, connected=True, now=100.1)
        self.assertEqual(navigation_gate_reason(source, health, connected=True, hdop_max=3.0, rtk_required=False, correction_age_s=None), "GPS_HDOP_BAD")
        source = self.source(rtk_state="RTK_FLOAT")
        health = evaluate_gps_health(source, connected=True, now=100.1)
        self.assertIsNone(navigation_gate_reason(source, health, connected=True, hdop_max=3.0, rtk_required=True, correction_age_s=0.1))

    def test_strict_rtk_gate_remains_available_when_fallback_disabled(self) -> None:
        source = self.source(rtk_state="RTK_FLOAT")
        health = evaluate_gps_health(source, connected=True, now=100.1)
        self.assertEqual(
            navigation_gate_reason(
                source, health, connected=True, hdop_max=3.0,
                rtk_required=True, correction_age_s=0.1,
                rtk_fallback_to_gps=False,
            ),
            "RTK_REQUIRED",
        )

    def test_correction_stale(self) -> None:
        source = self.source(rtk_state="RTK_FIXED")
        health = evaluate_gps_health(source, connected=True, now=100.1)
        self.assertEqual(
            navigation_gate_reason(
                source, health, connected=True, hdop_max=3.0,
                rtk_required=True, correction_age_s=12.0,
                rtk_fallback_to_gps=False,
            ),
            "RTK_CORRECTION_STALE",
        )

    def test_stale_rtk_correction_does_not_poison_gps_navigation_health(self) -> None:
        health = evaluate_gps_health(
            self.source(rtk_state="RTK_FLOAT"), connected=True, now=100.1,
            correction_age_s=30.0,
        )
        self.assertEqual(health["status"], "BAD")
        self.assertEqual(health["navigation_status"], "GOOD")


class LoggerAndNtripTests(unittest.TestCase):
    def test_logger_start_write_stop_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = GpsCsvLogger(temp)
            first = logger.start()
            logger.write({"latitude": 35.0, "longitude": 129.0, "gps_health": "GOOD"})
            logger.stop()
            second = logger.start()
            logger.stop()
            self.assertNotEqual(first, second)
            with open(first, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["gps_health"], "GOOD")

    def test_ntrip_env_permission_and_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".ntrip.env"
            config = NtripConfig(True, "caster.example", 2101, "MOUNT", "user", "secret")
            save_ntrip_env(path, config)
            loaded = load_ntrip_env(path)
            self.assertEqual(loaded.password, "secret")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_ntrip_auth_header_and_success(self) -> None:
        class FakeSocket:
            def __init__(self): self.sent = b""; self.parts = [b"ICY 200 OK\r\n\r\n"]
            def settimeout(self, _value): pass
            def sendall(self, data): self.sent += data
            def recv(self, _size): return self.parts.pop(0) if self.parts else b""
            def close(self): pass
        fake = FakeSocket()
        client = NtripClient(NtripConfig(True, "caster.example", 2101, "M", "u", "p"), lambda _data: None)
        with patch("rcboat.ntrip.socket.create_connection", return_value=fake):
            client._connect().close()
        self.assertIn(b"Authorization: Basic", fake.sent)

    def test_ntrip_auth_failure(self) -> None:
        class FakeSocket:
            def settimeout(self, _value): pass
            def sendall(self, _data): pass
            def recv(self, _size): return b"HTTP/1.1 401 Unauthorized\r\n\r\n"
            def close(self): pass
        client = NtripClient(NtripConfig(True, "caster.example", 2101, "M", "u", "bad"), lambda _data: None)
        with patch("rcboat.ntrip.socket.create_connection", return_value=FakeSocket()):
            with self.assertRaises(PermissionError):
                client._connect()

    def test_gga_uplink_format(self) -> None:
        data = build_gga(35.078, 129.086)
        self.assertTrue(data.startswith(b"$GPGGA,"))
        self.assertTrue(data.endswith(b"\r\n"))


class ControllerWeek6Tests(unittest.TestCase):
    def test_navigation_health_gate_and_rtk_loss_uses_gps_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = MockHardware(); hardware.start()
            original = hardware.snapshot
            hardware.snapshot = lambda: replace(original(), gps_quality=1, gps_hdop=4.2)
            controller = BoatController(hardware, RouteManager(routes_file(temp)), RuntimeSettings())
            controller.set_mode("NAVIGATION"); controller.step()
            self.assertEqual(controller.failsafe_reason, "GPS_HDOP_BAD")
            hardware.snapshot = lambda: replace(original(), gps_quality=1, gps_hdop=0.8)
            controller.settings.rtk_required_for_navigation = True
            controller.step()
            self.assertEqual(controller.operation_state, "NAVIGATION_ACTIVE")
            self.assertEqual(controller.failsafe_reason, "")
            self.assertTrue(controller.state()["gps"]["rtk_fallback_active"])

    def test_navigation_rudder_is_inverted_and_large_error_slows_not_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            path.write_text(
                '{"routes":[{"id":"east","name":"East","waypoints":['
                '{"lat":35.078,"lon":129.086},'
                '{"lat":35.078,"lon":129.087}]}]}',
                encoding="utf-8",
            )
            hardware = MockHardware(); hardware.start()
            original = hardware.snapshot
            hardware.snapshot = lambda: replace(
                original(),
                gps_lat=35.078,
                gps_lon=129.086,
                gps_course_deg=0.0,
                gps_hdop=0.8,
                gps_quality=1,
            )
            controller = BoatController(
                hardware, RouteManager(path), RuntimeSettings(auto_cruise_pwm=6650)
            )
            controller.set_mode("NAVIGATION")
            controller.step()
            self.assertEqual(controller.operation_state, "NAVIGATION_ACTIVE")
            self.assertLess(controller.steering_pwm, 6000)
            self.assertGreater(controller.throttle_pwm, 6450)
            self.assertLess(controller.throttle_pwm, 6650)
            route_state = controller.state()["route"]
            self.assertTrue(route_state["navigation_steering_inverted"])
            self.assertGreater(abs(route_state["heading_error_deg"]), 80.0)

    def test_rtk_fixed_navigation_with_fresh_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = MockHardware(); hardware.start()
            hardware.ntrip_status = lambda: {"last_correction_age_s": 0.1, "enabled": True, "connected": True}
            controller = BoatController(hardware, RouteManager(routes_file(temp)), RuntimeSettings(rtk_required_for_navigation=True))
            controller.set_mode("NAVIGATION"); controller.step()
            self.assertEqual(controller.operation_state, "NAVIGATION_ACTIVE")



class RoutePersistenceTests(unittest.TestCase):
    def test_reload_prefers_persisted_selected_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            payload = {
                "selected_route_id": "a",
                "routes": [
                    {"id": "a", "name": "A", "waypoints": [{"lat": 35.0, "lon": 129.0}]},
                    {"id": "b", "name": "B", "waypoints": [{"lat": 35.1, "lon": 129.1}]},
                ],
            }
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            manager = RouteManager(path)
            self.assertEqual(manager.selected.route_id, "a")
            payload["selected_route_id"] = "b"
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            self.assertTrue(manager.load())
            self.assertEqual(manager.selected.route_id, "b")
            self.assertEqual(manager.persisted_selected_route_id, "b")

    def test_saved_recorded_route_is_reloaded_and_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            path.write_text(
                '{"selected_route_id":"a","routes":[{"id":"a","name":"A","waypoints":[{"lat":35.0,"lon":129.0}]}]}',
                encoding="utf-8",
            )
            manager = RouteManager(path)
            manager.start_recording("Recorded", minimum_distance_m=0.1, minimum_interval_s=0.1)
            self.assertTrue(
                manager.record_position(
                    (35.0, 129.0), now=1.0,
                    timestamp="2026-10-13T19:00:00.000+09:00",
                    heading_deg=12.34,
                )
            )
            self.assertTrue(
                manager.record_position(
                    (35.00001, 129.00001), now=2.0,
                    timestamp="2026-10-13T19:00:01.000+09:00",
                    heading_deg=361.0,
                )
            )
            state = manager.recording_state()
            self.assertEqual(state["point_count"], 2)
            self.assertEqual(len(state["waypoints"]), 2)
            self.assertEqual(
                state["latest_sample"]["timestamp"],
                "2026-10-13T19:00:01.000+09:00",
            )
            self.assertEqual(state["latest_sample"]["heading_deg"], 1.0)
            route_id = manager.stop_recording(save=True)
            self.assertIsNotNone(route_id)
            self.assertEqual(manager.selected.route_id, route_id)
            self.assertEqual(manager.persisted_selected_route_id, route_id)
            saved = __import__("json").loads(path.read_text(encoding="utf-8"))
            recorded = next(
                item for item in saved["routes"] if item["id"] == route_id
            )
            self.assertEqual(
                recorded["waypoints"][0]["timestamp"],
                "2026-10-13T19:00:00.000+09:00",
            )
            self.assertEqual(recorded["waypoints"][0]["heading_deg"], 12.34)
            self.assertEqual(recorded["waypoints"][1]["heading_deg"], 1.0)
            public = next(
                item for item in manager.public_routes() if item["id"] == route_id
            )
            self.assertEqual(public["waypoints"][0]["heading_deg"], 12.34)
            self.assertIn("timestamp", public["waypoints"][0])

    def test_legacy_route_without_metadata_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            path.write_text(
                '{"routes":[{"id":"legacy","name":"Legacy","waypoints":['
                '{"lat":35.0,"lon":129.0},{"lat":35.0001,"lon":129.0001}]}]}',
                encoding="utf-8",
            )
            manager = RouteManager(path)
            route = manager.public_routes()[0]
            self.assertEqual(route["id"], "legacy")
            self.assertEqual(route["waypoints"][0], {"lat": 35.0, "lon": 129.0})
            self.assertEqual(len(manager.active.points), 2)

    def test_recorded_route_can_be_deleted_and_selection_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            payload = {
                "selected_route_id": "recorded_x",
                "routes": [
                    {
                        "id": "training_a",
                        "name": "훈련 경로 A",
                        "waypoints": [{"lat": 35.0, "lon": 129.0}],
                    },
                    {
                        "id": "recorded_x",
                        "name": "삭제 대상",
                        "waypoints": [{"lat": 35.1, "lon": 129.1}],
                    },
                ],
            }
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            manager = RouteManager(path)
            deleted = manager.delete_recorded_route("recorded_x")
            self.assertEqual(deleted, "삭제 대상")
            self.assertEqual(manager.selected.route_id, "training_a")
            stored = __import__("json").loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["selected_route_id"], "training_a")
            self.assertNotIn(
                "recorded_x", [str(item.get("id")) for item in stored["routes"]]
            )

    def test_training_route_delete_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            path.write_text(
                '{"selected_route_id":"training_a","routes":['
                '{"id":"training_a","name":"훈련 경로 A","waypoints":[{"lat":35.0,"lon":129.0}]},'
                '{"id":"recorded_x","name":"기록","waypoints":[{"lat":35.1,"lon":129.1}]}]}',
                encoding="utf-8",
            )
            manager = RouteManager(path)
            with self.assertRaises(ValueError):
                manager.delete_recorded_route("training_a")


class MultiPathGroupTests(unittest.TestCase):
    def test_multipath_group_summary_lists_matching_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            payload = {
                "selected_route_id": "a",
                "routes": [
                    {
                        "id": "a", "name": "A",
                        "waypoints": [
                            {"lat": 35.0, "lon": 129.0},
                            {"lat": 35.001, "lon": 129.001},
                        ],
                    },
                    {
                        "id": "b", "name": "B",
                        "waypoints": [
                            {"lat": 35.000001, "lon": 129.0},
                            {"lat": 35.001001, "lon": 129.001},
                        ],
                    },
                    {
                        "id": "far", "name": "Far",
                        "waypoints": [
                            {"lat": 35.01, "lon": 129.01},
                            {"lat": 35.02, "lon": 129.02},
                        ],
                    },
                ],
            }
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            manager = RouteManager(path)
            summary = manager.multipath_group_summary()
            self.assertEqual(summary["reference_route_id"], "a")
            self.assertEqual(summary["group_size"], 2)
            self.assertEqual(
                {item["id"] for item in summary["routes"]},
                {"a", "b"},
            )


class RouteDeleteSafetyTests(unittest.TestCase):
    def test_controller_rejects_route_delete_during_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routes.json"
            payload = {
                "selected_route_id": "recorded_x",
                "routes": [
                    {
                        "id": "training_a",
                        "name": "훈련 경로 A",
                        "waypoints": [{"lat": 35.0, "lon": 129.0}],
                    },
                    {
                        "id": "recorded_x",
                        "name": "기록",
                        "waypoints": [{"lat": 35.1, "lon": 129.1}],
                    },
                ],
            }
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            controller = BoatController(
                MockHardware(), RouteManager(path), RuntimeSettings()
            )
            controller.mode = "NAVIGATION"
            with self.assertRaises(RuntimeError):
                controller.delete_route("recorded_x")


class SafetyRepositoryTests(unittest.TestCase):
    def test_controller_boots_auto_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = MockHardware()
            controller = BoatController(
                hardware, RouteManager(routes_file(temp)), RuntimeSettings()
            )
            self.assertEqual(controller.mode, "AUTO")
            self.assertEqual(controller.operation_state, "AUTO_SAFE")
            self.assertEqual(controller.failsafe_reason, "BOOT_SAFE")
            self.assertEqual(controller.steering_pwm, 6000)
            self.assertEqual(controller.throttle_pwm, 6450)

    def test_fresh_auxiliary_data_does_not_hide_stale_position(self) -> None:
        source = {
            "fix": True,
            "latitude": 35.0,
            "longitude": 129.0,
            "satellites": 10,
            "hdop": 0.8,
            "last_update_monotonic": 99.9,
            "last_valid_fix_monotonic": 95.0,
        }
        health = evaluate_gps_health(source, connected=True, now=100.0)
        self.assertEqual(health["navigation_status"], "STALE")
        self.assertGreater(health["position_age_s"], 2.0)


if __name__ == "__main__":
    unittest.main()
