#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import socket
import socketserver
import threading
import time
import uuid

import rosnode
import rosservice
import rospy
from std_msgs.msg import Empty, String
from std_srvs.srv import Trigger

from rcboat_ros.msg import ActuatorStatus, BoatState, ControlCommand, GpsStatus, NavigationStatus, NtripStatus, RcInput, RouteState
from rcboat_ros.srv import ConfigureNtrip, DeleteRoute, InjectHilFault, SelectRoute, SetGpsSettings, SetMode, SetMultipath, SetPwm, StartRouteRecording, StopRouteRecording


def clean_float(value):
    return None if isinstance(value, float) and not math.isfinite(value) else value


class BridgeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.profile = rospy.get_param("/rcboat/profile", "real")
        self.rc = None
        self.gps = None
        self.ntrip = None
        self.route = None
        self.boat = None
        self.actuator = None
        self.navigation = None
        self.logging = {"active": False, "file_path": ""}
        self.ros = {"master": False, "nodes": [], "missing_nodes": [], "service_count": 0}
        self.events = []

    def event(self, level: str, message: str) -> None:
        with self.lock:
            self.events = (self.events + [{"timestamp": time.time(), "level": level, "message": message}])[-100:]

    def telemetry(self) -> dict:
        with self.lock:
            rc, gps, ntrip, route, boat, actuator, nav = self.rc, self.gps, self.ntrip, self.route, self.boat, self.actuator, self.navigation
            try: routes = json.loads(route.routes_json) if route else []
            except Exception: routes = []
            try: recording = json.loads(route.recording_json) if route else {"active": False, "point_count": 0}
            except Exception: recording = {"active": False, "point_count": 0}
            try: multipath = json.loads(route.multipath_json) if route else {}
            except Exception: multipath = {}
            route_state = {
                "active_route_id": route.active_route_id if route else "",
                "active_route_name": route.active_route_name if route else "-",
                "selected_route_id": route.selected_route_id if route else "",
                "selected_route_name": route.selected_route_name if route else "-",
                "waypoint_index": route.waypoint_index if route else 0,
                "waypoint_count": route.waypoint_count if route else 0,
                "distance_to_waypoint_m": clean_float(route.distance_to_waypoint_m) if route else None,
                "distance_to_route_m": clean_float(route.distance_to_route_m) if route else None,
                "target_lat": clean_float(route.target_latitude) if route else None,
                "target_lon": clean_float(route.target_longitude) if route else None,
                "route_complete": route.route_complete if route else False,
                "switched_route": route.switched_route if route else False,
                "multipath": multipath,
                "load_error": route.error if route else "",
                "storage_path": str(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime")) + "/routes.json",
                "multipath_config_path": str(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime")) + "/multipath_settings.json",
                "selected_route_persisted": bool(route and route.selected_route_id),
            }
            health = {
                "status": gps.health_status if gps else "BAD",
                "navigation_status": gps.navigation_status if gps else "BAD",
                "reasons": [gps.health_reason] if gps and gps.health_reason else [],
                "age_s": clean_float(gps.age_s) if gps else None,
                "position_age_s": clean_float(gps.position_age_s) if gps else None,
            }
            gps_dict = {
                "fix": gps.fix if gps else False, "quality": gps.fix_quality if gps else 0,
                "fix_label": gps.fix_label if gps else "NO FIX",
                "lat": clean_float(gps.latitude) if gps else None, "lon": clean_float(gps.longitude) if gps else None,
                "satellites": gps.satellites if gps else 0, "altitude_m": clean_float(gps.altitude_m) if gps else None,
                "hdop": clean_float(gps.hdop) if gps else None, "pdop": clean_float(gps.pdop) if gps else None,
                "vdop": clean_float(gps.vdop) if gps else None, "cno_avg_dbhz": clean_float(gps.cno_avg_dbhz) if gps else None,
                "hacc_m": clean_float(gps.hacc_m) if gps else None, "speed_mps": clean_float(gps.speed_mps) if gps else None,
                "course_deg": clean_float(gps.course_deg) if gps else None, "utc_time": gps.utc_time if gps else "",
                "age_s": clean_float(gps.age_s) if gps else None, "last_fix_age_s": clean_float(gps.position_age_s) if gps else None,
                "health": health, "rtk_state": gps.rtk_state if gps else "NO_RTK",
                "rtk_fallback_active": gps.rtk_fallback_active if gps else False,
                "navigation_fix_mode": gps.navigation_fix_mode if gps else "NO_FIX",
                "parser_error_count": gps.parser_error_count if gps else 0,
                "nmea_sentence_count": gps.nmea_sentence_count if gps else 0,
                "ubx_message_count": gps.ubx_message_count if gps else 0,
                "nav_pvt_message_count": gps.nav_pvt_message_count if gps else 0,
                "hacc_source": "UBX-NAV-PVT" if gps and math.isfinite(gps.hacc_m) else "UBX-NAV-PVT 대기",
                "utm_easting": clean_float(gps.utm_easting) if gps else None,
                "utm_northing": clean_float(gps.utm_northing) if gps else None,
                "utm_zone": gps.utm_zone if gps else "",
            }
            ntrip_dict = {
                "enabled": ntrip.enabled if ntrip else False, "connected": ntrip.connected if ntrip else False,
                "host": ntrip.host if ntrip else "", "port": ntrip.port if ntrip else 2101,
                "mountpoint": ntrip.mountpoint if ntrip else "", "tls": ntrip.tls if ntrip else False,
                "last_correction_age_s": clean_float(ntrip.last_correction_age_s) if ntrip else None,
                "bytes_received": ntrip.bytes_received if ntrip else 0,
                "reconnect_count": ntrip.reconnect_count if ntrip else 0,
                "last_error": ntrip.last_error if ntrip else "",
            }
            state = {
                "type": "telemetry", "software_version": "0.1.0-beta.1",
                "timestamp": time.time(), "uptime_s": round(time.monotonic() - self.started, 1),
                "backend": "ROS1_NOETIC", "profile": self.profile,
                "ros": dict(self.ros),
                "mode": boat.mode if boat else "AUTO", "operation_state": boat.operation_state if boat else "AUTO_SAFE",
                "navigation_active": bool(boat and boat.operation_state in {"NAVIGATION_ACTIVE", "HIL_ACTIVE"}),
                "estop": boat.estop if boat else False, "failsafe_reason": boat.failsafe_reason if boat else "ROS_WAITING",
                "manual_waiting_for_neutral": boat.manual_waiting_for_neutral if boat else False,
                "auto_to_manual_gesture_armed": boat.auto_to_manual_gesture_armed if boat else False,
                "auto_cruise_pwm": boat.auto_cruise_pwm if boat else 6650,
                "manual_throttle_mapping": {"reverse_input_us": 1106, "neutral_input_us": 1500, "forward_input_us": 1786, "reverse_pwm": 5800, "stop_pwm": 6450, "forward_pwm": 7000},
                "gps_recording": recording, "gps_logging": dict(self.logging), "ntrip": ntrip_dict,
                "gps_settings": {
                    "health_stale_s": rospy.get_param("/rcboat/gps/health_stale_s", 2.0),
                    "navigation_max_hdop": rospy.get_param("/rcboat/gps/navigation_max_hdop", 3.0),
                    "rtk_required_for_navigation": rospy.get_param("/rcboat/gps/rtk_required_for_navigation", False),
                    "rtk_fallback_to_gps": rospy.get_param("/rcboat/gps/rtk_fallback_to_gps", True),
                    "rtk_correction_max_age_s": rospy.get_param("/rcboat/gps/rtk_correction_max_age_s", 10.0),
                },
                "hil": {"active": bool(boat and boat.hil), "lat": gps_dict["lat"], "lon": gps_dict["lon"], "course_deg": gps_dict["course_deg"]},
                "mock": self.profile == "hil",
                "rc": {"steering_us": rc.steering_us if rc else None, "throttle_us": rc.throttle_us if rc else None, "age_s": clean_float(rc.age_s) if rc else None},
                "pca": {"frequency_hz": 60, "steering_channel": 0, "throttle_channel": 6, "steering_pwm": actuator.steering_pwm if actuator else 6000, "throttle_pwm": actuator.throttle_pwm if actuator else 6450},
                "gps": gps_dict,
                "devices": {"arduino": rc.connected if rc else False, "gps": gps.connected if gps else False, "pca9685": actuator.connected if actuator else False},
                "route": route_state, "routes": routes,
                "hardware_errors": [value for value in [rc.error if rc else "", actuator.error if actuator else "", gps.health_reason if gps and not gps.connected else ""] if value],
                "events": list(self.events[-20:]),
                "measured_values": {"steering_low_pwm": 4900, "steering_center_pwm": 6000, "steering_high_pwm": 7300, "throttle_reverse_pwm": 5800, "throttle_stop_pwm": 6450, "throttle_forward_pwm": 7000},
            }
            if nav:
                state["route"].update({"target_bearing_deg": clean_float(nav.target_bearing_deg), "heading_error_deg": clean_float(nav.heading_error_deg), "navigation_speed_fraction": nav.speed_fraction, "severe_turn_recovery": nav.severe_turn_recovery})
            return state


class Bridge:
    def __init__(self) -> None:
        self.state = BridgeState()
        self.drop_heartbeat_until = 0.0
        self.remote_pub = rospy.Publisher("/rcboat/remote/command", ControlCommand, queue_size=10)
        self.heartbeat_pub = rospy.Publisher("/rcboat/remote/heartbeat", Empty, queue_size=10)
        self._subscribe()
        rospy.Timer(rospy.Duration(1.0), self._update_ros_health)

    def _update_ros_health(self, _event) -> None:
        expected = {
            "/gui_bridge_node", "/route_manager_node", "/navigation_node",
            "/safety_supervisor_node", "/gps_logger_node",
        }
        if self.state.profile == "hil":
            expected.add("/mock_hardware_node")
        else:
            expected.update({"/rc_input_node", "/gps_node", "/ntrip_node", "/actuator_node"})
        try:
            nodes = sorted(rosnode.get_node_names())
            services = rosservice.get_service_list()
            status = {
                "master": True,
                "nodes": nodes,
                "missing_nodes": sorted(expected.difference(nodes)),
                "expected_node_count": len(expected),
                "service_count": len(services),
            }
        except Exception as exc:
            status = {
                "master": False, "nodes": [], "missing_nodes": sorted(expected),
                "expected_node_count": len(expected), "service_count": 0, "error": str(exc),
            }
        with self.state.lock:
            self.state.ros = status

    def _subscribe(self) -> None:
        def bind(topic, msg_type, attr):
            rospy.Subscriber(topic, msg_type, lambda msg: self._set(attr, msg), queue_size=10)
        bind("/rcboat/rc/input", RcInput, "rc")
        bind("/rcboat/gps/status", GpsStatus, "gps")
        bind("/rcboat/ntrip/status", NtripStatus, "ntrip")
        bind("/rcboat/route/state", RouteState, "route")
        bind("/rcboat/safety/state", BoatState, "boat")
        bind("/rcboat/actuator/status", ActuatorStatus, "actuator")
        bind("/rcboat/navigation/status", NavigationStatus, "navigation")
        rospy.Subscriber("/rcboat/gps/logging_state", String, self._logging_cb, queue_size=2)

    def _set(self, attr, value):
        with self.state.lock: setattr(self.state, attr, value)

    def _logging_cb(self, msg):
        try: value = json.loads(msg.data)
        except Exception: return
        with self.state.lock: self.state.logging = value

    @staticmethod
    def _call(name, service_type, *args):
        rospy.wait_for_service(name, timeout=3.0)
        return rospy.ServiceProxy(name, service_type)(*args)

    def command(self, msg: dict) -> dict:
        request_id = msg.get("request_id")
        command = str(msg.get("command", "")).upper()
        try:
            result = None
            if command == "HEARTBEAT":
                if time.monotonic() >= self.drop_heartbeat_until:
                    self.heartbeat_pub.publish(Empty())
            elif command == "SET_MODE":
                result = self._call("/rcboat/set_mode", SetMode, str(msg["mode"]))
            elif command == "REMOTE_CONTROL":
                out = ControlCommand()
                out.header.stamp = rospy.Time.now()
                out.steering_pwm = int(msg["steering_pwm"])
                out.throttle_pwm = int(msg["throttle_pwm"])
                out.source = "GUI_REMOTE"
                out.valid = True
                self.remote_pub.publish(out)
            elif command == "SET_AUTO_CRUISE_PWM":
                result = self._call("/rcboat/set_auto_cruise", SetPwm, int(msg["value"]))
            elif command == "SET_MULTIPATH":
                current = json.loads(self.state.route.multipath_json) if self.state.route else {}
                vals = {key: msg.get(key, current.get(key)) for key in ("enabled", "endpoint_tolerance_m", "off_route_distance_m", "off_route_hold_s", "closer_advantage_m", "switch_cooldown_s")}
                result = self._call("/rcboat/set_multipath", SetMultipath, vals["enabled"], vals["endpoint_tolerance_m"], vals["off_route_distance_m"], vals["off_route_hold_s"], vals["closer_advantage_m"], vals["switch_cooldown_s"])
            elif command in {"EMERGENCY_STOP", "CLEAR_ESTOP"}:
                result = self._call("/rcboat/emergency_stop" if command == "EMERGENCY_STOP" else "/rcboat/clear_estop", Trigger)
            elif command == "SELECT_ROUTE":
                result = self._call("/rcboat/routes/select", SelectRoute, str(msg["route_id"]))
            elif command == "DELETE_ROUTE":
                result = self._call("/rcboat/routes/delete", DeleteRoute, str(msg["route_id"]))
            elif command in {"START_GPS_RECORDING", "START_ROUTE_RECORDING"}:
                result = self._call("/rcboat/routes/start_recording", StartRouteRecording, str(msg.get("name", "")), float(msg.get("minimum_distance_m", msg.get("min_spacing_m", 1.0))), float(msg.get("minimum_interval_s", 0.5)), float(msg.get("arrival_radius_m", 3.0)))
            elif command in {"STOP_GPS_RECORDING", "STOP_ROUTE_RECORDING"}:
                result = self._call("/rcboat/routes/stop_recording", StopRouteRecording, True)
            elif command in {"CANCEL_GPS_RECORDING", "CANCEL_ROUTE_RECORDING"}:
                result = self._call("/rcboat/routes/stop_recording", StopRouteRecording, False)
            elif command == "RELOAD_ROUTES":
                result = self._call("/rcboat/routes/reload", Trigger)
            elif command == "START_GPS_LOGGING":
                result = self._call("/rcboat/gps/start_logging", Trigger)
            elif command == "STOP_GPS_LOGGING":
                result = self._call("/rcboat/gps/stop_logging", Trigger)
            elif command == "SET_GPS_SETTINGS":
                current = self.state.telemetry()["gps_settings"]
                vals = {key: msg.get(key, current[key]) for key in current}
                result = self._call("/rcboat/gps/set_settings", SetGpsSettings, vals["health_stale_s"], vals["navigation_max_hdop"], vals["rtk_required_for_navigation"], vals["rtk_fallback_to_gps"], vals["rtk_correction_max_age_s"])
            elif command == "CONFIGURE_NTRIP":
                current = self.state.telemetry()["ntrip"]
                result = self._call("/rcboat/ntrip/configure", ConfigureNtrip, bool(msg.get("enabled", current["enabled"])), str(msg.get("host", current["host"])), int(msg.get("port", current["port"])), str(msg.get("mountpoint", current["mountpoint"])), str(msg.get("username", "")), str(msg.get("password", "")), bool(msg.get("tls", current["tls"])), float(msg.get("timeout_s", 10.0)), float(msg.get("gga_interval_s", 10.0)))
            elif command == "DISABLE_NTRIP":
                result = self._call("/rcboat/ntrip/disable", Trigger)
            elif command == "START_HIL":
                if self.state.profile != "hil":
                    raise RuntimeError("HIL requires rcboat_ros_hil.service; real actuator profile rejects HIL")
                if msg.get("route_id"):
                    selected = self._call("/rcboat/routes/select", SelectRoute, str(msg["route_id"]))
                    if not selected.ok: raise RuntimeError(selected.message)
                result = self._call("/rcboat/set_mode", SetMode, "NAVIGATION")
            elif command == "STOP_HIL":
                result = self._call("/rcboat/safety/force_safe", Trigger)
            elif command.startswith("SIM_"):
                if self.state.profile != "hil":
                    raise RuntimeError("simulation commands require rcboat_ros_hil.service")
                if command == "SIM_SET_ARDUINO":
                    result = self._call("/rcboat/hil/inject_fault", InjectHilFault, "rc_disconnect", not bool(msg.get("connected", True)))
                elif command == "SIM_SET_GPS_CONNECTED":
                    result = self._call("/rcboat/hil/inject_fault", InjectHilFault, "gps_disconnect", not bool(msg.get("connected", True)))
                elif command == "SIM_SET_GPS_FIX":
                    result = self._call("/rcboat/hil/inject_fault", InjectHilFault, "gps_no_fix", not bool(msg.get("fix", True)))
                elif command == "SIM_REMOTE_HEARTBEAT_LOSS":
                    self.drop_heartbeat_until = time.monotonic() + 1.0
                elif command == "SIM_MULTIPATH_SWITCH":
                    result = self._call("/rcboat/hil/inject_fault", InjectHilFault, "multipath_switch", True)
                else:
                    mapping = {
                        "SIM_GPS_DISCONNECT": "gps_disconnect",
                        "SIM_GPS_NO_FIX": "gps_no_fix",
                        "SIM_ARDUINO_DISCONNECT": "rc_disconnect",
                        "SIM_PCA_FAILURE": "actuator_fault",
                    }
                    fault = mapping.get(command)
                    if not fault:
                        raise ValueError(f"unknown simulation command: {command}")
                    result = self._call("/rcboat/hil/inject_fault", InjectHilFault, fault, True)
            elif command in {"GET_STATE", "REFRESH_NTRIP"}:
                pass
            else:
                raise ValueError(f"unknown command: {command}")
            if result is not None and hasattr(result, "ok") and not result.ok:
                raise RuntimeError(result.message)
            response = {"type": "ack", "request_id": request_id, "command": command, "ok": True}
            if result is not None:
                for key in ("route_id", "deleted_name", "message"):
                    if hasattr(result, key): response[key] = getattr(result, key)
            return response
        except Exception as exc:
            self.state.event("ERROR", f"{command}: {exc}")
            return {"type": "ack", "request_id": request_id, "command": command, "ok": False, "error": str(exc)}


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(0.1)
        bridge = self.server.bridge
        buffer = bytearray()
        last_telemetry = 0.0
        while not rospy.is_shutdown():
            try:
                chunk = self.connection.recv(65536)
                if not chunk:
                    return
                buffer.extend(chunk)
            except socket.timeout:
                pass
            except (ConnectionError, OSError, ValueError, json.JSONDecodeError):
                return
            if len(buffer) > 1_048_576:
                return
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                if not raw:
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    response = bridge.command(payload)
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                    response = {"type": "ack", "ok": False, "error": str(exc)}
                try:
                    self.connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                except (ConnectionError, OSError):
                    return
            now = time.monotonic()
            if now - last_telemetry >= 0.2:
                try:
                    self.connection.sendall((json.dumps(bridge.state.telemetry(), ensure_ascii=False) + "\n").encode("utf-8"))
                except (ConnectionError, OSError):
                    return
                last_telemetry = now


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    rospy.init_node("gui_bridge_node")
    bridge = Bridge()
    port = int(rospy.get_param("~port", 8876))
    server = Server(("127.0.0.1", port), RequestHandler)
    server.bridge = bridge
    server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    server_thread.start()
    def stop_server():
        server.shutdown()
        server.server_close()
    rospy.on_shutdown(stop_server)
    rospy.loginfo("ROS GUI bridge listening on 127.0.0.1:%d", port)
    rospy.spin()
    server_thread.join(timeout=1.0)
