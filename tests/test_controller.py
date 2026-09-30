from __future__ import annotations

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from rcboat.config import RuntimeSettings, load_runtime_settings
from rcboat.controller import BoatController, piecewise_map
from rcboat.hardware import MockHardware
from rcboat.navigation import RouteManager


def make_routes(directory: str) -> Path:
    path = Path(directory) / "routes.json"
    path.write_text(
        json.dumps(
            {
                "routes": [
                    {"id": "a", "name": "A", "waypoints": [{"lat": 35.0000, "lon": 129.0000}, {"lat": 35.0001, "lon": 129.0000}, {"lat": 35.0002, "lon": 129.0000}]},
                    {"id": "b", "name": "B", "waypoints": [{"lat": 35.0000, "lon": 129.0000}, {"lat": 35.0001, "lon": 129.0003}, {"lat": 35.0002, "lon": 129.0000}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.hardware = MockHardware()
        self.hardware.start()
        self.routes = RouteManager(make_routes(self.temp.name))
        self.settings = RuntimeSettings(nav_throttle_pwm=None, mock_nav_throttle_pwm=6200)
        self.controller = BoatController(self.hardware, self.routes, self.settings)

    def tearDown(self) -> None:
        self.hardware.close()
        self.temp.cleanup()

    def test_boot_is_manual_and_waits_safely_for_neutral(self) -> None:
        self.controller.step()
        state = self.controller.state()
        self.assertEqual(state["mode"], "MANUAL")
        self.assertFalse(state["navigation_active"])
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))

    def test_auto_to_manual_waits_for_neutral_then_activates(self) -> None:
        self.hardware.set_rc(1640, 1700)
        self.controller.set_mode("MANUAL")
        start = time.monotonic()
        self.controller.step(start)
        self.assertEqual(self.controller.operation_state, "MANUAL_WAITING_NEUTRAL")
        self.assertEqual(self.hardware.last_throttle, 6450)
        self.hardware.set_rc(1640, 1500)
        self.controller.step(start + 0.01)
        self.controller.step(start + 0.32)
        self.assertEqual(self.controller.operation_state, "MANUAL_ACTIVE")

    def test_manual_to_auto_transmitter_gesture(self) -> None:
        self.controller.set_mode("MANUAL")
        self.hardware.set_rc(2000, 1500)
        start = time.monotonic() - 3.1
        self.controller.step(start)
        self.controller.step(time.monotonic())
        self.assertEqual(self.controller.mode, "AUTO")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6650))

    def test_auto_to_manual_transmitter_gesture(self) -> None:
        self.hardware.set_rc(1640, 1500)
        self.controller.set_mode("AUTO")
        self.controller.step()
        self.hardware.set_rc(1640, 1900)
        start = time.monotonic()
        self.controller.step(start)
        self.controller.step(start + 0.51)
        self.assertEqual(self.controller.mode, "MANUAL")
        self.assertEqual(self.controller.operation_state, "MANUAL_WAITING_NEUTRAL")

    def test_gui_auto_mode_is_not_cancelled_by_already_high_throttle(self) -> None:
        self.hardware.set_rc(1640, 1900)
        self.controller.set_mode("AUTO")
        start = time.monotonic() - 0.55
        self.controller.step(start)
        self.controller.step()
        self.assertEqual(self.controller.mode, "AUTO")
        self.assertEqual(self.hardware.last_throttle, 6650)

        self.hardware.set_rc(1640, 1500)
        self.controller.step()
        self.hardware.set_rc(1640, 1900)
        second_start = time.monotonic() - 0.55
        self.controller.step(second_start)
        self.controller.step()
        self.assertEqual(self.controller.mode, "MANUAL")

    def test_auto_speed_apply_changes_active_output_on_next_control_step(self) -> None:
        config_path = Path(self.temp.name) / "boat_config.json"
        config_path.write_text(
            json.dumps({"auto_cruise_pwm": 6650}),
            encoding="utf-8",
        )
        controller = BoatController(
            self.hardware,
            self.routes,
            load_runtime_settings(config_path),
        )
        self.hardware.set_rc(1640, 1500)
        controller.set_mode("AUTO")
        controller.step()
        self.assertEqual(self.hardware.last_throttle, 6650)

        controller.set_auto_cruise_pwm(6700)
        controller.step()
        self.assertEqual(self.hardware.last_throttle, 6700)
        self.assertEqual(controller.state()["auto_cruise_pwm"], 6700)

    def test_navigation_waits_without_gps_and_auto_resumes(self) -> None:
        self.hardware.set_gps(False)
        self.controller.set_mode("NAVIGATION")
        self.controller.step()
        self.assertEqual(self.controller.operation_state, "NAVIGATION_WAITING_GPS")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))
        self.hardware.set_gps(True, True)
        self.controller.step()
        self.assertEqual(self.controller.operation_state, "NAVIGATION_ACTIVE")
        self.assertEqual(self.hardware.last_throttle, 6650)

    def test_navigation_starts_straight_when_stationary_gps_has_no_course(self) -> None:
        original_snapshot = self.hardware.snapshot

        def no_course_snapshot():
            return replace(original_snapshot(), gps_course_deg=None)

        self.hardware.snapshot = no_course_snapshot
        self.controller.set_mode("NAVIGATION")
        self.controller.step()

        self.assertEqual(self.controller.mode, "NAVIGATION")
        self.assertEqual(self.controller.operation_state, "NAVIGATION_ACTIVE")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6650))

    def test_real_navigation_uses_auto_cruise_pwm(self) -> None:
        self.hardware.is_mock = False
        self.controller.set_mode("NAVIGATION")
        self.controller.step()
        self.assertEqual(self.controller.operation_state, "NAVIGATION_ACTIVE")
        self.assertEqual(self.hardware.last_throttle, 6650)

    def test_hil_uses_selected_route_without_real_gps_and_stops_safely(self) -> None:
        self.hardware.set_gps(False)
        self.controller.start_hil("a")
        self.controller.step(self.controller._hil_started_at + 0.5)
        state = self.controller.state()
        self.assertEqual(self.controller.mode, "NAVIGATION")
        self.assertEqual(self.controller.operation_state, "HIL_ACTIVE")
        self.assertTrue(state["hil"]["active"])
        self.assertEqual(self.hardware.last_throttle, 6650)

        self.controller.stop_hil()
        self.controller.step()
        self.assertEqual(self.controller.mode, "AUTO")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))

    def test_gps_route_recording_saves_and_selects_new_route(self) -> None:
        self.routes.start_recording("실험 기록 항로")
        self.assertTrue(self.routes.record_position((35.1, 129.1), now=1.0))
        self.assertTrue(self.routes.record_position((35.10002, 129.1), now=2.0))
        route_id = self.routes.stop_recording(save=True)

        self.assertIsNotNone(route_id)
        self.assertEqual(self.routes.selected.route_id, route_id)
        saved = json.loads(self.routes.route_path.read_text(encoding="utf-8"))
        recorded = next(item for item in saved["routes"] if item["id"] == route_id)
        self.assertEqual(recorded["name"], "실험 기록 항로")
        self.assertEqual(len(recorded["waypoints"]), 2)

    def test_remote_heartbeat_timeout_returns_to_auto_safe(self) -> None:
        self.controller.set_mode("REMOTE")
        self.controller.set_remote_pwm(7300, 5800)
        self.controller.step(self.controller.remote_last_heartbeat + 0.2)
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (7300, 5800))
        self.controller.step(self.controller.remote_last_heartbeat + 0.71)
        self.assertEqual(self.controller.mode, "AUTO")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))

    def test_estop_release_returns_to_auto_without_restoring_throttle(self) -> None:
        self.controller.set_mode("REMOTE")
        self.controller.set_remote_pwm(7300, 5800)
        self.controller.emergency_stop()
        self.controller.clear_estop()
        self.controller.step()
        self.assertEqual(self.controller.mode, "AUTO")
        self.assertFalse(self.controller.estop)
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))

    def test_arduino_loss_returns_manual_to_auto_and_reconnect_allows_retry(self) -> None:
        self.controller.set_mode("MANUAL")
        self.hardware.set_arduino_connected(False)
        self.controller.step()
        self.assertEqual(self.controller.mode, "MANUAL")
        self.assertEqual(self.controller.operation_state, "MANUAL_WAITING_RC")
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))
        self.hardware.set_arduino_connected(True)
        self.hardware.set_rc(1640, 1500)
        self.controller.set_mode("MANUAL")
        self.assertEqual(self.controller.mode, "MANUAL")

    def test_auto_cruise_is_saved_and_used_only_in_normal_auto(self) -> None:
        config_path = Path(self.temp.name) / "boat_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "nav_throttle_pwm": None,
                    "mock_nav_throttle_pwm": 6200,
                    "reconnect_interval_s": 1.0,
                    "auto_cruise_pwm": 6650,
                }
            ),
            encoding="utf-8",
        )
        controller = BoatController(
            self.hardware,
            self.routes,
            load_runtime_settings(config_path),
        )
        controller.set_auto_cruise_pwm(6700)
        controller.set_mode("AUTO")
        controller.step()
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6700))
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["auto_cruise_pwm"], 6700)
        self.assertEqual(controller.state()["auto_cruise_pwm"], 6700)

    def test_auto_cruise_rejects_values_outside_low_speed_range(self) -> None:
        for value in (6479, 6901):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.settings.validate_auto_cruise_pwm(value)

    def test_auto_cruise_never_overrides_remote_timeout_or_estop(self) -> None:
        self.controller.set_mode("REMOTE")
        self.controller.set_remote_pwm(7300, 5800)
        self.controller.step(self.controller.remote_last_heartbeat + 0.71)
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))
        self.controller.emergency_stop()
        self.controller.step()
        self.assertEqual((self.hardware.last_steering, self.hardware.last_throttle), (6000, 6450))

    def test_manual_rejected_without_arduino(self) -> None:
        self.hardware.set_arduino_connected(False)
        with self.assertRaises(RuntimeError):
            self.controller.set_mode("MANUAL")
        self.assertEqual(self.controller.mode, "AUTO")

    def test_exact_piecewise_endpoints(self) -> None:
        self.assertEqual(piecewise_map(1214, 1214, 1640, 2000, 4900, 6000, 7300), 4900)
        self.assertEqual(piecewise_map(1640, 1214, 1640, 2000, 4900, 6000, 7300), 6000)
        self.assertEqual(piecewise_map(2000, 1214, 1640, 2000, 4900, 6000, 7300), 7300)
        self.assertEqual(piecewise_map(1106, 1106, 1500, 1786, 7000, 6450, 5800), 7000)
        self.assertEqual(piecewise_map(1500, 1106, 1500, 1786, 7000, 6450, 5800), 6450)
        self.assertEqual(piecewise_map(1786, 1106, 1500, 1786, 7000, 6450, 5800), 5800)

    def test_manual_throttle_restores_measured_full_forward_output(self) -> None:
        self.hardware.set_rc(1640, 1500)
        self.controller.set_mode("MANUAL")
        start = time.monotonic()
        self.controller.step(start)
        self.controller.step(start + 0.31)
        self.hardware.set_rc(1640, 1786)
        self.controller.step(start + 0.32)
        self.assertEqual(self.controller.operation_state, "MANUAL_ACTIVE")
        self.assertEqual(self.hardware.last_throttle, 5800)
        self.assertEqual(self.controller.state()["manual_throttle_mapping"]["forward_input_us"], 1786)

    def test_multi_path_switch_requires_three_seconds_and_two_metre_advantage(self) -> None:
        point_near_b = (35.0001, 129.0003)
        self.assertEqual(self.routes.update_position(point_near_b, now=10.0)["active_route_id"], "a")
        self.assertEqual(self.routes.update_position(point_near_b, now=12.9)["active_route_id"], "a")
        result = self.routes.update_position(point_near_b, now=13.1)
        self.assertEqual(result["active_route_id"], "b")
        self.assertTrue(result["switched_route"])

    def test_multi_path_only_compares_common_start_and_destination_group(self) -> None:
        self.routes.endpoint_tolerance_m = 0.10
        self.routes.routes[1].points[-1] = (35.0003, 129.0000)
        point_near_b = (35.0001, 129.0003)
        self.routes.update_position(point_near_b, now=10.0)
        result = self.routes.update_position(point_near_b, now=14.0)
        self.assertEqual(result["active_route_id"], "a")
        self.assertEqual(result["multipath_group_route_ids"], ["a"])

    def test_multi_path_can_be_disabled(self) -> None:
        self.routes.multipath_enabled = False
        point_near_b = (35.0001, 129.0003)
        self.routes.update_position(point_near_b, now=10.0)
        result = self.routes.update_position(point_near_b, now=14.0)
        self.assertEqual(result["active_route_id"], "a")

    def test_multi_path_settings_are_validated_and_persisted(self) -> None:
        config_path = Path(self.temp.name) / "boat_config.json"
        config_path.write_text(json.dumps({"auto_cruise_pwm": 6650}), encoding="utf-8")
        controller = BoatController(self.hardware, self.routes, load_runtime_settings(config_path))
        controller.set_multipath({"endpoint_tolerance_m": 0.55, "off_route_hold_s": 2.0})
        saved = json.loads(config_path.read_text(encoding="utf-8"))["multipath"]
        self.assertEqual(saved["endpoint_tolerance_m"], 0.55)
        self.assertEqual(saved["off_route_hold_s"], 2.0)
        self.assertEqual(controller.state()["route"]["multipath"]["endpoint_tolerance_m"], 0.55)
        with self.assertRaises(ValueError):
            controller.set_multipath({"endpoint_tolerance_m": 1.01})


if __name__ == "__main__":
    unittest.main()
