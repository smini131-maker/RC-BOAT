from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "jetson_backend"
TRANSPORT_FILE = (
    ROOT
    / "beta"
    / "ros2_bridge"
    / "ros2_ws"
    / "src"
    / "rcboat_ros2_bridge"
    / "rcboat_ros2_bridge"
    / "transport.py"
)
SPEC = importlib.util.spec_from_file_location("rcboat_ros2_transport", TRANSPORT_FILE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DaemonTransport = MODULE.DaemonTransport


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


class TransportTests(unittest.TestCase):
    def test_command_validation(self) -> None:
        transport = DaemonTransport("127.0.0.1", 1, lambda _message: None)
        with self.assertRaises(TypeError):
            transport.send([])
        with self.assertRaises(ValueError):
            transport.send({})
        request_id = transport.send({"command": "GET_STATE"})
        self.assertTrue(request_id)

    def test_mock_daemon_roundtrip_and_existing_failsafe(self) -> None:
        port = free_port()
        messages: list[dict] = []
        connection_events: list[bool] = []
        lock = threading.Lock()

        def on_message(message: dict) -> None:
            with lock:
                messages.append(message)

        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(BACKEND / "rcboat_daemon.py"),
                    "--mock",
                    "--port",
                    str(port),
                    "--lock-file",
                    str(Path(temp) / "daemon.lock"),
                    "--routes",
                    str(BACKEND / "routes.json"),
                    "--config",
                    str(BACKEND / "boat_config.json"),
                ],
                cwd=BACKEND,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            transport = DaemonTransport(
                "127.0.0.1",
                port,
                on_message,
                connection_events.append,
                reconnect_delay_s=0.05,
            )
            try:
                transport.start()
                deadline = time.time() + 5.0
                while time.time() < deadline and not transport.connected:
                    time.sleep(0.02)
                self.assertTrue(transport.connected)

                transport.send({"command": "SET_MODE", "mode": "REMOTE"})
                transport.send(
                    {
                        "command": "REMOTE_CONTROL",
                        "steering_pwm": 7300,
                        "throttle_pwm": 5800,
                    }
                )

                remote_seen = False
                safe_seen = False
                deadline = time.time() + 4.0
                while time.time() < deadline:
                    with lock:
                        snapshot = list(messages)
                    for message in snapshot:
                        if message.get("type") != "telemetry":
                            continue
                        pca = message.get("pca", {})
                        if message.get("mode") == "REMOTE" and pca.get("throttle_pwm") == 5800:
                            remote_seen = True
                        if remote_seen and message.get("failsafe_reason") == "REMOTE_HEARTBEAT_TIMEOUT":
                            self.assertEqual(message.get("mode"), "AUTO")
                            self.assertEqual(pca.get("steering_pwm"), 6000)
                            self.assertEqual(pca.get("throttle_pwm"), 6450)
                            safe_seen = True
                            break
                    if safe_seen:
                        break
                    time.sleep(0.02)

                self.assertTrue(remote_seen)
                self.assertTrue(safe_seen)
                self.assertTrue(any(item.get("type") == "ack" for item in messages))
                self.assertIn(True, connection_events)
            finally:
                if process.poll() is None:
                    try:
                        transport.send({"command": "SHUTDOWN_MOCK"})
                        time.sleep(0.2)
                    except (RuntimeError, ValueError):
                        pass
                transport.stop()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
