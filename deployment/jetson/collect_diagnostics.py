#!/usr/bin/env python3
"""Read boot/service evidence without probing I2C or changing the system."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def redact(text):
    return re.sub(r'(?im)((?:password|token|secret|authorization)\s*[=:]\s*)[^\r\n]+',
                  r'\1[redacted]',text)


def read_command(args, timeout=8, limit=24000):
    try:
        result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              timeout=timeout,text=True,errors='replace')
        return 'exit=%s\n%s'%(result.returncode,redact(result.stdout[-limit:]))
    except (OSError,subprocess.TimeoutExpired) as exc:
        return 'unavailable: '+str(exc)


def collect():
    sections=[]
    commands=[
        ('system',['uname','-a']),('uptime',['uptime']),
        ('reboot history',['last','-x','-n','12']),
        ('available boots',['journalctl','--list-boots','--no-pager','-n','8']),
        ('previous kernel',['journalctl','-b','-1','-k','--no-pager','-n','160']),
        ('previous ROS service',['journalctl','-b','-1','-u','rcboat_ros.service','--no-pager','-n','80']),
        ('current kernel warnings',['journalctl','-b','-k','-p','warning','--no-pager','-n','180']),
        ('ROS service',['journalctl','-b','-u','rcboat_ros.service','--no-pager','-n','160']),
        ('ROS unit result',['systemctl','show','rcboat_ros.service','-p','ActiveState','-p','SubState',
            '-p','Result','-p','ExecMainStatus','-p','NRestarts','-p','ExecStart','-p','WorkingDirectory']),
        ('SSH service',['journalctl','-b','-u','ssh.service','--no-pager','-n','80']),
        ('resolver symlink',['ls','-l','/etc/resolv.conf']),
        ('resolver target',['readlink','-e','/etc/resolv.conf']),
        ('resolver service',['systemctl','is-active','systemd-resolved.service']),
        ('root mount',['findmnt','-T','/']),
        ('squashfs mounts',['findmnt','-t','squashfs','-o','SOURCE,TARGET,FSTYPE,OPTIONS']),
        ('disk space',['df','-h','/','/var/log']),('memory',['free','-m']),
    ]
    for title,args in commands:
        sections.append('\n===== '+title+' =====\n'+read_command(args))
    for path in [Path('/etc/nv_tegra_release'),*Path('/sys/class/thermal').glob('thermal_zone*/temp')]:
        try:sections.append('\n===== '+str(path)+' =====\n'+path.read_text()[:2000])
        except OSError as exc:sections.append(str(exc))
    root=Path(__file__).resolve().parents[2]
    for rel in ('VERSION','catkin_ws/src/rcboat_ros/package.xml'):
        try:sections.append('\n===== deployed '+rel+' =====\n'+(root/rel).read_text()[:3000])
        except OSError as exc:sections.append(str(exc))
    try:
        from verify_release import read_status,local_token
        response=read_status(token=local_token())
        # Do not include GPS coordinates or credential settings in this boot report.
        summary={k:response.get(k) for k in ('version','master_online','gateway_online','runtime_identity')}
        summary['node_versions']={k:(response.get('telemetry',{}).get(k) or {}).get('software_version')
                                  for k in ('gps','ntrip','safety')}
        sections.append('\n===== live gateway =====\n'+json.dumps(summary,ensure_ascii=False,indent=2))
    except Exception as exc:sections.append('\nGateway unavailable: '+str(exc))
    return '\n'.join(sections)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    folder=Path('/home/jetson/rcboat_ros_data/diagnostics')
    path=args.output or folder/('boot_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'.txt')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(collect(),encoding='utf-8')
    path.chmod(0o600)
    if os.geteuid()==0:
        import pwd
        try:
            user=pwd.getpwnam('jetson')
            os.chown(str(path),user.pw_uid,user.pw_gid)
            os.chown(str(path.parent),user.pw_uid,user.pw_gid)
        except KeyError:pass
    print('Diagnostic report: '+str(path))
    print('Read-only collection complete; no I2C probes or service changes performed.')


if __name__=='__main__':main()
