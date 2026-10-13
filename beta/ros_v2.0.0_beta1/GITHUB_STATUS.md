# GitHub Upload & Windows EXE — Complete

- Beta branch: https://github.com/smini131-maker/RC-BOAT/tree/beta/ros-v2.0.0-beta.1
- Source path: `beta/ros_v2.0.0_beta1/`
- Extracted source: 93 text/code/config/test/manual files (PDF and PNG samples remain in the separately supplied chat ZIP).
- Existing stable branch `release/1.6.0` is unchanged at `cdee62b6169b8602723b12f0e921c15a54cbba86`.
- Latest successful GitHub Actions Windows build: https://github.com/smini131-maker/RC-BOAT/actions/runs/38413477441
- Executable artifact: `RCBoatControl_ROS_v2.0.0-beta.1_Windows_x64` (EXE + SHA256SUMS.txt).
- Result: Python regression tests passed (26), Qt headless GUI smoke test passed, PyInstaller Windows x64 build passed, bundled EXE smoke test passed, artifact uploaded.
- The build runner is Windows; **Jetson Nano ROS hardware, RTCM/RTK, real GPS walk, PCA9685 actuator isolation, and vessel navigation were not tested**.

## Download the Windows build
1. Open the successful Actions run linked above while signed in to GitHub.
2. Under **Artifacts**, download `RCBoatControl_ROS_v2.0.0-beta.1_Windows_x64`.
3. Unzip and verify `SHA256SUMS.txt` if needed.
4. Launch `RCBoatControl_ROS_v2.0.0-beta.1.exe`.

## Safety
ROS and the existing daemon must never own Arduino, GPS, or I2C simultaneously. Until Jetson field checks complete, keep `rcboat.service` as the boot-default and `propulsion_allowed=false` in ROS beta.
