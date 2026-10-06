from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import ARDUINO_BY_ID, GPS_BY_ID, RuntimeSettings, VALUES
from .gps_parser import MixedGpsParser, nmea_degrees, valid_nmea_checksum
from .pca_direct import DirectLinuxPCA9685


@dataclass
class HardwareSnapshot:
    rc_steering_us: int | None = None
    rc_throttle_us: int | None = None
    rc_last_update: float = 0.0
    gps_fix: bool = False
    gps_quality: int = 0
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_satellites: int = 0
    gps_altitude_m: float | None = None
    gps_hdop: float | None = None
    gps_speed_mps: float = 0.0
    gps_course_deg: float | None = None
    gps_last_update: float = 0.0
    gps_last_fix: float = 0.0
    arduino_connected: bool = False
    gps_connected: bool = False
    pca_connected: bool = False
    errors: list[str] = field(default_factory=list)


def _nmea_degrees(raw: str, hemisphere: str) -> float:
    return nmea_degrees(raw, hemisphere)


def _valid_nmea_checksum(sentence: str) -> bool:
    return valid_nmea_checksum(sentence)


def _extract_nmea_sentences(buffer: bytearray) -> list[str]:
    """Compatibility extractor used by the R12 regression tests."""

    result: list[str] = []
    while True:
        start = buffer.find(b"$")
        if start < 0:
            if len(buffer) > 2:
                del buffer[:-2]
            break
        if start:
            del buffer[:start]
        endings = [p for marker in (b"\r", b"\n") if (p := buffer.find(marker, 1)) >= 0]
        next_start = buffer.find(b"$", 1)
        if next_start >= 0:
            endings.append(next_start)
        if not endings:
            break
        end = min(endings)
        raw = bytes(buffer[:end])
        del buffer[:end]
        while bytes(buffer[:1]) in {b"\r", b"\n"}:
            del buffer[:1]
        try:
            sentence = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if sentence[3:6] in {"GGA", "RMC", "GSA", "GSV"} and valid_nmea_checksum(sentence):
            result.append(sentence)
    return result


