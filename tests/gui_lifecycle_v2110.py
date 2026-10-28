"""Reproduce slow SSH disconnect/window close using actual Qt threads, no Jetson."""
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'windows_gui'))
from PySide6.QtCore import QThread,Qt
from PySide6.QtWidgets import QApplication
from rcboat_gui.main_window import MainWindow
from rcboat_gui.ssh_worker import SSHWorker

app=QApplication([])
app.setQuitOnLastWindowClosed(False)


def until(predicate,timeout=5):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:
        app.processEvents();time.sleep(.01)
    app.processEvents()
    assert predicate(),'timed out waiting for Qt thread cleanup'


class SlowClient:
    def __init__(self):self.entered=threading.Event();self.closed=False
    def load_system_host_keys(self):pass
    def load_host_keys(self,*args):pass
    def set_missing_host_key_policy(self,*args):pass
    def connect(self,*args,**kwargs):
        self.entered.set();time.sleep(1.9)
        raise OSError('simulated slow SSH failure')
    def close(self):self.closed=True


with patch.object(MainWindow,'_load_settings',lambda self:None):
    window=MainWindow();window.show();app.processEvents()
    ui_threads=[]
    window.logs.textChanged.connect(lambda:ui_threads.append(QThread.currentThread()),Qt.DirectConnection)
    for cycle in range(3):
        client=SlowClient()
        worker=SSHWorker('127.0.0.1',22,'test','')
        worker._send_operator_link=lambda value:None
        worker._bridge=lambda payload:(_ for _ in ()).throw(OSError('simulated offline gateway'))
        worker.setParent(window);window.worker=worker
        worker.finished.connect(window._on_worker_finished)
        worker.disconnected.connect(window.on_disconnected,Qt.QueuedConnection)
        worker.log.connect(window.log,Qt.QueuedConnection)
        worker.telemetry.connect(window.update_telemetry,Qt.QueuedConnection)
        worker.terminal_state.connect(window.on_terminal_state,Qt.QueuedConnection)
        with patch('rcboat_gui.ssh_worker.paramiko.SSHClient',return_value=client):
            worker.start();until(client.entered.is_set)
            window._set_connected(True)
            assert window.connect_button.text()=='재연결 중 · 중지'
            window.on_terminal_state(True,'test connection')
            assert window.connect_button.text()=='연결 해제'
            window.on_terminal_state(False,'test lost')
            assert window.connect_button.text()=='재연결 중 · 중지'
            begin=time.monotonic();window.toggle_connection()
            assert time.monotonic()-begin<.5,'UI blocked while waiting for SSH'
            assert window.worker is worker and window._disconnecting
            window.toggle_connection()  # Repeated clicks must not create/replace a live worker.
            assert window.worker is worker
            assert not window.connect_button.isEnabled()
            assert client.closed,'pending SSH client not closed by stop'
            until(lambda:window.worker is None)
    assert window.isVisible(),'disconnect unexpectedly closed the app'
    assert ui_threads and all(t==app.thread() for t in ui_threads),'UI was updated off the GUI thread'
    window.close();app.processEvents()

    class DelayedStop(QThread):
        def stop(self):pass
        def run(self):time.sleep(1.8)

    window=MainWindow();window.show();app.processEvents()
    delayed=DelayedStop(window);window.worker=delayed
    delayed.finished.connect(window._on_worker_finished)
    delayed.start();until(delayed.isRunning)
    begin=time.monotonic();window.close()
    assert time.monotonic()-begin<.5
    assert window.isVisible() and window.worker is delayed
    until(lambda:not window.isVisible())
    assert window.worker is None

    # Unexpected worker errors must restore a usable window, never quit the app.
    window=MainWindow();window.show();app.processEvents()
    failed=SSHWorker('127.0.0.1',22,'test','')
    failed._run_connections=lambda:(_ for _ in ()).throw(RuntimeError('simulated worker failure'))
    failed.setParent(window);window.worker=failed
    failed.finished.connect(window._on_worker_finished,Qt.QueuedConnection)
    failed.disconnected.connect(window.on_disconnected,Qt.QueuedConnection)
    with patch('logging.Logger.exception'):
        failed.start();until(lambda:window.worker is None)
    assert window.isVisible() and window.connect_button.isEnabled()
    window.close();app.processEvents()

# A silent gateway read used to outlive the 1.2/1.5 s GUI shutdown waits.
server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1)
accepted=threading.Event();request_done=threading.Event()
def silent_gateway():
    with server.accept()[0] as client:
        client.recv(4096);accepted.set()
        client.recv(1)
    server.close()
def request():
    try:worker._bridge({'action':'status'})
    except (OSError,ValueError):pass
    finally:request_done.set()
worker=SSHWorker('127.0.0.1',22,'test','',gateway_port=server.getsockname()[1])
network=threading.Thread(target=silent_gateway);network.start()
reader=threading.Thread(target=request);reader.start()
assert accepted.wait(2)
begin=time.monotonic();worker.stop()
assert request_done.wait(1),'stop did not interrupt gateway recv'
reader.join();network.join()
assert time.monotonic()-begin<1
print('PASS: slow SSH disconnect keeps window alive; close waits asynchronously; pending client/socket cancelled; no running QThread destroyed')
