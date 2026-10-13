# GitHub Upload Status

- Branch created: `beta/ros-v2.0.0-beta.1`, based on `release/1.6.0`.
- Staging status file is committed (`STAGING_STATUS.md`).
- **Source code from this ZIP has NOT yet been pushed to GitHub.** The connected GitHub API in this environment does not accept an entire container directory/archive as a source tree input.
- To upload after reviewing local files: install Git for Windows, authenticate, then execute `UPLOAD_GITHUB.cmd`. This uploads only to `beta/ros_v2.0.0_beta1/` on the isolated beta branch and adds the Windows EXE GitHub Actions workflow. No stable branch is rewritten.
- The GitHub workflow may build an EXE on Windows after upload. Its success must be verified from the Actions page; no finished EXE exists in this ZIP.
