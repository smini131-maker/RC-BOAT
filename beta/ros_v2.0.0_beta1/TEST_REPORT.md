# RC BOAT ROS v2.0.0-beta.1 – Test Report

2026-10-13 소스 코드 패키지 검증 기록. 이 환경은 Ubuntu Linux 컨테이너이므로 Jetson Nano ROS/하드웨어와 Windows EXE 실기 검증 불가능. Sample trajectory는 synthetic fixture이며 실제 walking test 결과가 아님.

| 항목 | 검증 상태 |
| --- | --- |
| Python compile / pure unit tests | PASS: 15 Python unittest; compileall PASS |
| ROS Noetic catkin_make / roslaunch | UNTESTED (actual Jetson required) |
| rqt_graph | UNTESTED |
| GPS / UBX / NMEA / hAcc / F9R-F9P identification | Parser unit checks only; real device UNTESTED |
| NTRIP / actual RTK FLOAT-FIXED | UNTESTED |
| Arduino 9600 baud / live RC | UNTESTED |
| I2C/PCA register write / readback | UNTESTED |
| MANUAL / REMOTE / NAVIGATION / AUTO_SAFE | Source implementation, real integration UNTESTED |
| Ground mode two-stage software neutral interlock | Source reviewed + tests; physical motor UNTESTED |
| Path resampling and Multi-Path threshold | Pure unit tests; physical walking UNTESTED |
| GPS route persistence / timestamp/heading | Pure unit tests; ROS live persistence UNTESTED |
| MATLAB 3 plots | Script written; MATLAB runtime UNTESTED |
| QGIS CSV import | CSV schema generated; real QGIS GUI UNTESTED |
| Windows PySide6 and PyInstaller EXE | Source provided; Windows build UNTESTED |
| Revert ROS -> daemon | Transition script reviewed; actual systemd UNTESTED |
| Real low-speed water test | NOT AUTHORIZED by this report |

**Release gate:** Do not mark v2.0.0-beta.1 fully deployed or field-verified. Keep v1.6.0 default active until all stages pass.

## 2026-10-13 offline execution

`PYTHONPATH=catkin_ws/src/rcboat_ros/src python -m unittest discover -s tests -v` → **15 passed**. `python -m compileall -q` → PASS. Synthetic 220 samples @ 4 Hz, switch RIGHT→CENTER at t=34.50 s, hAcc fixture 0.05m, 4 exported graph PNG files. These are synthetic, not physical tests.
