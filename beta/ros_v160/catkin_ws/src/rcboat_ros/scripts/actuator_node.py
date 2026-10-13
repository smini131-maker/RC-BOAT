#!/usr/bin/env python3
from __future__ import annotations

import threading
import time

import rospy

from rcboat_ros.msg import ActuatorStatus, ControlCommand
from rcboat_ros.pca_direct import DirectLinuxPCA9685
from rcboat_ros.ros_utils import clamp_int


class ActuatorNode:
    def __init__(self) -> None:
        self.bus = int(rospy.get_param("/rcboat/hardware/i2c_bus", 1))
        self.address = int(rospy.get_param("/rcboat/hardware/pca_address", 0x40))
        self.frequency = int(rospy.get_param("/rcboat/hardware/pca_frequency_hz", 60))
        self.steering_channel = int(rospy.get_param("/rcboat/hardware/steering_channel", 0))
        self.throttle_channel = int(rospy.get_param("/rcboat/hardware/throttle_channel", 6))
        self.steer_low = int(rospy.get_param("/rcboat/hardware/steering_low_pwm", 4900))
        self.center = int(rospy.get_param("/rcboat/hardware/steering_center_pwm", 6000))
        self.steer_high = int(rospy.get_param("/rcboat/hardware/steering_high_pwm", 7300))
        self.throttle_low = min(int(rospy.get_param("/rcboat/hardware/throttle_reverse_pwm", 5800)), int(rospy.get_param("/rcboat/hardware/throttle_forward_pwm", 7000)))
        self.throttle_high = max(int(rospy.get_param("/rcboat/hardware/throttle_reverse_pwm", 5800)), int(rospy.get_param("/rcboat/hardware/throttle_forward_pwm", 7000)))
        self.stop_pwm = int(rospy.get_param("/rcboat/hardware/throttle_stop_pwm", 6450))
        self.timeout_s = float(rospy.get_param("/rcboat/hardware/command_timeout_s", 0.3))
        self._lock = threading.Lock()
        self.pca = None
        self.last_command = 0.0
        self.requested = (self.center, self.stop_pwm)
        self.applied = (self.center, self.stop_pwm)
        self.error = "PCA not connected"
        self.status_pub = rospy.Publisher("/rcboat/actuator/status", ActuatorStatus, queue_size=10, latch=True)
        rospy.Subscriber("/rcboat/safety/actuator_command", ControlCommand, self._command, queue_size=1)
        rospy.on_shutdown(self.close)
        self._connect()

    def _connect(self) -> None:
        if self.pca is not None:
            return
        try:
            candidate = DirectLinuxPCA9685(self.bus, self.address, self.frequency)
            candidate.set_duty_cycle(self.steering_channel, self.center)
            candidate.set_duty_cycle(self.throttle_channel, self.stop_pwm)
            self.pca = candidate
            self.applied = (self.center, self.stop_pwm)
            self.error = ""
        except Exception as exc:
            self.pca = None
            self.error = f"PCA connect: {exc}"

    def _command(self, msg: ControlCommand) -> None:
        with self._lock:
            if msg.valid:
                steering = clamp_int(msg.steering_pwm, self.steer_low, self.steer_high)
                throttle = clamp_int(msg.throttle_pwm, self.throttle_low, self.throttle_high)
                self.requested = (steering, throttle)
                self.last_command = time.monotonic()
            else:
                self.requested = (self.center, self.stop_pwm)
                self.last_command = 0.0

    def _write(self, steering: int, throttle: int) -> None:
        if self.pca is None:
            self._connect()
        if self.pca is None:
            return
        try:
            self.pca.set_duty_cycle(self.steering_channel, steering)
            self.pca.set_duty_cycle(self.throttle_channel, throttle)
            self.applied = (steering, throttle)
            self.error = ""
        except Exception as exc:
            self.error = f"PCA write: {exc}"
            try:
                self.pca.close()
            except Exception:
                pass
            self.pca = None

    def spin(self) -> None:
        rate = rospy.Rate(50)
        while not rospy.is_shutdown():
            with self._lock:
                age = time.monotonic() - self.last_command if self.last_command else float("inf")
                requested = self.requested
            watchdog = age > self.timeout_s
            steering, throttle = (self.center, self.stop_pwm) if watchdog else requested
            self._write(steering, throttle)
            status = ActuatorStatus()
            status.header.stamp = rospy.Time.now()
            status.connected = self.pca is not None
            status.mock = False
            status.steering_pwm, status.throttle_pwm = self.applied
            status.command_age_s = age
            status.watchdog_safe = watchdog
            status.error = self.error
            self.status_pub.publish(status)
            rate.sleep()

    def close(self) -> None:
        try:
            self._write(self.center, self.stop_pwm)
        finally:
            if self.pca is not None:
                try:
                    self.pca.close()
                except Exception:
                    pass
                self.pca = None


if __name__ == "__main__":
    rospy.init_node("actuator_node")
    ActuatorNode().spin()
