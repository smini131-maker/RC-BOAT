"""Exercise the new GUI tab and start/stop sequence without Jetson hardware."""
import os
from pathlib import Path
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"windows_gui"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rcboat_gui.main_window import MainWindow
from rcboat_gui.mock_worker import MockWorker
from rcboat_gui.ssh_worker import SSHWorker

def main():
    stop = SSHWorker._translate({"command": "SET_MODE", "mode": "AUTO"})
    assert stop["arguments"] == {"mode": "AUTO_SAFE", "armed": False}
    app = QApplication([])
    window = MainWindow()
    worker = MockWorker()
    window.worker, window.is_simulation = worker, True
    worker.telemetry.connect(window.update_telemetry)
    worker.acknowledgement.connect(window.on_ack)
    worker.connected.connect(window.on_connected)
    window.tabs.setCurrentWidget(window.balloon_panel)
    window.show()
    failures = []
    def start():
        worker.send_command("VISION_ENABLE", enabled=True)
    def arm():
        try:
            assert window.balloon_panel.start_button.isEnabled()
            window._request_mode("BALLOON")
        except Exception as exc:
            failures.append("start: "+repr(exc))
    def stop_tracking():
        try:
            assert window.current_mode == "BALLOON"
            assert worker.throttle == 6550
            window._request_mode("AUTO")
        except Exception as exc:
            failures.append("track: "+repr(exc))
    def finish():
        try:
            assert worker.throttle == 6450
            assert window.current_mode == "AUTO"
            assert "카메라" in window.balloon_panel.summary.text()
            viewport = window.centralWidget()
            viewport.verticalScrollBar().setValue(viewport.verticalScrollBar().maximum())
            app.processEvents()
            output = ROOT/"artifacts/gui_balloon_tracking_v220.png"
            output.parent.mkdir(exist_ok=True)
            assert window.grab().save(str(output))
        except Exception as exc:
            failures.append("stop: "+repr(exc))
        window.close()
        app.quit()
    worker.start()
    QTimer.singleShot(250, start)
    QTimer.singleShot(750, arm)
    QTimer.singleShot(1300, stop_tracking)
    QTimer.singleShot(1800, finish)
    app.exec()
    if failures:
        raise RuntimeError("; ".join(failures))
    print("GUI BALLOON START/STOP SMOKE: PASSED")

if __name__ == "__main__":
    main()
