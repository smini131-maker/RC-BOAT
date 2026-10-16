#!/usr/bin/env python3
"""Authoritative ROS ground-test recorder. It never owns or drives hardware."""
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import time

import rospy
from std_msgs.msg import String
from rcboat_ros.srv import Execute, ExecuteResponse
from rcboat_ros.common import pack, unpack
from rcboat_ros.geo import enrich_waypoints


VERSION = "2.1.3"
CSV_FIELDS = [
    "sample_index", "sample_time_epoch_s", "logger_time_utc", "measurement_time_utc", "gps_received_time_utc",
    "output_time_utc", "elapsed_time_s", "latitude", "longitude", "utm_easting_m",
    "utm_northing_m", "utm_zone", "heading_deg", "heading_source", "speed_mps",
    "course_deg", "gps_fix", "rtk_state", "gps_validity", "gps_healthy", "gps_data_age_s",
    "correction_age_s", "satellites", "hdop", "pdop", "vdop", "hacc_m", "cno_dbhz",
    "course_quality", "gps_quality_used_json", "execution_target_type", "execution_target_id",
    "execution_target_name", "selected_route_id", "active_route_id", "previous_active_route_id",
    "test_route_ids", "target_waypoint_number", "target_waypoint_index", "distance_to_waypoint_m",
    "cross_track_error_m", "target_path_distance_m", "candidate_route_distance_m",
    "multipath_switch_threshold_m", "switch_threshold_exceeded", "switch_decision",
    "multipath_candidate_id", "multipath_switch", "controller_mode",
    "target_heading_deg", "heading_error_deg", "desired_rudder_angle_deg", "final_rudder_angle_deg",
    "target_speed_mps", "desired_steering_pwm", "desired_throttle_pwm", "route_candidates_json",
    "final_steering_pwm", "final_throttle_pwm", "actual_steering_pwm", "actual_throttle_pwm",
    "output_send_success", "output_status", "operation_mode", "effective_source",
    "output_locked", "ground_test_actuation_enabled", "throttle_locked", "steering_test_enabled",
    "manual_intervention", "estop", "navigation_valid", "logger_state",
]

