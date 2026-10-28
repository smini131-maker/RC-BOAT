#!/usr/bin/env python3
"""Verify deployed files and the running gateway, without issuing control commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
TEXT = {'.py', '.sh', '.service', '.launch', '.yaml', '.xml', '.msg', '.srv', '.json', '.txt'}


def file_hash(path):
    data = path.read_bytes()
    if path.suffix in TEXT or path.name in ('VERSION', 'CMakeLists.txt'):
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def verify_sources(root=ROOT):
    manifest = json.loads((root / 'deployment_manifest.json').read_text(encoding='utf-8-sig'))
    version = (root / 'VERSION').read_text(encoding='utf-8-sig').strip()
    package = ET.parse(root / 'catkin_ws/src/rcboat_ros/package.xml').getroot().findtext('version')
    if manifest['version'] != version or package != version:
        raise RuntimeError('VERSION/package.xml/deployment manifest version mismatch')
    if not manifest.get('files'):
        raise RuntimeError('empty deployment manifest')
    for name, expected in manifest['files'].items():
        path = root / name
        if os.path.commonpath([str(path.resolve()), str(root.resolve())]) != str(root.resolve()):
            raise RuntimeError('manifest path outside workspace')
        if not path.is_file() or file_hash(path) != expected:
            raise RuntimeError('deployment file missing or hash mismatch: ' + name)
    return version, manifest


def assert_idle(port=8765):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError as exc:
            raise RuntimeError('Port %d still in use: close the old roslaunch terminal with Ctrl+C, then run the installer again' % port) from exc
    # A hand-launched old node may own PCA even after its gateway has exited.
    proc = Path('/proc')
    for folder in proc.glob('[0-9]*'):
        try:
            if folder.stat().st_uid != os.getuid():
                continue
            args = (folder / 'cmdline').read_bytes().split(b'\0')
            if any(b'/rcboat_ros_ws/' in arg and
                   (b'/rcboat_ros/nodes/' in arg or b'/devel/lib/rcboat_ros/' in arg) for arg in args):
                raise RuntimeError('Old ROS node PID %s is still running; close its roslaunch terminal before installing' % folder.name)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue


def clean_build(root=ROOT):
    workspace = root / 'catkin_ws'
    for name in ('build', 'devel'):
        path = workspace / name
        if path.is_symlink() or path.resolve().parent != workspace.resolve():
            raise RuntimeError('unsafe generated build path: ' + str(path))
        if path.exists():
            shutil.rmtree(str(path))


def read_status(host='127.0.0.1', port=8765, token=''):
    payload = {'action': 'status', 'arguments': {}}
    if token:
        payload['token'] = token
    with socket.create_connection((host, port), timeout=2) as sock:
        sock.settimeout(3)
        sock.sendall((json.dumps(payload) + '\n').encode())
        data = b''
        while not data.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 8_000_000:
                raise RuntimeError('unexpectedly large gateway status')
    result = json.loads(data)
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'gateway status failed')
    return result


def verify_runtime(result, version, manifest, root=ROOT):
    identity = result.get('runtime_identity') or {}
    source_name = 'catkin_ws/src/rcboat_ros/nodes/gui_bridge_node.py'
    if result.get('version') != version:
        raise RuntimeError('RUNNING gateway v%s, expected v%s' % (result.get('version'), version))
    if Path(identity.get('source', '')).resolve() != (root / source_name).resolve():
        raise RuntimeError('gateway is running from a different workspace')
    if identity.get('source_sha256') != manifest['files'][source_name]:
        raise RuntimeError('running gateway source hash mismatch; old process still loaded')
    for name in ('gps', 'ntrip', 'safety'):
        state = (result.get('telemetry') or {}).get(name) or {}
        if state.get('software_version') != version:
            raise RuntimeError('%s node runtime version is %s; expected %s' %
                               (name,state.get('software_version') or 'unavailable',version))
    if not result.get('master_online'):
        raise RuntimeError('ROS master offline')
    return identity


def local_token():
    token = os.getenv('RCBOAT_GATEWAY_TOKEN', '')
    path = Path.home() / 'rcboat_ros_data/ntrip.env'
    if not token and path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('RCBOAT_GATEWAY_TOKEN='):
                value = line.split('=', 1)[1].strip()
                try: token = json.loads(value)
                except ValueError: token = value.strip('"\'')
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources-only', action='store_true')
    parser.add_argument('--idle', action='store_true')
    parser.add_argument('--clean-build', action='store_true')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    version, manifest = verify_sources()
    print('DEPLOYED FILES VERIFIED: v%s / %d hashes' % (version, len(manifest['files'])))
    if args.idle:
        assert_idle()
    if args.clean_build:
        clean_build()
    if args.sources_only:
        return
    deadline = time.monotonic() + args.timeout
    error = 'no response'
    while time.monotonic() < deadline:
        try:
            result = read_status(token=local_token())
            identity = verify_runtime(result, version, manifest)
            print('RUNNING GATEWAY VERIFIED: v%s / %s / started %s' %
                  (version, identity['source'], identity.get('started_at_utc')))
            return
        except (OSError, ValueError, RuntimeError) as exc:
            error = str(exc)
            time.sleep(.5)
    raise RuntimeError('RELEASE VERIFICATION FAILED: ' + error)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('ERROR: ' + str(exc))
        raise SystemExit(1)
