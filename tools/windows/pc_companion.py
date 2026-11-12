"""Windows companion controls over authenticated SSH, without an operator heartbeat."""
import ipaddress
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, ttk

import keyring
import paramiko


CONFIG = Path.home()/'.rcboat'/'pc-companion.json'
TS = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Tailscale'/'tailscale.exe'
BRIDGE = 'python3 ~/rcboat_ros_ws/deployment/jetson/bridge_client.py'
LABELS = {'AUTO_SAFE': '자동 대기', 'MANUAL': '수동', 'BALLOON': '풍선 추적',
          'NAVIGATION': '항로 주행', 'GROUND_TEST': '도보 시험', 'REMOTE': '원격'}


def peer_address(state, hostname):
    if state.get('BackendState') != 'Running':
        raise RuntimeError('PC의 Tailscale 연결을 기다리는 중')
    peers = [p for p in (state.get('Peer') or {}).values() if p.get('HostName') == hostname]
    if len(peers) != 1:
        raise RuntimeError('사설망에서 등록된 Jetson을 확인할 수 없습니다')
    addresses = (ipaddress.ip_address(ip) for ip in peers[0].get('TailscaleIPs', ()))
    return str(next(address for address in addresses if address.version == 4))


class Bridge:
    def __init__(self, config):
        self.config = config
        self.client = None
        self.address = ''

    def open(self):
        raw = subprocess.check_output([str(TS),'status','--json'], timeout=3,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        address = peer_address(json.loads(raw), self.config['peer_name'])
        keys = paramiko.HostKeys(str(Path.home()/'.ssh'/'known_hosts'))
        host_key = keys[self.config['known_host']]['ssh-ed25519']
        password = keyring.get_password('RCBoatControl', self.config['credential_account'])
        if not password:
            raise RuntimeError('Windows 자격 증명에 Jetson SSH 비밀번호가 없습니다')
        client = paramiko.SSHClient()
        client.get_host_keys().add(address, 'ssh-ed25519', host_key)
        try:
            client.connect(address, username='jetson', password=password, allow_agent=False,
                           look_for_keys=False, timeout=3, banner_timeout=3, auth_timeout=3)
        except Exception:
            client.close()
            raise
        client.get_transport().set_keepalive(10)
        self.client, self.address = client, address

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def request(self, action, arguments=None):
        if action not in ('status','set_mode','estop','vision_enable'):
            raise ValueError('unsupported companion action')
        if self.client is None or not self.client.get_transport().is_active():
            self.close()
            self.open()
        try:
            stdin, stdout, _ = self.client.exec_command(BRIDGE, timeout=3)
            stdin.write(json.dumps(dict(action=action, arguments=arguments or {})))
            stdin.channel.shutdown_write()
            response = json.loads(stdout.readline())
        except Exception:
            self.close()
            raise
        if not response.get('success'):
            raise RuntimeError(response.get('error') or 'Jetson이 명령을 거부했습니다')
        return response


class Panel:
    def __init__(self, root, config):
        self.root = root
        self.status_bridge, self.command_bridge = Bridge(config), Bridge(config)
        self.stop_bridge = Bridge(config)
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.poll = self.pending = self.stopping = None
        self.last_poll = self.status_at = 0.
        self.status = {}
        self.link = tk.StringVar(value='Jetson 자동 연결 중')
        self.mode = tk.StringVar(value='운항 상태 확인 중')
        self.notice = tk.StringVar(value='')
        root.title('RC 보트 · PC 보조 관제')
        root.minsize(455, 280)
        panel = ttk.Frame(root, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, textvariable=self.link).pack(anchor='w')
        ttk.Label(panel, textvariable=self.mode, wraplength=440, font=('Malgun Gothic',12,'bold')).pack(anchor='w',pady=(8,12))
        row = ttk.Frame(panel)
        row.pack(fill='x')
        self.buttons = []
        controls = (
            ('수동 전환','set_mode',{'mode':'MANUAL'}),
            ('자동 대기','set_mode',{'mode':'AUTO_SAFE'}),
            ('카메라 켜기','vision_enable',{'enabled':True}),
        )
        for title,action,args in controls:
            button=ttk.Button(row,text=title,command=lambda a=action,d=args:self.send(a,d))
            button.pack(side='left',fill='x',expand=True,padx=(0,5))
            self.buttons.append(button)
        self.stop = ttk.Button(row,text='비상정지',command=self.emergency_stop)
        self.stop.pack(side='left',fill='x',expand=True)
        self.start = ttk.Button(panel,text='풍선 추적 시작',command=self.confirm_start)
        self.start.pack(fill='x',pady=(12,0))
        ttk.Label(panel,textvariable=self.notice,wraplength=440).pack(anchor='w',pady=(10,0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.tick()

    def confirm_start(self):
        safe = self.status.get('telemetry',{}).get('safety',{})
        stamp = safe.get('mode_since_monotonic')
        if stamp is None or time.monotonic()-self.status_at>2.5:
            return
        if messagebox.askyesno('풍선 추적 시작','모터 출력이 시작될 수 있습니다. 풍선 추적을 시작할까요?',parent=self.root):
            self.send('set_mode',dict(mode='BALLOON',armed=True,expected_mode_since_monotonic=stamp))

    def emergency_stop(self):
        if self.stopping is None:
            self.notice.set('비상정지 전송 중')
            self.stopping = self.pool.submit(self.stop_bridge.request,'estop',{'origin':'desktop'})

    def send(self, action, arguments):
        if self.pending is not None:
            return
        self.notice.set('명령 응답 대기')
        self.pending = self.pool.submit(self.command_bridge.request,action,arguments)

    def tick(self):
        if self.poll is not None and self.poll.done():
            try:
                self.status = self.poll.result()
                self.status_at = time.monotonic()
                self.link.set('사설 SSH 연결 · '+self.status_bridge.address)
                t=self.status['telemetry']
                safe=t['safety'];v=t.get('vision',{});op=t.get('operator_link',{})
                mode=LABELS.get(safe.get('mode'),safe.get('mode','미수신'))
                locked='출력 잠금' if safe.get('actuator_locked') else '출력 허용'
                phone='보트 제어 링크 정상' if op.get('ssh_connected') and abs(v.get('monotonic',0)-op.get('monotonic',0))<3 else '보트 제어 링크 확인 필요'
                camera='카메라 켜짐' if v.get('camera_online') else '카메라 대기'
                self.mode.set(f'{mode} · {locked}  |  {phone}  |  {camera}')
            except Exception as exc:
                self.link.set(str(exc))
                self.mode.set('Jetson 상태 대기')
                self.status_at=0.
            self.poll=None
        if self.pending is not None and self.pending.done():
            try:
                self.pending.result()
                self.notice.set('Jetson에서 명령을 확인했습니다')
            except Exception as exc:
                self.notice.set('명령 응답: '+str(exc))
            self.pending=None
        if self.stopping is not None and self.stopping.done():
            try:
                self.stopping.result()
                self.notice.set('Jetson에서 비상정지를 확인했습니다')
            except Exception as exc:
                self.notice.set('비상정지 응답: '+str(exc))
            self.stopping=None
        now=time.monotonic()
        if self.poll is None and now-self.last_poll>=1:
            self.last_poll=now
            self.poll=self.pool.submit(self.status_bridge.request,'status')
        ready=now-self.status_at<2.5 and self.pending is None and self.stopping is None
        for button in self.buttons:
            button.configure(state='normal' if ready else 'disabled')
        self.start.configure(state='normal' if ready else 'disabled')
        self.stop.configure(state='normal' if self.stopping is None else 'disabled')
        self.root.after(100,self.tick)

    def close(self):
        if self.pending is not None or self.stopping is not None:
            self.notice.set('명령 응답을 확인한 뒤 창을 닫으세요')
            return
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.status_bridge.close()
        self.command_bridge.close()
        self.stop_bridge.close()
        self.root.destroy()


def main():
    root=tk.Tk()
    try:
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        root.withdraw()
        messagebox.showerror('RC 보트','PC 보조 관제의 로컬 연결 설정을 확인하세요.',parent=root)
        root.destroy()
        return
    Panel(root,config)
    root.mainloop()


if __name__=='__main__':
    main()
