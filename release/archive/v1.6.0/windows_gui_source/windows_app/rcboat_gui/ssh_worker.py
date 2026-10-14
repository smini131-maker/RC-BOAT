from __future__ import annotations

import base64
import codecs
import hashlib
import json
import queue
import re
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import paramiko
from PySide6.QtCore import QThread, Signal


MAX_MESSAGE_BYTES = 1_048_576
SAFE_STEERING_PWM = 6000
SAFE_THROTTLE_PWM = 6450

ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|\([A-Z0-9])"
)


def clean_terminal_output(text: str) -> str:
    """Remove terminal styling codes that a plain-text Qt widget cannot render."""

    return ANSI_ESCAPE_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def host_key_fingerprint(key: paramiko.PKey) -> str:
    """Return the OpenSSH-style SHA256 fingerprint shown to the operator."""

    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Require an explicit operator decision before trusting an unknown host key."""

    def __init__(self, worker: "SSHWorker"):
        self.worker = worker

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        if not self.worker.confirm_unknown_host_key(hostname, key):
            raise paramiko.SSHException("알 수 없는 SSH 호스트 키를 사용자가 승인하지 않았습니다")
        client.get_host_keys().add(hostname, key.get_name(), key)
        self.worker.save_host_keys(client)


class SSHWorker(QThread):
    connected = Signal()
    disconnected = Signal(str)
    telemetry = Signal(dict)
    acknowledgement = Signal(dict)
    log = Signal(str)
    host_key_confirmation = Signal(str, str, str)
    terminal_output = Signal(str)
    terminal_state = Signal(bool, str)

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        known_hosts_path: str | Path | None = None,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.known_hosts_path = Path(known_hosts_path or Path.home() / ".ssh" / "known_hosts")
        self._commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_requested = False
        self._remote_active = False
        self._client: paramiko.SSHClient | None = None
        self._channel = None
        self._shell_channel = None
        self._terminal_commands: queue.Queue[bytes] = queue.Queue()
        self._host_key_event = threading.Event()
        self._host_key_accepted = False

    def send_command(self, command: str, **kwargs: Any) -> str:
        request_id = uuid.uuid4().hex[:12]
        payload = {"command": command, "request_id": request_id, **kwargs}
        self._commands.put(payload)
        return request_id

    def send_terminal_input(self, text: str) -> None:
        """Queue one command line for the interactive SSH shell."""

        if not text.endswith("\n"):
            text += "\n"
        self._terminal_commands.put(text.encode("utf-8"))

    def interrupt_terminal(self) -> None:
        """Send Ctrl+C to the interactive SSH shell."""

        self._terminal_commands.put(b"\x03")

    def stop(self) -> None:
        self._stop_requested = True
        self._host_key_event.set()
        # connect() can otherwise remain blocked until its socket timeout.
        if self._client is not None and self._channel is None:
            try:
                self._client.close()
            except Exception:
                pass

    def respond_to_host_key(self, accepted: bool) -> None:
        self._host_key_accepted = bool(accepted)
        self._host_key_event.set()

    def confirm_unknown_host_key(self, hostname: str, key: paramiko.PKey) -> bool:
        self._host_key_accepted = False
        self._host_key_event.clear()
        self.host_key_confirmation.emit(hostname, key.get_name(), host_key_fingerprint(key))
        deadline = time.monotonic() + 60.0
        while not self._stop_requested and time.monotonic() < deadline:
            if self._host_key_event.wait(0.1):
                break
        return not self._stop_requested and self._host_key_accepted

    def save_host_keys(self, client: paramiko.SSHClient) -> None:
        try:
            self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(self.known_hosts_path))
        except Exception as exc:
            raise paramiko.SSHException(
                f"SSH 호스트 키를 known_hosts에 저장하지 못했습니다: {exc}"
            ) from exc

    def _send(self, message: dict[str, Any]) -> None:
        if self._channel is None:
            raise ConnectionError("SSH tunnel is not ready")
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        self._channel.sendall(data)

    def _safe_remote_shutdown(self) -> None:
        if not self._remote_active or self._channel is None:
            return
        self._send(
            {
                "command": "REMOTE_CONTROL",
                "request_id": uuid.uuid4().hex[:12],
                "steering_pwm": SAFE_STEERING_PWM,
                "throttle_pwm": SAFE_THROTTLE_PWM,
            }
        )
        self._send(
            {
                "command": "SET_MODE",
                "request_id": uuid.uuid4().hex[:12],
                "mode": "AUTO",
            }
        )
        self._remote_active = False

    def _process_message(self, raw: bytes) -> None:
        try:
            decoded = raw.decode("utf-8")
            message = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.log.emit(f"손상된 daemon 메시지를 건너뜁니다: {type(exc).__name__}")
            return
        if not isinstance(message, dict):
            self.log.emit("형식이 잘못된 daemon 메시지를 건너뜁니다")
            return
        message_type = message.get("type")
        if message_type == "telemetry":
            self._remote_active = (
                str(message.get("mode", "")).upper() == "REMOTE"
                and not bool(message.get("estop"))
            )
            self.telemetry.emit(message)
        elif message_type == "ack":
            command = str(message.get("command", "")).upper()
            if message.get("ok") and command in {"EMERGENCY_STOP", "CLEAR_ESTOP"}:
                self._remote_active = False
            self.acknowledgement.emit(message)
        else:
            self.log.emit("알 수 없는 daemon 메시지를 건너뜁니다")

    def run(self) -> None:
        buffer = bytearray()
        last_heartbeat = 0.0
        terminal_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            client = paramiko.SSHClient()
            self._client = client
            client.load_system_host_keys()
            if self.known_hosts_path.exists():
                client.load_host_keys(str(self.known_hosts_path))
            client.set_missing_host_key_policy(ConfirmHostKeyPolicy(self))
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self._password,
                timeout=8,
                auth_timeout=8,
                banner_timeout=8,
                look_for_keys=True,
                allow_agent=True,
            )
            self._password = ""
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise ConnectionError("SSH transport is not active")
            channel = transport.open_channel(
                "direct-tcpip", ("127.0.0.1", 8765), ("127.0.0.1", 0), timeout=5
            )
            channel.settimeout(0.1)
            self._channel = channel
            try:
                shell_channel = transport.open_session(timeout=5)
                shell_channel.get_pty(term="xterm-256color", width=120, height=32)
                shell_channel.invoke_shell()
                shell_channel.settimeout(0.0)
                self._shell_channel = shell_channel
                self.terminal_state.emit(True, f"{self.username}@{self.host}")
            except Exception as exc:
                self._shell_channel = None
                self.terminal_state.emit(False, f"터미널을 열지 못했습니다: {exc}")
                self.log.emit(f"SSH 제어 연결은 유지하지만 터미널을 열지 못했습니다: {exc}")
            if self._stop_requested:
                return
            self.connected.emit()
            self.log.emit("Jetson 제어 서비스에 SSH로 연결되었습니다")

            while True:
                if self._stop_requested:
                    self._safe_remote_shutdown()
                    break
                while True:
                    try:
                        self._send(self._commands.get_nowait())
                    except queue.Empty:
                        break
                shell_channel = self._shell_channel
                if shell_channel is not None:
                    try:
                        while True:
                            try:
                                terminal_data = self._terminal_commands.get_nowait()
                            except queue.Empty:
                                break
                            shell_channel.sendall(terminal_data)
                        while shell_channel.recv_ready():
                            terminal_data = shell_channel.recv(65536)
                            if not terminal_data:
                                raise ConnectionError("SSH shell channel closed")
                            terminal_text = clean_terminal_output(
                                terminal_decoder.decode(terminal_data)
                            )
                            if terminal_text:
                                self.terminal_output.emit(terminal_text)
                        if shell_channel.closed:
                            raise ConnectionError("SSH shell channel closed")
                    except Exception as exc:
                        try:
                            shell_channel.close()
                        except Exception:
                            pass
                        self._shell_channel = None
                        self.terminal_state.emit(False, f"터미널 연결 종료: {exc}")
                now = time.monotonic()
                if self._remote_active and now - last_heartbeat >= 0.2:
                    self._send({"command": "HEARTBEAT", "request_id": uuid.uuid4().hex[:12]})
                    last_heartbeat = now
                try:
                    chunk = channel.recv(65536)
                    if not chunk:
                        raise ConnectionError("daemon tunnel closed")
                    buffer.extend(chunk)
                except socket.timeout:
                    chunk = None
                if len(buffer) > MAX_MESSAGE_BYTES:
                    raise ConnectionError("daemon message exceeded the safety size limit")
                while b"\n" in buffer:
                    raw, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if not raw:
                        continue
                    if len(raw) > MAX_MESSAGE_BYTES:
                        self.log.emit("크기 제한을 넘은 daemon 메시지를 건너뜁니다")
                        continue
                    self._process_message(raw)
                time.sleep(0.02)
        except Exception as exc:
            if not self._stop_requested:
                self.disconnected.emit(str(exc))
        finally:
            self._password = ""
            self.terminal_state.emit(False, "SSH 연결이 종료되었습니다")
            try:
                if self._shell_channel:
                    self._shell_channel.close()
            except Exception:
                pass
            try:
                if self._channel:
                    self._channel.close()
            except Exception:
                pass
            try:
                if self._client:
                    self._client.close()
            except Exception:
                pass
