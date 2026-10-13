#!/usr/bin/env python3
"""SSH stdin JSON -> local ROS bridge UNIX socket -> stdout JSON."""
import json
import os
import socket
import sys

def main():
    try:
        data=json.load(sys.stdin)
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(6)
        sock.connect(os.path.expanduser('~/rcboat_ros_data/gui_bridge.sock'))
        sock.sendall((json.dumps(data)+'\n').encode())
        buf=b''
        while not buf.endswith(b'\n') and len(buf)<1000000:
            piece=sock.recv(8192)
            if not piece:break
            buf+=piece
        result=json.loads(buf)
        sock.close()
    except Exception as e:result={'success':False,'error':str(e)}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('success') else 1
if __name__=='__main__':sys.exit(main())
