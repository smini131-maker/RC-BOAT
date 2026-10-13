# New isolated ROS v2 source manifest

- catkin_ws/src/rcboat_ros: independent ROS1 Noetic nine-node package, custom `.msg`/`.srv`, configuration, route and actuator runtime.
- deployment/jetson: preflight, safe PWM readback, systemd backend collision prevention and rollback.
- deployment/windows: SSH/SCP Windows launchers, no automatic changes to old daemon source.
- systemd/rcboat_ros.service: conflict with legacy, beta disabled by installer.
- windows_gui/app.py: PySide6 GUI over SSH Unix-socket bridge; independent executable name.
- matlab/analyze_path_tracking.m and tools/analyze_csv.py: MATLAB primary graphs, optional PNG plots.
- tools/resample_route.py: non-destructive WGS84 route resampling.
- qgis/: EPSG:4326 CSV samples.
- samples/: synthetic ground-test fixture and four PNG plots, not real GPS experiments.
- tests/: offline logic, route switching, GPS UBX parser, CSV and safety static regression checks.
- GITHUB_STATUS.md: staging branch and push instructions.

No file in the original `release/1.6.0` branch is changed as part of archive creation.
