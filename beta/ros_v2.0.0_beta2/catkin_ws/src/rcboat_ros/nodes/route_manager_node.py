#!/usr/bin/env python3
"""Single route manager; writes only ROS data directory, never legacy route file."""
import time
import os
import json
import pathlib
import rospy
from std_msgs.msg import String
from rcboat_ros.common import unpack,pack
from rcboat_ros.path_tracking import RouteManager
from rcboat_ros.srv import Execute, ExecuteResponse

class Node:
    def __init__(self):
        f=rospy.get_param('/rcboat/routes_file')
        self.rm=RouteManager(f,rospy.get_param('/rcboat/endpoint_tolerance_m',.75),
                             rospy.get_param('/rcboat/off_route_distance_m',8),rospy.get_param('/rcboat/off_route_hold_s',3),
                             rospy.get_param('/rcboat/closer_advantage_m',2),rospy.get_param('/rcboat/switch_cooldown_s',5))
        self.settings_file=pathlib.Path(os.path.expanduser('~/rcboat_ros_data/multipath_settings.json'))
        if self.settings_file.exists():
            try:
                settings=json.loads(self.settings_file.read_text(encoding='utf-8'))
                for key,attribute in [('endpoint_tolerance_m','endpoint_tolerance'),('off_route_distance_m','off_route'),
                     ('off_route_hold_s','hold_s'),('closer_advantage_m','advantage'),('switch_cooldown_s','cooldown')]:
                    if key in settings:setattr(self.rm,attribute,float(settings[key]))
            except (ValueError,OSError) as e:rospy.logwarn('invalid multipath settings %s',e)
        self.gps={}
        self.pub=rospy.Publisher('/rcboat/route/state',String,queue_size=10)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=10)
        rospy.Service('/rcboat/route/execute',Execute,self.execute)
        self.commands=rospy.Subscriber('/rcboat/route/commands',String,self.command)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
    def execute(self,req):
        import json
        try:
            args=json.loads(req.arguments_json or '{}')
            action=req.action
            result={}
            if action=='select_route':self.rm.select(args['route_id'])
            elif action=='delete_route':self.rm.delete(args['route_id'])
            elif action=='choose_nearest_group_route':
                if not self.gps.get('healthy'):raise ValueError('healthy GPS required')
                result={'active_route_id':self.rm.choose_nearest_group_route(
                    (float(self.gps['latitude']),float(self.gps['longitude'])))}
            elif action=='record_start':self.rm.record_start(args.get('name','Recorded route'))
            elif action=='record_stop':result={'route_id':self.rm.record_stop()}
            elif action=='list_routes':result={'routes':list(self.rm.routes.values()),'selected_route_id':self.rm.selected}
            elif action=='set_multipath':
                updates={k:float(args[k]) for k in ('endpoint_tolerance_m','off_route_distance_m','off_route_hold_s','closer_advantage_m','switch_cooldown_s')}
                if any(v<=0 or v>1000 for v in updates.values()):raise ValueError('invalid multipath settings')
                for key,attribute in [('endpoint_tolerance_m','endpoint_tolerance'),('off_route_distance_m','off_route'),
                     ('off_route_hold_s','hold_s'),('closer_advantage_m','advantage'),('switch_cooldown_s','cooldown')]:
                    setattr(self.rm,attribute,updates[key])
                from rcboat_ros.path_tracking import _atomic_json
                _atomic_json(self.settings_file,updates)
                result={'multipath':updates}
            else:raise ValueError('unknown route action')
            return ExecuteResponse(True,pack(**result))
        except Exception as e:return ExecuteResponse(False,pack(error=str(e)))
    def command(self,msg):
        obj=unpack(msg)
        try:
            action=obj.get('action');args=obj.get('arguments',{})
            if action=='select_route':self.rm.select(args['route_id'])
            elif action=='delete_route':self.rm.delete(args['route_id'])
            elif action=='record_start':self.rm.record_start(args.get('name','Recorded route'))
            elif action=='record_stop':self.rm.record_stop()
        except Exception as e:self.events.publish(pack(type='ROUTE_COMMAND_ERROR',detail=str(e)))
    def run(self):
        rate=rospy.Rate(4)
        while not rospy.is_shutdown():
            data={'selected_route_id':self.rm.selected,'active_route_id':self.rm.active,
                  'group_routes':list(self.rm.group()),'routes':list(self.rm.routes.values())}
            if self.gps.get('healthy'):
                try:
                    data.update(self.rm.update((float(self.gps['latitude']),float(self.gps['longitude']))))
                    if self.rm.recording is not None:
                        self.rm.record_point(float(self.gps['latitude']),float(self.gps['longitude']),
                                             self.gps.get('heading_deg'))
                    if self.rm.event:self.events.publish(pack(**self.rm.event))
                except Exception as e:rospy.logerr('route update %s',e)
            self.pub.publish(pack(**data));rate.sleep()
if __name__=='__main__':
    rospy.init_node('route_manager_node');Node().run()