class BaseHardware:
    is_mock = False

    def start(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def snapshot(self) -> HardwareSnapshot:
        raise NotImplementedError

    def write_pwm(self, steering: int, throttle: int) -> None:
        raise NotImplementedError


class RealHardware(BaseHardware):
    """Reference Direct-I2C implementation; the installer preserves the live driver."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self._snapshot = HardwareSnapshot()
        self._lock = threading.Lock()
        self._pwm_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._serial_module = None
        self._arduino = None
        self._gps = None
        self._pca: DirectLinuxPCA9685 | None = None
        self._gga_fix = False
        self._rmc_fix = False
        self._week6_parser = MixedGpsParser()

    def start(self) -> None:
        import serial

        self._serial_module = serial
        try:
            self._connect_pca()
        except Exception as exc:
            self._append_error(f"PCA9685 connect: {exc}")
        self._threads = [
            threading.Thread(target=self._arduino_loop, name="arduino-reconnect", daemon=True),
            threading.Thread(target=self._gps_loop, name="gps-reconnect", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _connect_pca(self) -> None:
        candidate = DirectLinuxPCA9685(1, 0x40, VALUES.pca_frequency_hz)
        try:
            candidate.set_duty_cycle(VALUES.steering_channel, VALUES.steering_center_pwm)
            candidate.set_duty_cycle(VALUES.throttle_channel, VALUES.throttle_stop_pwm)
        except Exception:
            candidate.close()
            raise
        self._pca = candidate
        with self._lock:
            self._snapshot.pca_connected = True

    def _mark_pca_offline(self, message: str) -> None:
        candidate, self._pca = self._pca, None
        if candidate:
            try:
                candidate.close()
            except Exception:
                pass
        with self._lock:
            self._snapshot.pca_connected = False
        self._append_error(message)

    def _append_error(self, message: str) -> None:
        with self._lock:
            if not self._snapshot.errors or self._snapshot.errors[-1] != message:
                self._snapshot.errors = (self._snapshot.errors + [message])[-10:]

    @staticmethod
    def _close_port(port) -> None:
        if port is not None:
            try:
                port.close()
            except Exception:
                pass

    def _mark_arduino_offline(self) -> None:
        self._close_port(self._arduino)
        self._arduino = None
        with self._lock:
            self._snapshot.arduino_connected = False
            self._snapshot.rc_steering_us = None
            self._snapshot.rc_throttle_us = None
            self._snapshot.rc_last_update = 0.0

    def _mark_gps_offline(self) -> None:
        self._close_port(self._gps)
        self._gps = None
        with self._lock:
            self._snapshot.gps_connected = False
            self._snapshot.gps_fix = False
            self._snapshot.gps_quality = 0
            self._snapshot.gps_lat = None
            self._snapshot.gps_lon = None
            self._snapshot.gps_last_update = 0.0

    def _connect_arduino(self) -> bool:
        if not Path(ARDUINO_BY_ID).exists():
            return False
        try:
            self._arduino = self._serial_module.Serial(ARDUINO_BY_ID, 9600, timeout=0.2)
            with self._lock:
                self._snapshot.arduino_connected = True
            return True
        except Exception as exc:
            self._append_error(f"Arduino connect: {exc}")
            self._mark_arduino_offline()
            return False

    def _connect_gps(self) -> bool:
        if not Path(GPS_BY_ID).exists():
            return False
        try:
            self._gps = self._serial_module.Serial(GPS_BY_ID, self.settings.gps_baudrate, timeout=0.2)
            with self._lock:
                self._snapshot.gps_connected = True
            return True
        except Exception as exc:
            self._append_error(f"GPS connect: {exc}")
            self._mark_gps_offline()
            return False

    def _arduino_loop(self) -> None:
        last_data = time.monotonic()
        while not self._stop.is_set():
            if self._arduino is None:
                if not self._connect_arduino():
                    self._stop.wait(self.settings.reconnect_interval_s)
                    continue
                last_data = time.monotonic()
            try:
                line = self._arduino.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    if time.monotonic() - last_data > VALUES.serial_stale_timeout_s:
                        raise TimeoutError("Arduino serial data became stale")
                    continue
                steering_s, throttle_s = line.split(",", 1)
                steering, throttle = int(steering_s), int(throttle_s)
                if not (800 <= steering <= 2200 and 800 <= throttle <= 2200):
                    raise ValueError("out-of-range RC data")
                with self._lock:
                    self._snapshot.rc_steering_us = steering
                    self._snapshot.rc_throttle_us = throttle
                    self._snapshot.rc_last_update = time.monotonic()
                    self._snapshot.arduino_connected = True
                last_data = time.monotonic()
            except Exception as exc:
                self._append_error(f"Arduino disconnected: {exc}")
                self._mark_arduino_offline()
                self._stop.wait(self.settings.reconnect_interval_s)

    def _gps_loop(self) -> None:
        last_data = time.monotonic()
        while not self._stop.is_set():
            if self._gps is None:
                if not self._connect_gps():
                    self._stop.wait(self.settings.reconnect_interval_s)
                    continue
                last_data = time.monotonic()
            try:
                chunk = self._gps.read(512)
                if not chunk:
                    if time.monotonic() - last_data > VALUES.gps_stale_timeout_s:
                        raise TimeoutError("GPS byte stream became stale")
                    continue
                last_data = time.monotonic()
                if self._week6_parser.feed(chunk, last_data):
                    self._copy_week6_data()
            except Exception as exc:
                self._append_error(f"GPS disconnected: {exc}")
                self._mark_gps_offline()
                self._stop.wait(self.settings.reconnect_interval_s)

    def _parse_nmea(self, line: str) -> None:
        self._week6_parser.feed((line + "\r\n").encode("ascii"))
        self._copy_week6_data()

    def _copy_week6_data(self) -> None:
        data = self._week6_parser.data
        with self._lock:
            self._snapshot.gps_fix = data.fix
            self._snapshot.gps_quality = data.fix_quality
            self._snapshot.gps_lat = data.latitude
            self._snapshot.gps_lon = data.longitude
            self._snapshot.gps_satellites = data.satellites
            self._snapshot.gps_altitude_m = data.altitude_m
            self._snapshot.gps_hdop = data.hdop
            self._snapshot.gps_speed_mps = data.speed_mps
            self._snapshot.gps_course_deg = data.course_deg
            self._snapshot.gps_last_update = data.last_update_monotonic
            self._snapshot.gps_last_fix = data.last_valid_fix_monotonic

    def write_pwm(self, steering: int, throttle: int) -> None:
        with self._pwm_lock:
            if self._pca is None:
                self._connect_pca()
            try:
                self._pca.set_duty_cycle(VALUES.steering_channel, int(steering))
                self._pca.set_duty_cycle(VALUES.throttle_channel, int(throttle))
            except Exception as exc:
                self._mark_pca_offline(f"PCA9685 write: {exc}")
                raise

    def snapshot(self) -> HardwareSnapshot:
        with self._lock:
            return HardwareSnapshot(**vars(self._snapshot))

    def close(self) -> None:
        self._stop.set()
        try:
            self.write_pwm(VALUES.steering_center_pwm, VALUES.throttle_stop_pwm)
        except Exception:
            pass
        self._mark_arduino_offline()
        self._mark_gps_offline()
        for thread in self._threads:
            thread.join(timeout=0.5)
        if self._pca:
            self._pca.close()
        with self._lock:
            self._snapshot.pca_connected = False


class MockHardware(BaseHardware):
    is_mock = True

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.last_steering = VALUES.steering_center_pwm
        self.last_throttle = VALUES.throttle_stop_pwm
        self._closed = False
        self._arduino_connected = True
        self._gps_connected = True
        self._gps_fix = True
        self._rc_steering_us = VALUES.steering_center_us
        self._rc_throttle_us = VALUES.throttle_center_us

    def start(self) -> None:
        self.started_at = time.monotonic()
        self._closed = False

    def set_arduino_connected(self, connected: bool) -> None:
        self._arduino_connected = connected

    def set_gps(self, connected: bool, fix: bool | None = None) -> None:
        self._gps_connected = connected
        self._gps_fix = connected and (self._gps_fix if fix is None else fix)

    def set_rc(self, steering_us: int, throttle_us: int) -> None:
        self._rc_steering_us = steering_us
        self._rc_throttle_us = throttle_us

    def snapshot(self) -> HardwareSnapshot:
        t = time.monotonic() - self.started_at
        now = time.monotonic()
        lat = 35.0780 + math.sin(t / 20.0) * 0.00003
        lon = 129.0860 + math.cos(t / 20.0) * 0.00003
        return HardwareSnapshot(
            rc_steering_us=self._rc_steering_us if self._arduino_connected else None,
            rc_throttle_us=self._rc_throttle_us if self._arduino_connected else None,
            rc_last_update=now if self._arduino_connected else 0.0,
            gps_fix=self._gps_connected and self._gps_fix,
            gps_quality=4 if self._gps_connected and self._gps_fix else 0,
            gps_lat=lat if self._gps_connected and self._gps_fix else None,
            gps_lon=lon if self._gps_connected and self._gps_fix else None,
            gps_satellites=18 if self._gps_connected and self._gps_fix else 0,
            gps_altitude_m=4.2 if self._gps_connected and self._gps_fix else None,
            gps_hdop=0.8 if self._gps_connected and self._gps_fix else None,
            gps_speed_mps=1.2 if self._gps_connected and self._gps_fix else 0.0,
            gps_course_deg=(t * 8.0) % 360.0 if self._gps_connected and self._gps_fix else None,
            gps_last_update=now if self._gps_connected else 0.0,
            gps_last_fix=now if self._gps_connected and self._gps_fix else 0.0,
            arduino_connected=self._arduino_connected,
            gps_connected=self._gps_connected,
            pca_connected=not self._closed,
        )

    def write_pwm(self, steering: int, throttle: int) -> None:
        if self._closed:
            raise RuntimeError("mock hardware is closed")
        self.last_steering = int(steering)
        self.last_throttle = int(throttle)

    def close(self) -> None:
        self.last_steering = VALUES.steering_center_pwm
        self.last_throttle = VALUES.throttle_stop_pwm
        self._closed = True
