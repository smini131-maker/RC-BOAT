import json
import os
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "catkin_ws/src/rcboat_ros/src"
sys.path.insert(0, str(SRC))

from rcboat_ros.geo import enrich_waypoints, latlon_to_utm
from rcboat_ros.path_tracking import RouteManager


class ReleaseV210(unittest.TestCase):
    def test_release_identity_and_empty_default_routes(self):
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "2.1.7")
        routes = json.loads((ROOT / "catkin_ws/src/rcboat_ros/config/routes.json").read_text())
        self.assertEqual(routes["routes"], [])
        self.assertEqual(routes["multipaths"], [])
        self.assertEqual(routes["selected_route_id"], "")

    def test_manual_route_crud_and_utm_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            path.write_text('{"schema_version":2,"selected_route_id":"","routes":[]}')
            manager = RouteManager(path)
            self.assertEqual(manager.routes, {})
            route_id = manager.upsert("", "LEFT", [{"lat": 35.0, "lon": 129.0},
                                                      {"lat": 35.0001, "lon": 129.0001}], 2.0)
            saved = manager.routes[route_id]
            self.assertEqual(saved["name"], "LEFT")
            self.assertEqual([point["waypoint_number"] for point in saved["waypoints"]], [1, 2])
            for point in saved["waypoints"]:
                self.assertIn("utm_easting_m", point); self.assertIn("utm_northing_m", point)
                self.assertEqual(point["utm_zone"], "52N")
            manager.upsert(route_id, "CENTER", saved["waypoints"], 3.0)
            self.assertEqual(manager.routes[route_id]["name"], "CENTER")
            manager.delete(route_id)
            self.assertEqual(manager.routes, {})

    def test_gps_recording_needs_no_existing_route_and_survives_early_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            path.write_text('{"schema_version":3,"selected_route_id":"","routes":[]}')
            manager = RouteManager(path)
            self.assertEqual(manager.selected, "")
            manager.record_start("walk", minimum_distance_m=1.0, minimum_interval_s=0.5)
            self.assertTrue(manager.record_point(35.0, 129.0, heading=10.0,
                                                 timestamp="2026-10-16T00:00:00Z", now=0.0))
            with self.assertRaisesRegex(ValueError, "recording remains active"):
                manager.record_stop()
            self.assertIsNotNone(manager.recording)
            self.assertTrue(manager.record_point(35.00002, 129.0, heading=11.0,
                                                 timestamp="2026-10-16T00:00:01Z", now=1.0))
            route_id = manager.record_stop()
            self.assertIn(route_id, manager.routes)
            self.assertEqual(len(manager.routes[route_id]["waypoints"]), 2)
            self.assertEqual([point["waypoint_number"] for point in manager.routes[route_id]["waypoints"]], [1, 2])
        node = (ROOT / "catkin_ws/src/rcboat_ros/nodes/route_manager_node.py").read_text(encoding="utf-8")
        self.assertLess(node.index("if self.rm.recording is not None:"),
                        node.index("if self.gps.get('healthy') and self.rm.selected:"))
        self.assertIn("capture_status", node)

    def test_named_multipath_supports_n_routes_without_endpoint_constraint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            routes = []
            for index, name in enumerate(("A", "B", "C", "D")):
                routes.append({"id": name, "name": name, "waypoints": [
                    {"lat": 35.0, "lon": 129.0 + index * 1e-7},
                    {"lat": 35.001, "lon": 129.001 + index * 1e-7}]})
            path.write_text(json.dumps({"schema_version": 3, "selected_route_id": "A",
                                        "selected_multipath_id": "", "multipath_enabled": True,
                                        "multipaths": [], "routes": routes}))
            manager = RouteManager(path)
            multipath_id = manager.upsert_multipath("", "대루트 A", ["A", "B", "C"], "B")
            manager.select_multipath(multipath_id)
            self.assertEqual(list(manager.group()), ["A", "B", "C"])
            self.assertNotIn("D", manager.group())
            manager.set_test_route_ids(["A", "B"])
            self.assertEqual(list(manager.group()), ["A", "B"])
            manager.set_test_route_ids([])
            manager.set_multipath_enabled(False)
            self.assertEqual(list(manager.group()), ["B"])

    def test_endpoint_compatibility_is_only_an_optional_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            routes = [
                {"id": "near", "name": "near", "waypoints": [{"lat": 35, "lon": 129}, {"lat": 35.001, "lon": 129.001}]},
                {"id": "far", "name": "far", "waypoints": [{"lat": 36, "lon": 130}, {"lat": 36.001, "lon": 130.001}]},
            ]
            path.write_text(json.dumps({"selected_route_id": "near", "routes": routes}))
            manager = RouteManager(path)
            self.assertEqual(manager.compatible_route_ids("near"), ["near"])
            group_id = manager.upsert_multipath("", "mixed", ["near", "far"], "near")
            manager.select_multipath(group_id)
            self.assertEqual(set(manager.group()), {"near", "far"})

    def test_route_update_emits_per_subroute_graph_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            routes = [
                {"id": "a", "name": "A", "waypoints": [{"lat": 35, "lon": 129}, {"lat": 35.001, "lon": 129}]},
                {"id": "b", "name": "B", "waypoints": [{"lat": 35, "lon": 129.001}, {"lat": 35.001, "lon": 129.001}]},
            ]
            path.write_text(json.dumps({"selected_route_id": "a", "routes": routes}))
            manager = RouteManager(path)
            group_id = manager.upsert_multipath("", "A", ["a", "b"], "a")
            manager.select_multipath(group_id)
            state = manager.update((35.0002, 129.0002), heading=10.0)
            self.assertEqual(len(state["route_candidates"]), 2)
            for metric in state["route_candidates"]:
                for key in ("distance_to_route_m", "cross_track_error_m", "target_waypoint_number",
                            "target_heading_deg", "heading_error_deg"):
                    self.assertIn(key, metric)

    def test_multipath_always_selects_the_nearest_route_without_a_distance_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            metres_per_degree_lon = 91188.0
            routes = [
                {"id": "center", "name": "Center", "waypoints": [
                    {"lat": 35.0, "lon": 129.0}, {"lat": 35.001, "lon": 129.0}]},
                {"id": "right", "name": "Right", "waypoints": [
                    {"lat": 35.0, "lon": 129.0 + 3.0 / metres_per_degree_lon},
                    {"lat": 35.001, "lon": 129.0 + 3.0 / metres_per_degree_lon}]},
            ]
            path.write_text(json.dumps({"schema_version": 3, "selected_route_id": "center",
                                        "selected_multipath_id": "group", "multipath_enabled": True,
                                        "multipaths": [{"id": "group", "name": "A",
                                                        "route_ids": ["center", "right"],
                                                        "default_route_id": "center"}],
                                        "routes": routes}))
            manager = RouteManager(path)
            nearer_right = manager.update((35.0002, 129.0 + 1.8 / metres_per_degree_lon), heading=0.0)
            self.assertEqual(nearer_right["active_route_id"], "right")
            self.assertTrue(nearer_right["multipath_switch"])
            self.assertLess(nearer_right["previous_target_path_distance_m"], 2.0)
            self.assertEqual(nearer_right["switch_decision"], "SWITCH_TO_NEAREST_ROUTE")
            self.assertEqual(nearer_right["selection_metric"], "MINIMUM_POLYLINE_DISTANCE")
            self.assertNotIn("switch_threshold_m", nearer_right)
            self.assertNotIn("switch_threshold_exceeded", nearer_right)
            nearer_center = manager.update((35.0003, 129.0 + 1.2 / metres_per_degree_lon), heading=0.0)
            self.assertEqual(nearer_center["active_route_id"], "center")
            self.assertTrue(nearer_center["multipath_switch"])

            tracking_source = (SRC / "rcboat_ros/path_tracking.py").read_text(encoding="utf-8")
            gui_source = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
            config_source = (ROOT / "catkin_ws/src/rcboat_ros/config/boat.yaml").read_text(encoding="utf-8")
            self.assertNotIn("switch_threshold", tracking_source + gui_source + config_source)

    def test_utm_is_plausible_and_not_placeholder_zero(self):
        easting, northing, zone = latlon_to_utm(35.0, 129.0)
        self.assertEqual(zone, "52N")
        self.assertGreater(easting, 100000); self.assertGreater(northing, 1000000)
        enriched = enrich_waypoints([{"lat": 35.0, "lon": 129.0}])[0]
        self.assertNotEqual(enriched["utm_easting_m"], 0)

    def test_ground_logger_contract(self):
        source = (ROOT / "catkin_ws/src/rcboat_ros/nodes/ground_test_logger_node.py").read_text(encoding="utf-8")
        for filename in ("ground_test.csv", "ground_test.jsonl", "reference_routes.csv",
                         "reference_routes.json", "route_changes.jsonl", "events.jsonl",
                         "test_metadata.json", "export_manifest.json", "route_metrics.csv",
                         "route_switches.csv", "analysis_manifest.json", "plot_ground_test_week7.m"):
            self.assertIn(filename, source)
        for field in ("measurement_time_utc", "output_time_utc", "heading_source", "gps_data_age_s",
                      "correction_age_s", "gps_quality_used_json", "target_waypoint_number",
                      "output_send_success", "manual_intervention", "output_locked",
                      "desired_rudder_angle_deg", "target_speed_mps", "route_candidates_json",
                      "execution_target_type", "target_path_distance_m",
                      "previous_target_path_distance_m", "route_distance_improvement_m", "selection_metric",
                      "switch_decision", "ground_test_actuation_enabled"):
            self.assertIn(field, source)
        self.assertIn("already_stopped", source)
        self.assertIn("LOGGER_RESTART_DETECTED", source)

    def test_gateway_stop_and_download_do_not_require_ssh(self):
        gateway = (ROOT / "catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py").read_text(encoding="utf-8")
        worker = (ROOT / "windows_gui/rcboat_gui/ssh_worker.py").read_text(encoding="utf-8")
        self.assertIn("tcp_server.bind", gateway)
        self.assertIn('command == "ground_stop"', gateway)
        self.assertIn("download_ground_test", gateway)
        self.assertIn("socket.create_connection((self.host, self.gateway_port)", worker)
        self.assertNotIn("SSH session not active", worker)
        self.assertIn("ROS gateway worker with an independent", worker)

    def test_gps_fields_flow_end_to_end(self):
        parser = (SRC / "rcboat_ros/gps_mix.py").read_text(encoding="utf-8")
        node = (ROOT / "catkin_ws/src/rcboat_ros/nodes/gps_node.py").read_text(encoding="utf-8")
        gateway = (ROOT / "windows_gui/rcboat_gui/ssh_worker.py").read_text(encoding="utf-8")
        gui = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
        for token in ("utc_time", "utm_easting_m", "gps_data_age_s", "utc_status"):
            self.assertTrue(token in parser or token in node)
            self.assertIn(token if token != "utm_easting_m" else "utm_easting", gateway)
        for token in ("unsupported", "no_data", "invalid", "stale"):
            self.assertIn(token, (gateway + gui).lower())

    def test_statuses_are_independent(self):
        gui = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
        for label in ("SSH 연결", "ROS master", "ROS gateway", "Logger", "GPS", "RTK"):
            self.assertIn(label, gui)

    def test_ssh_status_uses_active_liveness_probe(self):
        worker_source = (ROOT / "windows_gui/rcboat_gui/ssh_worker.py").read_text(encoding="utf-8")
        gui_source = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("def _ssh_is_healthy", worker_source)
        self.assertIn("transport.open_session(timeout=self.SSH_HEALTH_TIMEOUT_S)", worker_source)
        self.assertIn("shell.closed or shell.exit_status_ready()", worker_source)
        self.assertIn('self.cards["ssh"].set_value("connected" if ready else "disconnected", ready)', gui_source)

    def test_ground_test_full_output_requires_explicit_opt_in(self):
        supervisor = (ROOT / "catkin_ws/src/rcboat_ros/nodes/safety_supervisor_node.py").read_text(encoding="utf-8")
        actuator = (ROOT / "catkin_ws/src/rcboat_ros/nodes/actuator_node.py").read_text(encoding="utf-8")
        bridge = (ROOT / "catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py").read_text(encoding="utf-8")
        gui = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("ground_test_actuation_enabled", supervisor)
        self.assertIn("actuation_enabled", bridge)
        self.assertIn("actuation_enabled", gui)
        self.assertIn("GROUND_TEST_NAVIGATION", supervisor)
        self.assertIn("GROUND_TEST_NAVIGATION", actuator)
        self.assertIn("프로펠러 제거 확인", gui)

    def test_gui_supports_large_route_and_single_route_targets(self):
        gui = (ROOT / "windows_gui/rcboat_gui/main_window.py").read_text(encoding="utf-8")
        bridge = (ROOT / "catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py").read_text(encoding="utf-8")
        for token in ("대루트 추가", "UPSERT_MULTIPATH", "DELETE_MULTIPATH", "single_route",
                      "공통 출발·도착인 항로 자동 체크"):
            self.assertIn(token, gui)
        self.assertIn('target_type=="multipath"', bridge)
        self.assertIn('target_type=="single_route"', bridge)

    def test_no_formal_daemon_fallback_or_secret_file(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runner = (ROOT / "tools/windows/runner.ps1").read_text(encoding="utf-8")
        self.assertNotIn("USE_DAEMON", runner)
        self.assertNotIn("systemctl restart rcboat.service", readme)
        ignores = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/ntrip.local.json", ignores)
        self.assertIn("**/ntrip.env", ignores)

    def test_ntrip_secret_is_jetson_local_and_direct_roslaunch_can_load_it(self):
        node = (ROOT / "catkin_ws/src/rcboat_ros/nodes/ntrip_node.py").read_text(encoding="utf-8")
        setup = (ROOT / "deployment/jetson/configure_ntrip_local.py").read_text(encoding="utf-8")
        self.assertIn("~/rcboat_ros_data/ntrip.env", node)
        self.assertIn("load_local_env(NTRIP_ENV_PATH)", node)
        self.assertIn("credentials_saved", node)
        self.assertIn("getpass.getpass", setup)
        self.assertIn("chmod(0o600)", setup)
        self.assertNotIn("RCBOAT_NTRIP_PASSWORD=example", node + setup)

    def test_all_formal_python_sources_compile(self):
        for base in (ROOT / "catkin_ws", ROOT / "windows_gui"):
            for path in base.rglob("*.py"):
                py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()
