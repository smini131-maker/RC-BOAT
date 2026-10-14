#!/usr/bin/env python3
"""Make SCP-transferred ROS source safe for Linux Bash and roslaunch.
Only changes the dedicated /home/jetson/rcboat_ros_ws workspace.
Invoke via python3, not the shebang, to tolerate initial CRLF.
"""
from pathlib import Path
import stat
import sys

ROOT = Path('/home/jetson/rcboat_ros_ws')
SAFE_DIRS = ('deployment/jetson', 'catkin_ws/src', 'systemd')
EXTENSIONS = {'.sh', '.py', '.service', '.launch', '.yaml', '.xml', '.msg', '.srv', '.json'}

def normalize(root=ROOT):
    if not root.is_dir():
        raise RuntimeError('Isolated ROS workspace missing: '+str(root))
    changed = 0
    inspected = 0
    for rel in SAFE_DIRS:
        base = root / rel
        if not base.is_dir():
            raise RuntimeError('Required directory missing: '+str(base))
        for path in base.rglob('*'):
            if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts:
                continue
            if path.suffix not in EXTENSIONS and path.name != 'CMakeLists.txt':
                continue
            data=path.read_bytes()
            if b'\0' in data:
                raise RuntimeError('Binary file in ROS text directory: '+str(path))
            new=data.replace(b'\r\n',b'\n')
            if new != data:
                path.write_bytes(new)
                changed+=1
            inspected+=1
    nodes=root/'catkin_ws/src/rcboat_ros/nodes'
    if not nodes.is_dir():
        raise RuntimeError('ROS nodes not found')
    count=0
    for path in nodes.glob('*.py'):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        count+=1
    print('ROS TEXT READY: %d files inspected, %d CRLF fixes, %d executable nodes' % (inspected, changed, count))
    return changed,count

if __name__=='__main__':
    try:
        normalize()
    except Exception as exc:
        print('ROS TEXT NORMALIZATION FAILED: '+str(exc),file=sys.stderr)
        sys.exit(1)
