from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rcboat_gui.main_window import MainWindow


class Week6GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def state(self) -> dict:
        return {
            "mode": "NAVIGATION", "operation_state": "NAVIGATION_ACTIVE",
            "navigation_active": True, "estop": False, "mock": True,
            "failsafe_reason": "", "auto_cruise_pwm": 6650,
            "devices": {"arduino": True, "gps": True, "pca9685": True},
            "rc": {}, "pca": {"steering_pwm": 6000, "throttle_pwm": 6650},
            "gps": {
                "fix": True, "quality": 4, "fix_label": "RTK FIXED",
                "lat": 35.078, "lon": 129.086, "satellites": 18,
                "hdop": 0.8, "pdop": 1.2, "vdop": 1.0,
                "cno_avg_dbhz": 43.0, "hacc_m": 0.02, "age_s": 0.1,
                "last_fix_age_s": 0.1, "rtk_state": "RTK_FIXED",
                "health": {"status": "GOOD", "navigation_status": "GOOD", "rtk_status": "GOOD", "reasons": ["Satellites 18", "HDOP 0.80"]},
                "rtk_fallback_active": False, "navigation_fix_mode": "RTK_FIXED",
                "utm_easting": 508000.0, "utm_northing": 3882000.0, "utm_zone": "52N",
            },
            "ntrip": {"enabled": True, "connected": True, "host": "caster.example", "port": 2101, "mountpoint": "BUS0", "tls": False, "last_correction_age_s": 0.2, "bytes_received": 4096, "last_error": ""},
            "gps_logging": {"active": True, "file_path": "/home/jetson/rcboat/logs/gps/test.csv", "samples": 12},
            "gps_settings": {"navigation_max_hdop": 3.0, "rtk_required_for_navigation": False, "rtk_fallback_to_gps": True},
            "gps_recording": {}, "hil": {}, "route": {}, "routes": [],
            "events": [], "hardware_errors": [],
        }

    def test_gps_health_and_rtk_status_render(self) -> None:
        self.window.update_telemetry(self.state())
        self.assertIn("GOOD", self.window.gps_health_status.text())
        self.assertEqual(self.window.gps_detail_labels["rtk_state"].text(), "RTK_FIXED")
        self.assertIn("연결됨", self.window.ntrip_status.text())
        self.assertIn("12 samples", self.window.gps_log_status.text())

    def test_rtk_loss_is_shown_as_gps_fallback_not_navigation_stop(self) -> None:
        state = self.state()
        state["gps"]["rtk_state"] = "NO_RTK"
        state["gps"]["rtk_fallback_active"] = True
        state["gps"]["navigation_fix_mode"] = "GPS_FALLBACK"
        state["ntrip"]["connected"] = False
        self.window.update_telemetry(state)
        self.assertIn("GPS 대체 운항", self.window.gps_health_status.text())
        self.assertIn("GPS 운항 계속", self.window.gps_detail_labels["rtk_state"].text())
        self.assertTrue(self.window.rtk_fallback.isChecked())

    def test_ntrip_password_is_sent_once_then_cleared(self) -> None:
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "ntrip-request"
        self.window.ntrip_enabled.setChecked(True)
        self.window.ntrip_host.setText("caster.example")
        self.window.ntrip_port.setValue(2101)
        self.window.ntrip_mountpoint.setText("BUS0")
        self.window.ntrip_username.setText("student")
        self.window.ntrip_password.setText("temporary-secret")
        self.window.apply_ntrip()
        self.assertEqual(self.window.ntrip_password.text(), "")
        kwargs = self.window.worker.send_command.call_args.kwargs
        self.assertEqual(kwargs["password"], "temporary-secret")


    def test_ntrip_user_edit_is_not_overwritten_by_telemetry(self) -> None:
        state = self.state()
        state["ntrip"]["enabled"] = False
        self.window.ntrip_enabled.setChecked(True)
        self.assertTrue(self.window._ntrip_dirty)
        self.window.update_telemetry(state)
        self.assertTrue(self.window.ntrip_enabled.isChecked())

    def test_ntrip_ack_releases_editor_for_server_sync(self) -> None:
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "ntrip-request"
        self.window.ntrip_enabled.setChecked(True)
        self.window.ntrip_host.setText("caster.example")
        self.window.ntrip_mountpoint.setText("BUS0")
        self.window.ntrip_username.setText("student")
        self.window.ntrip_password.setText("temporary-secret")
        self.window.apply_ntrip()
        self.assertEqual(self.window._pending_ntrip_request, "ntrip-request")
        self.window.on_ack({
            "type": "ack", "ok": True, "command": "CONFIGURE_NTRIP",
            "request_id": "ntrip-request",
        })
        self.assertFalse(self.window._ntrip_dirty)
        self.assertIsNone(self.window._pending_ntrip_request)
        self.assertTrue(self.window.ntrip_apply.isEnabled())

    def test_gps_threshold_ranges_are_visible(self) -> None:
        text = self.window.gps_range_note.text()
        self.assertIn("위성 좋음 ≥8", text)
        self.assertIn("HDOP 좋음 ≤2", text)
        self.assertIn("VDOP ≤5", text)
        self.assertIn("C/N0 ≥40", text)
        self.assertIn("RTK 보정 age ≤5", text)


    def test_route_editor_is_not_overwritten_before_apply(self) -> None:
        state = self.state()
        state["route"] = {
            "active_route_id": "training_a",
            "selected_route_id": "training_a",
            "selected_route_name": "훈련 경로 A",
            "active_route_name": "훈련 경로 A",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "training_a",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        state["routes"] = [
            {"id": "training_a", "name": "훈련 경로 A", "waypoints": []},
            {"id": "training_b", "name": "훈련 경로 B", "waypoints": []},
        ]
        self.window.update_telemetry(state)
        self.window.route_combo.setCurrentIndex(
            self.window.route_combo.findData("training_b")
        )
        self.assertTrue(self.window._route_dirty)
        self.window.update_telemetry(state)
        self.assertEqual(self.window.route_combo.currentData(), "training_b")

    def test_route_apply_waits_for_telemetry_confirmation(self) -> None:
        state = self.state()
        state["route"] = {
            "active_route_id": "training_a",
            "selected_route_id": "training_a",
            "selected_route_name": "훈련 경로 A",
            "active_route_name": "훈련 경로 A",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "training_a",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        state["routes"] = [
            {"id": "training_a", "name": "훈련 경로 A", "waypoints": []},
            {"id": "training_b", "name": "훈련 경로 B", "waypoints": []},
        ]
        self.window.update_telemetry(state)
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "route-request"
        self.window.route_combo.setCurrentIndex(
            self.window.route_combo.findData("training_b")
        )
        self.window.select_route()
        self.assertEqual(self.window.pending_route_id, "training_b")
        self.assertFalse(self.window.route_select_button.isEnabled())
        self.window.on_ack({
            "type": "ack", "ok": True, "command": "SELECT_ROUTE",
            "request_id": "route-request",
        })
        state["route"]["active_route_id"] = "training_b"
        state["route"]["selected_route_id"] = "training_b"
        state["route"]["selected_route_name"] = "훈련 경로 B"
        state["route"]["active_route_name"] = "훈련 경로 B"
        state["route"]["persisted_selected_route_id"] = "training_b"
        self.window.update_telemetry(state)
        self.assertIsNone(self.window.pending_route_id)
        self.assertTrue(self.window.route_select_button.isEnabled())
        self.assertEqual(self.window.route_combo.currentData(), "training_b")

    def test_recorded_route_ack_is_added_and_selected(self) -> None:
        state = self.state()
        state["route"] = {
            "active_route_id": "training_a",
            "selected_route_id": "training_a",
            "selected_route_name": "훈련 경로 A",
            "active_route_name": "훈련 경로 A",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "training_a",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        state["routes"] = [
            {"id": "training_a", "name": "훈련 경로 A", "waypoints": []},
        ]
        self.window.update_telemetry(state)
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "reload-request"
        self.window.on_ack({
            "type": "ack", "ok": True, "command": "STOP_GPS_RECORDING",
            "request_id": "record-stop", "route_id": "recorded_20261013_180000",
        })
        self.assertEqual(self.window.pending_route_id, "recorded_20261013_180000")
        state["routes"].append({
            "id": "recorded_20261013_180000",
            "name": "새 기록 항로",
            "waypoints": [],
        })
        state["route"].update({
            "active_route_id": "recorded_20261013_180000",
            "selected_route_id": "recorded_20261013_180000",
            "selected_route_name": "새 기록 항로",
            "active_route_name": "새 기록 항로",
            "persisted_selected_route_id": "recorded_20261013_180000",
        })
        self.window.update_telemetry(state)
        self.assertGreaterEqual(
            self.window.route_combo.findData("recorded_20261013_180000"), 0
        )
        self.assertEqual(
            self.window.route_combo.currentData(), "recorded_20261013_180000"
        )

    def test_terminal_ready_does_not_force_tab_change(self) -> None:
        gps_tab_index = 1
        self.window.tabs.setCurrentIndex(gps_tab_index)
        self.window.on_terminal_state(True, "jetson@10.69.235.215")
        self.assertEqual(self.window.tabs.currentIndex(), gps_tab_index)

    def test_ntrip_status_changes_are_written_to_log(self) -> None:
        state = self.state()
        state["ntrip"]["enabled"] = False
        state["ntrip"]["connected"] = False
        self.window.update_telemetry(state)
        state["ntrip"]["enabled"] = True
        state["ntrip"]["connected"] = True
        state["ntrip"]["bytes_received"] = 1024
        self.window.update_telemetry(state)
        log_text = self.window.logs.toPlainText()
        self.assertIn("RTK/NTRIP 상태 변경", log_text)
        self.assertIn("RTK 보정 데이터 수신 시작", log_text)


    def test_bad_gps_shows_primary_reason(self) -> None:
        state = self.state()
        state["gps"]["health"] = {
            "status": "BAD",
            "navigation_status": "BAD",
            "rtk_status": "UNAVAILABLE",
            "reasons": ["Satellites 12", "HDOP 2.20 (warning)", "C/N0 17.6 dB-Hz (low)"],
        }
        self.window.update_telemetry(state)
        self.assertIn("주요 원인", self.window.gps_health_primary_reason.text())
        self.assertIn("C/N0 17.6", self.window.gps_health_primary_reason.text())

    def test_main_control_surface_is_scrollable(self) -> None:
        from PySide6.QtWidgets import QScrollArea
        self.assertIsInstance(self.window.centralWidget(), QScrollArea)
        self.assertTrue(self.window.centralWidget().widgetResizable())


    def test_ntrip_404_shows_mountpoint_fix(self) -> None:
        state = self.state()
        state["ntrip"].update({
            "enabled": True,
            "connected": False,
            "mountpoint": "VRS_RTCM32",
            "last_error": "NTRIP caster rejected request: HTTP/1.1 404 Mountpoint of request not found",
        })
        self.window.update_telemetry(state)
        self.assertIn("Mount Point 없음(404)", self.window.ntrip_status.text())
        self.assertTrue(self.window.ntrip_mount_fix.isVisible())

    def test_recommended_mountpoint_button_sets_hyphen_value(self) -> None:
        self.window.ntrip_mountpoint.setText("VRS_RTCM32")
        self.window.apply_recommended_mountpoint()
        self.assertEqual(self.window.ntrip_mountpoint.text(), "VRS-RTCM32")
        self.assertTrue(self.window._ntrip_dirty)

if __name__ == "__main__":
    unittest.main()
