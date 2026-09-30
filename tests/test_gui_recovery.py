from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import paramiko
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from rcboat_gui.main_window import MainWindow
from rcboat_gui.mock_worker import MockWorker
from rcboat_gui.ssh_worker import SSHWorker, clean_terminal_output, host_key_fingerprint


class CapturingChannel:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def sendall(self, payload: bytes) -> None:
        self.messages.append(json.loads(payload.decode("utf-8")))


class GuiRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def test_keyboard_remote_press_and_release_returns_to_safe_axes(self) -> None:
        self.window.current_mode = "REMOTE"
        with patch.object(self.window, "send_remote") as send:
            self.window.eventFilter(
                self.window,
                QKeyEvent(QEvent.KeyPress, Qt.Key_W, Qt.NoModifier),
            )
            self.window.eventFilter(
                self.window,
                QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier),
            )
            self.assertEqual(self.window.remote_throttle.value(), 5800)
            self.assertEqual(self.window.remote_steering.value(), 4900)

            self.window.eventFilter(
                self.window,
                QKeyEvent(QEvent.KeyRelease, Qt.Key_W, Qt.NoModifier),
            )
            self.window.eventFilter(
                self.window,
                QKeyEvent(QEvent.KeyRelease, Qt.Key_A, Qt.NoModifier),
            )
            self.assertEqual(self.window.remote_throttle.value(), 6450)
            self.assertEqual(self.window.remote_steering.value(), 6000)
            self.assertGreaterEqual(send.call_count, 4)

    def test_simulation_faults_produce_safe_outputs(self) -> None:
        worker = MockWorker()
        worker.send_command("SET_MODE", mode="REMOTE")
        worker.send_command("REMOTE_CONTROL", steering_pwm=7300, throttle_pwm=5800)
        worker.send_command("SIM_REMOTE_HEARTBEAT_LOSS")
        self.assertEqual(worker.mode, "AUTO")
        self.assertEqual((worker.steering, worker.throttle), (6000, 6450))
        self.assertEqual(worker.failsafe_reason, "REMOTE_HEARTBEAT_TIMEOUT")

        worker.send_command("SET_MODE", mode="NAVIGATION")
        worker.send_command("SIM_SET_GPS_FIX", fix=False)
        self.assertEqual(worker.operation_state, "NAVIGATION_WAITING_GPS")
        self.assertEqual((worker.steering, worker.throttle), (6000, 6450))

    def test_selected_route_and_active_multipath_route_render_separately(self) -> None:
        worker = MockWorker()
        routes = worker.ROUTES
        state = {
            "mode": "NAVIGATION",
            "operation_state": "NAVIGATION_ACTIVE",
            "navigation_active": True,
            "estop": False,
            "mock": True,
            "failsafe_reason": "",
            "devices": {"arduino": True, "gps": True, "pca9685": True},
            "gps": {"fix": True, "lat": 35.0, "lon": 129.0},
            "rc": {},
            "pca": {"steering_pwm": 6000, "throttle_pwm": 6650},
            "route": {
                "selected_route_id": "training_a",
                "selected_route_name": "훈련 경로 A",
                "active_route_id": "training_b",
                "active_route_name": "훈련 경로 B",
                "waypoint_index": 1,
                "waypoint_count": 3,
                "distance_to_waypoint_m": 4.0,
                "distance_to_route_m": 1.0,
            },
            "routes": routes,
            "events": [],
            "hardware_errors": [],
        }
        self.window.update_telemetry(state)
        self.assertEqual(self.window.route_combo.currentData(), "training_a")
        self.assertIn("선택한 항로: 훈련 경로 A", self.window.route_status.text())
        self.assertIn("활성 항로: 훈련 경로 B", self.window.route_status.text())

    def test_remote_shutdown_sends_neutral_then_auto(self) -> None:
        worker = SSHWorker("example.invalid", 22, "jetson", "temporary")
        channel = CapturingChannel()
        worker._channel = channel
        worker._remote_active = True
        worker._safe_remote_shutdown()
        self.assertEqual(channel.messages[0]["steering_pwm"], 6000)
        self.assertEqual(channel.messages[0]["throttle_pwm"], 6450)
        self.assertEqual(channel.messages[1]["mode"], "AUTO")

    def test_host_key_fingerprint_is_sha256_format(self) -> None:
        key = paramiko.RSAKey.generate(1024)
        fingerprint = host_key_fingerprint(key)
        self.assertTrue(fingerprint.startswith("SHA256:"))
        self.assertNotIn("=", fingerprint)

    def test_terminal_input_and_interrupt_are_queued_for_ssh_shell(self) -> None:
        worker = SSHWorker("example.invalid", 22, "jetson", "temporary")
        worker.send_terminal_input("pwd")
        worker.interrupt_terminal()
        self.assertEqual(worker._terminal_commands.get_nowait(), b"pwd\n")
        self.assertEqual(worker._terminal_commands.get_nowait(), b"\x03")

    def test_terminal_output_removes_ansi_styling(self) -> None:
        output = clean_terminal_output("\x1b[32mjetson\x1b[0m\r\n$ ")
        self.assertEqual(output, "jetson\n$ ")

    def test_terminal_controls_enable_only_when_shell_is_ready(self) -> None:
        self.window.on_terminal_state(True, "jetson@example")
        self.assertTrue(self.window.terminal_input.isEnabled())
        self.assertEqual(self.window.tabs.currentIndex(), self.window.terminal_tab_index)
        self.window.on_terminal_state(False, "연결 종료")
        self.assertFalse(self.window.terminal_input.isEnabled())

    def test_auto_speed_loads_from_telemetry_and_requires_apply(self) -> None:
        state = {
            "mode": "AUTO",
            "operation_state": "AUTO_ACTIVE",
            "auto_cruise_pwm": 6700,
            "devices": {},
            "gps": {},
            "rc": {},
            "pca": {},
            "route": {},
            "routes": [],
            "events": [],
            "hardware_errors": [],
        }
        self.window.update_telemetry(state)
        self.assertEqual(self.window.auto_speed_spin.value(), 6700)
        self.assertFalse(self.window._auto_speed_dirty)
        self.window.auto_speed_slider.setValue(6600)
        self.assertEqual(self.window.auto_speed_spin.value(), 6600)
        self.assertTrue(self.window._auto_speed_dirty)
        with patch.object(self.window, "command") as command:
            self.window.apply_auto_speed()
            command.assert_called_once_with("SET_AUTO_CRUISE_PWM", value=6600)

    def test_auto_speed_default_button_only_edits_ui(self) -> None:
        self.window.auto_speed_spin.setValue(6800)
        with patch.object(self.window, "command") as command:
            self.window.reset_auto_speed()
            self.assertEqual(self.window.auto_speed_spin.value(), 6650)
            command.assert_not_called()

    def test_live_telemetry_does_not_overwrite_unapplied_mode_selection(self) -> None:
        def state(mode: str) -> dict:
            return {
                "mode": mode,
                "operation_state": mode,
                "devices": {},
                "gps": {},
                "rc": {},
                "pca": {},
                "route": {},
                "routes": [],
                "events": [],
                "hardware_errors": [],
            }

        self.window.update_telemetry(state("AUTO"))
        navigation = self.window.mode_combo.findData("NAVIGATION")
        self.window.mode_combo.setCurrentIndex(navigation)
        self.window.update_telemetry(state("AUTO"))
        self.assertEqual(self.window.mode_combo.currentData(), "NAVIGATION")
        self.assertTrue(self.window._mode_dirty)

    def test_mode_editor_waits_for_ack_and_matching_telemetry(self) -> None:
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "mode-request"
        navigation = self.window.mode_combo.findData("NAVIGATION")
        self.window.mode_combo.setCurrentIndex(navigation)

        self.window.set_mode()

        self.window.worker.send_command.assert_called_once_with("SET_MODE", mode="NAVIGATION")
        self.assertFalse(self.window.mode_combo.isEnabled())
        self.window.on_ack(
            {
                "type": "ack",
                "request_id": "mode-request",
                "command": "SET_MODE",
                "ok": True,
            }
        )
        self.window.update_telemetry(
            {
                "mode": "NAVIGATION",
                "operation_state": "NAVIGATION_WAITING_GPS",
                "devices": {},
                "gps": {},
                "rc": {},
                "pca": {},
                "route": {},
                "routes": [],
                "events": [],
                "hardware_errors": [],
            }
        )
        self.assertEqual(self.window.current_mode, "NAVIGATION")
        self.assertFalse(self.window._mode_dirty)
        self.assertIsNone(self.window._pending_mode_target)
        self.assertTrue(self.window.mode_combo.isEnabled())

    def test_route_start_waits_for_route_ack_before_navigation(self) -> None:
        self.window.route_combo.addItem("훈련 경로 A", "training_a")
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "route-request"

        self.window.start_selected_route()

        self.window.worker.send_command.assert_called_once_with(
            "SELECT_ROUTE", route_id="training_a"
        )
        self.window.on_ack(
            {
                "type": "ack",
                "request_id": "route-request",
                "command": "SELECT_ROUTE",
                "ok": True,
            }
        )
        self.window.worker.send_command.assert_called_with(
            "SET_MODE", mode="NAVIGATION"
        )

    def test_route_start_does_not_navigate_after_selection_failure(self) -> None:
        self.window.route_combo.addItem("훈련 경로 A", "training_a")
        self.window.worker = Mock()
        self.window.worker.isRunning.return_value = True
        self.window.worker.send_command.return_value = "route-request"

        self.window.start_selected_route()
        self.window.on_ack(
            {
                "type": "ack",
                "request_id": "route-request",
                "command": "SELECT_ROUTE",
                "ok": False,
                "error": "unknown route",
            }
        )
        self.assertEqual(self.window.worker.send_command.call_count, 1)


if __name__ == "__main__":
    unittest.main()
