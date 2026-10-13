#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import rospy
from std_msgs.msg import Empty
from std_srvs.srv import Trigger, TriggerResponse

from rcboat_ros.msg import ActuatorStatus, BoatState, ControlCommand, RcInput
from rcboat_ros.ros_utils import clamp_int, piecewise_map
from rcboat_ros.srv import SetMode, SetModeResponse, SetPwm, SetPwmResponse


class SafetySupervisorNode:
    MODES = {"AUTO", "MANUAL", "NAVIGATION", "REMOTE"}

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.hil = bool(rospy.get_param("~hil", False))
        self.mode = "AUTO"
        self.operation = "AUTO_SAFE"
        self.estop = False
        self.failsafe = "BOOT_SAFE"
        self.manual_waiting = False
        self.auto_to_manual_armed = False
        self.gesture_since = None
        self.manual_neutral_since = None
        self.remote_last_heartbeat = 0.0
        self.rc = None
        self.nav = None
        self.nav_received = 0.0
        self.remote = None
        self.actuator = None
        self.center = int(rospy.get_param("/rcboat/hardware/steering_center_pwm", 6000))
        self.stop_pwm = int(rospy.get_param("/rcboat/hardware/throttle_stop_pwm", 6450))
        self.steer_low_pwm = int(rospy.get_param("/rcboat/hardware/steering_low_pwm", 4900))
        self.steer_high_pwm = int(rospy.get_param("/rcboat/hardware/steering_high_pwm", 7300))
        self.throttle_reverse_pwm = int(rospy.get_param("/rcboat/hardware/throttle_reverse_pwm", 5800))
        self.throttle_forward_pwm = int(rospy.get_param("/rcboat/hardware/throttle_forward_pwm", 7000))
        self.steer_low_us = int(rospy.get_param("/rcboat/safety/steering_low_us", 1214))
        self.steer_center_us = int(rospy.get_param("/rcboat/safety/steering_center_us", 1640))
        self.steer_high_us = int(rospy.get_param("/rcboat/safety/steering_high_us", 2000))
        self.throttle_reverse_us = int(rospy.get_param("/rcboat/safety/throttle_reverse_us", 1106))
        self.throttle_center_us = int(rospy.get_param("/rcboat/safety/throttle_center_us", 1500))
        self.throttle_forward_us = int(rospy.get_param("/rcboat/safety/throttle_forward_us", 1786))
        self.rc_stale_s = float(rospy.get_param("/rcboat/safety/rc_stale_timeout_s", 0.7))
        self.remote_timeout_s = float(rospy.get_param("/rcboat/safety/remote_heartbeat_timeout_s", 0.7))
        self.nav_timeout_s = float(rospy.get_param("/rcboat/safety/navigation_command_timeout_s", 0.5))
        self.manual_to_auto_steering_us = int(rospy.get_param("/rcboat/safety/manual_to_auto_steering_us", 1950))
        self.manual_to_auto_neutral_tolerance_us = int(rospy.get_param("/rcboat/safety/manual_to_auto_neutral_tolerance_us", 30))
        self.manual_to_auto_hold_s = float(rospy.get_param("/rcboat/safety/manual_to_auto_hold_s", 3.0))
        self.auto_to_manual_throttle_us = int(rospy.get_param("/rcboat/safety/auto_to_manual_throttle_us", 1850))
        self.auto_to_manual_hold_s = float(rospy.get_param("/rcboat/safety/auto_to_manual_hold_s", 0.5))
        self.manual_rearm_hold_s = float(rospy.get_param("/rcboat/safety/manual_rearm_hold_s", 0.3))
        self.runtime = Path(rospy.get_param("/rcboat/runtime_dir", "/home/jetson/rcboat_ros_ws/runtime"))
        self.cruise_path = self.runtime / "safety_settings.json"
        self.auto_cruise = self._load_cruise()
        self.command_pub = rospy.Publisher("/rcboat/safety/actuator_command", ControlCommand, queue_size=10)
        self.state_pub = rospy.Publisher("/rcboat/safety/state", BoatState, queue_size=10, latch=True)
        rospy.Subscriber("/rcboat/rc/input", RcInput, self._rc_cb, queue_size=10)
        rospy.Subscriber("/rcboat/navigation/command", ControlCommand, self._nav_cb, queue_size=10)
        rospy.Subscriber("/rcboat/remote/command", ControlCommand, self._remote_cb, queue_size=10)
        rospy.Subscriber("/rcboat/remote/heartbeat", Empty, self._heartbeat_cb, queue_size=10)
        rospy.Subscriber("/rcboat/actuator/status", ActuatorStatus, self._actuator_cb, queue_size=10)
        rospy.Service("/rcboat/set_mode", SetMode, self._set_mode_srv)
        rospy.Service("/rcboat/set_auto_cruise", SetPwm, self._set_cruise_srv)
        rospy.Service("/rcboat/emergency_stop", Trigger, self._estop_srv)
        rospy.Service("/rcboat/clear_estop", Trigger, self._clear_estop_srv)
        rospy.Service("/rcboat/safety/force_safe", Trigger, self._force_safe_srv)
        rospy.on_shutdown(self._shutdown)

    def _load_cruise(self) -> int:
        default = int(rospy.get_param("/rcboat/safety/auto_cruise_pwm", 6650))
        try:
            value = int(json.loads(self.cruise_path.read_text(encoding="utf-8"))["auto_cruise_pwm"])
        except (OSError, ValueError, TypeError, KeyError):
            value = default
        return clamp_int(value, int(rospy.get_param("/rcboat/safety/auto_cruise_min_pwm", 6480)), int(rospy.get_param("/rcboat/safety/auto_cruise_max_pwm", 6900)))

    def _save_cruise(self) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        tmp = self.cruise_path.with_name(f".{self.cruise_path.name}.tmp")
        tmp.write_text(json.dumps({"auto_cruise_pwm": self.auto_cruise}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.cruise_path)

    def _rc_cb(self, msg):
        with self._lock: self.rc = msg

    def _nav_cb(self, msg):
        with self._lock:
            self.nav = msg
            self.nav_received = time.monotonic()

    def _remote_cb(self, msg):
        with self._lock: self.remote = msg

    def _heartbeat_cb(self, _msg):
        with self._lock: self.remote_last_heartbeat = time.monotonic()

    def _actuator_cb(self, msg):
        with self._lock: self.actuator = msg

    def _rc_ready(self) -> bool:
        return bool(self.rc and self.rc.connected and self.rc.age_s <= self.rc_stale_s)

    def _return_safe(self, reason: str) -> None:
        self.mode = "AUTO"
        self.operation = "AUTO_SAFE"
        self.failsafe = reason
        self.manual_waiting = False
        self.manual_neutral_since = None
        self.gesture_since = None
        self.auto_to_manual_armed = False

    def _set_mode(self, requested: str) -> None:
        mode = requested.upper().replace("-SAFE", "")
        if mode not in self.MODES:
            raise ValueError(f"invalid mode: {requested}")
        if self.estop:
            raise RuntimeError("Emergency Stop is latched")
        if mode == "MANUAL" and not self._rc_ready():
            self._return_safe("ARDUINO_OR_RC_UNAVAILABLE")
            raise RuntimeError("Arduino/RC data is unavailable")
        self.mode = mode
        self.failsafe = ""
        self.gesture_since = None
        if mode == "MANUAL":
            self.manual_waiting = True
            self.manual_neutral_since = None
            self.operation = "MANUAL_WAITING_NEUTRAL"
        elif mode == "REMOTE":
            self.manual_waiting = False
            self.remote_last_heartbeat = time.monotonic()
            self.remote = None
            self.operation = "REMOTE_ACTIVE"
        elif mode == "NAVIGATION":
            self.manual_waiting = False
            self.operation = "NAVIGATION_WAITING_GPS"
        else:
            self.manual_waiting = False
            self.operation = "AUTO"
        self.auto_to_manual_armed = bool(self.rc and self.rc.throttle_us < self.auto_to_manual_throttle_us)

    def _set_mode_srv(self, req):
        try:
            with self._lock: self._set_mode(req.mode)
            return SetModeResponse(True, f"mode={self.mode}")
        except Exception as exc:
            return SetModeResponse(False, str(exc))

    def _set_cruise_srv(self, req):
        low = int(rospy.get_param("/rcboat/safety/auto_cruise_min_pwm", 6480))
        high = int(rospy.get_param("/rcboat/safety/auto_cruise_max_pwm", 6900))
        if not low <= req.value <= high:
            return SetPwmResponse(False, f"value must be {low}..{high}")
        with self._lock:
            self.auto_cruise = int(req.value)
            self._save_cruise()
        return SetPwmResponse(True, "AUTO cruise saved")

    def _estop_srv(self, _req):
        with self._lock:
            self.estop = True
            self._return_safe("EMERGENCY_STOP")
            self.operation = "EMERGENCY_STOP"
        return TriggerResponse(True, "E-STOP latched")

    def _clear_estop_srv(self, _req):
        with self._lock:
            self.estop = False
            self._return_safe("ESTOP_CLEARED")
        return TriggerResponse(True, "E-STOP cleared; safe output remains")

    def _force_safe_srv(self, _req):
        with self._lock: self._return_safe("FORCE_SAFE")
        self._publish_safe_burst()
        return TriggerResponse(True, "safe output requested")

    def _check_gesture(self, now: float) -> None:
        if not self._rc_ready():
            self.gesture_since = None
            return
        if self.mode == "MANUAL":
            active = self.rc.steering_us >= self.manual_to_auto_steering_us and abs(self.rc.throttle_us - self.throttle_center_us) <= self.manual_to_auto_neutral_tolerance_us
            if active:
                self.gesture_since = self.gesture_since or now
                if now - self.gesture_since >= self.manual_to_auto_hold_s:
                    self._set_mode("AUTO")
            else:
                self.gesture_since = None
        elif self.mode in {"AUTO", "NAVIGATION"}:
            if not self.auto_to_manual_armed:
                if self.rc.throttle_us < self.auto_to_manual_throttle_us:
                    self.auto_to_manual_armed = True
                return
            if self.rc.throttle_us >= self.auto_to_manual_throttle_us:
                self.gesture_since = self.gesture_since or now
                if now - self.gesture_since >= self.auto_to_manual_hold_s:
                    self._set_mode("MANUAL")
            else:
                self.gesture_since = None

    def _manual_command(self, now: float) -> tuple[int, int]:
        if self.manual_waiting:
            neutral = abs(self.rc.throttle_us - self.throttle_center_us) <= self.manual_to_auto_neutral_tolerance_us
            if neutral:
                self.manual_neutral_since = self.manual_neutral_since or now
                if now - self.manual_neutral_since >= self.manual_rearm_hold_s:
                    self.manual_waiting = False
                    self.operation = "MANUAL_ACTIVE"
            else:
                self.manual_neutral_since = None
            return self.center, self.stop_pwm
        steering = piecewise_map(self.rc.steering_us, self.steer_low_us, self.steer_center_us, self.steer_high_us, self.steer_low_pwm, self.center, self.steer_high_pwm)
        throttle = piecewise_map(self.rc.throttle_us, self.throttle_reverse_us, self.throttle_center_us, self.throttle_forward_us, self.throttle_reverse_pwm, self.stop_pwm, self.throttle_forward_pwm)
        self.operation = "MANUAL_ACTIVE"
        return steering, throttle

    def _decide(self) -> ControlCommand:
        now = time.monotonic()
        self._check_gesture(now)
        steering, throttle, source, valid = self.center, self.stop_pwm, "AUTO_SAFE", True
        if self.estop:
            self.operation = "EMERGENCY_STOP"
            source = "E_STOP"
        elif self.actuator is not None and not self.actuator.connected and not self.actuator.mock:
            self.operation = "AUTO_SAFE"
            self.failsafe = "ACTUATOR_UNAVAILABLE"
            source = "ACTUATOR_FAULT"
        elif self.mode == "MANUAL":
            if not self._rc_ready():
                self.operation = "MANUAL_WAITING_RC"
                self.failsafe = "ARDUINO_OR_RC_LOST"
                source = "RC_FAULT"
            else:
                steering, throttle = self._manual_command(now)
                self.failsafe = ""
                source = "MANUAL"
        elif self.mode == "REMOTE":
            if now - self.remote_last_heartbeat >= self.remote_timeout_s:
                self._return_safe("REMOTE_HEARTBEAT_TIMEOUT")
            elif self.remote is None or not self.remote.valid:
                self.operation = "REMOTE_WAITING_COMMAND"
                source = "REMOTE_WAIT"
            else:
                steering = clamp_int(self.remote.steering_pwm, self.steer_low_pwm, self.steer_high_pwm)
                throttle = clamp_int(self.remote.throttle_pwm, min(self.throttle_reverse_pwm, self.throttle_forward_pwm), max(self.throttle_reverse_pwm, self.throttle_forward_pwm))
                self.operation = "REMOTE_ACTIVE"
                self.failsafe = ""
                source = "REMOTE"
        elif self.mode == "NAVIGATION":
            if self.nav is None or now - self.nav_received > self.nav_timeout_s or not self.nav.valid:
                self.operation = "NAVIGATION_WAITING_GPS"
                self.failsafe = "NAVIGATION_COMMAND_TIMEOUT" if self.nav is not None else "NAVIGATION_UNAVAILABLE"
                source = "NAVIGATION_SAFE"
            else:
                steering = clamp_int(self.nav.steering_pwm, self.steer_low_pwm, self.steer_high_pwm)
                throttle = clamp_int(self.nav.throttle_pwm, min(self.throttle_reverse_pwm, self.throttle_forward_pwm), max(self.throttle_reverse_pwm, self.throttle_forward_pwm))
                self.operation = "HIL_ACTIVE" if self.hil else "NAVIGATION_ACTIVE"
                self.failsafe = ""
                source = "HIL" if self.hil else "NAVIGATION"
        else:
            if self.failsafe:
                self.operation = "AUTO_SAFE"
            elif not self._rc_ready():
                self.operation = "AUTO_SAFE"
                self.failsafe = "ARDUINO_OR_RC_LOST"
                source = "AUTO_SAFE"
            else:
                steering, throttle = self.center, self.auto_cruise
                self.operation = "AUTO_ACTIVE"
                source = "AUTO"
        cmd = ControlCommand()
        cmd.header.stamp = rospy.Time.now()
        cmd.steering_pwm = steering
        cmd.throttle_pwm = throttle
        cmd.source = source
        cmd.valid = valid
        return cmd

    def _state(self) -> BoatState:
        msg = BoatState()
        msg.header.stamp = rospy.Time.now()
        msg.mode = self.mode
        msg.operation_state = self.operation
        msg.estop = self.estop
        msg.failsafe_reason = self.failsafe
        msg.manual_waiting_for_neutral = self.manual_waiting
        msg.auto_to_manual_gesture_armed = self.auto_to_manual_armed
        msg.auto_cruise_pwm = self.auto_cruise
        msg.hil = self.hil
        return msg

    def spin(self) -> None:
        rate = rospy.Rate(50)
        while not rospy.is_shutdown():
            with self._lock:
                cmd = self._decide()
                state = self._state()
            self.command_pub.publish(cmd)
            self.state_pub.publish(state)
            rate.sleep()

    def _publish_safe_burst(self) -> None:
        msg = ControlCommand()
        msg.header.stamp = rospy.Time.now()
        msg.steering_pwm = self.center
        msg.throttle_pwm = self.stop_pwm
        msg.source = "SHUTDOWN_SAFE"
        msg.valid = True
        for _ in range(3):
            self.command_pub.publish(msg)
            time.sleep(0.02)

    def _shutdown(self) -> None:
        with self._lock: self._return_safe("SUPERVISOR_SHUTDOWN")
        self._publish_safe_burst()


if __name__ == "__main__":
    rospy.init_node("safety_supervisor_node")
    SafetySupervisorNode().spin()
