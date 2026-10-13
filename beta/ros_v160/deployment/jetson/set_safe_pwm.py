#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

workspace = Path("/home/jetson/rcboat_ros_ws")
sys.path.insert(0, str(workspace / "src" / "rcboat_ros" / "src"))

from rcboat_ros.pca_direct import DirectLinuxPCA9685


def main() -> int:
    pca = DirectLinuxPCA9685(1, 0x40, 60)
    try:
        pca.set_duty_cycle(0, 6000)
        pca.set_duty_cycle(6, 6450)
    finally:
        pca.close()
    print("SAFE PWM applied: steering=6000 throttle=6450")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
