#!/usr/bin/env python3
"""NTRIP reads correction stream and publishes RTCM, never opens GPS port."""
import base64
import os
import socket
import ssl
import threading
import time
import urllib.parse
import rospy
from std_msgs.msg import String,UInt8MultiArray
from rcboat_ros.common import pack
from rcboat_ros.srv import Execute,ExecuteResponse
import json
import pathlib

NTRIP_ENV_PATH = pathlib.Path(os.path.expanduser('~/rcboat_balloon_data/ntrip.env'))


def load_local_env(path):
    """Read the Jetson-only EnvironmentFile without exporting its secret."""
    values = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key.startswith('RCBOAT_NTRIP_'):
            continue
        value = value.strip()
        try:
            values[key] = str(json.loads(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            values[key] = value.strip('"\'')
    return values


class Ntrip:
    def __init__(self):
        local = load_local_env(NTRIP_ENV_PATH)
        setting = lambda key, default='': os.getenv(key, local.get(key, default))
        self.gps={}
        self.received=0
        self.connected=False
        self.last_error=''
        self.last_correction=0
        # Environment variables win, while the local file also works with a
        # direct `roslaunch` that is not started by systemd.
        self.enabled=setting('RCBOAT_NTRIP_ENABLED','false').lower()=='true'
        self.host=setting('RCBOAT_NTRIP_HOST')
        self.port=int(setting('RCBOAT_NTRIP_PORT','2101'))
        self.mount=setting('RCBOAT_NTRIP_MOUNTPOINT').lstrip('/')
        self.user=setting('RCBOAT_NTRIP_USERNAME')
        self.password=setting('RCBOAT_NTRIP_PASSWORD')
        self.tls=setting('RCBOAT_NTRIP_TLS','false').lower()=='true'
        self.reconnect=False
        rospy.Service('/rcboat/ntrip/execute',Execute,self.execute)
        self.pub=rospy.Publisher('/rcboat/gps/rtcm',UInt8MultiArray,queue_size=10)
        self.status=rospy.Publisher('/rcboat/ntrip/status',String,queue_size=5)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=8)
        rospy.Subscriber('/rcboat/gps/status',String,self.position)
    def execute(self,req):
        try:
            if req.action!='configure':raise ValueError('unknown NTRIP action')
            args=json.loads(req.arguments_json or '{}')
            for key,attribute in [('enabled','enabled'),('host','host'),('port','port'),('mountpoint','mount'),
                                  ('username','user'),('password','password'),('tls','tls')]:
                if key in args:
                    val=args[key]
                    if key in ('enabled','tls'):val=bool(val)
                    if key=='port':val=int(val)
                    setattr(self,attribute,val)
            self.reconnect=True
            path=NTRIP_ENV_PATH
            path.parent.mkdir(parents=True,exist_ok=True)
            values={'RCBOAT_NTRIP_ENABLED':str(self.enabled).lower(),'RCBOAT_NTRIP_HOST':self.host,
                    'RCBOAT_NTRIP_PORT':str(self.port),'RCBOAT_NTRIP_MOUNTPOINT':self.mount,
                    'RCBOAT_NTRIP_USERNAME':self.user,'RCBOAT_NTRIP_PASSWORD':self.password,
                    'RCBOAT_NTRIP_TLS':str(self.tls).lower()}
            # EnvironmentFile uses KEY=VALUE syntax; quote values so spaces and delimiters are preserved.
            payload=''.join(k+'='+json.dumps(str(v))+'\n' for k,v in values.items())
            tmp=path.with_suffix('.tmp');tmp.write_text(payload,encoding='utf-8');tmp.chmod(0o600)
            tmp.replace(path);path.chmod(0o600)
            self.events.publish(pack(type='CONFIG_CHANGE',change_type='ntrip',
                                     after={'enabled':self.enabled,'host':self.host,'port':self.port,
                                            'mountpoint':self.mount,'tls':self.tls,'credentials':'redacted'}))
            return ExecuteResponse(True,pack(enabled=self.enabled,host=self.host,mountpoint=self.mount,
                                             tls=self.tls,credentials_saved=bool(self.user and self.password)))
        except Exception as exc:return ExecuteResponse(False,pack(error=str(exc)))
    def position(self,msg):
        from rcboat_ros.common import unpack
        self.gps=unpack(msg)
    def _nmea_gga(self):
        a=self.gps
        if not a.get('healthy'):return ''
        lat=float(a['latitude']);lon=float(a['longitude'])
        def ddmm(value):
            v=abs(value);d=int(v);return d*100+(v-d)*60
        utc=time.gmtime()
        core='GPGGA,%02d%02d%02d,%.6f,%s,%.6f,%s,1,%02d,%.1f,0,M,0,M,,' % (utc.tm_hour,utc.tm_min,utc.tm_sec,ddmm(lat),'N' if lat>=0 else 'S',ddmm(lon),'E' if lon>=0 else 'W',int(a.get('satellites',0)),float(a.get('hdop',1)))
        xor=0
        for c in core:xor^=ord(c)
        return '$%s*%02X\r\n'%(core,xor)
    def run(self):
        while not rospy.is_shutdown():
            if not self.enabled or not self.host or not self.mount:
                self.status.publish(pack(enabled=self.enabled,connected=False,host=self.host,port=self.port,
                    mountpoint=self.mount,tls=self.tls,bytes_received=self.received,
                    correction_age=None,last_correction_age_s=None,
                    credentials_saved=bool(self.user and self.password),
                    last_error='NTRIP disabled or unconfigured'))
                rospy.sleep(2);continue
            try:
                sock=socket.create_connection((self.host,self.port),timeout=8)
                if self.tls:sock=ssl.create_default_context().wrap_socket(sock,server_hostname=self.host)
                sock.settimeout(7)
                token=base64.b64encode((self.user+':'+self.password).encode()).decode()
                req=('GET /%s HTTP/1.1\r\nHost: %s\r\nUser-Agent: NTRIP RCBoatROS/2.0\r\nNtrip-Version: Ntrip/2.0\r\nAuthorization: Basic %s\r\nConnection: close\r\n\r\n'%(self.mount,self.host,token)).encode()
                sock.sendall(req)
                header=b''
                while b'\r\n\r\n' not in header and len(header)<8192:
                    header+=sock.recv(1024)
                head,sep,left=header.partition(b'\r\n\r\n')
                if not head.startswith((b'ICY 200',b'HTTP/1.1 200',b'HTTP/1.0 200')):
                    raise RuntimeError('NTRIP HTTP status not 200: '+head[:70].decode(errors='replace'))
                self.connected=True; self.last_error='';last_gga=0
                while not rospy.is_shutdown():
                    if self.reconnect or not self.enabled:
                        self.reconnect=False
                        break
                    if time.monotonic()-last_gga>5:
                        gga=self._nmea_gga()
                        if gga:sock.sendall(gga.encode())
                        last_gga=time.monotonic()
                    chunk=left if left else sock.recv(4096)
                    left=b''
                    if not chunk: raise ConnectionError('NTRIP stream ended')
                    self.pub.publish(UInt8MultiArray(data=list(chunk)))
                    self.received+=len(chunk);self.last_correction=time.monotonic()
                    self.status.publish(pack(enabled=True,connected=True,host=self.host,port=self.port,
                        mountpoint=self.mount,tls=self.tls,bytes_received=self.received,
                        correction_age=0.0,last_correction_age_s=0.0,
                        credentials_saved=bool(self.user and self.password),last_error=''))
                sock.close()
            except Exception as e:
                self.connected=False;self.last_error=str(e)
                age=time.monotonic()-self.last_correction if self.last_correction else None
                self.status.publish(pack(enabled=True,connected=False,host=self.host,port=self.port,
                    mountpoint=self.mount,tls=self.tls,bytes_received=self.received,
                    correction_age=age,last_correction_age_s=age,
                    credentials_saved=bool(self.user and self.password),last_error=self.last_error))
                rospy.logwarn('NTRIP connection error: %s',e)
                rospy.sleep(4)
if __name__=='__main__':
    rospy.init_node('ntrip_node');Ntrip().run()
