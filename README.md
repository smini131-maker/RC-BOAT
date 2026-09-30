# RC-BOAT

Adventure Design RC Boat project restore package.

This repository contains the RC Boat Multi-Path R11 restore package prepared on 2026-09-30.

## Contents

- `jetson_patch/`: Jetson backend patch for current RC Boat deployment
- `windows_gui_source/`: Windows PySide6 GUI source and build script
- `tests/`: regression tests used for the restore package
- `README_먼저읽기.md`: Korean installation notes
- `GITHUB_UPLOAD_NOTE.md`: GitHub upload and safety notes

## Important Safety Notes

- Do not overwrite Jetson `hardware.py` or `pca_direct.py` with old Blinka versions.
- Do not install `Jetson.GPIO` or switch back to `import board`/Blinka control.
- The Jetson patch intentionally avoids overwriting `boat_config.json` and `routes.json`.
- Keep the Direct-I2C PCA9685 setup that uses `/dev/i2c-1`.

## Jetson Apply

Copy `jetson_patch` to the Jetson and run:

```bash
cd /home/jetson/jetson_patch
chmod +x install_patch.sh
./install_patch.sh
```

## Windows GUI Build

On Windows:

```bat
BUILD_WINDOWS_EXE.bat
```

