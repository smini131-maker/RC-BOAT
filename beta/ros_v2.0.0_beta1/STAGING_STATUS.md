# RC BOAT ROS v2.0.0-beta.1 — staging branch

This branch preserves release/1.6.0 and is reserved for the independent ROS Noetic rewrite.

**Status:** The full working source ZIP is delivered separately in the ChatGPT conversation. It has NOT yet been committed to this branch. Do not treat this branch as a ready-to-deploy ROS release.

Safety gates to maintain before merging:
- Keep legacy `/home/jetson/rcboat` and `rcboat.service` intact.
- Prevent ROS/daemon simultaneous hardware ownership.
- Default ROS propulsion_allowed=false; GROUND_TEST must output 6000/6450.
- Require real Jetson/Windows/GPS/RTK/I2C field tests before stable release.

Use the provided `UPLOAD_GITHUB.cmd` from the source archive on Windows with Git authentication to commit its files into `beta/ros_v2.0.0_beta1/`.

Stable source reference: `release/1.6.0`, commit `cdee62b6169b8602723b12f0e921c15a54cbba86`.
