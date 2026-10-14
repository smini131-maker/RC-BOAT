from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GPS_LOG_FIELDS = (
    "local_timestamp", "utc_time", "latitude", "longitude", "altitude_m",
    "fix_quality", "fix_label", "satellites", "hdop", "pdop", "vdop",
    "speed_mps", "course_deg", "cno_avg_dbhz", "hacc_m", "rtk_state",
    "rtk_correction_age_s", "gps_health", "active_route_id", "navigation_state",
    "utm_easting", "utm_northing", "utm_zone",
)


class GpsCsvLogger:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._handle = None
        self._writer: csv.DictWriter | None = None
        self.file_path = ""
        self.samples = 0
        self.started_at: str | None = None

    @property
    def active(self) -> bool:
        return self._handle is not None

    def start(self, now: datetime | None = None) -> str:
        with self._lock:
            if self.active:
                raise RuntimeError("GPS data logging is already active")
            now = now or datetime.now().astimezone()
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"gps_{now:%Y%m%d_%H%M%S}.csv"
            suffix = 1
            while path.exists():
                path = self.directory / f"gps_{now:%Y%m%d_%H%M%S}_{suffix}.csv"
                suffix += 1
            handle = path.open("x", encoding="utf-8-sig", newline="")
            self._handle = handle
            self._writer = csv.DictWriter(handle, fieldnames=GPS_LOG_FIELDS, extrasaction="ignore")
            self._writer.writeheader()
            handle.flush()
            os.fsync(handle.fileno())
            self.file_path = str(path)
            self.samples = 0
            self.started_at = now.isoformat()
            return self.file_path

    def write(self, sample: dict[str, Any]) -> None:
        with self._lock:
            if not self.active or self._writer is None:
                return
            row = {key: sample.get(key, "") for key in GPS_LOG_FIELDS}
            row["local_timestamp"] = row["local_timestamp"] or datetime.now().astimezone().isoformat(timespec="milliseconds")
            for key, value in list(row.items()):
                if value is None:
                    row[key] = ""
            self._writer.writerow(row)
            self.samples += 1
            self._handle.flush()
            if self.samples % 10 == 0:
                os.fsync(self._handle.fileno())

    def stop(self) -> str:
        with self._lock:
            if not self.active:
                raise RuntimeError("GPS data logging is not active")
            path = self.file_path
            try:
                self._handle.flush()
                os.fsync(self._handle.fileno())
            finally:
                self._handle.close()
                self._handle = None
                self._writer = None
            return path

    def state(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "file_path": self.file_path,
            "samples": self.samples,
            "started_at": self.started_at,
        }

    def close(self) -> None:
        if self.active:
            self.stop()

