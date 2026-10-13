#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import rospy
from std_srvs.srv import Trigger, TriggerResponse

from rcboat_ros.msg import BoatState, GpsStatus, RouteState
from rcboat_ros.navigation import RouteManager
from rcboat_ros.srv import (
    DeleteRoute, DeleteRouteResponse, SelectRoute, SelectRouteResponse,
    SetMultipath, SetMultipathResponse, StartRouteRecording,
    StartRouteRecordingResponse, StopRouteRecording, StopRouteRecordingResponse,
)


class RouteManagerNode:
    def __init__(self) -> None:
        runtime = Path(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime"))
        runtime.mkdir(parents=True, exist_ok=True)
        self.settings_path = runtime / "multipath_settings.json"
        self.manager = RouteManager(runtime / "routes.json")
        self._configure_from_files()
        self._lock = threading.RLock()
        self._gps = None
        self._mode = "AUTO"
        self._last_status = {}
        self._navigation_prepared = False
        self.publisher = rospy.Publisher("/rcboat/route/state", RouteState, queue_size=10, latch=True)
        rospy.Subscriber("/rcboat/gps/status", GpsStatus, self._on_gps, queue_size=10)
        rospy.Subscriber("/rcboat/safety/state", BoatState, self._on_boat, queue_size=10)
        rospy.Service("/rcboat/routes/select", SelectRoute, self._select)
        rospy.Service("/rcboat/routes/delete", DeleteRoute, self._delete)
        rospy.Service("/rcboat/routes/start_recording", StartRouteRecording, self._start_recording)
        rospy.Service("/rcboat/routes/stop_recording", StopRouteRecording, self._stop_recording)
        rospy.Service("/rcboat/routes/reload", Trigger, self._reload)
        rospy.Service("/rcboat/set_multipath", SetMultipath, self._set_multipath)

    def _configure_from_files(self) -> None:
        values = {
            "enabled": bool(rospy.get_param("/rcboat/multipath/enabled", True)),
            "endpoint_tolerance_m": float(rospy.get_param("/rcboat/multipath/endpoint_tolerance_m", 0.75)),
            "off_route_distance_m": float(rospy.get_param("/rcboat/multipath/off_route_distance_m", 8.0)),
            "off_route_hold_s": float(rospy.get_param("/rcboat/multipath/off_route_hold_s", 3.0)),
            "closer_advantage_m": float(rospy.get_param("/rcboat/multipath/closer_advantage_m", 2.0)),
            "switch_cooldown_s": float(rospy.get_param("/rcboat/multipath/switch_cooldown_s", 5.0)),
        }
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                values.update({key: saved[key] for key in values if key in saved})
        except (OSError, ValueError, TypeError):
            pass
        self._validate_multipath(values)
        self.manager.configure_multipath(values)

    @staticmethod
    def _validate_multipath(values: dict) -> None:
        limits = {
            "endpoint_tolerance_m": (0.10, 1.00),
            "off_route_distance_m": (1.0, 100.0),
            "off_route_hold_s": (0.0, 30.0),
            "closer_advantage_m": (0.0, 50.0),
            "switch_cooldown_s": (0.0, 60.0),
        }
        for key, (low, high) in limits.items():
            value = float(values[key])
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            values[key] = value
        values["enabled"] = bool(values["enabled"])

    def _save_settings(self, values: dict) -> None:
        temporary = self.settings_path.with_name(f".{self.settings_path.name}.tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.settings_path)

    def _on_gps(self, msg: GpsStatus) -> None:
        with self._lock:
            self._gps = msg

    def _on_boat(self, msg: BoatState) -> None:
        with self._lock:
            if self._mode == "NAVIGATION" and msg.mode != "NAVIGATION":
                self._navigation_prepared = False
                self._last_status = {}
            self._mode = msg.mode

    @staticmethod
    def _usable(gps: GpsStatus | None) -> bool:
        return bool(
            gps and gps.connected and gps.fix and gps.age_s <= 2.0
            and math.isfinite(gps.latitude) and math.isfinite(gps.longitude)
        )

    def _update(self) -> None:
        with self._lock:
            gps = self._gps
            if self.manager.recording and self._usable(gps):
                self.manager.record_position(
                    (gps.latitude, gps.longitude), time.monotonic(),
                    heading_deg=gps.course_deg if math.isfinite(gps.course_deg) else None,
                )
            if self._mode == "NAVIGATION" and self._usable(gps) and self.manager.active:
                position = (gps.latitude, gps.longitude)
                if not self._navigation_prepared:
                    self.manager.choose_nearest_group_route(position)
                    self._navigation_prepared = True
                self._last_status = self.manager.update_position(position)
            self.publisher.publish(self._state_message())

    def _state_message(self) -> RouteState:
        msg = RouteState()
        msg.header.stamp = rospy.Time.now()
        active = self.manager.active
        selected = self.manager.selected
        status = self._last_status
        msg.available = bool(active and active.points)
        msg.selected_route_id = selected.route_id if selected else ""
        msg.selected_route_name = selected.name if selected else "-"
        msg.active_route_id = active.route_id if active else ""
        msg.active_route_name = active.name if active else "-"
        target = None
        if status.get("target_lat") is not None and status.get("target_lon") is not None:
            target = (float(status["target_lat"]), float(status["target_lon"]))
        elif active and active.points:
            index = min(self.manager.waypoint_index, len(active.points) - 1)
            target = active.points[index]
        msg.target_latitude = target[0] if target else float("nan")
        msg.target_longitude = target[1] if target else float("nan")
        msg.distance_to_waypoint_m = float(status.get("distance_to_waypoint_m", float("nan")))
        msg.distance_to_route_m = float(status.get("distance_to_route_m", float("nan")))
        msg.waypoint_index = int(status.get("waypoint_index", self.manager.waypoint_index))
        msg.waypoint_count = len(active.points) if active else 0
        msg.route_complete = bool(status.get("route_complete", self.manager.route_complete))
        msg.switched_route = bool(status.get("switched_route", False))
        msg.multipath_enabled = self.manager.multipath_enabled
        msg.routes_json = json.dumps(self.manager.public_routes(), ensure_ascii=False)
        msg.recording_json = json.dumps(self.manager.recording_state(), ensure_ascii=False)
        multipath = self.manager.multipath_group_summary()
        multipath.update({
            "off_route_distance_m": self.manager.off_route_distance_m,
            "off_route_hold_s": self.manager.off_route_hold_s,
            "closer_advantage_m": self.manager.closer_advantage_m,
            "switch_cooldown_s": self.manager.switch_cooldown_s,
        })
        msg.multipath_json = json.dumps(multipath, ensure_ascii=False)
        msg.error = self.manager.load_error
        return msg

    def _select(self, req: SelectRoute.Request) -> SelectRouteResponse:
        try:
            with self._lock:
                self.manager.select(req.route_id)
                self._last_status = {}
                self._navigation_prepared = False
            return SelectRouteResponse(True, "route selected")
        except Exception as exc:
            return SelectRouteResponse(False, str(exc))

    def _delete(self, req: DeleteRoute.Request) -> DeleteRouteResponse:
        try:
            with self._lock:
                if self._mode == "NAVIGATION":
                    raise RuntimeError("stop navigation before deleting a route")
                name = self.manager.delete_recorded_route(req.route_id)
                self._last_status = {}
                self._navigation_prepared = False
            return DeleteRouteResponse(True, "route deleted", name)
        except Exception as exc:
            return DeleteRouteResponse(False, str(exc), "")

    def _start_recording(self, req: StartRouteRecording.Request) -> StartRouteRecordingResponse:
        try:
            with self._lock:
                if not self._usable(self._gps):
                    raise RuntimeError("fresh GPS fix is required")
                self.manager.start_recording(
                    req.name,
                    minimum_distance_m=req.minimum_distance_m,
                    minimum_interval_s=req.minimum_interval_s,
                    arrival_radius_m=req.arrival_radius_m,
                )
                self.manager.record_position(
                    (self._gps.latitude, self._gps.longitude),
                    heading_deg=self._gps.course_deg if math.isfinite(self._gps.course_deg) else None,
                )
            return StartRouteRecordingResponse(True, "recording started")
        except Exception as exc:
            return StartRouteRecordingResponse(False, str(exc))

    def _stop_recording(self, req: StopRouteRecording.Request) -> StopRouteRecordingResponse:
        try:
            with self._lock:
                route_id = self.manager.stop_recording(save=req.save) or ""
            return StopRouteRecordingResponse(True, "recording saved" if req.save else "recording cancelled", route_id)
        except Exception as exc:
            return StopRouteRecordingResponse(False, str(exc), "")

    def _reload(self, _req: Trigger.Request) -> TriggerResponse:
        with self._lock:
            ok = self.manager.load()
            self._last_status = {}
            self._navigation_prepared = False
        return TriggerResponse(ok, "routes reloaded" if ok else self.manager.load_error)

    def _set_multipath(self, req: SetMultipath.Request) -> SetMultipathResponse:
        values = {
            "enabled": req.enabled,
            "endpoint_tolerance_m": req.endpoint_tolerance_m,
            "off_route_distance_m": req.off_route_distance_m,
            "off_route_hold_s": req.off_route_hold_s,
            "closer_advantage_m": req.closer_advantage_m,
            "switch_cooldown_s": req.switch_cooldown_s,
        }
        try:
            self._validate_multipath(values)
            with self._lock:
                self.manager.configure_multipath(values)
                self._save_settings(values)
                self._navigation_prepared = False
            return SetMultipathResponse(True, "multipath settings saved")
        except Exception as exc:
            return SetMultipathResponse(False, str(exc))

    def spin(self) -> None:
        rate = rospy.Rate(10)
        while not rospy.is_shutdown():
            try:
                self._update()
            except Exception as exc:
                rospy.logerr_throttle(2.0, "route update failed: %s", exc)
            rate.sleep()


if __name__ == "__main__":
    rospy.init_node("route_manager_node")
    RouteManagerNode().spin()
