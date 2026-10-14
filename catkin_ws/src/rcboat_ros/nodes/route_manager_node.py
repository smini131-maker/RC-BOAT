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
                             rospy.get_param('/rcboat/closer_advantage_m',0))
        self.settings_file=pathlib.Path(os.path.expanduser('~/rcboat_ros_data/multipath_settings.json'))
        if self.settings_file.exists():
            try:
                settings=json.loads(self.settings_file.read_text(encoding='utf-8'))
                if 'endpoint_tolerance_m' in settings:
                    self.rm.endpoint_tolerance=float(settings['endpoint_tolerance_m'])
                if 'enabled' in settings:
                    self.rm.multipath_enabled=bool(settings['enabled'])
            except (ValueError,OSError) as e:rospy.logwarn('invalid multipath settings %s',e)
        self.gps={}
        self.pub=rospy.Publisher('/rcboat/route/state',String,queue_size=10)
        self.events=rospy.Publisher('/rcboat/events',String,queue_size=10)
        rospy.Service('/rcboat/route/execute',Execute,self.execute)
        self.commands=rospy.Subscriber('/rcboat/route/commands',String,self.command)
        rospy.Subscriber('/rcboat/gps/status',String,lambda m:setattr(self,'gps',unpack(m)))
    def changed(self,change_type,**details):
        self.events.publish(pack(type='ROUTE_CHANGE',change_type=change_type,
                                 wall_time=time.time(),**details))
    def execute(self,req):
        import json
        try:
            args=json.loads(req.arguments_json or '{}')
            action=req.action
            result={}
            if action=='select_route':
                self.rm.select(args['route_id']);result={'route_id':args['route_id']}
                self.changed('selected',route_id=args['route_id'])
            elif action=='select_multipath':
                self.rm.select_multipath(args['multipath_id']);result={'multipath_id':args['multipath_id']}
                self.changed('multipath_selected',multipath_id=args['multipath_id'])
            elif action=='upsert_multipath':
                before=self.rm.multipaths.get(str(args.get('multipath_id') or ''))
                multipath_id=self.rm.upsert_multipath(args.get('multipath_id'),args.get('name'),
                    args.get('route_ids',[]),args.get('default_route_id',''))
                result={'multipath_id':multipath_id,'multipath':self.rm.multipaths[multipath_id]}
                self.changed('multipath_updated' if before else 'multipath_created',multipath_id=multipath_id,
                             before=before,after=self.rm.multipaths[multipath_id])
            elif action=='delete_multipath':
                multipath_id=str(args['multipath_id']);before=self.rm.multipaths.get(multipath_id,{})
                self.rm.delete_multipath(multipath_id);result={'multipath_id':multipath_id}
                self.changed('multipath_deleted',multipath_id=multipath_id,before=before)
            elif action=='compatible_routes':
                result={'route_ids':self.rm.compatible_route_ids(args['reference_route_id'])}
            elif action=='delete_route':
                route_id=str(args['route_id']);old=self.rm.routes.get(route_id,{})
                self.rm.delete(route_id);result={'route_id':route_id,'deleted_name':old.get('name',route_id)}
                self.changed('deleted',route_id=route_id,before=old)
            elif action=='upsert_route':
                before=self.rm.routes.get(str(args.get('route_id') or ''))
                route_id=self.rm.upsert(args.get('route_id'),args.get('name'),args.get('waypoints',[]),
                                        args.get('arrival_radius_m',3.0))
                result={'route_id':route_id,'route':self.rm.routes[route_id]}
                self.changed('updated' if before else 'created',route_id=route_id,before=before,
                             after=self.rm.routes[route_id])
            elif action=='set_test_route_set':
                ids=args.get('route_ids',[]);self.rm.set_test_route_ids(ids)
                result={'route_ids':list(self.rm.test_route_ids)}
                self.changed('test_set',route_ids=list(self.rm.test_route_ids))
            elif action=='choose_nearest_group_route':
                if not self.gps.get('healthy'):raise ValueError('healthy GPS required')
                result={'active_route_id':self.rm.choose_nearest_group_route(
                    (float(self.gps['latitude']),float(self.gps['longitude'])))}
            elif action=='record_start':self.rm.record_start(args.get('name','Recorded route'),
                args.get('minimum_distance_m',1.0),args.get('minimum_interval_s',.5),args.get('arrival_radius_m',3.0))
            elif action=='record_stop':result={'route_id':self.rm.record_stop()}
            elif action=='record_cancel':self.rm.record_cancel()
            elif action=='list_routes':result={'routes':list(self.rm.routes.values()),'multipaths':list(self.rm.multipaths.values()),
                'selected_route_id':self.rm.selected,'selected_multipath_id':self.rm.selected_multipath,
                'multipath_enabled':self.rm.multipath_enabled}
            elif action=='set_multipath':
                updates={'enabled':bool(args.get('enabled',self.rm.multipath_enabled)),
                         'endpoint_tolerance_m':float(args['endpoint_tolerance_m'])}
                if updates['endpoint_tolerance_m']<=0 or updates['endpoint_tolerance_m']>1000:raise ValueError('invalid multipath settings')
                self.rm.endpoint_tolerance=updates['endpoint_tolerance_m']
                self.rm.set_multipath_enabled(updates['enabled'])
                from rcboat_ros.path_tracking import _atomic_json
                _atomic_json(self.settings_file,updates)
                result={'multipath':{'enabled':self.rm.multipath_enabled,
                                     'endpoint_tolerance_m':self.rm.endpoint_tolerance,
                                     'switch_rule':'nearest_route_in_named_multipath'}}
                self.changed('multipath_settings',after=updates)
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
            recording=self.rm.recording
            data={'selected_route_id':self.rm.selected,'active_route_id':self.rm.active,
                  'group_routes':list(self.rm.group()),'test_route_ids':list(self.rm.test_route_ids),
                  'selected_multipath_id':self.rm.selected_multipath,
                  'execution_target_type':'multipath' if self.rm.multipath_enabled else 'single_route',
                  'routes':list(self.rm.routes.values()),'multipaths':list(self.rm.multipaths.values()),
                  'multipath':{'enabled':self.rm.multipath_enabled,'endpoint_tolerance_m':self.rm.endpoint_tolerance,
                               'switch_rule':'nearest_route_in_named_multipath',
                               'off_route_gate':False,'priority_gate':False,'cooldown_gate':False},
                  'recording':{'active':recording is not None,
                               'name':(recording or {}).get('name',''),
                               'point_count':len((recording or {}).get('waypoints',[])),
                               'minimum_distance_m':(recording or {}).get('minimum_distance_m',1.0),
                               'minimum_interval_s':(recording or {}).get('minimum_interval_s',.5),
                               'arrival_radius_m':(recording or {}).get('arrival_radius_m',3.0),
                               'waypoints':list((recording or {}).get('waypoints',[])),
                               'latest_sample':((recording or {}).get('waypoints') or [None])[-1]}}
            if self.gps.get('healthy') and self.rm.selected:
                try:
                    data.update(self.rm.update((float(self.gps['latitude']),float(self.gps['longitude'])),
                                               self.gps.get('heading_deg')))
                    if self.rm.recording is not None:
                        self.rm.record_point(float(self.gps['latitude']),float(self.gps['longitude']),
                                             self.gps.get('heading_deg'))
                    if self.rm.event:self.events.publish(pack(**self.rm.event))
                except Exception as e:rospy.logerr('route update %s',e)
            self.pub.publish(pack(**data));rate.sleep()
if __name__=='__main__':
    rospy.init_node('route_manager_node');Node().run()
