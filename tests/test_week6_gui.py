from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

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
        self.assertIn("좋음", self.window.gps_health_status.text())
        self.assertEqual(self.window.gps_detail_labels["rtk_state"].text(), "RTK_FIXED")
        self.assertEqual(self.window.ntrip_link_card.value_label.text(), "연결됨")
        self.assertIn("12 samples", self.window.gps_log_status.text())

    def test_rtk_loss_is_shown_as_gps_fallback_not_navigation_stop(self) -> None:
        state = self.state()
        state["gps"]["rtk_state"] = "NO_RTK"
        state["gps"]["fix_label"] = "DGPS"
        state["gps"]["rtk_fallback_active"] = True
        state["gps"]["navigation_fix_mode"] = "GPS_FALLBACK"
        state["ntrip"]["connected"] = False
        self.window.update_telemetry(state)
        self.assertIn("GPS 기반 항법", self.window.gps_health_status.text())
        self.assertIn("DGPS · GPS 기반 운항", self.window.gps_detail_labels["rtk_state"].text())
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
        self.assertIn("≥8 좋음", self.window.gps_metric_cards["satellites"].hint_label.text())
        self.assertIn("≤2 좋음", self.window.gps_metric_cards["hdop"].hint_label.text())
        self.assertIn("≤5 양호", self.window.gps_metric_cards["vdop"].hint_label.text())
        self.assertIn("25~29 주의", self.window.gps_metric_cards["cno"].hint_label.text())
        self.assertIn("≤5 s 좋음", self.window.gps_metric_cards["correction_age"].hint_label.text())


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
        self.assertIn("RTK 상태 변경", log_text)
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
        self.assertIn("가장 큰 영향", self.window.gps_health_primary_reason.text())
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
        self.assertFalse(self.window.ntrip_mount_fix.isHidden())

    def test_recommended_mountpoint_button_sets_hyphen_value(self) -> None:
        self.window.ntrip_mountpoint.setText("VRS_RTCM32")
        self.window.apply_recommended_mountpoint()
        self.assertEqual(self.window.ntrip_mountpoint.text(), "VRS-RTCM32")
        self.assertTrue(self.window._ntrip_dirty)


    def test_route_map_excludes_training_routes_and_has_layer_switches(self) -> None:
        state = self.state()
        state["routes"] = [
            {
                "id": "training_a", "name": "훈련 경로 A",
                "waypoints": [{"lat": 35.0, "lon": 129.0}, {"lat": 35.0001, "lon": 129.0001}],
            },
            {
                "id": "recorded_test", "name": "실제 기록",
                "waypoints": [{"lat": 35.0, "lon": 129.0}, {"lat": 35.0001, "lon": 129.0001}],
            },
        ]
        state["route"] = {
            "active_route_id": "recorded_test",
            "selected_route_id": "recorded_test",
            "selected_route_name": "실제 기록",
            "active_route_name": "실제 기록",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "recorded_test",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        self.window.update_telemetry(state)
        self.assertNotIn("training_a", self.window.route_layer_checks)
        self.assertIn("recorded_test", self.window.route_layer_checks)
        self.assertNotIn("training_a", self.window.route_plot.visible_route_ids())
        self.assertIn("recorded_test", self.window.route_plot.visible_route_ids())

    def test_live_recording_points_are_sent_to_route_plot(self) -> None:
        state = self.state()
        state["gps_recording"] = {
            "active": True,
            "name": "테스트 기록",
            "point_count": 2,
            "arrival_radius_m": 3.0,
            "waypoints": [
                {"lat": 35.0, "lon": 129.0},
                {"lat": 35.0001, "lon": 129.0001},
            ],
        }
        self.window.update_telemetry(state)
        route_ids = {str(route.get("id")) for route in self.window.route_plot.routes}
        self.assertIn("__recording__", route_ids)

    def test_ntrip_link_and_solution_update_independently(self) -> None:
        state = self.state()
        state["gps"]["rtk_state"] = "RTK_FLOAT"
        state["gps"]["fix_label"] = "RTK FLOAT"
        state["ntrip"]["connected"] = True
        self.window.update_telemetry(state)
        self.assertEqual(self.window.ntrip_link_card.value_label.text(), "연결됨")
        self.assertIn("RTK Float", self.window.ntrip_solution_card.value_label.text())

        state["gps"]["rtk_state"] = "NO_RTK"
        state["gps"]["fix_label"] = "DGPS"
        self.window.update_telemetry(state)
        self.assertEqual(self.window.ntrip_link_card.value_label.text(), "연결됨")
        self.assertIn("DGPS · RTK 미고정", self.window.ntrip_solution_card.value_label.text())

    def test_selected_route_can_export_to_json(self) -> None:
        state = self.state()
        state["routes"] = [
            {
                "id": "recorded_export", "name": "내 항로",
                "arrival_radius_m": 3.0,
                "waypoints": [
                    {
                        "timestamp": "2026-10-13T19:10:00.000+09:00",
                        "lat": 35.0, "lon": 129.0, "heading_deg": 10.5,
                    },
                    {
                        "timestamp": "2026-10-13T19:10:01.000+09:00",
                        "lat": 35.0001, "lon": 129.0001, "heading_deg": 11.25,
                    },
                ],
            }
        ]
        state["route"] = {
            "active_route_id": "recorded_export",
            "selected_route_id": "recorded_export",
            "selected_route_name": "내 항로",
            "active_route_name": "내 항로",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "recorded_export",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        self.window.update_telemetry(state)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "route.json"
            with patch(
                "rcboat_gui.main_window.QFileDialog.getSaveFileName",
                return_value=(str(destination), "JSON (*.json)"),
            ), patch("rcboat_gui.main_window.QMessageBox.information"):
                self.window.export_selected_route()
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(payload["id"], "recorded_export")
            self.assertEqual(len(payload["waypoints"]), 2)
            self.assertEqual(
                payload["waypoints"][0]["timestamp"],
                "2026-10-13T19:10:00.000+09:00",
            )
            self.assertEqual(payload["waypoints"][0]["heading_deg"], 10.5)

    def test_selected_route_csv_export_contains_time_and_heading(self) -> None:
        state = self.state()
        state["routes"] = [
            {
                "id": "recorded_csv", "name": "CSV 경로",
                "arrival_radius_m": 3.0,
                "waypoints": [
                    {
                        "timestamp": "2026-10-13T19:20:00.000+09:00",
                        "lat": 35.0, "lon": 129.0, "heading_deg": 270.0,
                    },
                    {
                        "timestamp": "2026-10-13T19:20:01.000+09:00",
                        "lat": 35.0001, "lon": 129.0001, "heading_deg": None,
                    },
                ],
            }
        ]
        state["route"] = {
            "active_route_id": "recorded_csv",
            "selected_route_id": "recorded_csv",
            "selected_route_name": "CSV 경로",
            "active_route_name": "CSV 경로",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "recorded_csv",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        self.window.update_telemetry(state)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "route.csv"
            with patch(
                "rcboat_gui.main_window.QFileDialog.getSaveFileName",
                return_value=(str(destination), "CSV (*.csv)"),
            ), patch("rcboat_gui.main_window.QMessageBox.information"):
                self.window.export_selected_route()
            content = destination.read_text(encoding="utf-8-sig")
            self.assertIn(
                "index,timestamp,latitude,longitude,heading_deg", content
            )
            self.assertIn("2026-10-13T19:20:00.000+09:00", content)
            self.assertIn(",270.00", content)

    def test_delete_recorded_route_sends_daemon_command(self) -> None:
        state = self.state()
        state["mode"] = "AUTO"
        state["operation_state"] = "AUTO_SAFE"
        state["navigation_active"] = False
        state["routes"] = [
            {
                "id": "recorded_delete", "name": "삭제할 항로",
                "waypoints": [{"lat": 35.0, "lon": 129.0}],
            }
        ]
        state["route"] = {
            "active_route_id": "recorded_delete",
            "selected_route_id": "recorded_delete",
            "selected_route_name": "삭제할 항로",
            "active_route_name": "삭제할 항로",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "recorded_delete",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {},
        }
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "delete-request"
        self.window.update_telemetry(state)
        with patch(
            "rcboat_gui.main_window.QMessageBox.warning",
            return_value=QMessageBox.Yes,
        ):
            self.window.delete_selected_route()
        self.window.worker.send_command.assert_called_with(
            "DELETE_ROUTE", route_id="recorded_delete"
        )


    def test_hacc_waiting_shows_ubx_counter_hint(self) -> None:
        state = self.state()
        state["gps"]["hacc_m"] = None
        state["gps"]["ubx_message_count"] = 0
        state["gps"]["nmea_sentence_count"] = 123
        state["gps"]["hacc_source"] = "UBX-NAV-PVT 대기"
        self.window.update_telemetry(state)
        self.assertEqual(
            self.window.gps_metric_cards["hacc"].value_label.text(),
            "NAV-PVT 대기",
        )
        hint = self.window.gps_metric_cards["hacc"].hint_label.text()
        self.assertIn("UBX 0", hint)
        self.assertIn("NMEA 123", hint)

    def test_multipath_group_names_are_readable(self) -> None:
        state = self.state()
        state["route"] = {
            "active_route_id": "recorded_a",
            "active_route_name": "A 경로",
            "selected_route_id": "recorded_a",
            "selected_route_name": "A 경로",
            "selected_route_persisted": True,
            "persisted_selected_route_id": "recorded_a",
            "storage_path": "/home/jetson/rcboat/routes.json",
            "multipath_config_path": "/home/jetson/rcboat/boat_config.json",
            "multipath": {
                "enabled": True,
                "endpoint_tolerance_m": 0.75,
                "off_route_distance_m": 8.0,
                "off_route_hold_s": 3.0,
                "closer_advantage_m": 2.0,
                "switch_cooldown_s": 5.0,
            },
            "multipath_group": {
                "reference_route_id": "recorded_a",
                "reference_route_name": "A 경로",
                "active_route_id": "recorded_b",
                "active_route_name": "B 경로",
                "group_size": 2,
                "routes": [
                    {
                        "id": "recorded_a", "name": "A 경로",
                        "start_gap_m": 0.0, "end_gap_m": 0.0,
                    },
                    {
                        "id": "recorded_b", "name": "B 경로",
                        "start_gap_m": 0.3, "end_gap_m": 0.4,
                    },
                ],
            },
        }
        state["routes"] = [
            {"id": "recorded_a", "name": "A 경로", "waypoints": []},
            {"id": "recorded_b", "name": "B 경로", "waypoints": []},
        ]
        self.window.update_telemetry(state)
        text = self.window.multipath_group_status.text()
        self.assertIn("A 경로", text)
        self.assertIn("B 경로", text)
        self.assertIn("같은 그룹 2개", text)

if __name__ == "__main__":
    unittest.main()
