#!/usr/bin/env python3
"""Jetson loopback UNIX-socket bridge: Windows connects using existing SSH only."""
import json
import os
import socket
import threading
import time
import rospy
from std_msgs.msg import String
from rcboat_ros.srv import Execute
from rcboat_ros.common import pack,unpack

SOCKET=os.path.expanduser('~/rcboat_ros_data/gui_bridge.sock')
TOPICS={'gps':'/rcboat/gps/status','ntrip':'/rcboat/ntrip/status','route':'/rcboat/route/state',
        'navigation':'/rcboat/navigation/desired','safety':'/rcboat/safety/state',
        'actuator':'/rcboat/actuator/status','ground_test':'/rcboat/ground_test/status',
        'rc':'/rcboat/rc/input'}

class Bridge:
    def __init__(self):
        self.cache={}
        for name,topic in TOPICS.items():
            rospy.Subscriber(topic,String,lambda m,n=name:self.cache.__setitem__(n,unpack(m)))
        self.sock=None
    def dispatch(self,payload):
        command=payload.get('action','status')
        args=payload.get('arguments',{})
        if command=='status':
            try:
                import rosnode
                nodes=rosnode.get_node_names()
            except Exception:nodes=[]
            return {'success':True,'version':'2.0.0-beta.2','backend':'ROS','telemetry':dict(self.cache),'nodes':nodes}
        if command in ('ground_start','ground_stop'):
            safety='/rcboat/safety/execute';logger='/rcboat/logger/execute'
            rospy.wait_for_service(safety,timeout=3)
            rospy.wait_for_service(logger,timeout=3)
            if command=='ground_start':
                v=rospy.ServiceProxy(safety,Execute)('set_mode',pack(mode='GROUND_TEST'))
                if not v.success:return {'success':False,'error':v.response_json}
                rospy.sleep(.25)
                v=rospy.ServiceProxy(logger,Execute)('start','{}')
            else:
                v=rospy.ServiceProxy(logger,Execute)('stop','{}')
                rospy.ServiceProxy(safety,Execute)('set_mode',pack(mode='AUTO_SAFE'))
            return {'success':v.success,'response':json.loads(v.response_json)}
        namespace='/rcboat/safety/execute' if command in ('set_mode','estop','reset_estop','set_remote_pwm','heartbeat') else '/rcboat/route/execute' if command in ('select_route','delete_route','list_routes','record_start','record_stop','set_multipath','choose_nearest_group_route') else '/rcboat/ntrip/execute' if command in ('configure',) else '/rcboat/navigation/execute' if command=='set_tracking_mode' else None
        if not namespace:return {'success':False,'error':'unsupported action'}
        rospy.wait_for_service(namespace,timeout=3)
        result=rospy.ServiceProxy(namespace,Execute)(command,json.dumps(args))
        return {'success':result.success,'response':json.loads(result.response_json)}
    def client(self,connection):
        with connection:
            try:
                data=b''
                while len(data)<65536 and b'\n' not in data:
                    chunk=connection.recv(4096)
                    if not chunk:break
                    data+=chunk
                request=json.loads(data.decode().strip())
                response=self.dispatch(request)
            except Exception as e:response={'success':False,'error':str(e)}
            connection.sendall((json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n').encode())
    def run(self):
        os.makedirs(os.path.dirname(SOCKET),exist_ok=True)
        try:os.unlink(SOCKET)
        except FileNotFoundError:pass
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        s.bind(SOCKET);os.chmod(SOCKET,0o600);s.listen(5);s.settimeout(.5)
        self.sock=s
        try:
            while not rospy.is_shutdown():
                try:conn,_=s.accept()
                except socket.timeout:continue
                threading.Thread(target=self.client,args=(conn,),daemon=True).start()
        finally:
            s.close()
            try:os.unlink(SOCKET)
            except FileNotFoundError:pass
if __name__=='__main__':rospy.init_node('gui_bridge_node');Bridge().run()
