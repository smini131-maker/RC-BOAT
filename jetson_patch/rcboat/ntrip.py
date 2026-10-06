from __future__ import annotations

import base64
import os
import socket
import ssl
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass
class NtripConfig:
    enabled: bool = False
    host: str = ""
    port: int = 2101
    mountpoint: str = ""
    username: str = ""
    password: str = ""
    tls: bool = False
    timeout_s: float = 10.0
    gga_interval_s: float = 10.0

    def validate(self) -> None:
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("NTRIP port must be 1..65535")
        if self.enabled and not all((self.host.strip(), self.mountpoint.strip(), self.username.strip(), self.password)):
            raise ValueError("enabled NTRIP requires host, mountpoint, username and password")
        if not 1.0 <= float(self.timeout_s) <= 120.0:
            raise ValueError("NTRIP timeout must be 1..120 seconds")
        if not 1.0 <= float(self.gga_interval_s) <= 60.0:
            raise ValueError("NTRIP GGA interval must be 1..60 seconds")


def _clean(value: str) -> str:
    return str(value).replace("\r", "").replace("\n", "").strip()


def load_ntrip_env(path: str | Path) -> NtripConfig:
    values: dict[str, str] = {}
    source = Path(path)
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    for key in (
        "NTRIP_ENABLED", "NTRIP_HOST", "NTRIP_PORT", "NTRIP_MOUNTPOINT",
        "NTRIP_USERNAME", "NTRIP_PASSWORD", "NTRIP_TLS", "NTRIP_TIMEOUT_S",
        "NTRIP_GGA_INTERVAL_S",
    ):
        if key in os.environ:
            values[key] = os.environ[key]
    truthy = {"1", "true", "yes", "on"}
    return NtripConfig(
        enabled=values.get("NTRIP_ENABLED", "false").lower() in truthy,
        host=values.get("NTRIP_HOST", ""),
        port=int(values.get("NTRIP_PORT", "2101") or 2101),
        mountpoint=values.get("NTRIP_MOUNTPOINT", "").lstrip("/"),
        username=values.get("NTRIP_USERNAME", ""),
        password=values.get("NTRIP_PASSWORD", ""),
        tls=values.get("NTRIP_TLS", "false").lower() in truthy,
        timeout_s=float(values.get("NTRIP_TIMEOUT_S", "10") or 10),
        gga_interval_s=float(values.get("NTRIP_GGA_INTERVAL_S", "10") or 10),
    )


