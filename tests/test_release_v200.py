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


class ReleaseV200(unittest.TestCase):
    def test_release_identity_and_empty_default_routes(self):
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "2.0.0")
        routes = json.loads((ROOT / "catkin_ws/src/rcboat_ros/config/routes.json").read_text())
        self.assertEqual(routes["routes"], [])
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

    def test_exactly_three_test_routes_and_no_auto_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routes.json"
            routes = []
            for index, name in enumerate(("A", "B", "C", "D")):
                routes.append({"id": name, "name": name, "waypoints": [
                    {"lat": 35.0, "lon": 129.0 + index * 1e-7},
                    {"lat": 35.001, "lon": 129.001 + index * 1e-7}]})
            path.write_text(json.dumps({"selected_route_id": "A", "routes": routes}))
            manager = RouteManager(path)
            with self.assertRaises(ValueError): manager.set_test_route_ids(["A", "B"])
            manager.set_test_route_ids(["A", "B", "C"])
            self.assertEqual(set(manager.group()), {"A", "B", "C"})
            self.assertNotIn("D", manager.group())

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
                         "test_metadata.json", "export_manifest.json"):
            self.assertIn(filename, source)
        for field in ("measurement_time_utc", "output_time_utc", "heading_source", "gps_data_age_s",
                      "correction_age_s", "gps_quality_used_json", "target_waypoint_number",
                      "output_send_success", "manual_intervention", "output_locked"):
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

    def test_no_formal_daemon_fallback_or_secret_file(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runner = (ROOT / "tools/windows/runner.ps1").read_text(encoding="utf-8")
        self.assertNotIn("USE_DAEMON", runner)
        self.assertNotIn("systemctl restart rcboat.service", readme)
        ignores = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/ntrip.local.json", ignores)
        self.assertIn("**/ntrip.env", ignores)

    def test_all_formal_python_sources_compile(self):
        for base in (ROOT / "catkin_ws", ROOT / "windows_gui"):
            for path in base.rglob("*.py"):
                py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()