ROUTE_METRIC_FIELDS = [
    "sample_index", "logger_time_utc", "elapsed_time_s", "route_id", "route_name", "is_active",
    "distance_to_route_m", "cross_track_error_m", "nearest_segment_index", "target_waypoint_number",
    "target_waypoint_index", "target_latitude", "target_longitude", "target_heading_deg", "heading_error_deg",
]
ROUTE_SWITCH_FIELDS = [
    "sample_index", "logger_time_utc", "elapsed_time_s", "previous_route_id", "new_route_id",
    "candidate_route_id", "previous_target_path_distance_m", "candidate_route_distance_m",
    "switch_threshold_m", "switch_decision", "selection_metric",
]


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Logger:
    def __init__(self):
        self.cache = {}
        self.folder = None
        self.files = {}
        self.writer = None
        self.count = 0
        self.start_clock = 0.0
        self.state = "idle"
        self.last_error = ""
        self.test_route_ids = []
        self.execution_target_type = ""
        self.execution_target_id = ""
        self.execution_target_name = ""
        self.previous_active_route_id = ""
        self.actuation_enabled = False
        root = rospy.get_param("/rcboat/ground_test_log_root", "~/rcboat_ros_data/logs/ground_tests")
        self.root = pathlib.Path(os.path.expanduser(root))
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover_interrupted_runs()
        for topic, key in [
            ("/rcboat/gps/status", "gps"), ("/rcboat/navigation/desired", "nav"),
            ("/rcboat/route/state", "route"), ("/rcboat/safety/state", "safety"),
            ("/rcboat/actuator/status", "actuator"), ("/rcboat/ntrip/status", "ntrip"),
            ("/rcboat/rc/input", "rc"),
        ]:
            rospy.Subscriber(topic, String, lambda message, name=key: self.cache.__setitem__(name, unpack(message)))
        rospy.Subscriber("/rcboat/events", String, self.on_event)
        self.pub = rospy.Publisher("/rcboat/ground_test/status", String, queue_size=4, latch=True)
        rospy.Service("/rcboat/logger/execute", Execute, self.execute)
        rospy.on_shutdown(self.close)
        self.publish_status()

    @staticmethod
    def _manifest(folder):
        entries = []
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.name != "export_manifest.json":
                entries.append({"name": path.name, "bytes": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        json_dump(folder / "export_manifest.json", {"schema_version": 1, "test_id": folder.name,
                                                     "created_at_utc": utc_now(), "files": entries})

    def recover_interrupted_runs(self):
        """Make a power-loss/restart visible and leave the partial run exportable."""
        for folder in sorted(self.root.glob("ground_test_*")):
            metadata_path = folder / "test_metadata.json"
            if not folder.is_dir() or not metadata_path.exists() or (folder / "export_manifest.json").exists():
                continue
            try:
                detected_at = utc_now()
                with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "LOGGER_RESTART_DETECTED",
                                             "event_time_utc": detected_at,
                                             "reason": "previous run ended without a manifest"},
                                            ensure_ascii=False, separators=(",", ":")) + "\n")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata.update(stopped_at_utc=detected_at, final_state="interrupted",
                                error="ROS logger restarted or lost power before a clean stop")
                json_dump(metadata_path, metadata)
                self._manifest(folder)
            except (OSError, ValueError) as exc:
                rospy.logerr("failed to recover interrupted ground test %s: %s", folder, exc)

    def publish_status(self):
        self.pub.publish(pack(state=self.state, active=self.state == "recording",
                              folder=str(self.folder or ""), samples=self.count, error=self.last_error,
                              test_route_ids=self.test_route_ids,
                              actuation_enabled=self.actuation_enabled))

    def _write_jsonl(self, key, value):
        handle = self.files.get(key)
        if handle:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()

    def on_event(self, message):
        event = unpack(message)
        event.setdefault("event_time_utc", utc_now())
        event["elapsed_time_s"] = round(time.monotonic() - self.start_clock, 3) if self.folder else None
        self._write_jsonl("events", event)
        if event.get("type") in {"ROUTE_CHANGE", "CONFIG_CHANGE"}:
            snapshot = dict(event)
            snapshot["routes_snapshot"] = self.cache.get("route", {}).get("routes", [])
            self._write_jsonl("route_changes", snapshot)

    def execute(self, request):
        try:
            args = json.loads(request.arguments_json or "{}")
            if request.action == "start":
                if self.folder:
                    raise RuntimeError("ground test already recording")
                self.start(args.get("route_ids", []), args.get("target_type", "single_route"),
                           args.get("target_id", ""), bool(args.get("actuation_enabled", False)))
                result = {"folder": str(self.folder), "test_id": self.folder.name}
            elif request.action == "stop":
                if not self.folder:
                    result = {"state": "idle", "samples": self.count, "already_stopped": True}
                else:
                    folder = str(self.folder); count = self.count
                    self.close()
                    result = {"folder": folder, "samples": count, "state": self.state}
            elif request.action == "status":
                result = {"state": self.state, "active": bool(self.folder), "folder": str(self.folder or ""),
                          "samples": self.count, "error": self.last_error}
            else:
                raise ValueError("unknown logger action")
            return ExecuteResponse(True, pack(**result))
        except Exception as exc:
            self.last_error = str(exc); self.state = "error"; self.publish_status()
            return ExecuteResponse(False, pack(error=str(exc), state=self.state))

    def _reference_routes(self, route_ids):
        routes = self.cache.get("route", {}).get("routes", [])
        by_id = {str(route.get("id")): route for route in routes}
        ids = [str(value) for value in route_ids]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("select one or more distinct reference routes")
        missing = [value for value in ids if value not in by_id]
        if missing:
            raise ValueError("reference routes not found: " + ", ".join(missing))
        selected = []
        for route_id in ids:
            route = dict(by_id[route_id])
            route["waypoints"] = enrich_waypoints(route.get("waypoints", []))
            selected.append(route)
        return selected

    def start(self, route_ids, target_type="single_route", target_id="", actuation_enabled=False):
        safety = self.cache.get("safety", {})
        actuator = self.cache.get("actuator", {})
        gps = self.cache.get("gps", {})
        if safety.get("mode") != "GROUND_TEST" or safety.get("actuator_locked") is not True:
            if not (actuation_enabled and safety.get("mode") == "GROUND_TEST" and
                    safety.get("ground_test_actuation_enabled") is True):
                raise RuntimeError("GROUND_TEST output mode did not activate")
        if bool(safety.get("ground_test_actuation_enabled")) != bool(actuation_enabled):
            raise RuntimeError("ground-test actuation acknowledgement mismatch")
        output_fresh = 0 <= time.monotonic() - float(actuator.get("monotonic") or 0) <= 1.0
        steering = actuator.get("actual_steering_pwm"); throttle = actuator.get("actual_throttle_pwm")
        if not (actuator.get("command_applied") is True and output_fresh and
                steering is not None and throttle is not None and
                4900 <= int(steering) <= 7300 and 5800 <= int(throttle) <= 7000):
            raise RuntimeError("actuator command confirmation is missing")
        if not actuation_enabled and (int(steering) != 6000 or int(throttle) != 6450):
            raise RuntimeError("neutral output confirmation is missing")
        if not gps.get("healthy"):
            raise RuntimeError("valid, current GPS FIX is required")
        routes = self._reference_routes(route_ids)
        target_type = str(target_type)
        target_id = str(target_id)
        route_state = self.cache.get("route", {})
        if target_type not in {"multipath", "single_route"}:
            raise ValueError("target_type must be multipath or single_route")
        if target_type == "multipath":
            groups = {str(item.get("id")): item for item in route_state.get("multipaths", [])}
            if target_id not in groups:
                raise ValueError("selected multipath was not found")
            target_name = str(groups[target_id].get("name") or target_id)
        else:
            target_id = target_id or str(routes[0].get("id"))
            target_name = str(routes[0].get("name") or target_id)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self.root / ("ground_test_" + stamp)
        suffix = 1
        while folder.exists():
            suffix += 1; folder = self.root / ("ground_test_" + stamp + "_" + str(suffix))
        folder.mkdir(parents=True)
        self.folder = folder; self.count = 0; self.start_clock = time.monotonic()
        self.state = "recording"; self.last_error = ""; self.test_route_ids = [route["id"] for route in routes]
        self.execution_target_type = target_type; self.execution_target_id = target_id
        self.execution_target_name = target_name; self.previous_active_route_id = ""
        self.actuation_enabled = bool(actuation_enabled)
        self.files["csv"] = (folder / "ground_test.csv").open("w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.files["csv"], fieldnames=CSV_FIELDS, extrasaction="ignore")
        self.writer.writeheader(); self.files["csv"].flush()
        self.files["route_metrics"] = (folder / "route_metrics.csv").open("w", newline="", encoding="utf-8-sig")
        self.route_metrics_writer = csv.DictWriter(self.files["route_metrics"], fieldnames=ROUTE_METRIC_FIELDS,
                                                   extrasaction="ignore")
        self.route_metrics_writer.writeheader(); self.files["route_metrics"].flush()
        self.files["route_switches"] = (folder / "route_switches.csv").open("w", newline="", encoding="utf-8-sig")
        self.route_switches_writer = csv.DictWriter(self.files["route_switches"], fieldnames=ROUTE_SWITCH_FIELDS,
                                                    extrasaction="ignore")
        self.route_switches_writer.writeheader(); self.files["route_switches"].flush()
        for key, filename in (("jsonl", "ground_test.jsonl"), ("route_changes", "route_changes.jsonl"),
                              ("events", "events.jsonl")):
            self.files[key] = (folder / filename).open("w", encoding="utf-8")
        json_dump(folder / "reference_routes.json", {"schema_version": 3,
                  "execution_target": {"type": target_type, "id": target_id, "name": target_name},
                  "routes": routes})
        with (folder / "reference_routes.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            fields = ["route_id", "route_name", "waypoint_number", "latitude", "longitude",
                      "utm_easting_m", "utm_northing_m", "utm_zone"]
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
            for route in routes:
                for point in route["waypoints"]:
                    writer.writerow({"route_id": route["id"], "route_name": route.get("name", ""),
                                     "waypoint_number": point["waypoint_number"], "latitude": point["lat"],
                                     "longitude": point["lon"], "utm_easting_m": point["utm_easting_m"],
                                     "utm_northing_m": point["utm_northing_m"], "utm_zone": point["utm_zone"]})
        metadata = {
            "schema_version": 3, "software_version": VERSION, "ros_distribution": os.getenv("ROS_DISTRO", "noetic"),
            "started_at_utc": utc_now(), "test_route_ids": self.test_route_ids,
            "execution_target_type": target_type, "execution_target_id": target_id,
            "execution_target_name": target_name, "subroute_count": len(routes),
            "ground_test_actuation_enabled": self.actuation_enabled,
            "configuration": rospy.get_param("/rcboat", {}),
            "servo_calibration": {key: rospy.get_param("/rcboat/" + key, None) for key in
                                  ("steering_low", "steering_center", "steering_high", "throttle_stop",
                                   "throttle_forward_max", "throttle_reverse_max", "pca_frequency")},
            "safety_note": "Actuation requires explicit GUI confirmation and removed propellers. Actual PWM fields are commanded values; physical feedback is unsupported.",
        }
        json_dump(folder / "test_metadata.json", metadata)
        json_dump(folder / "analysis_manifest.json", {
            "schema_version": 1,
            "purpose": "MATLAB/QGIS and lecture walking-test graph reconstruction",
            "datasets": {
                "ground_test.csv": "one row per time sample: position, heading, speed, command and safety state",
                "route_metrics.csv": "long format: one row per time sample per candidate subroute",
                "route_switches.csv": "active subroute transition instants",
                "reference_routes.csv": "all frozen reference waypoints with WGS84 and UTM coordinates",
            },
            "recommended_graphs": [
                "actual GPS path and all reference subroutes",
                "desired/final rudder angle versus elapsed time",
                "per-subroute heading error versus elapsed time",
                "current Target Path distance versus the 2 m switch threshold",
                "active subroute bands and switch instants",
                "target and measured speed versus elapsed time",
                "desired/final steering and throttle PWM versus elapsed time",
            ],
        })
        analysis_script = pathlib.Path(__file__).resolve().parents[4] / "matlab" / "plot_ground_test_week7.m"
        if analysis_script.exists():
            shutil.copy2(str(analysis_script), str(folder / analysis_script.name))
        self._write_jsonl("events", {"type": "GROUND_TEST_STARTED", "event_time_utc": utc_now(),
                                     "test_route_ids": self.test_route_ids,
                                     "execution_target_type": target_type, "execution_target_id": target_id,
                                     "actuation_enabled": self.actuation_enabled})
        self.publish_status()

    def sample(self):
        if not self.folder:
            return
        safety = self.cache.get("safety", {}); actuator = self.cache.get("actuator", {})
        if safety.get("mode") != "GROUND_TEST" or bool(safety.get("ground_test_actuation_enabled")) != self.actuation_enabled:
            self.last_error = "ground-test safety mode or actuation acknowledgement lost"
            self._write_jsonl("events", {"type": "LOGGER_FORCED_STOP", "event_time_utc": utc_now(),
                                         "error": self.last_error})
            self.close(error=self.last_error); return
        steering = actuator.get("actual_steering_pwm"); throttle = actuator.get("actual_throttle_pwm")
        confirmed = (actuator.get("command_applied") is True and steering is not None and throttle is not None and
                     4900 <= int(steering) <= 7300 and 5800 <= int(throttle) <= 7000 and
                     0 <= time.monotonic() - float(actuator.get("monotonic") or 0) <= 1.0)
        if confirmed and not self.actuation_enabled:
            confirmed = int(steering) == 6000 and int(throttle) == 6450
        if not confirmed:
            self.last_error = "actuator confirmation lost, invalid or stale"
            self._write_jsonl("events", {"type": "OUTPUT_ERROR", "event_time_utc": utc_now(),
                                         "error": self.last_error})
            self.close(error=self.last_error); return
        gps = self.cache.get("gps", {}); nav = self.cache.get("nav", {}); route = self.cache.get("route", {})
        ntrip = self.cache.get("ntrip", {})
        self.count += 1
        sample_utc = utc_now(); elapsed = round(time.monotonic() - self.start_clock, 3)
        quality = {key: gps.get(key) for key in ("hdop", "pdop", "vdop", "hacc_m", "cno_dbhz",
                                                  "gps_data_age_s", "course_quality", "data_validity")}
        row = {
            "sample_index": self.count, "sample_time_epoch_s": round(time.time(), 6), "logger_time_utc": sample_utc,
            "measurement_time_utc": gps.get("measurement_time_utc") or gps.get("utc_time"),
            "gps_received_time_utc": gps.get("received_time_utc"), "output_time_utc": actuator.get("output_time_utc"),
            "elapsed_time_s": elapsed,
            "latitude": gps.get("latitude"), "longitude": gps.get("longitude"),
            "utm_easting_m": gps.get("utm_easting_m"), "utm_northing_m": gps.get("utm_northing_m"),
            "utm_zone": gps.get("utm_zone"), "heading_deg": gps.get("heading_deg"),
            "heading_source": gps.get("heading_source") or "unsupported", "speed_mps": gps.get("speed_mps"),
            "course_deg": gps.get("heading_deg"), "gps_fix": gps.get("fix"), "rtk_state": gps.get("rtk_state") or "no_data",
            "gps_validity": gps.get("data_validity") or "no_data", "gps_healthy": gps.get("healthy"),
            "gps_data_age_s": gps.get("gps_data_age_s"), "correction_age_s": ntrip.get("last_correction_age_s"),
            "satellites": gps.get("satellites"), "hdop": gps.get("hdop"), "pdop": gps.get("pdop"),
            "vdop": gps.get("vdop"), "hacc_m": gps.get("hacc_m"), "cno_dbhz": gps.get("cno_dbhz"),
            "course_quality": gps.get("course_quality"), "gps_quality_used_json": json.dumps(quality, separators=(",", ":")),
            "execution_target_type": self.execution_target_type, "execution_target_id": self.execution_target_id,
            "execution_target_name": self.execution_target_name,
            "selected_route_id": route.get("selected_route_id"), "active_route_id": route.get("active_route_id"),
            "previous_active_route_id": self.previous_active_route_id,
            "test_route_ids": "|".join(self.test_route_ids),
            "target_waypoint_number": (int(route.get("target_waypoint_index")) + 1) if route.get("target_waypoint_index") is not None else None,
            "target_waypoint_index": route.get("target_waypoint_index"),
            "distance_to_waypoint_m": route.get("distance_to_waypoint_m"),
            "cross_track_error_m": route.get("cross_track_error_m"),
            "target_path_distance_m": route.get("previous_target_path_distance_m"),
            "candidate_route_distance_m": route.get("candidate_route_distance_m"),
            "multipath_switch_threshold_m": route.get("switch_threshold_m"),
            "switch_threshold_exceeded": route.get("switch_threshold_exceeded"),
            "switch_decision": route.get("switch_decision"),
            "multipath_candidate_id": route.get("candidate_route_id"), "multipath_switch": route.get("multipath_switch"),
            "controller_mode": nav.get("controller_mode"), "target_heading_deg": nav.get("target_heading_deg"),
            "heading_error_deg": nav.get("heading_error_deg"),
            "desired_rudder_angle_deg": nav.get("desired_rudder_angle_deg"),
            "final_rudder_angle_deg": self._rudder_angle(safety.get("steering_pwm")),
            "target_speed_mps": nav.get("target_speed_mps"),
            "desired_steering_pwm": nav.get("desired_steering_pwm"),
            "desired_throttle_pwm": nav.get("desired_throttle_pwm"),
            "route_candidates_json": json.dumps(route.get("route_candidates") or [], separators=(",", ":")),
            "final_steering_pwm": safety.get("steering_pwm"), "final_throttle_pwm": safety.get("throttle_pwm"),
            "actual_steering_pwm": actuator.get("actual_steering_pwm"),
            "actual_throttle_pwm": actuator.get("actual_throttle_pwm"),
            "output_send_success": actuator.get("command_applied"), "output_status": actuator.get("status") or "no_data",
            "operation_mode": safety.get("mode"), "effective_source": safety.get("effective_source"),
            "output_locked": safety.get("actuator_locked"),
            "ground_test_actuation_enabled": safety.get("ground_test_actuation_enabled"),
            "throttle_locked": safety.get("throttle_locked"),
            "steering_test_enabled": safety.get("steering_test_enabled"),
            "manual_intervention": safety.get("effective_source") in {"MANUAL", "REMOTE"},
            "estop": safety.get("estop"), "navigation_valid": nav.get("valid"), "logger_state": self.state,
        }
        self.writer.writerow(row); self.files["csv"].flush(); self._write_jsonl("jsonl", row)
        active_route_id = str(route.get("active_route_id") or "")
        for metric in route.get("route_candidates") or []:
            metric_row = dict(metric)
            metric_row.update(sample_index=self.count, logger_time_utc=sample_utc, elapsed_time_s=elapsed,
                              is_active=str(metric.get("route_id")) == active_route_id,
                              target_latitude=metric.get("target_lat"), target_longitude=metric.get("target_lon"))
            self.route_metrics_writer.writerow(metric_row)
        self.files["route_metrics"].flush()
        if self.previous_active_route_id and active_route_id != self.previous_active_route_id:
            self.route_switches_writer.writerow({
                "sample_index": self.count, "logger_time_utc": sample_utc, "elapsed_time_s": elapsed,
                "previous_route_id": self.previous_active_route_id, "new_route_id": active_route_id,
                "candidate_route_id": route.get("candidate_route_id"),
                "previous_target_path_distance_m": route.get("previous_target_path_distance_m"),
                "candidate_route_distance_m": route.get("candidate_route_distance_m"),
                "switch_threshold_m": route.get("switch_threshold_m"),
                "switch_decision": route.get("switch_decision"),
                "selection_metric": route.get("selection_metric"),
            })
            self.files["route_switches"].flush()
        self.previous_active_route_id = active_route_id
        self.publish_status()

    @staticmethod
    def _rudder_angle(pwm):
        if pwm is None:
            return None
        value = float(pwm); center = float(rospy.get_param("/rcboat/steering_center", 6000))
        low = float(rospy.get_param("/rcboat/steering_low", 4900)); high = float(rospy.get_param("/rcboat/steering_high", 7300))
        span = high - center if value >= center else center - low
        return round((value - center) * 45.0 / span, 4) if span else None

    def close(self, error=""):
        if not self.folder:
            return
        folder = self.folder; self.state = "stopping"; self.publish_status()
        self._write_jsonl("events", {"type": "GROUND_TEST_STOPPED", "event_time_utc": utc_now(),
                                     "samples": self.count, "error": error or None})
        for handle in list(self.files.values()):
            try: handle.flush(); handle.close()
            except Exception: pass
        self.files = {}; self.writer = None; self.route_metrics_writer = None; self.route_switches_writer = None
        metadata_path = folder / "test_metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata.update(stopped_at_utc=utc_now(), sample_count=self.count,
                            final_state="error" if error else "complete", error=error or None)
            json_dump(metadata_path, metadata)
            self._manifest(folder)
            self.state = "error" if error else "idle"; self.last_error = error
        except Exception as exc:
            self.state = "error"; self.last_error = str(exc)
        self.folder = None; self.actuation_enabled = False; self.publish_status()

    def run(self):
        rate = rospy.Rate(rospy.get_param("/rcboat/log_rate_hz", 4.0))
        while not rospy.is_shutdown():
            self.sample(); rate.sleep()


if __name__ == "__main__":
    rospy.init_node("ground_test_logger_node"); Logger().run()
