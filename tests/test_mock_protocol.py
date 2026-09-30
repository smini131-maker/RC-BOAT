from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "jetson_backend"


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class MockProtocolTest(unittest.TestCase):
    def test_heartbeat_timeout_over_json_socket(self) -> None:
        port = free_port()
        with tempfile.TemporaryDirectory() as temp:
            lock = str(Path(temp) / "daemon.lock")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(BACKEND / "rcboat_daemon.py"),
                    "--mock",
                    "--port",
                    str(port),
                    "--lock-file",
                    lock,
                    "--routes",
                    str(BACKEND / "routes.json"),
                    "--config",
                    str(BACKEND / "boat_config.json"),
                ],
                cwd=BACKEND,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            stream = None
            sock = None
            try:
                deadline = time.time() + 5
                while time.time() < deadline:
                    try:
                        sock = socket.create_connection(("127.0.0.1", port), timeout=0.3)
                        break
                    except OSError:
                        time.sleep(0.05)
                self.assertIsNotNone(sock, "mock daemon did not open its socket")
                assert sock is not None
                stream = sock.makefile("rwb", buffering=0)
                stream.write(b'{"command":"SET_MODE","mode":"REMOTE","request_id":"1"}\n')
                stream.write(b'{"command":"REMOTE_CONTROL","steering_pwm":7300,"throttle_pwm":5800,"request_id":"2"}\n')
                remote_seen = False
                safe_seen = False
                deadline = time.time() + 3
                while time.time() < deadline:
                    line = stream.readline()
                    if not line:
                        break
                    msg = json.loads(line)
                    if msg.get("type") != "telemetry":
                        continue
                    if msg.get("mode") == "REMOTE" and msg["pca"]["throttle_pwm"] == 5800:
                        remote_seen = True
                    if remote_seen and msg.get("failsafe_reason") == "REMOTE_HEARTBEAT_TIMEOUT":
                        self.assertEqual(msg["mode"], "AUTO")
                        self.assertEqual(msg["pca"]["steering_pwm"], 6000)
                        self.assertEqual(msg["pca"]["throttle_pwm"], 6450)
                        safe_seen = True
                        break
                self.assertTrue(remote_seen)
                self.assertTrue(safe_seen)
            finally:
                if stream is not None and proc.poll() is None:
                    try:
                        stream.write(b'{"command":"SHUTDOWN_MOCK","request_id":"cleanup"}\n')
                    except OSError:
                        pass
                if stream is not None:
                    stream.close()
                if sock is not None:
                    sock.close()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
