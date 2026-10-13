#!/usr/bin/env python3
from __future__ import annotations

import threading
import time

import rospy
import serial

from rcboat_ros.msg import RcInput


class RcInputNode:
    def __init__(self) -> None:
        self.device = rospy.get_param(
            "/rcboat/hardware/arduino_device",
            "/dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00",
        )
        self.baudrate = int(rospy.get_param("/rcboat/hardware/arduino_baudrate", 9600))
        self.reconnect_s = float(rospy.get_param("/rcboat/hardware/reconnect_interval_s", 1.0))
        self.stale_s = float(rospy.get_param("/rcboat/safety/rc_stale_timeout_s", 0.7))
        self.publisher = rospy.Publisher("/rcboat/rc/input", RcInput, queue_size=10)
        self._lock = threading.Lock()
        self._port = None
        self._connected = False
        self._steering = 0
        self._throttle = 0
        self._last_update = 0.0
        self._error = "waiting for Arduino"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        rospy.on_shutdown(self.close)

    def _disconnect(self, error: str) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
        with self._lock:
            self._connected = False
            self._error = error

    def _read_loop(self) -> None:
        while not self._stop.is_set() and not rospy.is_shutdown():
            if self._port is None:
                try:
                    self._port = serial.Serial(self.device, self.baudrate, timeout=0.2)
                    with self._lock:
                        self._connected = True
                        self._error = ""
                except Exception as exc:
                    self._disconnect(f"Arduino connect: {exc}")
                    self._stop.wait(self.reconnect_s)
                    continue
            try:
                raw = self._port.readline().decode("utf-8", errors="ignore").strip()
                if not raw:
                    if self._last_update and time.monotonic() - self._last_update > self.stale_s:
                        raise TimeoutError("Arduino serial data became stale")
                    continue
                steering_s, throttle_s = raw.split(",", 1)
                steering, throttle = int(steering_s), int(throttle_s)
                if not (800 <= steering <= 2200 and 800 <= throttle <= 2200):
                    raise ValueError("out-of-range RC data")
                with self._lock:
                    self._steering = steering
                    self._throttle = throttle
                    self._last_update = time.monotonic()
                    self._connected = True
                    self._error = ""
            except Exception as exc:
                self._disconnect(f"Arduino read: {exc}")
                self._stop.wait(self.reconnect_s)

    def spin(self) -> None:
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            now = time.monotonic()
            with self._lock:
                msg = RcInput()
                msg.header.stamp = rospy.Time.now()
                msg.connected = self._connected and self._last_update > 0 and now - self._last_update <= self.stale_s
                msg.steering_us = self._steering
                msg.throttle_us = self._throttle
                msg.age_s = float(now - self._last_update) if self._last_update else float("inf")
                msg.error = self._error
            self.publisher.publish(msg)
            rate.sleep()

    def close(self) -> None:
        self._stop.set()
        self._disconnect("shutdown")
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)


if __name__ == "__main__":
    rospy.init_node("rc_input_node")
    RcInputNode().spin()
