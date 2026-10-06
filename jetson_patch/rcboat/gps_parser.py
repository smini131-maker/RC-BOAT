from __future__ import annotations

import math
import struct
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


FIX_LABELS = {
    0: "NO FIX",
    1: "GPS",
    2: "DGPS",
    4: "RTK FIXED",
    5: "RTK FLOAT",
}


@dataclass
class GpsData:
    utc_time: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    fix_quality: int = 0
    fix_label: str = "NO FIX"
    satellites: int = 0
    hdop: float | None = None
    pdop: float | None = None
    vdop: float | None = None
    speed_mps: float = 0.0
    course_deg: float | None = None
    cno_avg_dbhz: float | None = None
    hacc_m: float | None = None
    fix_type: int | None = None
    carr_soln: int | None = None
    rtk_state: str = "NO_RTK"
    last_update_monotonic: float = 0.0
    last_valid_fix_monotonic: float = 0.0
    parser_error_count: int = 0
    nmea_sentence_count: int = 0
    ubx_message_count: int = 0
    utm_easting: float | None = None
    utm_northing: float | None = None
    utm_zone: str | None = None

    @property
    def fix(self) -> bool:
        return self.fix_quality > 0 and self.latitude is not None and self.longitude is not None

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result["fix"] = self.fix
        return result


def nmea_degrees(raw: str, hemisphere: str) -> float:
    if not raw or hemisphere not in {"N", "S", "E", "W"}:
        raise ValueError("invalid NMEA coordinate")
    split = 2 if hemisphere in {"N", "S"} else 3
    if len(raw) <= split:
        raise ValueError("short NMEA coordinate")
    value = float(raw[:split]) + float(raw[split:]) / 60.0
    return -value if hemisphere in {"S", "W"} else value


def valid_nmea_checksum(sentence: str) -> bool:
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    payload, supplied = sentence[1:].split("*", 1)
    if len(supplied) < 2:
        return False
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    try:
        return checksum == int(supplied[:2], 16)
    except ValueError:
        return False


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _rtk_state(fix_quality: int, carr_soln: int | None) -> str:
    if carr_soln == 2 or fix_quality == 4:
        return "RTK_FIXED"
    if carr_soln == 1 or fix_quality == 5:
        return "RTK_FLOAT"
    if fix_quality == 2:
        return "DGPS"
    if fix_quality == 1:
        return "NO_RTK"
    return "UNKNOWN" if fix_quality not in {0, 1, 2, 4, 5} else "NO_RTK"


