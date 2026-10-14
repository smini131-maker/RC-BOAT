#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SOURCE_DIR/.." && pwd)"
TARGET=/home/jetson/rcboat
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$TARGET/backups/full_install_$STAMP"

mkdir -p "$TARGET" "$BACKUP_DIR" "$TARGET/logs/gps"
if [[ -d "$TARGET/rcboat" ]]; then
  cp -a "$TARGET/rcboat" "$BACKUP_DIR/rcboat"
fi
for name in "boat_config.json" "routes.json"; do
  if [[ -f "$TARGET/$name" ]]; then cp -a "$TARGET/$name" "$BACKUP_DIR/$name"; fi
done

python3 -m venv --system-site-packages "$TARGET/.venv"
"$TARGET/.venv/bin/python" -m pip install -r "$SOURCE_DIR/requirements.txt"

# Preserve the verified live DirectLinuxPCA9685 hardware.py/pca_direct.py.
if [[ ! -f "$TARGET/rcboat/hardware.py" || ! -f "$TARGET/rcboat/pca_direct.py" ]]; then
  echo "DirectLinuxPCA9685 live driver is required; use jetson_patch/install_patch.sh after restoring it."
  exit 1
fi
for path in "$TARGET/rcboat/hardware.py" "$TARGET/rcboat/pca_direct.py"; do
  grep -q "DirectLinuxPCA9685" "$path" || true
done

for name in config.py controller.py navigation.py server.py gps_parser.py gps_health.py gps_logger.py gps_runtime.py ntrip.py; do
  cp -a "$PROJECT_ROOT/jetson_patch/rcboat/$name" "$TARGET/rcboat/$name"
done
cp -a "$SOURCE_DIR/rcboat_daemon.py" "$TARGET/rcboat_daemon.py"
if [[ ! -f "$TARGET/boat_config.json" ]]; then cp -a "$SOURCE_DIR/boat_config.json" "$TARGET/boat_config.json"; fi
if [[ ! -f "$TARGET/routes.json" ]]; then cp -a "$SOURCE_DIR/routes.json" "$TARGET/routes.json"; fi
if [[ ! -f "$TARGET/.ntrip.env" ]]; then
  cp -a "$PROJECT_ROOT/jetson_patch/ntrip.env.example" "$TARGET/.ntrip.env"
  chmod 600 "$TARGET/.ntrip.env"
fi
sudo cp -a "$SOURCE_DIR/rcboat.service" /etc/systemd/system/rcboat.service
sudo systemctl daemon-reload
sudo systemctl enable rcboat.service
echo "설치 완료. 상태 확인 후 아래 명령으로 수동 시작하세요."
echo "  sudo systemctl start rcboat.service"
