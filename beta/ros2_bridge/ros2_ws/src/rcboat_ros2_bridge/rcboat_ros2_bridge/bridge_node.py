from __future__ import annotations

import json
import math
import queue
from typing import Any

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, NavSatStatus
from std_msgs.msg import Bool, Empty, Int32MultiArray, String

from .transport import DaemonTransport


class RcBoatBridge(Node):
    def __init__(self) -> None:
        super().__init__("rcboat_bridge")
        self.declare_parameter("daemon_host", "127.0.0.1")
        self.declare_parameter("daemon_port", 8765)
        self.declare_parameter("gps_frame_id", "gps_link")

        host = str(self.get_parameter("daemon_host").value)
        port = int(self.get_parameter("daemon_port").value)
        self.gps_frame_id = str(self.get_parameter("gps_frame_id").value)
        self._incoming: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=512)
        self._connection_events: queue.Queue[bool] = queue.Queue(maxsize=8)

        self.state_json_pub = self.create_publisher(String, "/rcboat/state/json", 10)
        self.ack_json_pub = self.create_publisher(String, "/rcboat/state/ack_json", 10)
        self.mode_pub = self.create_publisher(String, "/rcboat/state/mode", 10)
        self.connected_pub = self.create_publisher(Bool, "/rcboat/state/connected", 10)
        self.gps_pub = self.create_publisher(NavSatFix, "/rcboat/gps/fix", 10)

        self.create_subscription(String, "/rcboat/cmd/json", self._json_command, 10)
        self.create_subscription(String, "/rcboat/cmd/mode", self._mode_command, 10)
        self.create_subscription(Int32MultiArray, "/rcboat/cmd/pwm", self._pwm_command, 10)
        self.create_subscription(Empty, "/rcboat/cmd/heartbeat", self._heartbeat, 10)
        self.create_subscription(Empty, "/rcboat/cmd/emergency_stop", self._estop, 10)
        self.create_subscription(Empty, "/rcboat/cmd/clear_estop", self._clear_estop, 10)
        self.create_subscription(String, "/rcboat/cmd/route", self._route_command, 10)

        self.transport = DaemonTransport(
            host,
            port,
            on_message=self._queue_message,
            on_connection=self._queue_connection,
        )
        self.transport.start()
        self.create_timer(0.02, self._drain_queues)
        self.get_logger().info(f"Connecting to RC Boat daemon at {host}:{port}")

    def destroy_node(self) -> bool:
        self.transport.stop()
        return super().destroy_node()

    def _queue_message(self, message: dict[str, Any]) -> None:
        try:
            self._incoming.put_nowait(message)
        except queue.Full:
            try:
                self._incoming.get_nowait()
                self._incoming.put_nowait(message)
            except (queue.Empty, queue.Full):
                pass

    def _queue_connection(self, connected: bool) -> None:
        try:
            self._connection_events.put_nowait(connected)
        except queue.Full:
            pass

    def _drain_queues(self) -> None:
        while True:
            try:
                connected = self._connection_events.get_nowait()
            except queue.Empty:
                break
            self.connected_pub.publish(Bool(data=connected))
            level = self.get_logger().info if connected else self.get_logger().warning
            level("RC Boat daemon connected" if connected else "RC Boat daemon disconnected")

        for _ in range(64):
            try:
                message = self._incoming.get_nowait()
            except queue.Empty:
                break
            self._publish_message(message)

    @staticmethod
    def _json_text(message: dict[str, Any]) -> String:
        return String(data=json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    def _publish_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "ack":
            self.ack_json_pub.publish(self._json_text(message))
            return
        if message_type != "telemetry":
            return
        self.state_json_pub.publish(self._json_text(message))
        self.mode_pub.publish(String(data=str(message.get("mode", ""))))
        gps = message.get("gps")
        if isinstance(gps, dict):
            self._publish_gps(gps)

    def _publish_gps(self, gps: dict[str, Any]) -> None:
        msg = NavSatFix()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.gps_frame_id
        fix = bool(gps.get("fix"))
        msg.status.status = NavSatStatus.STATUS_FIX if fix else NavSatStatus.STATUS_NO_FIX
        msg.status.service = NavSatStatus.SERVICE_GPS
        msg.latitude = self._float_or_nan(gps.get("lat"))
        msg.longitude = self._float_or_nan(gps.get("lon"))
        msg.altitude = self._float_or_nan(gps.get("altitude_m"))
        hacc = self._optional_nonnegative_float(gps.get("hacc_m"))
        if hacc is not None:
            variance = hacc * hacc
            msg.position_covariance[0] = variance
            msg.position_covariance[4] = variance
            msg.position_covariance[8] = variance * 4.0
            msg.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
        else:
            msg.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        self.gps_pub.publish(msg)

    @staticmethod
    def _float_or_nan(value: Any) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return math.nan
        return result if math.isfinite(result) else math.nan

    @staticmethod
    def _optional_nonnegative_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result >= 0.0 else None

    def _send(self, command: dict[str, Any]) -> None:
        try:
            self.transport.send(command)
        except (TypeError, ValueError, RuntimeError) as exc:
            self.get_logger().error(str(exc))

    def _json_command(self, msg: String) -> None:
        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"Invalid command JSON: {exc}")
            return
        if not isinstance(command, dict):
            self.get_logger().error("Command JSON must be an object")
            return
        self._send(command)

    def _mode_command(self, msg: String) -> None:
        self._send({"command": "SET_MODE", "mode": msg.data.strip().upper()})

    def _pwm_command(self, msg: Int32MultiArray) -> None:
        if len(msg.data) != 2:
            self.get_logger().error("PWM command must contain [steering_pwm, throttle_pwm]")
            return
        self._send(
            {
                "command": "REMOTE_CONTROL",
                "steering_pwm": int(msg.data[0]),
                "throttle_pwm": int(msg.data[1]),
            }
        )

    def _heartbeat(self, _msg: Empty) -> None:
        self._send({"command": "HEARTBEAT"})

    def _estop(self, _msg: Empty) -> None:
        self._send({"command": "EMERGENCY_STOP"})

    def _clear_estop(self, _msg: Empty) -> None:
        self._send({"command": "CLEAR_ESTOP"})

    def _route_command(self, msg: String) -> None:
        self._send({"command": "SELECT_ROUTE", "route_id": msg.data.strip()})


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RcBoatBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
