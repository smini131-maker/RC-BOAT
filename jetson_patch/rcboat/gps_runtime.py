from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .config import GPS_BY_ID, VALUES
from .gps_parser import MixedGpsParser
from .ntrip import NtripClient, NtripConfig, build_gga, load_ntrip_env, save_ntrip_env


def install_hardware_extension() -> None:
    """Extend the installed Direct-I2C hardware class without replacing it.

    R12 deliberately does not ship hardware.py because the live Jetson owns a
    verified DirectLinuxPCA9685 driver. This adapter only replaces the GPS
    methods and leaves every PCA/Arduino method on that live class untouched.
    """

    from . import hardware as hardware_module

    real_type = getattr(hardware_module, "RealHardware", None)
    if real_type is None or getattr(real_type, "_week6_installed", False):
        return
    required = ("_connect_gps", "_gps_loop", "_mark_gps_offline", "_append_error", "snapshot")
    if not all(hasattr(real_type, name) for name in required):
        raise RuntimeError("installed hardware.py is not compatible with the Week6 GPS adapter")

    original_init = real_type.__init__
    original_start = real_type.start
    original_close = real_type.close

    def extended_init(self: Any, settings: Any) -> None:
        original_init(self, settings)
        self._week6_parser = MixedGpsParser()
        self._gps_io_lock = threading.Lock()
        config_path = getattr(settings, "config_path", None)
        base = Path(config_path).parent if config_path else Path("/home/jetson/rcboat")
        self._ntrip_env_path = base / ".ntrip.env"
        self._ntrip_client = _new_ntrip_client(self, load_ntrip_env(self._ntrip_env_path))

    def extended_start(self: Any) -> None:
        original_start(self)
        if self._ntrip_client.config.enabled:
            try:
                self._ntrip_client.start()
            except Exception as exc:
                self._append_error(f"NTRIP start: {exc}")

    def extended_connect_gps(self: Any) -> bool:
        if not Path(GPS_BY_ID).exists():
            return False
        try:
            baudrate = int(getattr(self.settings, "gps_baudrate", 115200))
            self._gps = self._serial_module.Serial(GPS_BY_ID, baudrate, timeout=0.2)
            with self._lock:
                self._snapshot.gps_connected = True
            return True
        except Exception as exc:
            self._append_error(f"GPS connect: {exc}")
            self._mark_gps_offline()
            return False

    def extended_gps_loop(self: Any) -> None:
        last_data = time.monotonic()
        while not self._stop.is_set():
            if self._gps is None:
                if not self._connect_gps():
                    self._stop.wait(self.settings.reconnect_interval_s)
                    continue
                last_data = time.monotonic()
            try:
                with self._gps_io_lock:
                    chunk = self._gps.read(512)
                if not chunk:
                    if time.monotonic() - last_data > VALUES.gps_stale_timeout_s:
                        raise TimeoutError("GPS byte stream became stale")
                    continue
                last_data = time.monotonic()
                if self._week6_parser.feed(chunk, last_data):
                    _copy_to_legacy_snapshot(self)
            except Exception as exc:
                self._append_error(f"GPS disconnected: {exc}")
                self._mark_gps_offline()
                self._stop.wait(self.settings.reconnect_interval_s)
                last_data = time.monotonic()

    def week6_gps_snapshot(self: Any) -> dict[str, Any]:
        with self._lock:
            result = self._week6_parser.data.public()
            result["connected"] = bool(self._snapshot.gps_connected)
        return result

    def ntrip_status(self: Any) -> dict[str, Any]:
        return self._ntrip_client.status()

    def configure_ntrip(self: Any, values: dict[str, Any]) -> dict[str, Any]:
        previous = self._ntrip_client.config
        password = str(values.get("password", ""))
        config = NtripConfig(
            enabled=bool(values.get("enabled", previous.enabled)),
            host=str(values.get("host", previous.host)),
            port=int(values.get("port", previous.port)),
            mountpoint=str(values.get("mountpoint", previous.mountpoint)).lstrip("/"),
            username=str(values.get("username", previous.username)),
            password=password or previous.password,
            tls=bool(values.get("tls", previous.tls)),
            timeout_s=float(values.get("timeout_s", previous.timeout_s)),
            gga_interval_s=float(values.get("gga_interval_s", previous.gga_interval_s)),
        )
        config.validate()
        self._ntrip_client.stop()
        save_ntrip_env(self._ntrip_env_path, config)
        self._ntrip_client = _new_ntrip_client(self, config)
        if config.enabled:
            self._ntrip_client.start()
        return self._ntrip_client.status()

    def extended_close(self: Any) -> None:
        try:
            self._ntrip_client.stop()
        finally:
            original_close(self)

    real_type.__init__ = extended_init
    real_type.start = extended_start
    real_type._connect_gps = extended_connect_gps
    real_type._gps_loop = extended_gps_loop
    real_type.week6_gps_snapshot = week6_gps_snapshot
    real_type.ntrip_status = ntrip_status
    real_type.configure_ntrip = configure_ntrip
    real_type.close = extended_close
    real_type._week6_installed = True


def _copy_to_legacy_snapshot(hardware: Any) -> None:
    data = hardware._week6_parser.data
    with hardware._lock:
        target = hardware._snapshot
        target.gps_fix = data.fix
        target.gps_quality = data.fix_quality
        target.gps_lat = data.latitude
        target.gps_lon = data.longitude
        target.gps_satellites = data.satellites
        target.gps_altitude_m = data.altitude_m
        target.gps_hdop = data.hdop
        target.gps_speed_mps = data.speed_mps
        target.gps_course_deg = data.course_deg
        target.gps_last_update = data.last_update_monotonic
        target.gps_last_fix = data.last_valid_fix_monotonic
        target.gps_connected = True


def _new_ntrip_client(hardware: Any, config: NtripConfig) -> NtripClient:
    def write_rtcm(data: bytes) -> None:
        with hardware._gps_io_lock:
            if hardware._gps is None:
                raise ConnectionError("GPS serial port is unavailable")
            hardware._gps.write(data)
            flush = getattr(hardware._gps, "flush", None)
            if flush:
                flush()

    def gga_provider() -> bytes | None:
        data = hardware._week6_parser.data
        if not data.fix or data.latitude is None or data.longitude is None:
            return None
        return build_gga(
            data.latitude,
            data.longitude,
            satellites=data.satellites,
            hdop=data.hdop or 1.0,
        )

    return NtripClient(config, write_rtcm, gga_provider)

