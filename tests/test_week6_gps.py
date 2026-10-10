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
        self.assertEqual(parser.data.nmea_sentence_count, 1)
        self.assertAlmostEqual(parser.data.hacc_m or 0, 0.02)

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

    def test_rtk_fixed_navigation_with_fresh_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hardware = MockHardware(); hardware.start()
            hardware.ntrip_status = lambda: {"last_correction_age_s": 0.1, "enabled": True, "connected": True}
            controller = BoatController(hardware, RouteManager(routes_file(temp)), RuntimeSettings(rtk_required_for_navigation=True))
            controller.set_mode("NAVIGATION"); controller.step()
            self.assertEqual(controller.operation_state, "NAVIGATION_ACTIVE")


if __name__ == "__main__":
    unittest.main()