def save_ntrip_env(path: str | Path, config: NtripConfig) -> None:
    config.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"NTRIP_ENABLED={'true' if config.enabled else 'false'}",
        f"NTRIP_HOST={_clean(config.host)}",
        f"NTRIP_PORT={int(config.port)}",
        f"NTRIP_MOUNTPOINT={_clean(config.mountpoint).lstrip('/')}",
        f"NTRIP_USERNAME={_clean(config.username)}",
        f"NTRIP_PASSWORD={_clean(config.password)}",
        f"NTRIP_TLS={'true' if config.tls else 'false'}",
        f"NTRIP_TIMEOUT_S={float(config.timeout_s):g}",
        f"NTRIP_GGA_INTERVAL_S={float(config.gga_interval_s):g}",
    ]
    temporary = target.with_name(f".{target.name}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_gga(latitude: float, longitude: float, *, satellites: int = 8, hdop: float = 1.0) -> bytes:
    def coordinate(value: float, latitude_axis: bool) -> tuple[str, str]:
        hemisphere = ("N" if value >= 0 else "S") if latitude_axis else ("E" if value >= 0 else "W")
        value = abs(value)
        degrees = int(value)
        minutes = (value - degrees) * 60.0
        width = 2 if latitude_axis else 3
        return f"{degrees:0{width}d}{minutes:07.4f}", hemisphere

    lat, ns = coordinate(latitude, True)
    lon, ew = coordinate(longitude, False)
    utc = time.strftime("%H%M%S", time.gmtime()) + ".00"
    payload = f"GPGGA,{utc},{lat},{ns},{lon},{ew},1,{max(0, min(99, satellites)):02d},{hdop:.1f},0.0,M,0.0,M,,"
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"${payload}*{checksum:02X}\r\n".encode("ascii")


class NtripClient:
    def __init__(
        self,
        config: NtripConfig,
        write_rtcm: Callable[[bytes], None],
        gga_provider: Callable[[], bytes | None] | None = None,
        *,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        self.config = config
        self.write_rtcm = write_rtcm
        self.gga_provider = gga_provider
        self.reconnect_delay_s = reconnect_delay_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.connected = False
        self.bytes_received = 0
        self.reconnect_count = 0
        self.last_correction_monotonic = 0.0
        self.last_error = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.config.validate()
        if not self.config.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ntrip-client", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout=max(1.0, self.config.timeout_s + 0.5))
        self._thread = None
        with self._lock:
            self.connected = False

    def _request(self) -> bytes:
        token = base64.b64encode(f"{self.config.username}:{self.config.password}".encode("utf-8")).decode("ascii")
        mount = self.config.mountpoint.lstrip("/")
        return (
            f"GET /{mount} HTTP/1.1\r\n"
            f"Host: {self.config.host}:{self.config.port}\r\n"
            "Ntrip-Version: Ntrip/2.0\r\n"
            "User-Agent: NTRIP RCBoat-Week6/1.0\r\n"
            f"Authorization: Basic {token}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")

    def _connect(self) -> socket.socket:
        raw = socket.create_connection((self.config.host, self.config.port), timeout=self.config.timeout_s)
        if self.config.tls:
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=self.config.host)
        raw.settimeout(1.0)
        raw.sendall(self._request())
        header = bytearray()
        while b"\r\n\r\n" not in header and len(header) < 16_384:
            part = raw.recv(1024)
            if not part:
                break
            header.extend(part)
        first = bytes(header).split(b"\r\n", 1)[0]
        if b"200" not in first:
            raw.close()
            if b"401" in first:
                raise PermissionError("NTRIP authentication failed")
            raise ConnectionError(f"NTRIP caster rejected request: {first.decode('ascii', errors='replace')}")
        remainder = bytes(header).split(b"\r\n\r\n", 1)
        if len(remainder) == 2 and remainder[1]:
            self._accept_correction(remainder[1])
        return raw

    def _accept_correction(self, data: bytes) -> None:
        if not data:
            return
        self.write_rtcm(data)
        with self._lock:
            self.bytes_received += len(data)
            self.last_correction_monotonic = time.monotonic()

    def _run(self) -> None:
        while not self._stop.is_set() and self.config.enabled:
            sock: socket.socket | None = None
            try:
                sock = self._connect()
                with self._lock:
                    self.connected = True
                    self.last_error = ""
                last_gga = 0.0
                while not self._stop.is_set():
                    now = time.monotonic()
                    if self.gga_provider and now - last_gga >= self.config.gga_interval_s:
                        gga = self.gga_provider()
                        if gga:
                            sock.sendall(gga)
                        last_gga = now
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        raise ConnectionError("NTRIP correction stream closed")
                    self._accept_correction(data)
            except Exception as exc:
                with self._lock:
                    self.connected = False
                    self.last_error = str(exc)
                    self.reconnect_count += 1
                if not self._stop.wait(self.reconnect_delay_s):
                    continue
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                with self._lock:
                    self.connected = False

    def status(self) -> dict[str, object]:
        with self._lock:
            age = (
                max(0.0, time.monotonic() - self.last_correction_monotonic)
                if self.last_correction_monotonic > 0 else None
            )
            return {
                "enabled": self.config.enabled,
                "connected": self.connected,
                "host": self.config.host,
                "port": self.config.port,
                "mountpoint": self.config.mountpoint,
                "tls": self.config.tls,
                "last_correction_age_s": round(age, 3) if age is not None else None,
                "bytes_received": self.bytes_received,
                "reconnect_count": self.reconnect_count,
                "last_error": self.last_error,
            }

