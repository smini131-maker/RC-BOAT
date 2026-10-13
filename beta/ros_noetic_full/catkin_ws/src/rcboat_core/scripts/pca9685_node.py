#!/usr/bin/env python3
from __future__ import annotations

import threading
import time

import rospy
from rcboat_core.constants import VALUES
from rcboat_core.direct_i2c import DirectLinuxPCA9685
from rcboat_msgs.msg import PwmCommand
from std_msgs.msg import Bool


class PcaNode:
    def __init__(self) -> None:
        bus = int(rospy.get_param("~bus", 1))
        address = int(str(rospy.get_param("~address", "0x40")), 0)
        frequency = int(rospy.get_param("~frequency_hz", VALUES.pca_frequency_hz))
        self.watchdog_s = float(
            rospy.get_param("~watchdog_timeout_s", VALUES.pwm_watchdog_timeout_s)
        )
        self.driver = DirectLinuxPCA9685(bus, address, frequency)
        self.last_command_at = 0.0
        self.lock = threading.Lock()
        self.connected_pub = rospy.Publisher("/rcboat/pca_connected", Bool, queue_size=1, latch=True)
        self.connected_pub.publish(Bool(data=True))
        self._safe_write()
        rospy.Subscriber("/rcboat/pwm_command", PwmCommand, self.command_callback, queue_size=1)
        rospy.Timer(rospy.Duration(0.05), self.watchdog_callback)
        rospy.on_shutdown(self.close)

    def _write(self, steering: int, throttle: int) -> None:
        self.driver.set_duty_cycle(VALUES.steering_channel, steering)
        self.driver.set_duty_cycle(VALUES.throttle_channel, throttle)

    def _safe_write(self) -> None:
        self._write(VALUES.steering_center_pwm, VALUES.throttle_stop_pwm)

    def command_callback(self, message: PwmCommand) -> None:
        with self.lock:
            try:
                self._write(int(message.steering_pwm), int(message.throttle_pwm))
                self.last_command_at = time.monotonic()
            except Exception as exc:
                self.connected_pub.publish(Bool(data=False))
                rospy.logfatal("PCA9685 write failed: %s", exc)
                try:
                    self._safe_write()
                except Exception:
                    pass
                rospy.signal_shutdown("PCA9685 write failure")

    def watchdog_callback(self, _event) -> None:
        with self.lock:
            if time.monotonic() - self.last_command_at > self.watchdog_s:
                try:
                    self._safe_write()
                except Exception as exc:
                    rospy.logfatal("PCA9685 watchdog safe write failed: %s", exc)
                    rospy.signal_shutdown("PCA9685 watchdog failure")

    def close(self) -> None:
        with self.lock:
            try:
                self._safe_write()
            except Exception:
                pass
            self.driver.close()


if __name__ == "__main__":
    rospy.init_node("rcboat_pca9685")
    node = PcaNode()
    rospy.spin()
