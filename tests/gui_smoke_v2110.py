"""Run using the Windows GUI venv; no Jetson connection or motor output."""
import sys
from unittest.mock import MagicMock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows_gui'))
from PySide6.QtWidgets import QApplication
from rcboat_gui.ssh_worker import SSHWorker
from rcboat_gui.main_window import MainWindow

app = QApplication([])
worker=SSHWorker('127.0.0.1',22,'test','')
client=MagicMock();transport=client.get_transport.return_value
transport.is_active.return_value=transport.is_authenticated.return_value=True
worker._client=client;worker._shell_channel=MagicMock()
worker._shell_channel.closed=False;worker._shell_channel.exit_status_ready.return_value=False
worker._ssh_confirmed=True
with patch.object(worker,'_ssh_is_healthy',side_effect=[False,True]) as probe:
    assert worker._update_ssh_health() is True
    assert worker._update_ssh_health() is True
    assert probe.call_count==2
assert not worker._ssh_health_failed.is_set()
with patch.object(worker,'_ssh_is_healthy',return_value=False):
    assert worker._update_ssh_health() is True
    assert worker._update_ssh_health() is False
assert worker._ssh_health_failed.is_set()
worker._ssh_health_failed.clear();worker._ssh_confirmed=True
worker._shell_channel.exit_status_ready.return_value=True
assert worker._update_ssh_health() is False
acks=[];worker.acknowledgement.connect(acks.append)
worker._backend_version='2.1.3'
worker._handle_request(dict(command='SET_MODE',mode='NAVIGATION',request_id='version-test'))
assert not acks[-1]['ok'] and '2.1.3' in acks[-1]['error']
with patch.object(worker,'_bridge',return_value={'success':True}):
    worker._handle_request(dict(command='EMERGENCY_STOP',request_id='stop-test'))
assert acks[-1]['ok']
worker._client=None;worker._shell_channel=None
assert SSHWorker._translate({'command': 'SET_MODE', 'mode': 'AUTO'}) == {
    'action': 'set_mode', 'arguments': {'mode': 'AUTO_SAFE', 'armed': False}}
window = MainWindow()
window.show()
response = dict(success=True, version='2.1.12', master_online=True, gateway_online=True,
                nodes=['/safety_supervisor_node'], telemetry={'safety': dict(
                    mode='MANUAL', reason='SSH_DISCONNECTED', armed=False,
                    manual_rearm_pending=True, rc_fresh=True, actuator_locked=True),
                    'actuator': dict(actual_steering_pwm=6000, actual_throttle_pwm=6450)})
response['telemetry']['ntrip']=dict(correction_age_source='JETSON_RTCM3_CRC_RECEPTION',
    last_correction_age_s=.34,correction_age_status='valid',enabled=True,connected=True)
response['telemetry']['gps']=dict(receiver_correction_age_s=None,receiver_correction_age_status='no_data')
state = SSHWorker._normalize(response, ssh_connected=False)
assert state['mode'] == 'MANUAL'
assert state['operation_state'] == 'MANUAL_WAITING_NEUTRAL'
assert not state['backend']['ssh_connected']
assert state['backend']['gateway_online']
window.update_telemetry(state)
app.processEvents()
assert window.gps_detail_labels['correction_age'].text()=='0.34 s'
assert window.gps_detail_labels['receiver_correction_age'].text()=='no_data'
legacy=dict(response,version='2.1.3',telemetry={'ntrip':{'last_correction_age_s':0}})
assert SSHWorker._normalize(legacy)['ntrip']['last_correction_age_s'] is None
window.tabs.setCurrentIndex(1)
app.processEvents()
target = ROOT / 'release/v2.1.12/gui_failsafe_v2.1.12.png'
target.parent.mkdir(parents=True, exist_ok=True)
assert window.grab().save(str(target))
response['telemetry']['safety'].update(estop=True)
assert SSHWorker._normalize(response)['operation_state'] == 'EMERGENCY_STOP'
window.close()
print('GUI correction age / unsupported legacy zero / receiver no_data / SSH transient and sustained loss / old backend motion refusal / E-STOP: PASS')