def latlon_to_utm(latitude: float, longitude: float) -> tuple[float, float, str]:
    """Convert WGS84 to UTM without changing the navigation algorithm.

    PyProj is imported lazily so a missing optional dependency cannot stop the
    safety daemon. The installer adds it, while tests can still exercise all
    non-UTM functions on a minimal Python environment.
    """

    if not (-80.0 <= latitude <= 84.0 and -180.0 <= longitude <= 180.0):
        raise ValueError("coordinate is outside UTM coverage")
    zone_number = int((longitude + 180.0) // 6.0) + 1
    zone_number = max(1, min(60, zone_number))
    epsg = (32600 if latitude >= 0 else 32700) + zone_number
    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        easting, northing = transformer.transform(longitude, latitude)
    except ImportError:
        # WGS84 transverse-Mercator fallback keeps logging available even if
        # PyProj installation is temporarily unavailable on the Jetson.
        a = 6378137.0
        eccentricity_sq = 0.00669437999014
        k0 = 0.9996
        lat_rad = math.radians(latitude)
        lon_rad = math.radians(longitude)
        central_meridian = math.radians((zone_number - 1) * 6 - 180 + 3)
        second_eccentricity_sq = eccentricity_sq / (1 - eccentricity_sq)
        n = a / math.sqrt(1 - eccentricity_sq * math.sin(lat_rad) ** 2)
        t = math.tan(lat_rad) ** 2
        c = second_eccentricity_sq * math.cos(lat_rad) ** 2
        aa = math.cos(lat_rad) * (lon_rad - central_meridian)
        m = a * (
            (1 - eccentricity_sq / 4 - 3 * eccentricity_sq ** 2 / 64 - 5 * eccentricity_sq ** 3 / 256) * lat_rad
            - (3 * eccentricity_sq / 8 + 3 * eccentricity_sq ** 2 / 32 + 45 * eccentricity_sq ** 3 / 1024) * math.sin(2 * lat_rad)
            + (15 * eccentricity_sq ** 2 / 256 + 45 * eccentricity_sq ** 3 / 1024) * math.sin(4 * lat_rad)
            - (35 * eccentricity_sq ** 3 / 3072) * math.sin(6 * lat_rad)
        )
        easting = k0 * n * (aa + (1 - t + c) * aa ** 3 / 6 + (5 - 18 * t + t ** 2 + 72 * c - 58 * second_eccentricity_sq) * aa ** 5 / 120) + 500000.0
        northing = k0 * (m + n * math.tan(lat_rad) * (aa ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * aa ** 4 / 24 + (61 - 58 * t + t ** 2 + 600 * c - 330 * second_eccentricity_sq) * aa ** 6 / 720))
        if latitude < 0:
            northing += 10000000.0
    hemisphere = "N" if latitude >= 0 else "S"
    return float(easting), float(northing), f"{zone_number}{hemisphere}"


class MixedGpsParser:
    """Incremental NMEA/UBX parser for a mixed u-blox byte stream."""

    MAX_BUFFER = 16_384

    def __init__(self) -> None:
        self.data = GpsData()
        self._buffer = bytearray()
        self._gga_valid = False
        self._rmc_valid = False
        self._gsv_snr: list[float] = []

    def feed(self, chunk: bytes, now: float | None = None) -> bool:
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("GPS input must be bytes")
        if not chunk:
            return False
        now = time.monotonic() if now is None else now
        self._buffer.extend(chunk)
        changed = False
        while self._buffer:
            dollar = self._buffer.find(b"$")
            ubx = self._buffer.find(b"\xb5\x62")
            starts = [value for value in (dollar, ubx) if value >= 0]
            if not starts:
                if len(self._buffer) > 2:
                    del self._buffer[:-2]
                break
            start = min(starts)
            if start:
                del self._buffer[:start]
            if self._buffer.startswith(b"$"):
                boundary = self._nmea_boundary()
                if boundary is None:
                    break
                raw = bytes(self._buffer[:boundary])
                del self._buffer[:boundary]
                while bytes(self._buffer[:1]) in {b"\r", b"\n"}:
                    del self._buffer[:1]
                try:
                    sentence = raw.decode("ascii", errors="strict").strip()
                except UnicodeDecodeError:
                    self.data.parser_error_count += 1
                    continue
                if not valid_nmea_checksum(sentence):
                    self.data.parser_error_count += 1
                    continue
                try:
                    changed = self._parse_nmea(sentence, now) or changed
                    self.data.nmea_sentence_count += 1
                except (ValueError, IndexError):
                    self.data.parser_error_count += 1
            elif self._buffer.startswith(b"\xb5\x62"):
                if len(self._buffer) < 6:
                    break
                length = int.from_bytes(self._buffer[4:6], "little")
                total = 6 + length + 2
                if length > 4096:
                    del self._buffer[:2]
                    self.data.parser_error_count += 1
                    continue
                if len(self._buffer) < total:
                    break
                packet = bytes(self._buffer[:total])
                del self._buffer[:total]
                if not self._valid_ubx(packet):
                    self.data.parser_error_count += 1
                    continue
                try:
                    changed = self._parse_ubx(packet, now) or changed
                    self.data.ubx_message_count += 1
                except (ValueError, IndexError, struct.error):
                    self.data.parser_error_count += 1
            if len(self._buffer) > self.MAX_BUFFER:
                del self._buffer[:-2]
                self.data.parser_error_count += 1
        if changed:
            self._update_utm()
        return changed

    def _nmea_boundary(self) -> int | None:
        newline = [p for marker in (b"\r", b"\n") if (p := self._buffer.find(marker, 1)) >= 0]
        next_dollar = self._buffer.find(b"$", 1)
        next_ubx = self._buffer.find(b"\xb5\x62", 1)
        candidates = newline + [p for p in (next_dollar, next_ubx) if p >= 0]
        if candidates:
            return min(candidates)
        if len(self._buffer) > 1024:
            return len(self._buffer)
        return None

    @staticmethod
    def _valid_ubx(packet: bytes) -> bool:
        ck_a = 0
        ck_b = 0
        for value in packet[2:-2]:
            ck_a = (ck_a + value) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return packet[-2:] == bytes((ck_a, ck_b))

    def _parse_nmea(self, sentence: str, now: float) -> bool:
        fields = sentence.split("*", 1)[0].split(",")
        message = fields[0][-3:]
        if message == "GGA":
            quality = int(fields[6] or 0)
            self.data.utc_time = fields[1] or self.data.utc_time
            self.data.fix_quality = quality
            self.data.fix_label = FIX_LABELS.get(quality, f"FIX {quality}")
            self.data.satellites = int(fields[7] or 0)
            self.data.hdop = _optional_float(fields[8])
            self.data.altitude_m = _optional_float(fields[9])
            self._gga_valid = quality > 0
            if self._gga_valid and fields[2] and fields[4]:
                self.data.latitude = nmea_degrees(fields[2], fields[3])
                self.data.longitude = nmea_degrees(fields[4], fields[5])
                self.data.last_valid_fix_monotonic = now
            self.data.last_update_monotonic = now
        elif message == "RMC":
            self.data.utc_time = fields[1] or self.data.utc_time
            valid = fields[2] == "A"
            self._rmc_valid = valid
            if valid and fields[3] and fields[5]:
                self.data.latitude = nmea_degrees(fields[3], fields[4])
                self.data.longitude = nmea_degrees(fields[5], fields[6])
                self.data.speed_mps = float(fields[7] or 0.0) * 0.514444
                self.data.course_deg = _optional_float(fields[8])
                self.data.last_valid_fix_monotonic = now
                if self.data.fix_quality == 0:
                    self.data.fix_quality = 1
                    self.data.fix_label = "GPS"
            elif not self._gga_valid:
                self.data.fix_quality = 0
                self.data.fix_label = "NO FIX"
            self.data.last_update_monotonic = now
        elif message == "GSA":
            # NMEA 2.x: mode1, mode2, 12 PRNs, PDOP, HDOP, VDOP.
            if len(fields) >= 18:
                self.data.pdop = _optional_float(fields[-3])
                self.data.hdop = _optional_float(fields[-2]) or self.data.hdop
                self.data.vdop = _optional_float(fields[-1])
                self.data.last_update_monotonic = now
        elif message == "GSV":
            total_messages = int(fields[1] or 1)
            message_number = int(fields[2] or 1)
            if message_number == 1:
                self._gsv_snr = []
            for index in range(7, len(fields), 4):
                value = fields[index] if index < len(fields) else ""
                if value:
                    self._gsv_snr.append(float(value))
            if message_number >= total_messages and self._gsv_snr:
                self.data.cno_avg_dbhz = sum(self._gsv_snr) / len(self._gsv_snr)
            self.data.last_update_monotonic = now
        else:
            return False
        self.data.rtk_state = _rtk_state(self.data.fix_quality, self.data.carr_soln)
        return True

    def _parse_ubx(self, packet: bytes, now: float) -> bool:
        msg_class, msg_id = packet[2], packet[3]
        payload = packet[6:-2]
        if (msg_class, msg_id) != (0x01, 0x07) or len(payload) < 92:
            return False
        year = int.from_bytes(payload[4:6], "little")
        month, day, hour, minute, second = payload[6:11]
        valid = payload[11]
        fix_type = payload[20]
        flags = payload[21]
        num_sv = payload[23]
        lon = struct.unpack_from("<i", payload, 24)[0] * 1e-7
        lat = struct.unpack_from("<i", payload, 28)[0] * 1e-7
        height_msl = struct.unpack_from("<i", payload, 36)[0] / 1000.0
        hacc_m = int.from_bytes(payload[40:44], "little") / 1000.0
        ground_speed = struct.unpack_from("<i", payload, 60)[0] / 1000.0
        heading = struct.unpack_from("<i", payload, 64)[0] * 1e-5
        pdop = int.from_bytes(payload[76:78], "little") * 0.01
        carr_soln = (flags >> 6) & 0x03
        gnss_fix_ok = bool(flags & 0x01) and fix_type >= 2
        self.data.fix_type = fix_type
        self.data.carr_soln = carr_soln
        self.data.satellites = num_sv
        self.data.hacc_m = hacc_m
        self.data.pdop = pdop
        self.data.speed_mps = max(0.0, ground_speed)
        self.data.course_deg = heading % 360.0 if heading >= 0 else None
        if valid & 0x03 and year >= 2000:
            try:
                stamp = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                self.data.utc_time = stamp.isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
        if gnss_fix_ok:
            self.data.latitude = lat
            self.data.longitude = lon
            self.data.altitude_m = height_msl
            self.data.last_valid_fix_monotonic = now
            if carr_soln == 2:
                self.data.fix_quality = 4
            elif carr_soln == 1:
                self.data.fix_quality = 5
            elif self.data.fix_quality == 0:
                self.data.fix_quality = 1
            self.data.fix_label = FIX_LABELS.get(self.data.fix_quality, f"FIX {self.data.fix_quality}")
        elif not self._gga_valid and not self._rmc_valid:
            self.data.fix_quality = 0
            self.data.fix_label = "NO FIX"
        self.data.rtk_state = _rtk_state(self.data.fix_quality, carr_soln)
        self.data.last_update_monotonic = now
        return True

    def _update_utm(self) -> None:
        if self.data.latitude is None or self.data.longitude is None:
            return
        try:
            easting, northing, zone = latlon_to_utm(self.data.latitude, self.data.longitude)
        except (ImportError, ValueError, RuntimeError):
            return
        if all(math.isfinite(value) for value in (easting, northing)):
            self.data.utm_easting = easting
            self.data.utm_northing = northing
            self.data.utm_zone = zone
