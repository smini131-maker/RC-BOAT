"""Qt UI and independent heartbeat test; no Jetson or hardware connection."""
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows_gui'))
from PySide6.QtWidgets import QApplication, QMessageBox
from rcboat_gui.main_window import MainWindow
from rcboat_gui.ssh_worker import SSHWorker, GUI_VERSION

app = QApplication([])
worker = SSHWorker('127.0.0.1', 22, 'fixture', '')
entered = threading.Event(); release = threading.Event(); sent = []

def stalled_probe():
    entered.set(); release.wait(5)
    return True

worker._update_ssh_health = stalled_probe
worker._send_operator_link = lambda value: sent.append(time.monotonic())
health = threading.Thread(target=worker._ssh_health_loop)
heartbeat = threading.Thread(target=worker._operator_link_loop)
health.start(); assert entered.wait(1)
heartbeat.start()
try:
    time.sleep(2.3)
    assert len(sent) >= 3, 'SSH probe blocked the ROS safety heartbeat'
    assert max(b-a for a,b in zip(sent, sent[1:])) < 1.5
finally:
    worker._stop_requested = True; release.set()
    health.join(2); heartbeat.join(2)
assert not health.is_alive() and not heartbeat.is_alive()

response = dict(success=True, version=GUI_VERSION, master_online=True, gateway_online=True,
    telemetry=dict(safety=dict(mode='MANUAL', reason='GPS_INVALID_OR_STALE',
        actuator_locked=True, manual_rearm_pending=True),
        ground_test=dict(active=True, state='recording', samples=180, actuation_enabled=True,
            output_paused=True, pause_reason='GPS_INVALID_OR_STALE')))
with patch.object(MainWindow, '_load_settings', lambda self: None):
    window = MainWindow(); window.resize(1440, 1000); window.show()
    window.update_telemetry(SSHWorker._normalize(response, False)); app.processEvents()
    assert not window.ground_start_button.isEnabled()
    assert window.ground_stop_button.isEnabled()
    assert window.ground_resume_button.isEnabled()
    assert '기록 계속' in window.ground_status.text()
    assert 'GPS_INVALID_OR_STALE' in window.ground_status.text()
    requests = []
    window.command = lambda command, **kwargs: requests.append(command)
    with patch.object(QMessageBox, 'warning', return_value=QMessageBox.Yes):
        window.ground_resume_button.click()
    assert requests == ['GROUND_TEST_RESUME']
    assert SSHWorker._translate(dict(command='GROUND_TEST_RESUME'))['action'] == 'ground_resume'
    for index in range(window.tabs.count()):
        if '도보' in window.tabs.tabText(index): window.tabs.setCurrentIndex(index)
    app.processEvents()
    target = ROOT / 'release/v2.1.12/gui_ground_pause.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(target))
    response['telemetry']['ground_test'].update(output_paused=False, pause_reason='')
    response['telemetry']['safety']['mode'] = 'GROUND_TEST'
    window.update_telemetry(SSHWorker._normalize(response, False)); app.processEvents()
    assert not window.ground_resume_button.isEnabled()
    assert window.ground_stop_button.isEnabled()
    response['telemetry']['safety'].update(gps_grace_active=True,gps_grace_remaining_s=3.2,
        actuator_locked=True,reason='GROUND_TEST_GPS_GRACE')
    response['telemetry']['ground_test'].update(output_paused=True,pause_reason='GROUND_TEST_GPS_GRACE')
    window.update_telemetry(SSHWorker._normalize(response, False)); app.processEvents()
    assert 'GPS 복구 유예 3.2초' in window.ground_status.text()
    assert '중립 출력' in window.ground_status.text()
    assert not window.ground_resume_button.isEnabled()
    assert window.ground_stop_button.isEnabled()
    assert window.grab().save(str(target.with_name('gui_gps_grace.png')))
    window.close(); app.processEvents()
print('PASS: independent heartbeat; pause/resume UI and confirmation; GPS grace countdown/neutral output; manual resume disabled during grace')
