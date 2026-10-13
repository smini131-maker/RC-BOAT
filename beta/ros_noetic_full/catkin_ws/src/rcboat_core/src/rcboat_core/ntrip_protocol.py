from __future__ import annotations

import time
from pathlib import Path


def load_env(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def nmea_coordinate(value: float, latitude: bool) -> tuple[str, str]:
    if latitude:
        direction = "N" if value >= 0 else "S"
    else:
        direction = "E" if value >= 0 else "W"
    value = abs(value)
    degrees = int(value)
    minutes = (value - degrees) * 60.0
    width = 2 if latitude else 3
    return f"{degrees:0{width}d}{minutes:07.4f}", direction


def build_gga(latitude: float, longitude: float) -> bytes:
    lat, ns = nmea_coordinate(latitude, True)
    lon, ew = nmea_coordinate(longitude, False)
    utc = time.strftime("%H%M%S", time.gmtime()) + ".00"
    body = f"GPGGA,{utc},{lat},{ns},{lon},{ew},1,08,1.0,0.0,M,0.0,M,,"
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


def pop_rtcm_frames(buffer: bytearray) -> list[bytes]:
    """Remove and return every complete RTCM3 frame currently in buffer."""
    frames: list[bytes] = []
    while True:
        start = buffer.find(b"\xd3")
        if start < 0:
            buffer.clear()
            return frames
        if start:
            del buffer[:start]
        if len(buffer) < 3:
            return frames
        payload_length = ((buffer[1] & 0x03) << 8) | buffer[2]
        frame_length = 3 + payload_length + 3
        if len(buffer) < frame_length:
            return frames
        frames.append(bytes(buffer[:frame_length]))
        del buffer[:frame_length]
