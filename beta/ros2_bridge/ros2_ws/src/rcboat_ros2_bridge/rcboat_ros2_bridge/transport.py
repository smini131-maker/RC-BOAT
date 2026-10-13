from __future__ import annotations

import json
import queue
import socket
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any


JsonObject = dict[str, Any]


class DaemonTransport:
    """Reconnectable newline-delimited JSON client for rcboat_daemon.

    It deliberately does not own hardware, generate heartbeat messages, or
    change daemon state on connection. The existing daemon remains the single
    safety authority.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_message: Callable[[JsonObject], None],
        on_connection: Callable[[bool], None] | None = None,
        reconnect_delay_s: float = 1.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.on_message = on_message
        self.on_connection = on_connection or (lambda _connected: None)
        self.reconnect_delay_s = max(0.05, float(reconnect_delay_s))
        self._outbound: queue.Queue[JsonObject] = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._connected = False
        self._state_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return self._connected

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rcboat-daemon-transport",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 3.0) -> None:
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout_s))
        self._set_connected(False)

    def send(self, command: JsonObject) -> str:
        if not isinstance(command, dict):
            raise TypeError("command must be a JSON object")
        item = dict(command)
        name = item.get("command")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("command field is required")
        request_id = str(item.get("request_id") or uuid.uuid4())
        item["request_id"] = request_id
        try:
            self._outbound.put_nowait(item)
        except queue.Full as exc:
            raise RuntimeError("outbound command queue is full") from exc
        return request_id

    def _set_connected(self, connected: bool) -> None:
        changed = False
        with self._state_lock:
            if self._connected != connected:
                self._connected = connected
                changed = True
        if changed:
            try:
                self.on_connection(connected)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=1.0) as sock:
                    self._socket = sock
                    sock.settimeout(0.1)
                    self._set_connected(True)
                    self._connected_loop(sock)
            except OSError:
                pass
            finally:
                self._socket = None
                self._set_connected(False)
            if not self._stop.wait(self.reconnect_delay_s):
                continue

    def _connected_loop(self, sock: socket.socket) -> None:
        buffer = bytearray()
        while not self._stop.is_set():
            self._flush_commands(sock)
            try:
                chunk = sock.recv(65_536)
            except socket.timeout:
                continue
            if not chunk:
                return
            buffer.extend(chunk)
            if len(buffer) > 1_048_576:
                raise OSError("daemon receive buffer exceeded limit")
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(message, dict):
                    try:
                        self.on_message(message)
                    except Exception:
                        pass

    def _flush_commands(self, sock: socket.socket) -> None:
        while True:
            try:
                item = self._outbound.get_nowait()
            except queue.Empty:
                return
            payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            try:
                sock.sendall(payload.encode("utf-8") + b"\n")
            except OSError:
                try:
                    self._outbound.put_nowait(item)
                except queue.Full:
                    pass
                raise
