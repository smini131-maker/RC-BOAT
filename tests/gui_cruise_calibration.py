"""Offscreen Qt and real worker/gateway/navigation setting path; no device I/O."""
from pathlib import Path
import json
import sys
import tempfile
from unittest.mock import patch,MagicMock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'windows_gui'),str(ROOT/'tests')]
from PySide6.QtWidgets import QApplication,QAbstractSlider
from rcboat_gui.main_window import MainWindow
from rcboat_gui.ssh_worker import SSHWorker
from rcboat_gui.mock_worker import MockWorker
from rcboat_ros.control_config import RC_DEFAULTS
import test_ground_continuity_v2111 as harness

app=QApplication([])
with patch.object(MainWindow,'_load_settings',lambda self:None):
    window=MainWindow()
sent=[]
window.command=lambda command,**args: (sent.append(dict(command=command,**args)) or str(len(sent)))
assert window._confirmed_cruise_pwm is None
assert '%' not in window.auto_speed_status.text()
assert window.auto_speed_spin.maximum()==window.auto_speed_slider.maximum()==7397
assert window.remote_throttle.maximum()==7397
# Non-grid maximum must survive both editors and the end of the slider.
window.auto_speed_spin.setValue(7397)
assert window.auto_speed_slider.value()==7397
window.auto_speed_slider.setValue(7390)
window.auto_speed_slider.triggerAction(QAbstractSlider.SliderSingleStepAdd)
assert window.auto_speed_spin.value()==7397
window._set_auto_speed_editor(6650,dirty=False)
window.auto_speed_slider.triggerAction(QAbstractSlider.SliderSingleStepAdd)
assert window.auto_speed_spin.value()==6660 and not sent
window.auto_speed_spin.setValue(6670)
assert window.auto_speed_slider.value()==6670 and not sent
window.auto_speed_slider.setValue(6683)
assert window.auto_speed_spin.value()==6680
window.apply_auto_speed()
assert sent==[dict(command='SET_AUTO_CRUISE_PWM',value=6680)]
assert window._confirmed_cruise_pwm is None
# Wrong / obsolete request ACK must not clear this pending edit.
window.on_ack(dict(command='SET_AUTO_CRUISE_PWM',request_id='obsolete',ok=True,value=6650,cruise_applied_monotonic=2))
assert window._pending_cruise_request=='1'
window.auto_speed_spin.setValue(6690)  # Editing while previous request is in flight.

