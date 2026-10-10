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


if __name__ == "__main__":
    unittest.main()
