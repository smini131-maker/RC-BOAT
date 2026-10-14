from __future__ import annotations

import os
import sys
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rcboat_gui.main_window import MainWindow
from rcboat_gui.ssh_worker import SSHWorker


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.simulation.setChecked(True)
    window.toggle_connection()
    deadline = time.time() + 1.2
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert not window.windowIcon().isNull()
    assert not window.simulation_badge.isHidden()
    assert window.cards["ssh"].value_label.text() == "시뮬레이션"
    assert window.cards["gps"].value_label.text() == "모의 위치"
    assert window.value_labels["pca_throttle"].value_label.text() == "6450"
    assert not hasattr(window, "arm_button")

    route_b = window.route_combo.findData("training_b")
    assert route_b >= 0
    window.route_combo.setCurrentIndex(route_b)
    window.select_route()
    deadline = time.time() + 0.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.route_combo.currentData() == "training_b"
    assert "선택한 항로: 훈련 경로 B" in window.route_status.text()
    assert "활성 항로: 훈련 경로 B" in window.route_status.text()
    screenshot = os.environ.get("RCBOAT_GUI_SCREENSHOT")
    if screenshot:
        window.grab().save(screenshot)
    window.close()
    app.processEvents()

    errors: list[str] = []
    ssh = SSHWorker("invalid.test", 22, "jetson", "temporary")
    ssh.disconnected.connect(errors.append)
    with patch("paramiko.SSHClient.connect", side_effect=OSError("mock SSH failure")):
        ssh.run()
    assert errors and "mock SSH failure" in errors[-1]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
