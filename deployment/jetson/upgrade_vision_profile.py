#!/usr/bin/env python3
"""Migrate old camera profiles once; preserve user source/settings and a backup."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import validate_config


def upgrade(path):
    path = Path(path).expanduser()
    if not path.is_file():
        return False  # Fresh installs use the new YAML/defaults.
    before = json.loads(path.read_text(encoding='utf-8'))
    if 'long_range_enabled' in before:
        validate_config(before)
        return False  # Never overwrite a user decision after the migration.
    after = validate_config(dict(before, width=1920, height=1080, long_range_enabled=True))
    backup = path.with_name(path.name+'.before_v2.4.0_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    with backup.open('xb') as out:
        out.write(path.read_bytes())
    backup.chmod(0o600)
    temporary = path.with_suffix('.upgrade.tmp')
    temporary.write_text(json.dumps(after, indent=2), encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(str(temporary), str(path))
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path('~/.rcboat/vision.json'))
    args = parser.parse_args()
    print('VISION PROFILE: '+('migrated to native 1080p; previous file preserved' if upgrade(args.config) else 'current/default profile retained'))
