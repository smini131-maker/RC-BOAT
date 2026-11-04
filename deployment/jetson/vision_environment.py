#!/usr/bin/env python3
"""Isolate vision packages; share only named, existing Jetson camera/GPU bindings."""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import site
import subprocess
import sys
import venv

BINDINGS = ('cv2', 'tensorrt', 'pycuda', 'netifaces')
CUDA_HELPERS = ('pytools', 'decorator', 'appdirs', 'mako', 'markupsafe',
                'typing_extensions', 'platformdirs')


def inherits_host(cfg):
    values = dict(line.lower().split('=', 1) for line in cfg.read_text().splitlines() if '=' in line)
    return any(key.strip() == 'include-system-site-packages' and value.strip() == 'true'
               for key, value in values.items())


def inside(path, parent):
    try:
        return os.path.commonpath([str(Path(path).resolve()), str(Path(parent).resolve())]) == str(Path(parent).resolve())
    except ValueError:
        return False


def prepare(target):
    target = Path(target).absolute()
    if target.is_symlink():
        raise RuntimeError('Vision environment must be a directory, not a symlink: ' + str(target))
    cfg = target / 'pyvenv.cfg'
    if target.exists() and not cfg.is_file():
        raise RuntimeError('Refusing to replace an unrecognized directory: ' + str(target))
    if cfg.is_file() and inherits_host(cfg):
        # Preserve the old environment, including its packages. Never uninstall host packages.
        backup = target.with_name(target.name + '.backup-' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        target.rename(backup)
        print('Previous inherited environment preserved: ' + str(backup), flush=True)
    venv.EnvBuilder(system_site_packages=False, with_pip=True).create(str(target))
    print('Isolated vision environment: ' + str(target), flush=True)


def discover_bindings():
    # Use the base interpreter without PYTHONPATH or ~/.local. Finding specs does not
    # import cv2/NumPy, so a broken host NumPy ABI cannot hide the camera installation.
    names = BINDINGS + CUDA_HELPERS
    code = '''import importlib.util,json,sys
found={}
for name in json.loads(sys.argv[1]):
    spec=importlib.util.find_spec(name)
    if spec and spec.origin:
        found[name]={'origin':spec.origin,'package':list(spec.submodule_search_locations or [])}
print(json.dumps(found))
'''
    return json.loads(subprocess.check_output([sys.executable, '-I', '-c', code, json.dumps(names)], text=True))


def binding_plan(found):
    names = list(BINDINGS)
    if 'pycuda' in found:
        names.extend(CUDA_HELPERS)
    return {name: found[name] for name in names if name in found}


def link_bindings(target, found):
    target = Path(target).resolve()
    py = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python3')
    purelib = Path(subprocess.check_output([str(py), '-I', '-c',
        'import sysconfig;print(sysconfig.get_path("purelib"))'], text=True).strip())
    if not inside(purelib, target):
        raise RuntimeError('Vision site-packages is outside the virtual environment')
    plan = binding_plan(found)
    if 'cv2' not in plan:
        raise RuntimeError('System OpenCV not found. Install python3-opencv; do not install a pip OpenCV wheel.')
    linked = {}
    for name, spec in plan.items():
        source = Path(spec['package'][0]) if spec['package'] else Path(spec['origin'])
        if not source.exists():
            raise RuntimeError('Missing host binding: ' + str(source))
        dest = purelib / (name if spec['package'] else source.name)
        if dest.is_symlink():
            if dest.resolve() != source.resolve():
                dest.unlink()
            else:
                linked[name] = str(source)
                continue
        if dest.exists():
            if name in BINDINGS:
                raise RuntimeError('Unexpected local binding; refusing to overwrite: ' + str(dest))
            continue
        dest.symlink_to(source, target_is_directory=bool(spec['package']))
        linked[name] = str(source)
    (target / 'rcboat_bindings.json').write_text(json.dumps(linked, indent=2) + '\n', encoding='utf-8')
    print('Shared host bindings (no global package directory): ' + ', '.join(linked), flush=True)


def check(require_ros=False):
    prefix = Path(sys.prefix)
    cfg = prefix / 'pyvenv.cfg'
    if sys.prefix == sys.base_prefix or not cfg.is_file():
        raise RuntimeError('Run with ~/.rcboat/vision-venv/bin/python3')
    if site.ENABLE_USER_SITE or inherits_host(cfg):
        raise RuntimeError('Global/user packages are still inherited; rerun the vision installer')
    for entry in sys.path:
        # ROS workspace paths remain available through setup.bash, but whole host
        # site-packages/dist-packages must not leak in through PYTHONPATH either.
        if entry and Path(entry).name in ('site-packages', 'dist-packages') and not inside(entry, prefix):
            if '/opt/ros/' not in Path(entry).as_posix() and '/devel/' not in Path(entry).as_posix():
                raise RuntimeError('Unexpected global package directory in PYTHONPATH: ' + entry)
    import numpy as np
    import cv2
    import onnxruntime as ort
    for mod, expected in ((np, '1.23.5'), (ort, '1.16.3')):
        if mod.__version__ != expected or not inside(mod.__file__, prefix):
            raise RuntimeError('Unexpected vision package: %s %s at %s' % (mod.__name__, mod.__version__, mod.__file__))
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    if cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).shape != (8, 8):
        raise RuntimeError('OpenCV/NumPy array interoperability failed')
    if 'CPUExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('ONNX Runtime CPU provider unavailable')
    if importlib.util.find_spec('tensorflow') is not None:
        raise RuntimeError('TensorFlow is visible in the dedicated vision environment')
    if require_ros:
        import rospy
        from std_msgs.msg import String
        from rcboat_ros.srv import Execute
        from rosgraph.network import get_local_addresses
        get_local_addresses()  # Also exercise the host netifaces binding, without a ROS master.
    result = dict(python=sys.version.split()[0], executable=sys.executable, numpy=np.__version__,
                  numpy_path=np.__file__, opencv=cv2.__version__, opencv_path=cv2.__file__,
                  onnxruntime=ort.__version__, tensorflow_visible=False, ros_imports=require_ros,
                  gstreamer=next((line.strip() for line in cv2.getBuildInformation().splitlines()
                                  if 'GStreamer:' in line), 'GStreamer: unknown'))
    print(json.dumps(result, indent=2), flush=True)
    print('VISION_ENVIRONMENT_OK' + (' ROS_IMPORTS_OK' if require_ros else ''), flush=True)


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare', type=Path)
    modes.add_argument('--bridge', type=Path)
    modes.add_argument('--check', action='store_true')
    parser.add_argument('--ros', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        if not (3, 8) <= sys.version_info[:2] <= (3, 11):
            raise RuntimeError('This Nano vision environment requires Python 3.8 through 3.11')
        prepare(args.prepare)
    elif args.bridge:
        link_bindings(args.bridge, discover_bindings())
    else:
        check(args.ros)


if __name__ == '__main__':
    main()
