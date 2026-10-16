#!/usr/bin/env python3
"""ROS gateway with independent LAN and local UNIX-socket transports."""
import base64
import csv
import datetime as dt
import io
import json
import os
import pathlib
import socket
import threading
import zipfile

import rospy
from std_msgs.msg import String
from rcboat_ros.srv import Execute
from rcboat_ros.common import pack, unpack


VERSION = "2.1.5"
SOCKET = os.path.expanduser("~/rcboat_ros_data/gui_bridge.sock")
TOPICS = {
    "gps": "/rcboat/gps/status", "ntrip": "/rcboat/ntrip/status", "route": "/rcboat/route/state",
    "navigation": "/rcboat/navigation/desired", "safety": "/rcboat/safety/state",
    "actuator": "/rcboat/actuator/status", "ground_test": "/rcboat/ground_test/status",
    "rc": "/rcboat/rc/input",
}


class Bridge:
    def __init__(self):
        self.cache = {}
        self.gps_log_file = None; self.gps_log_writer = None; self.gps_log_samples = 0; self.gps_log_path = ""
        self.test_root = pathlib.Path(os.path.expanduser(rospy.get_param(
            "/rcboat/ground_test_log_root", "~/rcboat_ros_data/logs/ground_tests")))
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.bind_host = str(rospy.get_param("/rcboat/gui_gateway_bind", "0.0.0.0"))
        self.bind_port = int(rospy.get_param("/rcboat/gui_gateway_port", 8765))
        self.token = os.getenv("RCBOAT_GATEWAY_TOKEN", "")
        self.events = rospy.Publisher("/rcboat/events", String, queue_size=8)
        for name, topic in TOPICS.items():
            callback = self.gps_update if name == "gps" else lambda message, key=name: self.cache.__setitem__(key, unpack(message))
            rospy.Subscriber(topic, String, callback)
        rospy.on_shutdown(self.close)
        self.sockets = []

    def gps_update(self, message):
        data = unpack(message); self.cache["gps"] = data
        if self.gps_log_writer:
            self.gps_log_samples += 1
            row = {"logger_time_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")}
            row.update({key: data.get(key) for key in (
                "measurement_time_utc", "received_time_utc", "latitude", "longitude", "utm_easting_m",
                "utm_northing_m", "utm_zone", "altitude_m", "fix", "rtk_state", "data_validity",
                "satellites", "hdop", "hacc_m", "cno_dbhz", "speed_mps", "heading_deg",
                "heading_source", "gps_data_age_s")})
            self.gps_log_writer.writerow(row); self.gps_log_file.flush()

    def start_gps_log(self):
        if self.gps_log_file: raise RuntimeError("GPS logging already active")
        folder = pathlib.Path(os.path.expanduser("~/rcboat_ros_data/gps_logs")); folder.mkdir(parents=True, exist_ok=True)
        self.gps_log_path = str(folder / ("gps_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"))
        fields = ["logger_time_utc", "measurement_time_utc", "received_time_utc", "latitude", "longitude",
                  "utm_easting_m", "utm_northing_m", "utm_zone", "altitude_m", "fix", "rtk_state",
                  "data_validity", "satellites", "hdop", "hacc_m", "cno_dbhz", "speed_mps",
                  "heading_deg", "heading_source", "gps_data_age_s"]
        self.gps_log_file = open(self.gps_log_path, "w", newline="", encoding="utf-8-sig")
        self.gps_log_writer = csv.DictWriter(self.gps_log_file, fieldnames=fields)
        self.gps_log_writer.writeheader(); self.gps_log_samples = 0

    def close_gps_log(self):
        if self.gps_log_file: self.gps_log_file.close()
        self.gps_log_file = None; self.gps_log_writer = None

    def tests(self):
        result = []
        for folder in sorted(self.test_root.glob("ground_test_*"), key=lambda path: path.stat().st_mtime, reverse=True):
            if not folder.is_dir(): continue
            metadata = {}
            try: metadata = json.loads((folder / "test_metadata.json").read_text(encoding="utf-8"))
            except (OSError, ValueError): pass
            result.append({"id": folder.name, "sample_count": metadata.get("sample_count"),
                           "started_at_utc": metadata.get("started_at_utc"),
                           "complete": (folder / "export_manifest.json").exists()})
        return result

    def download_test(self, test_id):
        completed = [item["id"] for item in self.tests() if item["complete"]]
        available = set(completed)
        chosen = str(test_id or "")
        if not chosen:
            chosen = completed[0] if completed else ""
        if chosen not in available or pathlib.Path(chosen).name != chosen:
            raise ValueError("ground test not found or still recording")
        folder = self.test_root / chosen
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file(): archive.write(path, pathlib.Path(chosen) / path.relative_to(folder))
        payload = buffer.getvalue()
        return {"test_id": chosen, "filename": chosen + ".zip", "bytes": len(payload),
                "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                "zip_base64": base64.b64encode(payload).decode("ascii")}

    @staticmethod
    def service(namespace, action, arguments=None, timeout=3):
        rospy.wait_for_service(namespace, timeout=timeout)
        answer = rospy.ServiceProxy(namespace, Execute)(action, json.dumps(arguments or {}, ensure_ascii=False))
        detail = json.loads(answer.response_json or "{}")
        if not answer.success: raise RuntimeError(detail.get("error") or answer.response_json)
        return detail

    def ground_start(self, args):
        target_type=str(args.get("target_type") or "multipath")
        target_id=str(args.get("target_id") or "")
        actuation_enabled=bool(args.get("actuation_enabled",False))
        route_state=self.cache.get("route",{})
        multipath_state=route_state.get("multipath",{})
        multipath_settings={
            "endpoint_tolerance_m":float(multipath_state.get("endpoint_tolerance_m",.75)),
            "switch_threshold_m":float(multipath_state.get("switch_threshold_m",2.0)),
        }
        if target_type=="multipath":
            groups={str(item.get("id")):item for item in route_state.get("multipaths",[])}
            if target_id not in groups:raise ValueError("select a saved multipath")
            ids=[str(value) for value in groups[target_id].get("route_ids",[])]
            if not ids:raise ValueError("selected multipath has no subroutes")
            self.service("/rcboat/route/execute","select_multipath",{"multipath_id":target_id})
            self.service("/rcboat/route/execute","set_multipath",dict(multipath_settings,enabled=True))
        elif target_type=="single_route":
            routes={str(item.get("id")):item for item in route_state.get("routes",[])}
            if target_id not in routes:raise ValueError("select a saved subroute")
            ids=[target_id]
            self.service("/rcboat/route/execute","select_route",{"route_id":target_id})
            self.service("/rcboat/route/execute","set_multipath",dict(multipath_settings,enabled=False))
        else:raise ValueError("target_type must be multipath or single_route")
        self.service("/rcboat/route/execute", "set_test_route_set", {"route_ids": ids})
        try:
            self.service("/rcboat/safety/execute", "set_mode", {
                "mode": "GROUND_TEST", "ground_test_actuation_enabled": actuation_enabled})
            rospy.sleep(.25)
            return self.service("/rcboat/logger/execute", "start", {"route_ids": ids,
                "target_type":target_type,"target_id":target_id,
                "actuation_enabled":actuation_enabled})
        except Exception:
            try: self.service("/rcboat/safety/execute", "set_mode", {"mode": "AUTO_SAFE"})
            finally: self.service("/rcboat/route/execute", "set_test_route_set", {"route_ids": []})
            raise

    def ground_stop(self):
        errors = []; result = {}
        try: result = self.service("/rcboat/logger/execute", "stop", {})
        except Exception as exc: errors.append("logger: " + str(exc))
        try: self.service("/rcboat/safety/execute", "set_mode", {"mode": "AUTO_SAFE"})
        except Exception as exc: errors.append("safety: " + str(exc))
        try: self.service("/rcboat/route/execute", "set_test_route_set", {"route_ids": []})
        except Exception as exc: errors.append("route: " + str(exc))
        if errors: raise RuntimeError("; ".join(errors))
        return result

    def dispatch(self, payload):
        if self.token and payload.get("token") != self.token:
            return {"success": False, "error": "gateway authentication failed"}
        command = payload.get("action", "status"); args = payload.get("arguments", {})
        if command == "status":
            try:
                import rosnode
                nodes = rosnode.get_node_names()
                master_online = rospy.get_master().getPid()[0] == 1
            except Exception:
                nodes = []; master_online = False
            telemetry = dict(self.cache)
            telemetry["gps_logging"] = {"active": self.gps_log_file is not None, "file_path": self.gps_log_path,
                                        "samples": self.gps_log_samples}
            return {"success": True, "version": VERSION, "backend": "ROS Noetic", "master_online": master_online,
                    "gateway_online": True, "telemetry": telemetry, "nodes": nodes, "ground_tests": self.tests()}
        if command == "gps_log_start": self.start_gps_log(); return {"success": True, "response": {"file_path": self.gps_log_path}}
        if command == "gps_log_stop":
            path = self.gps_log_path; samples = self.gps_log_samples; self.close_gps_log()
            return {"success": True, "response": {"file_path": path, "samples": samples}}
        if command == "list_ground_tests": return {"success": True, "response": {"ground_tests": self.tests()}}
        if command == "download_ground_test": return {"success": True, "response": self.download_test(args.get("test_id"))}
        if command == "ground_start": return {"success": True, "response": self.ground_start(args)}
        if command == "ground_stop": return {"success": True, "response": self.ground_stop()}
        if command == "set_gps_settings":
            if "navigation_max_hdop" in args: rospy.set_param("/rcboat/max_hdop", float(args["navigation_max_hdop"]))
            self.events.publish(pack(type="CONFIG_CHANGE", change_type="gps_settings", after=args))
            return {"success": True, "response": args}
        namespace = (
            "/rcboat/safety/execute" if command in ("set_mode", "estop", "reset_estop", "set_remote_pwm", "heartbeat")
            else "/rcboat/route/execute" if command in ("select_route", "delete_route", "upsert_route", "list_routes",
                                                         "record_start", "record_stop", "record_cancel", "set_multipath",
                                                         "choose_nearest_group_route", "set_test_route_set",
                                                         "select_multipath","upsert_multipath","delete_multipath",
                                                         "compatible_routes")
            else "/rcboat/ntrip/execute" if command == "configure"
            else "/rcboat/navigation/execute" if command in ("set_tracking_mode", "set_auto_cruise_pwm") else None
        )
        if not namespace: return {"success": False, "error": "unsupported action"}
        try: return {"success": True, "response": self.service(namespace, command, args)}
        except Exception as exc: return {"success": False, "error": str(exc)}

    def client(self, connection):
        with connection:
            try:
                data = b""
                while len(data) < 2_000_000 and b"\n" not in data:
                    chunk = connection.recv(65536)
                    if not chunk: break
                    data += chunk
                response = self.dispatch(json.loads(data.decode("utf-8").strip()))
            except Exception as exc: response = {"success": False, "error": str(exc)}
            connection.sendall((json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))

    def serve(self, server):
        server.settimeout(.5)
        while not rospy.is_shutdown():
            try: connection, _ = server.accept()
            except socket.timeout: continue
            except OSError: break
            threading.Thread(target=self.client, args=(connection,), daemon=True).start()

    def close(self):
        self.close_gps_log()
        for server in self.sockets:
            try: server.close()
            except OSError: pass
        try: os.unlink(SOCKET)
        except FileNotFoundError: pass

    def run(self):
        os.makedirs(os.path.dirname(SOCKET), exist_ok=True)
        try: os.unlink(SOCKET)
        except FileNotFoundError: pass
        unix_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); unix_server.bind(SOCKET)
        os.chmod(SOCKET, 0o600); unix_server.listen(8)
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind((self.bind_host, self.bind_port)); tcp_server.listen(8)
        self.sockets = [unix_server, tcp_server]
        rospy.loginfo("GUI gateway listening on %s:%s and %s", self.bind_host, self.bind_port, SOCKET)
        thread = threading.Thread(target=self.serve, args=(unix_server,), daemon=True); thread.start()
        self.serve(tcp_server)


if __name__ == "__main__":
    rospy.init_node("gui_bridge_node"); Bridge().run()
