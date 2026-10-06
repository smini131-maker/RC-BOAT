#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/jetson/rcboat
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$PROJECT/backups/week6_gps_$STAMP"
FILES=(config.py controller.py navigation.py server.py gps_parser.py gps_health.py gps_logger.py ntrip.py gps_runtime.py)

if [[ ! -f "$PROJECT/rcboat/hardware.py" || ! -f "$PROJECT/rcboat/pca_direct.py" ]]; then
  echo "중단: Direct-I2C hardware.py/pca_direct.py가 없습니다. 먼저 R15.1 정상 드라이버를 복구하세요."
  exit 1
fi
if grep -Eq '^[[:space:]]*import board|Jetson\.GPIO|adafruit_blinka' "$PROJECT/rcboat/hardware.py"; then
  echo "중단: 현재 hardware.py가 Blinka/Jetson.GPIO 버전입니다. 이 패치는 하드웨어 드라이버를 덮지 않습니다."
  exit 1
fi
if ! grep -q 'DirectLinuxPCA9685' "$PROJECT/rcboat/hardware.py"; then
  echo "중단: 현재 hardware.py에서 DirectLinuxPCA9685를 확인하지 못했습니다."
  exit 1
fi

"$PROJECT/.venv/bin/python" -m pip install -r "$PATCH_DIR/requirements-week6.txt"
python3 -m py_compile "$PATCH_DIR/rcboat/"*.py

sudo systemctl stop rcboat.service
sudo systemctl reset-failed rcboat.service || true
mkdir -p "$BACKUP/rcboat" "$PROJECT/logs/gps"
for name in "${FILES[@]}"; do
  if [[ -f "$PROJECT/rcboat/$name" ]]; then
    cp -a "$PROJECT/rcboat/$name" "$BACKUP/rcboat/$name"
  fi
done
cp -a "$PROJECT/boat_config.json" "$BACKUP/boat_config.json"
cp -a "$PROJECT/routes.json" "$BACKUP/routes.json"

if [[ ! -f "$PROJECT/.ntrip.env" ]]; then
  cp -a "$PATCH_DIR/ntrip.env.example" "$PROJECT/.ntrip.env"
  chmod 600 "$PROJECT/.ntrip.env"
fi

for name in "${FILES[@]}"; do
  cp -a "$PATCH_DIR/rcboat/$name" "$PROJECT/rcboat/$name"
done

if ! "$PROJECT/.venv/bin/python" -m py_compile "$PROJECT/rcboat/"*.py; then
  echo "문법 검사 실패: 백업을 복원합니다."
  for name in "${FILES[@]}"; do
    if [[ -f "$BACKUP/rcboat/$name" ]]; then
      cp -a "$BACKUP/rcboat/$name" "$PROJECT/rcboat/$name"
    else
      rm -f "$PROJECT/rcboat/$name"
    fi
  done
  sudo systemctl reset-failed rcboat.service || true
  sudo systemctl start rcboat.service || true
  exit 1
fi

sudo systemctl start rcboat.service
sleep 3
if ! systemctl is-active --quiet rcboat.service; then
  echo "서비스 시작 실패: 백업을 복원합니다."
  sudo systemctl stop rcboat.service || true
  for name in "${FILES[@]}"; do
    if [[ -f "$BACKUP/rcboat/$name" ]]; then
      cp -a "$BACKUP/rcboat/$name" "$PROJECT/rcboat/$name"
    else
      rm -f "$PROJECT/rcboat/$name"
    fi
  done
  sudo systemctl reset-failed rcboat.service || true
  sudo systemctl start rcboat.service || true
  sudo systemctl --no-pager --full status rcboat.service || true
  exit 1
fi

echo "적용 완료. 백업: $BACKUP"
systemctl --no-pager --full status rcboat.service
echo
echo "최근 로그:"
sudo journalctl -u rcboat.service -n 30 --no-pager
