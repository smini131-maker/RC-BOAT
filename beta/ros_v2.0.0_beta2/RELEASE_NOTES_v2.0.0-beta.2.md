# RC BOAT ROS v2.0.0-beta.2 (prerelease)

This is the next **prerelease of v2.0.0**, not v2.1.0 and not a stable release.
Stable `release/1.6.0` and prior `beta/ros-v2.0.0-beta.1` remain unchanged.

## Changes
- HEAD/waypoint steering mode `HEADING` remains the default and uses the existing v1.6.0 heading-error cruise bands.
- New **experimental, ground-first** modes: `HEADING_CTE` (bounded cross-track correction), `LOS` (segment tangent and CTE), and `PURE_PURSUIT` (dynamic ahead waypoint bearing, not an Ackermann curvature controller).
- Ground Test GUI algorithm selector, `/rcboat/navigation/execute` service, closest compatible route selection.
- GNSS speed-adaptive lookahead, optional bounded PWM speed feedback **off by default**.
- New CSV diagnostics: `controller_mode`, `lookahead_m`, `cte_correction_deg` and selected lookahead target.
- Default `propulsion_allowed=false` and `experimental_nav_actuation_enabled=false`; experimental controllers are **locked out from physical NAVIGATION** until separate validation.
- Same multi-path thresholds, waypoint recording format, and protected legacy daemon as prior beta.
- All video MATLAB, QGIS and GPS Ground Test instructions are in VIDEO_TEST_STEPS_KO.md.

Offline tests are not physical safety certification. No verified Jetson, I2C, actual GNSS walking test, MATLAB/QGIS GUI run or water-driving trial is claimed.

- GNSS course quality: LOW_SPEED / MOVING_COG / LOW_POSITION_QUALITY logged for ground testing (default 0.35 m/s threshold). The quality flag is diagnostic and does not claim true hull heading.

### Windows scripts patch (2026-10-14, still v2.0.0-beta.2)
- CHECK_WINDOWS no longer echoes localized `where git.exe` errors or UTF-8 Korean paths in legacy CMD.
- Supports local Python 3.11/3.12/3.13 x64. Git is optional except for GitHub direct upload.
- All nine Windows root scripts normalize the trailing backslash when passing -Root to PowerShell.
- Native Python -c quoting on Windows PowerShell 5.1, function output merging, and Get-FileHash fallback were corrected.
- GitHub Actions tests actual CMD in normal and Korean/space folders, Python 3.13 local PyInstaller EXE build and runtime smoke.
- No change to legacy release/1.6.0, ROS actuator unlocks, or ROS beta2 vehicle-control semantics.
