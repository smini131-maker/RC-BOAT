#!/usr/bin/env python3
from __future__ import annotations

import time

import rospy
import serial
from rcboat_msgs.msg import RcInput


class ArduinoNode:
    def __init__(self) -> None:
        self.port = rospy.get_param("~port")
        self.baudrate = int(rospy.get_param("~baudrate", 9600))
        self.reconnect_s = float(rospy.get_param("~reconnect_s", 1.0))
        self.publisher = rospy.Publisher("/rcboat/rc_input", RcInput, queue_size=10)
        self.serial = None
        self.last_connect_attempt = 0.0
        rospy.on_shutdown(self.close)

    def close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            except serial.SerialException:
                pass
            self.serial = None

    def _connect(self) -> None:
        now = time.monotonic()
        if now - self.last_connect_attempt < self.reconnect_s:
            return
        self.last_connect_attempt = now
        try:
            self.serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=0.1,
                exclusive=True,
            )
            rospy.loginfo("Arduino connected: %s", self.port)
        except (OSError, serial.SerialException) as exc:
            self.serial = None
            rospy.logwarn_throttle(5.0, "Arduino unavailable: %s", exc)

    def run(self) -> None:
        rate = rospy.Rate(100)
        while not rospy.is_shutdown():
            if self.serial is None:
                self._connect()
                self._publish_disconnected("serial unavailable")
                rate.sleep()
                continue
            try:
                raw = self.serial.readline().decode("ascii", errors="strict").strip()
                if not raw:
                    rate.sleep()
                    continue
                fields = raw.split(",")
                if len(fields) < 2:
                    raise ValueError("expected steering,throttle")
                steering = int(fields[0])
                throttle = int(fields[1])
                if not 800 <= steering <= 2200 or not 800 <= throttle <= 2200:
                    raise ValueError("RC pulse outside 800..2200 us")
                message = RcInput()
                message.header.stamp = rospy.Time.now()
                message.connected = True
                message.steering_us = steering
                message.throttle_us = throttle
                self.publisher.publish(message)
            except (OSError, serial.SerialException, UnicodeDecodeError) as exc:
                rospy.logerr("Arduino connection lost: %s", exc)
                self.close()
                self._publish_disconnected(str(exc))
            except ValueError as exc:
                rospy.logwarn_throttle(2.0, "Arduino line rejected: %s", exc)
            rate.sleep()

    def _publish_disconnected(self, error: str) -> None:
        message = RcInput()
        message.header.stamp = rospy.Time.now()
        message.connected = False
        message.error = error
        self.publisher.publish(message)


if __name__ == "__main__":
    rospy.init_node("rcboat_arduino")
    ArduinoNode().run()
