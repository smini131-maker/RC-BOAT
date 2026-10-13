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