with tempfile.TemporaryDirectory() as folder:
    navmod=harness.load_node('navigation_node',Path(folder))
    params={}
    navmod.rospy.set_param=lambda k,v:params.update({k:v})
    nav=navmod.Navigation()
    bridgemod=harness.load_node('gui_bridge_node',Path(folder))
    bridge=bridgemod.Bridge.__new__(bridgemod.Bridge);bridge.token=''
    def service(namespace,action,args):
        assert namespace=='/rcboat/navigation/execute'
        response=nav.execute(type('Request',(),dict(action=action,arguments_json=json.dumps(args)))())
        assert response.success
        return json.loads(response.response_json)
    bridge.service=service
    worker=SSHWorker('127.0.0.1',22,'fixture','')
    acks=[];worker.acknowledgement.connect(acks.append)
    worker._bridge=bridge.dispatch
    worker._handle_request(dict(sent[-1],request_id='1'))
    assert acks[-1]['ok'] and params['/rcboat/cruise_pwm']==6680
    window.on_ack(acks[-1])
    assert window._confirmed_cruise_pwm==6680
    assert window.auto_speed_spin.value()==6690 and window._auto_speed_dirty
    stamp=acks[-1]['cruise_applied_monotonic']
    window._confirm_cruise(6650,stamp-1)  # Cached status from before this ACK.
    assert window._confirmed_cruise_pwm==6680
    window.apply_auto_speed()
    window.on_ack(dict(command='SET_AUTO_CRUISE_PWM',request_id='2',ok=False,error='rejected'))
    assert window._auto_speed_dirty and window._confirmed_cruise_pwm==6680
    window.apply_auto_speed();window._cruise_ack_timeout('3')
    assert window._pending_cruise_request is None and window._auto_speed_dirty
    for value in (6470,7398,7800,6651,True,'6650'):
        worker._handle_request(dict(command='SET_AUTO_CRUISE_PWM',value=value,request_id='bad'))
        assert not acks[-1]['ok']
    bridge.gps_settings_path=Path(folder)/'gps_settings.json'
    bridge.gps_settings={'navigation_max_hdop':3.0,'applied_monotonic':1.0}
    bridgemod.rospy.set_param=lambda k,v:params.update({k:v})
    bridge.events=harness.Publisher()
    window._sync_gps_settings(dict(navigation_max_hdop=3.0,applied_monotonic=1.0))
    window.gps_max_hdop.setValue(6.0)
    # Incoming polling must not revert a local edit, including keyboard typing.
    window._sync_gps_settings(dict(navigation_max_hdop=3.0,applied_monotonic=1.0))
    assert window.gps_max_hdop.value()==6.0
    window.apply_gps_safety()
    request_id=window._pending_gps_settings
    worker._handle_request(dict(sent[-1],request_id=request_id))
    assert acks[-1]['ok'] and params['/rcboat/max_hdop']==6.0
    window.on_ack(acks[-1])
    assert not window._gps_settings_dirty
    window._sync_gps_settings(dict(navigation_max_hdop=3.0,applied_monotonic=1.0))
    assert window.gps_max_hdop.value()==6.0
    normalized=SSHWorker._normalize(dict(success=True,gps_settings=dict(bridge.gps_settings),telemetry={}))
    assert normalized['gps_settings']['navigation_max_hdop']==6.0
    # Mock service is configuration-only even with an active simulated mode.
    mock=MockWorker();mock.estop=True;mock.throttle=6450
    mock.send_command('SET_AUTO_CRUISE_PWM',value=6690)
    app.processEvents()
    assert mock.auto_cruise_pwm==6690 and mock.throttle==6450
    mock.estop=False
    mock.send_command('SET_AUTO_CRUISE_PWM',value=7397)
    mock.send_command('SET_MODE',mode='NAVIGATION')
    app.processEvents()
    assert mock.auto_cruise_pwm==7397 and mock.throttle==6650
    payload=bridge.dispatch(dict(action='set_auto_cruise_pwm',arguments={'value':7397}))
    assert payload['success'] and params['/rcboat/cruise_pwm']==7397
    # Real worker -> gateway -> navigation ACK for the exceptional end value.
    worker._handle_request(dict(command='SET_AUTO_CRUISE_PWM',value=7397,request_id='ceiling'))
    assert acks[-1]['ok'] and acks[-1]['value']==7397
    window._set_auto_speed_editor(7397,dirty=True)
    window.apply_auto_speed()
    worker._handle_request(dict(sent[-1],request_id=window._pending_cruise_request))
    window.on_ack(acks[-1])
    assert window._confirmed_cruise_pwm==window.auto_speed_spin.value()==7397
    assert '7397' in window.auto_speed_status.text()
    for value in (7398,7400):
        worker._handle_request(dict(command='SET_AUTO_CRUISE_PWM',value=value,request_id='overflow'))
        assert not acks[-1]['ok']
    assert SSHWorker._translate(dict(command='REMOTE_CONTROL',steering_pwm=6000,throttle_pwm=7397))['arguments']['throttle_pwm']==7397
    try:SSHWorker._translate(dict(command='REMOTE_CONTROL',steering_pwm=6000,throttle_pwm=7398))
    except ValueError:pass
    else:raise AssertionError('remote overflow accepted')

state=SSHWorker._normalize(dict(success=True,telemetry={}))
assert state['auto_cruise_pwm'] is None
state=SSHWorker._normalize(dict(success=True,telemetry={
    'navigation':dict(fresh=True,auto_cruise_pwm=6680,cruise_applied_monotonic=stamp,ramp_throttle_pwm=6660),
    'safety':dict(rc_input_calibration=RC_DEFAULTS,throttle_pwm=6650)}))
state['route'].update(heading_error_deg=4.0,navigation_speed_fraction=.3)
window.update_telemetry(state);app.processEvents()
assert '%' not in window.route_status.text()
assert '1620' in window.value_labels['rc_steering'].toolTip()
assert '1499' in window.value_labels['rc_throttle'].toolTip()
assert state['ramp_throttle_pwm']==6660
assert '6650' in window.value_labels['pca_throttle'].toolTip()
probe_worker=SSHWorker('127.0.0.1',22,'fixture','')
client=MagicMock();transport=client.get_transport.return_value
transport.is_active.return_value=transport.is_authenticated.return_value=True
probe_worker._client=client;probe_worker._shell_channel=MagicMock()
probe_worker._shell_channel.closed=False;probe_worker._shell_channel.exit_status_ready.return_value=False
probe_worker._ssh_confirmed=True
def close_during_probe():
    transport.is_active.return_value=False
    return False
with patch.object(probe_worker,'_ssh_is_healthy',side_effect=close_during_probe):
    assert not probe_worker._update_ssh_health()
assert probe_worker._ssh_health_failed.is_set()
window._set_connected(False)
assert window._confirmed_cruise_pwm is None
window.close()
print('PASS: cruise grid/editor/apply ACK/stale response, RC metadata, mock E-STOP, real HDOP save/ACK/polling does not revert edits')
