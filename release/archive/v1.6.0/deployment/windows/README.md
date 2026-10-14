# Windows Jetson Deployment - v1.6.0

Run "01_DEPLOY_JETSON_v1.6.0.cmd".

This version fixes the long Downloads path failure where PowerShell Expand-Archive could fail while handling the GitHub ".github" directory.

- Work directory: %TEMP%\RCBoatDeploy_<GUID>
- Extraction: tar.exe first, .NET ZipFile fallback
- Expand-Archive is not used
- Source VERSION must be exactly 1.6.0
- Existing routes/config/Direct-I2C file hashes are checked
- Existing .ntrip.env is preserved
- Jetson telemetry version 1.6.0 is checked after install
- AUTO_SAFE steering 6000 / throttle 6450 is checked after install

Remove the propeller or disconnect propulsion power before running the launcher.
