"""Run using the Windows GUI venv; no Jetson connection or motor output."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows_gui'))
from PySide6.QtWidgets import QApplication
from rcboat_gui.ssh_worker import SSHWorker
from rcboat_gui.main_window import MainWindow

app = QApplication([])
assert SSHWorker._translate({'command': 'SET_MODE', 'mode': 'AUTO'}) == {
    'action': 'set_mode', 'arguments': {'mode': 'AUTO_SAFE', 'armed': False}}
window = MainWindow()
window.show()
response = dict(success=True, version='2.1.8', master_online=True, gateway_online=True,
                nodes=['/safety_supervisor_node'], telemetry={'safety': dict(
                    mode='MANUAL', reason='SSH_DISCONNECTED', armed=False,
                    manual_rearm_pending=True, rc_fresh=True, actuator_locked=True),
                    'actuator': dict(actual_steering_pwm=6000, actual_throttle_pwm=6450)})
state = SSHWorker._normalize(response, ssh_connected=False)
assert state['mode'] == 'MANUAL'
assert state['operation_state'] == 'MANUAL_WAITING_NEUTRAL'
assert not state['backend']['ssh_connected']
assert state['backend']['gateway_online']
window.update_telemetry(state)
app.processEvents()
target = ROOT / 'release/v2.1.8/gui_failsafe_v2.1.8.png'
target.parent.mkdir(parents=True, exist_ok=True)
assert window.grab().save(str(target))
response['telemetry']['safety'].update(estop=True)
assert SSHWorker._normalize(response)['operation_state'] == 'EMERGENCY_STOP'
window.close()
print('GUI translation / independent SSH and ROS / MANUAL neutral / E-STOP: PASS')
