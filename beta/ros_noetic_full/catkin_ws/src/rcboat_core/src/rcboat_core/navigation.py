from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_error_deg(target: float, current: float) -> float:
    return (target - current + 180.0) % 360.0 - 180.0


def _local_xy_m(origin: tuple[float, float], point: tuple[float, float]) -> tuple[float, float]:
    lat0 = math.radians(origin[0])
    x = math.radians(point[1] - origin[1]) * EARTH_RADIUS_M * math.cos(lat0)
    y = math.radians(point[0] - origin[0]) * EARTH_RADIUS_M
    return x, y


def distance_to_segment_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = _local_xy_m(start, point)
    ex, ey = _local_xy_m(start, end)
    denominator = ex * ex + ey * ey
    if denominator == 0:
        return math.hypot(px, py)
    ratio = max(0.0, min(1.0, (px * ex + py * ey) / denominator))
    return math.hypot(px - ratio * ex, py - ratio * ey)


def distance_to_route_m(point: tuple[float, float], points: list[tuple[float, float]]) -> float:
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine_m(point, points[0])
    return min(
        distance_to_segment_m(point, start, end)
        for start, end in zip(points, points[1:])
    )


@dataclass
class Route:
    route_id: str
    name: str
    points: list[tuple[float, float]]
    arrival_radius_m: float


