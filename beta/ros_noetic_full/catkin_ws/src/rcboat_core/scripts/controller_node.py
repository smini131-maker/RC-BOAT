#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path

import rospy
import yaml
from rcboat_core.constants import (
    AUTO_CRUISE_MAX_PWM,
    AUTO_CRUISE_MIN_PWM,
    VALUES,
)
from rcboat_core.controller_logic import ControllerLogic, GpsSample, RcSample
from rcboat_core.navigation import RouteManager, position_along_route
from rcboat_msgs.msg import BoatState, GpsStatus, PwmCommand, RcInput
from rcboat_msgs.srv import (
    SelectRoute,
    SelectRouteResponse,
    SetAutoCruise,
    SetAutoCruiseResponse,
    SetMode,
    SetModeResponse,
    SetMultipath,
    SetMultipathResponse,
    SetGpsSettings,
    SetGpsSettingsResponse,
    StartHil,
    StartHilResponse,
    StartRouteRecording,
    StartRouteRecordingResponse,
)
from std_msgs.msg import Bool, Empty
from std_srvs.srv import Trigger, TriggerResponse


class ControllerNode:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.config_path = Path(rospy.get_param("~config_file"))
        self.routes_path = Path(rospy.get_param("~routes_file"))
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        multipath = dict(self.config.get("multipath", {}))
        self.settings = {
            "auto_cruise_pwm": int(self.config.get("auto_cruise_pwm", 6650)),
            "gps_stale_s": float(self.config.get("gps", {}).get("stale_s", 2.0)),
            "navigation_max_hdop": float(
                self.config.get("gps", {}).get("navigation_max_hdop", 3.0)
            ),
            "rtk_required_for_navigation": bool(
                self.config.get("gps", {}).get("rtk_required_for_navigation", False)
            ),
            "rtk_fallback_to_gps": bool(
                self.config.get("gps", {}).get("rtk_fallback_to_gps", True)
            ),
            "rtk_correction_max_age_s": float(
                self.config.get("gps", {}).get("rtk_correction_max_age_s", 10.0)
            ),
        }
        self.routes = RouteManager(self.routes_path, multipath)
        self.logic = ControllerLogic(self.routes, self.settings)
        self.pca_connected = False
        self.is_mock = bool(rospy.get_param("~mock", False))
        self.allow_hil = bool(self.config.get("allow_hil", False))
        self.hil_enabled = False
        self.hil_started_at = 0.0
        self.hil_position = (math.nan, math.nan)
        self.hil_course_deg = math.nan

        self.pwm_pub = rospy.Publisher("/rcboat/pwm_command", PwmCommand, queue_size=1)
        self.state_pub = rospy.Publisher("/rcboat/state", BoatState, queue_size=10)
        rospy.Subscriber("/rcboat/rc_input", RcInput, self.rc_callback, queue_size=10)
        rospy.Subscriber("/rcboat/gps_status", GpsStatus, self.gps_callback, queue_size=10)
        rospy.Subscriber("/rcboat/remote_pwm", PwmCommand, self.remote_pwm_callback, queue_size=1)
        rospy.Subscriber("/rcboat/remote_heartbeat", Empty, self.heartbeat_callback, queue_size=10)
        rospy.Subscriber("/rcboat/pca_connected", Bool, self.pca_callback, queue_size=1)

        rospy.Service("/rcboat/set_mode", SetMode, self.set_mode)
        rospy.Service("/rcboat/emergency_stop", Trigger, self.emergency_stop)
        rospy.Service("/rcboat/clear_estop", Trigger, self.clear_estop)
        rospy.Service("/rcboat/select_route", SelectRoute, self.select_route)
        rospy.Service("/rcboat/set_auto_cruise", SetAutoCruise, self.set_auto_cruise)
        rospy.Service("/rcboat/set_multipath", SetMultipath, self.set_multipath)
        rospy.Service("/rcboat/set_gps_settings", SetGpsSettings, self.set_gps_settings)
        rospy.Service(
            "/rcboat/start_route_recording",
            StartRouteRecording,
            self.start_route_recording,
        )
        rospy.Service("/rcboat/stop_route_recording", Trigger, self.stop_route_recording)
        rospy.Service("/rcboat/cancel_route_recording", Trigger, self.cancel_route_recording)
        rospy.Service("/rcboat/reload_routes", Trigger, self.reload_routes)
        rospy.Service("/rcboat/start_hil", StartHil, self.start_hil)
        rospy.Service("/rcboat/stop_hil", Trigger, self.stop_hil)
        rospy.Timer(rospy.Duration(0.02), self.step)
        rospy.on_shutdown(self.shutdown)

    def rc_callback(self, message: RcInput) -> None:
        with self.lock:
            self.logic.update_rc(
                RcSample(
                    connected=message.connected,
                    steering_us=message.steering_us,
                    throttle_us=message.throttle_us,
                    updated_at=time.monotonic(),
                )
            )

    def gps_callback(self, message: GpsStatus) -> None:
        with self.lock:
            self.logic.update_gps(
                GpsSample(
                    connected=message.connected,
                    fix=message.fix,
                    latitude=message.latitude,
                    longitude=message.longitude,
                    course_deg=message.course_deg,
                    hdop=message.hdop,
                    health=message.health,
                    rtk_state=message.rtk_state,
                    correction_age_s=message.correction_age_s,
                    updated_at=time.monotonic(),
                )
            )

    def remote_pwm_callback(self, message: PwmCommand) -> None:
        with self.lock:
            self.logic.set_remote_pwm(message.steering_pwm, message.throttle_pwm)

    def heartbeat_callback(self, _message: Empty) -> None:
        with self.lock:
            self.logic.heartbeat(time.monotonic())

    def pca_callback(self, message: Bool) -> None:
        self.pca_connected = message.data

    def set_mode(self, request) -> SetModeResponse:
        with self.lock:
            try:
                if request.mode.upper().replace("-SAFE", "") != "NAVIGATION":
                    self.hil_enabled = False
                self.logic.set_mode(request.mode, time.monotonic())
                return SetModeResponse(True, self.logic.mode)
            except (ValueError, RuntimeError) as exc:
                return SetModeResponse(False, str(exc))

    def emergency_stop(self, _request) -> TriggerResponse:
        with self.lock:
            self.hil_enabled = False
            self.logic.emergency_stop()
            self._publish_pwm("ESTOP")
            return TriggerResponse(True, "Emergency Stop latched")

    def clear_estop(self, _request) -> TriggerResponse:
        with self.lock:
            self.hil_enabled = False
            self.logic.clear_estop()
            return TriggerResponse(True, "Emergency Stop cleared; safe output remains")

    def select_route(self, request) -> SelectRouteResponse:
        with self.lock:
            try:
                self.hil_enabled = False
                self.routes.select(request.route_id)
                self.logic.steering_pwm = VALUES.steering_center_pwm
                self.logic.throttle_pwm = VALUES.throttle_stop_pwm
                return SelectRouteResponse(True, request.route_id)
            except (OSError, ValueError, RuntimeError) as exc:
                return SelectRouteResponse(False, str(exc))

    def set_auto_cruise(self, request) -> SetAutoCruiseResponse:
        with self.lock:
            if not AUTO_CRUISE_MIN_PWM <= request.pwm <= AUTO_CRUISE_MAX_PWM:
                return SetAutoCruiseResponse(False, "PWM must be 6480..6900")
            self.settings["auto_cruise_pwm"] = int(request.pwm)
            self.config["auto_cruise_pwm"] = int(request.pwm)
            self._save_config()
            return SetAutoCruiseResponse(True, str(request.pwm))

    def set_multipath(self, request) -> SetMultipathResponse:
        values = {
            "enabled": request.enabled,
            "endpoint_tolerance_m": request.endpoint_tolerance_m,
            "off_route_distance_m": request.off_route_distance_m,
            "off_route_hold_s": request.off_route_hold_s,
            "closer_advantage_m": request.closer_advantage_m,
            "switch_cooldown_s": request.switch_cooldown_s,
        }
        with self.lock:
            try:
                self.routes.configure_multipath(values)
                self.config["multipath"] = dict(self.routes.multipath)
                self._save_config()
                return SetMultipathResponse(True, "saved")
            except (OSError, ValueError) as exc:
                return SetMultipathResponse(False, str(exc))

    def set_gps_settings(self, request) -> SetGpsSettingsResponse:
        with self.lock:
            try:
                hdop = float(request.navigation_max_hdop)
                correction_age = float(request.rtk_correction_max_age_s)
                if not 0.5 <= hdop <= 20.0:
                    raise ValueError("navigation_max_hdop must be 0.5..20.0")
                if not 1.0 <= correction_age <= 120.0:
                    raise ValueError("rtk_correction_max_age_s must be 1..120")
                gps = self.config.setdefault("gps", {})
                gps["navigation_max_hdop"] = hdop
                gps["rtk_required_for_navigation"] = bool(
                    request.rtk_required_for_navigation
                )
                gps["rtk_fallback_to_gps"] = bool(request.rtk_fallback_to_gps)
                gps["rtk_correction_max_age_s"] = correction_age
                self.settings.update(
                    navigation_max_hdop=hdop,
                    rtk_required_for_navigation=bool(
                        request.rtk_required_for_navigation
                    ),
                    rtk_fallback_to_gps=bool(request.rtk_fallback_to_gps),
                    rtk_correction_max_age_s=correction_age,
                )
                self._save_config()
                return SetGpsSettingsResponse(True, "saved")
            except (OSError, ValueError) as exc:
                return SetGpsSettingsResponse(False, str(exc))

    def start_route_recording(self, request) -> StartRouteRecordingResponse:
        with self.lock:
            gps = self.logic.gps
            if not gps.connected or not gps.fix or gps.health in {"BAD", "NO_FIX", "STALE"}:
                return StartRouteRecordingResponse(False, "valid GPS FIX required")
            try:
                self.routes.start_recording(
                    request.name,
                    request.minimum_distance_m,
                    request.minimum_interval_s,
                    request.arrival_radius_m,
                )
                self.routes.record_position((gps.latitude, gps.longitude), time.monotonic())
                return StartRouteRecordingResponse(True, "recording started")
            except (ValueError, RuntimeError) as exc:
                return StartRouteRecordingResponse(False, str(exc))

    def stop_route_recording(self, _request) -> TriggerResponse:
        with self.lock:
            try:
                route_id = self.routes.stop_recording(True)
                return TriggerResponse(True, str(route_id))
            except (OSError, ValueError, RuntimeError) as exc:
                return TriggerResponse(False, str(exc))

    def cancel_route_recording(self, _request) -> TriggerResponse:
        with self.lock:
            try:
                self.routes.stop_recording(False)
                return TriggerResponse(True, "cancelled")
            except RuntimeError as exc:
                return TriggerResponse(False, str(exc))

    def reload_routes(self, _request) -> TriggerResponse:
        with self.lock:
            self.hil_enabled = False
            if self.routes.load():
                self.logic.steering_pwm = VALUES.steering_center_pwm
                self.logic.throttle_pwm = VALUES.throttle_stop_pwm
                return TriggerResponse(True, "routes reloaded")
            return TriggerResponse(False, self.routes.load_error)

    def start_hil(self, request) -> StartHilResponse:
        with self.lock:
            try:
                if not self.allow_hil:
                    raise RuntimeError("HIL is disabled; set allow_hil: true explicitly")
                if self.logic.estop:
                    raise RuntimeError("Emergency Stop is latched")
                if request.route_id:
                    self.routes.select(request.route_id)
                route = self.routes.active
                if route is None or len(route.points) < 2:
                    raise RuntimeError("HIL requires a route with at least two points")
                self.hil_enabled = True
                self.hil_started_at = time.monotonic()
                self.hil_position = route.points[0]
                self.hil_course_deg = position_along_route(route.points, 0.0)[1]
                self.logic.set_mode("NAVIGATION", self.hil_started_at)
                return StartHilResponse(True, route.route_id)
            except (OSError, ValueError, RuntimeError) as exc:
                self.hil_enabled = False
                return StartHilResponse(False, str(exc))

    def stop_hil(self, _request) -> TriggerResponse:
        with self.lock:
            if not self.hil_enabled:
                return TriggerResponse(False, "HIL is not active")
            self.hil_enabled = False
            self.logic.safe("HIL_STOPPED")
            return TriggerResponse(True, "HIL stopped; safe output applied")

    def _update_hil_gps(self, now: float) -> None:
        route = self.routes.active
        if not self.hil_enabled or route is None:
            return
        self.hil_position, self.hil_course_deg = position_along_route(
            route.points, now - self.hil_started_at
        )
        self.logic.update_gps(
            GpsSample(
                connected=True,
                fix=True,
                latitude=self.hil_position[0],
                longitude=self.hil_position[1],
                course_deg=self.hil_course_deg,
                hdop=0.8,
                health="GOOD",
                rtk_state="RTK_FIXED",
                correction_age_s=0.0,
                updated_at=now,
            )
        )

    def _save_config(self) -> None:
        temporary = self.config_path.with_name(f".{self.config_path.name}.tmp")
        temporary.write_text(
            yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, self.config_path)

    def step(self, _event) -> None:
        with self.lock:
            now = time.monotonic()
            self._update_hil_gps(now)
            self.logic.step(now)
            self._publish_pwm("controller")
            self._publish_state()

    def _publish_pwm(self, source: str) -> None:
        message = PwmCommand()
        message.header.stamp = rospy.Time.now()
        message.steering_pwm = self.logic.steering_pwm
        message.throttle_pwm = self.logic.throttle_pwm
        message.source = source
        message.reason = self.logic.failsafe_reason
        self.pwm_pub.publish(message)

    def _publish_state(self) -> None:
        logic = self.logic
        route = logic.last_route_status
        message = BoatState()
        message.header.stamp = rospy.Time.now()
        message.mode = logic.mode
        message.operation_state = logic.operation_state
        message.navigation_active = logic.operation_state == "NAVIGATION_ACTIVE"
        message.estop = logic.estop
        message.failsafe_reason = logic.failsafe_reason
        message.manual_waiting_for_neutral = logic.manual_waiting_for_neutral
        message.auto_cruise_pwm = int(self.settings["auto_cruise_pwm"])
        message.arduino_connected = logic.rc.connected
        message.gps_connected = logic.gps.connected
        message.pca_connected = self.pca_connected
        message.rc_steering_us = logic.rc.steering_us
        message.rc_throttle_us = logic.rc.throttle_us
        message.steering_pwm = logic.steering_pwm
        message.throttle_pwm = logic.throttle_pwm
        message.gps_health = logic.gps.health
        message.rtk_state = logic.gps.rtk_state
        message.rtk_fallback_active = logic.gps.fix and logic.gps.rtk_state != "RTK_FIXED"
        message.selected_route_id = self.routes.selected.route_id if self.routes.selected else ""
        message.active_route_id = self.routes.active.route_id if self.routes.active else ""
        message.waypoint_index = int(route.get("waypoint_index", self.routes.waypoint_index))
        message.waypoint_count = int(route.get("waypoint_count", 0))
        message.distance_to_waypoint_m = float(route.get("distance_to_waypoint_m", math.nan))
        message.distance_to_route_m = float(route.get("distance_to_route_m", math.nan))
        message.route_complete = self.routes.route_complete
        message.route_recording = self.routes.recording
        message.recorded_point_count = len(self.routes.recording_points)
        message.recording_name = self.routes.recording_name
        message.mock = self.is_mock
        message.hil_active = self.hil_enabled
        message.hil_latitude = self.hil_position[0] if self.hil_enabled else math.nan
        message.hil_longitude = self.hil_position[1] if self.hil_enabled else math.nan
        message.hil_course_deg = self.hil_course_deg if self.hil_enabled else math.nan
        self.state_pub.publish(message)

    def shutdown(self) -> None:
        with self.lock:
            self.hil_enabled = False
            self.logic.safe("CONTROLLER_SHUTDOWN")
            for _ in range(3):
                self._publish_pwm("shutdown")
                rospy.sleep(0.02)


if __name__ == "__main__":
    rospy.init_node("rcboat_controller")
    ControllerNode()
    rospy.spin()