from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from .controller import BoatController

LOG = logging.getLogger("rcboat.server")
MAX_COMMAND_BYTES = 65_536


class ControlServer:
    def __init__(
        self,
        controller: BoatController,
        host: str = "127.0.0.1",
        port: int = 8765,
        request_stop: Callable[[], None] | None = None,
    ):
        self.controller = controller
        self.host = host
        self.port = port
        self.request_stop = request_stop
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._client, self.host, self.port)
        LOG.info("Control server listening on %s:%s", self.host, self.port)

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        LOG.info("GUI tunnel connected: %s", peer)
        try:
            while not reader.at_eof():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    raw = b""
                if raw:
                    if len(raw) > MAX_COMMAND_BYTES:
                        raise ValueError("command exceeds size limit")
                    decoded = json.loads(raw.decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise ValueError("command must be a JSON object")
                    response = self._command(decoded)
                    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                writer.write((json.dumps(self.controller.state(), ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                await asyncio.sleep(0.1)
        except (ConnectionError, asyncio.CancelledError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            LOG.info("GUI tunnel closed: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _command(self, msg: dict[str, Any]) -> dict[str, Any]:
        request_id = msg.get("request_id")
        command = str(msg.get("command", "")).upper()
        try:
            if command == "HEARTBEAT":
                self.controller.heartbeat()
            elif command == "SET_MODE":
                self.controller.set_mode(str(msg["mode"]))
            elif command == "REMOTE_CONTROL":
                self.controller.set_remote_pwm(int(msg["steering_pwm"]), int(msg["throttle_pwm"]))
            elif command == "SET_AUTO_CRUISE_PWM":
                value = msg.get("value")
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("auto_cruise_pwm must be an integer")
                self.controller.set_auto_cruise_pwm(value)
            elif command == "SET_MULTIPATH":
                values = {key: msg[key] for key in (
                    "enabled", "endpoint_tolerance_m", "off_route_distance_m",
                    "off_route_hold_s", "closer_advantage_m", "switch_cooldown_s",
                ) if key in msg}
                if not values:
                    raise ValueError("at least one multipath setting is required")
                self.controller.set_multipath(values)
            elif command == "EMERGENCY_STOP":
                self.controller.emergency_stop()
            elif command == "CLEAR_ESTOP":
                self.controller.clear_estop()
            elif command == "SELECT_ROUTE":
                self.controller.select_route(str(msg["route_id"]))
            elif command == "START_GPS_RECORDING":
                self.controller.start_gps_recording(
                    str(msg.get("name", "")),
                    minimum_distance_m=float(msg.get("minimum_distance_m", 1.0)),
                    minimum_interval_s=float(msg.get("minimum_interval_s", 0.5)),
                    arrival_radius_m=float(msg.get("arrival_radius_m", 3.0)),
                )
            elif command == "START_ROUTE_RECORDING":
                self.controller.start_gps_recording(
                    str(msg.get("name", "")),
                    minimum_distance_m=float(msg.get("min_spacing_m", msg.get("minimum_distance_m", 1.0))),
                    minimum_interval_s=float(msg.get("minimum_interval_s", 0.5)),
                    arrival_radius_m=float(msg.get("arrival_radius_m", 3.0)),
                )
            elif command == "STOP_GPS_RECORDING":
                route_id = self.controller.stop_gps_recording(save=True)
                return {
                    "type": "ack",
                    "request_id": request_id,
                    "command": command,
                    "ok": True,
                    "route_id": route_id,
                }
            elif command == "STOP_ROUTE_RECORDING":
                route_id = self.controller.stop_gps_recording(save=True)
                return {
                    "type": "ack",
                    "request_id": request_id,
                    "command": command,
                    "ok": True,
                    "route_id": route_id,
                }
            elif command == "CANCEL_GPS_RECORDING":
                self.controller.stop_gps_recording(save=False)
            elif command == "CANCEL_ROUTE_RECORDING":
                self.controller.stop_gps_recording(save=False)
            elif command == "START_GPS_LOGGING":
                path = self.controller.start_gps_data_logging()
                return {
                    "type": "ack", "request_id": request_id, "command": command,
                    "ok": True, "file_path": path,
                }
            elif command == "STOP_GPS_LOGGING":
                path = self.controller.stop_gps_data_logging()
                return {
                    "type": "ack", "request_id": request_id, "command": command,
                    "ok": True, "file_path": path,
                }
            elif command == "SET_GPS_SETTINGS":
                values = {key: msg[key] for key in (
                    "health_stale_s", "navigation_max_hdop",
                    "rtk_required_for_navigation", "rtk_correction_max_age_s",
                ) if key in msg}
                self.controller.set_gps_settings(values)
            elif command == "CONFIGURE_NTRIP":
                values = {key: msg[key] for key in (
                    "enabled", "host", "port", "mountpoint", "username", "password",
                    "tls", "timeout_s", "gga_interval_s",
                ) if key in msg}
                self.controller.configure_ntrip(values)
            elif command == "DISABLE_NTRIP":
                self.controller.configure_ntrip({"enabled": False})
            elif command == "REFRESH_NTRIP":
                pass
            elif command == "START_HIL":
                route_id = msg.get("route_id")
                self.controller.start_hil(None if route_id is None else str(route_id))
            elif command == "STOP_HIL":
                self.controller.stop_hil()
            elif command == "RELOAD_ROUTES":
                if not self.controller.routes.load():
                    raise RuntimeError(
                        self.controller.routes.load_error or "route file contains no usable route"
                    )
            elif command == "GET_STATE":
                pass
            elif command == "SHUTDOWN_MOCK":
                if not getattr(self.controller.hardware, "is_mock", False):
                    raise RuntimeError("mock-only command")
                if self.request_stop is None:
                    raise RuntimeError("shutdown callback unavailable")
                self.controller.force_safe("MOCK_SHUTDOWN")
                self.request_stop()
            else:
                raise ValueError(f"unknown command: {command}")
            return {"type": "ack", "request_id": request_id, "command": command, "ok": True}
        except Exception as exc:
            return {
                "type": "ack",
                "request_id": request_id,
                "command": command,
                "ok": False,
                "error": str(exc),
            }