class RouteManager:
    def __init__(self, route_path: str | Path, multipath: dict[str, Any]) -> None:
        self.route_path = Path(route_path)
        self.routes: list[Route] = []
        self.selected_index: int | None = None
        self.active_index: int | None = None
        self.waypoint_index = 0
        self.route_complete = False
        self.load_error = ""
        self.recording = False
        self.recording_name = ""
        self.recording_points: list[tuple[float, float]] = []
        self.recording_minimum_distance_m = 1.0
        self.recording_minimum_interval_s = 0.5
        self.recording_arrival_radius_m = 3.0
        self._recording_last_at: float | None = None
        self._off_route_since: float | None = None
        self._last_switch_at: float | None = None
        self.configure_multipath(multipath)
        self.load()

    def configure_multipath(self, values: dict[str, Any]) -> None:
        checked = {
            "enabled": bool(values.get("enabled", True)),
            "endpoint_tolerance_m": float(values.get("endpoint_tolerance_m", 0.75)),
            "off_route_distance_m": float(values.get("off_route_distance_m", 8.0)),
            "off_route_hold_s": float(values.get("off_route_hold_s", 3.0)),
            "closer_advantage_m": float(values.get("closer_advantage_m", 2.0)),
            "switch_cooldown_s": float(values.get("switch_cooldown_s", 5.0)),
        }
        limits = {
            "endpoint_tolerance_m": (0.1, 1.0),
            "off_route_distance_m": (1.0, 100.0),
            "off_route_hold_s": (0.0, 30.0),
            "closer_advantage_m": (0.0, 50.0),
            "switch_cooldown_s": (0.0, 60.0),
        }
        for key, (low, high) in limits.items():
            if not low <= checked[key] <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        self.multipath = checked
        self._off_route_since = None

    def load(self) -> bool:
        try:
            payload = json.loads(self.route_path.read_text(encoding="utf-8"))
            routes: list[Route] = []
            seen: set[str] = set()
            for item in payload.get("routes", []):
                route_id = str(item["id"]).strip()
                if not route_id or route_id in seen:
                    raise ValueError("duplicate or empty route id")
                points = [
                    (float(point["lat"]), float(point["lon"]))
                    for point in item.get("waypoints", [])
                ]
                if not points:
                    continue
                routes.append(
                    Route(
                        route_id,
                        str(item.get("name", route_id)),
                        points,
                        float(item.get("arrival_radius_m", 3.0)),
                    )
                )
                seen.add(route_id)
            if not routes:
                raise ValueError("no usable route")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.routes = []
            self.selected_index = None
            self.active_index = None
            self.load_error = str(exc)
            return False
        selected_id = str(payload.get("selected_route_id", ""))
        ids = [route.route_id for route in routes]
        if selected_id not in ids:
            selected_id = ids[0]
        self.routes = routes
        self.selected_index = ids.index(selected_id)
        self.active_index = self.selected_index
        self.waypoint_index = 0
        self.route_complete = False
        self.load_error = ""
        return True

    @property
    def selected(self) -> Route | None:
        if self.selected_index is None:
            return None
        return self.routes[self.selected_index]

    @property
    def active(self) -> Route | None:
        if self.active_index is None:
            return None
        return self.routes[self.active_index]

    def select(self, route_id: str) -> None:
        ids = [route.route_id for route in self.routes]
        if route_id not in ids:
            raise ValueError(f"unknown route: {route_id}")
        self._atomic_update_selected(route_id)
        self.selected_index = ids.index(route_id)
        self.active_index = self.selected_index
        self.waypoint_index = 0
        self.route_complete = False
        self._off_route_since = None
        self._last_switch_at = None

    def _atomic_update_selected(self, route_id: str) -> None:
        payload = json.loads(self.route_path.read_text(encoding="utf-8"))
        payload["selected_route_id"] = route_id
        temporary = self.route_path.with_name(f".{self.route_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.route_path)

    def start_recording(
        self,
        name: str,
        minimum_distance_m: float,
        minimum_interval_s: float,
        arrival_radius_m: float,
    ) -> None:
        name = " ".join(name.strip().split())
        if not name:
            raise ValueError("route name is required")
        if not 0.1 <= minimum_distance_m <= 100.0:
            raise ValueError("minimum distance out of range")
        if not 0.1 <= minimum_interval_s <= 60.0:
            raise ValueError("minimum interval out of range")
        if not 0.5 <= arrival_radius_m <= 100.0:
            raise ValueError("arrival radius out of range")
        self.recording = True
        self.recording_name = name
        self.recording_points = []
        self.recording_minimum_distance_m = minimum_distance_m
        self.recording_minimum_interval_s = minimum_interval_s
        self.recording_arrival_radius_m = arrival_radius_m
        self._recording_last_at = None

    def record_position(self, position: tuple[float, float], now: float) -> bool:
        if not self.recording:
            return False
        if self._recording_last_at is not None:
            if now - self._recording_last_at < self.recording_minimum_interval_s:
                return False
        if self.recording_points:
            if haversine_m(self.recording_points[-1], position) < self.recording_minimum_distance_m:
                return False
        self.recording_points.append(position)
        self._recording_last_at = now
        return True

    def stop_recording(self, save: bool) -> str | None:
        if not self.recording:
            raise RuntimeError("route recording is not active")
        points = list(self.recording_points)
        name = self.recording_name
        if save and len(points) < 2:
            raise RuntimeError("at least two GPS points are required")
        self.recording = False
        self.recording_name = ""
        self.recording_points = []
        self._recording_last_at = None
        if not save:
            return None
        payload = json.loads(self.route_path.read_text(encoding="utf-8"))
        existing = {str(item.get("id", "")) for item in payload.get("routes", [])}
        base = "recorded_" + time.strftime("%Y%m%d_%H%M%S")
        route_id = base
        suffix = 2
        while route_id in existing:
            route_id = f"{base}_{suffix}"
            suffix += 1
        payload["routes"].append(
            {
                "id": route_id,
                "name": name,
                "arrival_radius_m": self.recording_arrival_radius_m,
                "waypoints": [
                    {"lat": round(lat, 8), "lon": round(lon, 8)}
                    for lat, lon in points
                ],
            }
        )
        payload["selected_route_id"] = route_id
        temporary = self.route_path.with_name(f".{self.route_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.route_path)
        self.load()
        self.select(route_id)
        return route_id

    def _group_indices(self) -> list[int]:
        selected = self.selected
        if selected is None:
            return []
        tolerance = self.multipath["endpoint_tolerance_m"]
        return [
            index
            for index, route in enumerate(self.routes)
            if haversine_m(selected.points[0], route.points[0]) <= tolerance
            and haversine_m(selected.points[-1], route.points[-1]) <= tolerance
        ]

    def _nearest_next_waypoint(self, position: tuple[float, float], route: Route) -> int:
        if len(route.points) <= 1:
            return 0
        distances = [
            distance_to_segment_m(position, start, end)
            for start, end in zip(route.points, route.points[1:])
        ]
        return min(range(len(distances)), key=distances.__getitem__) + 1

    def update_position(self, position: tuple[float, float], now: float) -> dict[str, Any]:
        active = self.active
        if active is None or self.active_index is None:
            raise RuntimeError("no active route")
        target = active.points[self.waypoint_index]
        distance = haversine_m(position, target)
        if distance <= active.arrival_radius_m:
            if self.waypoint_index < len(active.points) - 1:
                self.waypoint_index += 1
                target = active.points[self.waypoint_index]
                distance = haversine_m(position, target)
            else:
                self.route_complete = True

        route_distances = [
            distance_to_route_m(position, route.points) for route in self.routes
        ]
        current_distance = route_distances[self.active_index]
        cooldown_ok = (
            self._last_switch_at is None
            or now - self._last_switch_at >= self.multipath["switch_cooldown_s"]
        )
        if (
            self.multipath["enabled"]
            and not self.route_complete
            and current_distance >= self.multipath["off_route_distance_m"]
            and cooldown_ok
        ):
            if self._off_route_since is None:
                self._off_route_since = now
            elif now - self._off_route_since >= self.multipath["off_route_hold_s"]:
                candidates = self._group_indices()
                closest = min(candidates, key=route_distances.__getitem__)
                if (
                    closest != self.active_index
                    and route_distances[closest]
                    <= current_distance - self.multipath["closer_advantage_m"]
                ):
                    self.active_index = closest
                    active = self.active
                    assert active is not None
                    self.waypoint_index = self._nearest_next_waypoint(position, active)
                    self._off_route_since = None
                    self._last_switch_at = now
                    target = active.points[self.waypoint_index]
                    distance = haversine_m(position, target)
        else:
            self._off_route_since = None

        active = self.active
        assert active is not None and self.active_index is not None
        return {
            "active_route_id": active.route_id,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(active.points),
            "target": target,
            "distance_to_waypoint_m": distance,
            "distance_to_route_m": route_distances[self.active_index],
            "route_complete": self.route_complete,
        }
