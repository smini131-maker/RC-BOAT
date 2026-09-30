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
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_error_deg(target: float, current: float) -> float:
    return (target - current + 180.0) % 360.0 - 180.0


def _local_xy_m(origin: tuple[float, float], point: tuple[float, float]) -> tuple[float, float]:
    lat0 = math.radians(origin[0])
    x = math.radians(point[1] - origin[1]) * EARTH_RADIUS_M * math.cos(lat0)
    y = math.radians(point[0] - origin[0]) * EARTH_RADIUS_M
    return x, y


def distance_to_segment_m(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    px, py = _local_xy_m(start, point)
    ex, ey = _local_xy_m(start, end)
    denom = ex * ex + ey * ey
    if denom == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * ex + py * ey) / denom))
    return math.hypot(px - t * ex, py - t * ey)


def distance_to_route_m(point: tuple[float, float], points: list[tuple[float, float]]) -> float:
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine_m(point, points[0])
    return min(distance_to_segment_m(point, a, b) for a, b in zip(points, points[1:]))


@dataclass
class Route:
    route_id: str
    name: str
    points: list[tuple[float, float]]
    arrival_radius_m: float


class RouteManager:
    def __init__(self, route_path: str | Path):
        self.route_path = Path(route_path)
        self.routes: list[Route] = []
        self.selected_index: int | None = None
        self.active_index: int | None = None
        self.waypoint_index = 0
        self._off_route_since: float | None = None
        self._last_switch_at: float | None = None
        self.multipath_enabled = True
        self.endpoint_tolerance_m = 0.75
        self.off_route_distance_m = 8.0
        self.off_route_hold_s = 3.0
        self.closer_advantage_m = 2.0
        self.switch_cooldown_s = 5.0
        self.route_complete = False
        self.load_error = ""
        self.recording = False
        self.recording_name = ""
        self.recording_points: list[tuple[float, float]] = []
        self._recording_last_at: float | None = None
        self.recording_minimum_distance_m = 1.0
        self.recording_minimum_interval_s = 0.5
        self.recording_arrival_radius_m = 3.0
        self.load()

    def configure_multipath(self, settings: dict[str, bool | float]) -> None:
        self.multipath_enabled = bool(settings["enabled"])
        self.endpoint_tolerance_m = float(settings["endpoint_tolerance_m"])
        self.off_route_distance_m = float(settings["off_route_distance_m"])
        self.off_route_hold_s = float(settings["off_route_hold_s"])
        self.closer_advantage_m = float(settings["closer_advantage_m"])
        self.switch_cooldown_s = float(settings["switch_cooldown_s"])
        self._off_route_since = None

    def multipath_settings(self) -> dict[str, bool | float]:
        return {
            "enabled": self.multipath_enabled,
            "endpoint_tolerance_m": self.endpoint_tolerance_m,
            "off_route_distance_m": self.off_route_distance_m,
            "off_route_hold_s": self.off_route_hold_s,
            "closer_advantage_m": self.closer_advantage_m,
            "switch_cooldown_s": self.switch_cooldown_s,
        }

    def load(self) -> bool:
        """Load routes without taking the daemon down when the file is unavailable.

        A missing, malformed, or empty route file leaves navigation safely unavailable.
        The error is exposed in telemetry so the operator can repair and reload it.
        """

        previous_selected = self.selected.route_id if self.selected else None
        previous_active = self.active.route_id if self.active else None
        try:
            payload = json.loads(self.route_path.read_text(encoding="utf-8"))
            routes: list[Route] = []
            seen_ids: set[str] = set()
            for item in payload.get("routes", []):
                route_id = str(item["id"]).strip()
                if not route_id or route_id in seen_ids:
                    raise ValueError(f"duplicate or empty route id: {route_id!r}")
                points = [(float(p["lat"]), float(p["lon"])) for p in item.get("waypoints", [])]
                if not points:
                    continue
                arrival_radius = float(item.get("arrival_radius_m", 3.0))
                if arrival_radius <= 0:
                    raise ValueError(f"arrival_radius_m must be positive for route {route_id}")
                routes.append(
                    Route(
                        route_id=route_id,
                        name=str(item.get("name", route_id)),
                        points=points,
                        arrival_radius_m=arrival_radius,
                    )
                )
                seen_ids.add(route_id)
            if not routes:
                raise ValueError("routes.json contains no route with at least one waypoint")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.routes = []
            self.selected_index = None
            self.active_index = None
            self.waypoint_index = 0
            self._off_route_since = None
            self.route_complete = False
            self.load_error = str(exc)
            return False

        self.routes = routes
        route_ids = [route.route_id for route in routes]
        selected_id = previous_selected if previous_selected in route_ids else route_ids[0]
        active_id = previous_active if previous_active in route_ids else selected_id
        self.selected_index = route_ids.index(selected_id)
        self.active_index = route_ids.index(active_id)
        self.waypoint_index = 0
        self._off_route_since = None
        self._last_switch_at = None
        self.route_complete = False
        self.load_error = ""
        return True

    @property
    def active(self) -> Route | None:
        if self.active_index is None or not (0 <= self.active_index < len(self.routes)):
            return None
        return self.routes[self.active_index]

    @property
    def selected(self) -> Route | None:
        if self.selected_index is None or not (0 <= self.selected_index < len(self.routes)):
            return None
        return self.routes[self.selected_index]

    def select(self, route_id: str) -> None:
        for idx, route in enumerate(self.routes):
            if route.route_id == route_id:
                self.selected_index = idx
                self.active_index = idx
                self.waypoint_index = 0
                self._off_route_since = None
                self._last_switch_at = None
                self.route_complete = False
                return
        raise ValueError(f"unknown route: {route_id}")

    def start_recording(
        self,
        name: str,
        *,
        minimum_distance_m: float = 1.0,
        minimum_interval_s: float = 0.5,
        arrival_radius_m: float = 3.0,
    ) -> None:
        clean_name = " ".join(str(name).strip().split())
        if not clean_name:
            raise ValueError("recording route name is required")
        if len(clean_name) > 60:
            raise ValueError("recording route name is too long")
        if not 0.1 <= minimum_distance_m <= 100.0:
            raise ValueError("minimum recording distance must be between 0.1 and 100 m")
        if not 0.1 <= minimum_interval_s <= 60.0:
            raise ValueError("minimum recording interval must be between 0.1 and 60 s")
        if not 0.5 <= arrival_radius_m <= 100.0:
            raise ValueError("arrival radius must be between 0.5 and 100 m")
        self.recording = True
        self.recording_name = clean_name
        self.recording_points = []
        self._recording_last_at = None
        self.recording_minimum_distance_m = float(minimum_distance_m)
        self.recording_minimum_interval_s = float(minimum_interval_s)
        self.recording_arrival_radius_m = float(arrival_radius_m)

    def record_position(
        self,
        position: tuple[float, float],
        now: float | None = None,
        *,
        minimum_distance_m: float | None = None,
        minimum_interval_s: float | None = None,
    ) -> bool:
        if not self.recording:
            return False
        minimum_distance_m = self.recording_minimum_distance_m if minimum_distance_m is None else minimum_distance_m
        minimum_interval_s = self.recording_minimum_interval_s if minimum_interval_s is None else minimum_interval_s
        now = time.monotonic() if now is None else now
        if self._recording_last_at is not None and now - self._recording_last_at < minimum_interval_s:
            return False
        if self.recording_points and haversine_m(self.recording_points[-1], position) < minimum_distance_m:
            return False
        self.recording_points.append((float(position[0]), float(position[1])))
        self._recording_last_at = now
        return True

    def stop_recording(self, *, save: bool) -> str | None:
        if not self.recording:
            raise RuntimeError("GPS route recording is not active")
        name = self.recording_name
        points = list(self.recording_points)
        if not save:
            self.recording = False
            self.recording_name = ""
            self.recording_points = []
            self._recording_last_at = None
            return None
        if len(points) < 2:
            raise RuntimeError("at least two GPS points are required to save a route")

        try:
            payload = json.loads(self.route_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"routes.json cannot be updated: {exc}") from exc
        items = payload.get("routes")
        if not isinstance(items, list):
            raise RuntimeError("routes.json does not contain a routes list")
        existing_ids = {str(item.get("id", "")) for item in items if isinstance(item, dict)}
        base_id = "recorded_" + time.strftime("%Y%m%d_%H%M%S", time.localtime())
        route_id = base_id
        suffix = 2
        while route_id in existing_ids:
            route_id = f"{base_id}_{suffix}"
            suffix += 1
        items.append(
            {
                "id": route_id,
                "name": name,
                "arrival_radius_m": self.recording_arrival_radius_m,
                "waypoints": [
                    {"lat": round(lat, 8), "lon": round(lon, 8)} for lat, lon in points
                ],
            }
        )
        temporary = self.route_path.with_name(f".{self.route_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.route_path)
        self.recording = False
        self.recording_name = ""
        self.recording_points = []
        self._recording_last_at = None
        if not self.load():
            raise RuntimeError(self.load_error or "saved route could not be reloaded")
        self.select(route_id)
        return route_id

    def recording_state(self) -> dict[str, Any]:
        return {
            "active": self.recording,
            "name": self.recording_name,
            "point_count": len(self.recording_points),
            "minimum_distance_m": self.recording_minimum_distance_m,
            "minimum_interval_s": self.recording_minimum_interval_s,
            "arrival_radius_m": self.recording_arrival_radius_m,
        }

    def _group_indices(self, reference_index: int | None = None) -> list[int]:
        if not self.routes:
            return []
        index = self.selected_index if reference_index is None else reference_index
        if index is None or not (0 <= index < len(self.routes)):
            return []
        reference = self.routes[index]
        return [
            idx for idx, route in enumerate(self.routes)
            if haversine_m(reference.points[0], route.points[0]) <= self.endpoint_tolerance_m
            and haversine_m(reference.points[-1], route.points[-1]) <= self.endpoint_tolerance_m
        ]

    def choose_nearest_group_route(self, position: tuple[float, float]) -> bool:
        if not self.multipath_enabled:
            return False
        candidates = self._group_indices()
        if not candidates:
            return False
        closest_idx = min(candidates, key=lambda idx: distance_to_route_m(position, self.routes[idx].points))
        changed = closest_idx != self.active_index
        self.active_index = closest_idx
        active = self.active
        assert active is not None
        self.waypoint_index = self._nearest_segment_next_waypoint(position, active.points)
        self._off_route_since = None
        self.route_complete = False
        return changed

    @staticmethod
    def _nearest_segment_next_waypoint(
        position: tuple[float, float], points: list[tuple[float, float]]
    ) -> int:
        if len(points) <= 1:
            return 0
        distances = [
            distance_to_segment_m(position, start, end)
            for start, end in zip(points, points[1:])
        ]
        nearest_segment = min(range(len(distances)), key=distances.__getitem__)
        return min(nearest_segment + 1, len(points) - 1)

    def update_position(self, position: tuple[float, float], now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        active = self.active
        if active is None or self.active_index is None:
            raise RuntimeError("no active route")
        if self.waypoint_index >= len(active.points):
            self.waypoint_index = len(active.points) - 1
        target = active.points[self.waypoint_index]
        distance = haversine_m(position, target)
        if distance <= active.arrival_radius_m and self.waypoint_index < len(active.points) - 1:
            self.waypoint_index += 1
            target = active.points[self.waypoint_index]
            distance = haversine_m(position, target)
        elif distance <= active.arrival_radius_m and self.waypoint_index == len(active.points) - 1:
            self.route_complete = True

        route_distances = [distance_to_route_m(position, route.points) for route in self.routes]
        current_distance = route_distances[self.active_index]
        switched = False
        group_indices = self._group_indices()
        switch_cooldown_elapsed = self._last_switch_at is None or now - self._last_switch_at >= self.switch_cooldown_s
        if self.multipath_enabled and not self.route_complete and current_distance >= self.off_route_distance_m and switch_cooldown_elapsed:
            if self._off_route_since is None:
                self._off_route_since = now
            elif now - self._off_route_since >= self.off_route_hold_s:
                closest_idx = min(group_indices, key=route_distances.__getitem__)
                if closest_idx != self.active_index and route_distances[closest_idx] <= current_distance - self.closer_advantage_m:
                    self.active_index = closest_idx
                    active = self.active
                    assert active is not None
                    self.waypoint_index = self._nearest_segment_next_waypoint(position, active.points)
                    self._off_route_since = None
                    self._last_switch_at = now
                    self.route_complete = False
                    switched = True
                    target = active.points[self.waypoint_index]
                    distance = haversine_m(position, target)
        else:
            self._off_route_since = None

        active = self.active
        assert active is not None and self.active_index is not None
        alternatives = [idx for idx in group_indices if idx != self.active_index]
        closest_alternative = min(alternatives, key=route_distances.__getitem__) if alternatives else None
        return {
            "active_route_id": active.route_id,
            "active_route_name": active.name,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(active.points),
            "target_lat": target[0],
            "target_lon": target[1],
            "distance_to_waypoint_m": distance,
            "distance_to_route_m": route_distances[self.active_index],
            "switched_route": switched,
            "route_complete": self.route_complete,
            "multipath_enabled": self.multipath_enabled,
            "multipath_group_route_ids": [self.routes[idx].route_id for idx in group_indices],
            "off_route_duration_s": 0.0 if self._off_route_since is None else max(0.0, now - self._off_route_since),
            "alternative_route_id": self.routes[closest_alternative].route_id if closest_alternative is not None else "",
            "alternative_distance_m": route_distances[closest_alternative] if closest_alternative is not None else None,
            "route_distances_m": {
                route.route_id: round(route_distances[i], 2) for i, route in enumerate(self.routes)
            },
        }

    def public_routes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": route.route_id,
                "name": route.name,
                "waypoints": [{"lat": lat, "lon": lon} for lat, lon in route.points],
                "arrival_radius_m": route.arrival_radius_m,
            }
            for route in self.routes
        ]
