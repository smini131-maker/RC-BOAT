"""ROS Noetic GPS tracking: baseline Heading plus CTE/LOS/Pure Pursuit."""
import datetime as dt
import json
import math
import os
import time
import re
import uuid
from pathlib import Path
from .common import clamp
from .geo import enrich_waypoints

R = 6371000.0

def meters(a, b):
    y1, x1, y2, x2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((y2-y1)/2)**2 + math.cos(y1)*math.cos(y2)*math.sin((x2-x1)/2)**2
    return 2*R*math.asin(min(1, math.sqrt(h)))

def bearing(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2-lon1
    return math.degrees(math.atan2(math.sin(dlon)*math.cos(lat2), math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dlon))) % 360

def angle_error(target, heading):
    return (target-heading+180) % 360 - 180

def local_xy(origin, point):
    lat = math.radians(origin[0])
    return (math.radians(point[1]-origin[1])*R*math.cos(lat), math.radians(point[0]-origin[0])*R)

def segment_cross_track(point, start, end):
    px, py = local_xy(start, point)
    ex, ey = local_xy(start, end)
    dd = ex*ex+ey*ey
    if dd < 1e-12:
        return math.hypot(px, py), 0.0
    t = clamp((px*ex+py*ey)/dd, 0, 1)
    nearest = (px-t*ex, py-t*ey)
    signed = (ex*py-ey*px) / math.sqrt(dd)  # left is positive
    return math.hypot(*nearest), signed

def nearest_route(point, waypoints):
    if len(waypoints) < 2:
        return (meters(point, waypoints[0]), 0, 0.0) if waypoints else (float('inf'), 0, 0.0)
    segments = [segment_cross_track(point, a, b) for a,b in zip(waypoints, waypoints[1:])]
    idx = min(range(len(segments)), key=lambda x:segments[x][0])
    return segments[idx][0], idx, segments[idx][1]

def nearest_waypoint(point, waypoints, start_index=0):
    """Return distance/index of the nearest non-past waypoint."""
    if not waypoints:
        return float('inf'), 0
    start=max(0,min(int(start_index),len(waypoints)-1))
    index=min(range(start,len(waypoints)),key=lambda i:meters(point,waypoints[i]))
    return meters(point,waypoints[index]),index

def _waypoints(route):
    return [(float(w['lat']), float(w['lon'])) for w in route.get('waypoints', [])]

def _atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name('.'+path.name+'.tmp')
    pending.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(pending, path)

class RouteManager:
    def __init__(self, filename, endpoint_tolerance=0.75, switch_threshold_m=2.0):
        self.filename = Path(filename)
        self.endpoint_tolerance = float(endpoint_tolerance)
        self.switch_threshold_m = float(switch_threshold_m)
        if self.switch_threshold_m <= 0:
            raise ValueError('multipath switch threshold must be positive')
        self.recording = None
        self.load()
        self.event = None

    def load(self):
        previous_test_ids=getattr(self,'test_route_ids',[])
        migrated=False
        if self.filename.exists():
            self.data = json.loads(self.filename.read_text(encoding='utf-8'))
        else:
            self.data = {'schema_version':3,'selected_route_id':'','selected_multipath_id':'',
                         'multipath_enabled':True,'multipaths':[],'routes':[]}
            _atomic_json(self.filename,self.data)
        if not isinstance(self.data.get('routes'),list):raise ValueError('routes must be a list')
        for key,value in (('schema_version',3),('selected_multipath_id',''),
                          ('multipath_enabled',True),('multipaths',[])):
            if key not in self.data:self.data[key]=value;migrated=True
        if self.data.get('schema_version') != 3:self.data['schema_version']=3;migrated=True
        if not isinstance(self.data.get('multipaths'),list):raise ValueError('multipaths must be a list')
        self.routes = {str(r['id']):r for r in self.data['routes'] if len(r.get('waypoints', [])) >= 1}
        self.multipaths={str(item['id']):item for item in self.data['multipaths'] if item.get('id')}
        self.selected = self.data.get('selected_route_id') or (next(iter(self.routes)) if self.routes else '')
        if self.selected not in self.routes:self.selected=next(iter(self.routes)) if self.routes else ''
        self.selected_multipath=str(self.data.get('selected_multipath_id') or '')
        if self.selected_multipath not in self.multipaths:self.selected_multipath=''
        self.multipath_enabled=bool(self.data.get('multipath_enabled',True))
        self.active = self.selected
        self.test_route_ids=[route_id for route_id in previous_test_ids if route_id in self.routes]
        self.next_index = 0
        self.progress = {route_id:0 for route_id in self.routes}
        self.progress_fraction = 0.0

    def select(self, route_id):
        if route_id not in self.routes: raise ValueError('route does not exist')
        self.data['selected_route_id'] = route_id
        _atomic_json(self.filename, self.data)
        self.selected = self.active = route_id
        self.next_index = 0
        self.progress = {name:0 for name in self.routes}
        self.progress_fraction = 0.0
        if migrated:_atomic_json(self.filename,self.data)

    def select_multipath(self, multipath_id):
        multipath_id=str(multipath_id)
        if multipath_id not in self.multipaths:raise ValueError('multipath does not exist')
        item=self.multipaths[multipath_id]
        ids=[route_id for route_id in item.get('route_ids',[]) if route_id in self.routes]
        if not ids:raise ValueError('multipath has no available subroutes')
        default=str(item.get('default_route_id') or '')
        if default not in ids:default=ids[0]
        self.data['selected_multipath_id']=multipath_id
        self.data['selected_route_id']=default
        _atomic_json(self.filename,self.data)
        self.selected_multipath=multipath_id
        self.selected=self.active=default
        self.next_index=0;self.progress={name:0 for name in self.routes};self.progress_fraction=0.0

    def set_multipath_enabled(self, enabled):
        self.multipath_enabled=bool(enabled)
        self.data['multipath_enabled']=self.multipath_enabled
        _atomic_json(self.filename,self.data)
        self.active=self.selected;self.next_index=0

    def upsert_multipath(self, multipath_id, name, route_ids, default_route_id=''):
        name=' '.join(str(name).split())
        if not name:raise ValueError('multipath name is required')
        ids=[]
        for value in route_ids:
            route_id=str(value)
            if route_id not in ids:ids.append(route_id)
        if not ids:raise ValueError('select at least one subroute')
        missing=[route_id for route_id in ids if route_id not in self.routes]
        if missing:raise ValueError('unknown routes: '+','.join(missing))
        multipath_id=str(multipath_id or '').strip()
        if not multipath_id:
            slug=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')[:32] or 'multipath'
            multipath_id=f'{slug}-{uuid.uuid4().hex[:8]}'
        default=str(default_route_id or '')
        if default not in ids:default=ids[0]
        item={'id':multipath_id,'name':name,'route_ids':ids,'default_route_id':default,
              'saved_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        groups=[item if str(group.get('id'))==multipath_id else group for group in self.data['multipaths']]
        if not any(str(group.get('id'))==multipath_id for group in self.data['multipaths']):groups.append(item)
        self.data['multipaths']=groups
        if not self.data.get('selected_multipath_id'):self.data['selected_multipath_id']=multipath_id
        _atomic_json(self.filename,self.data);self.load()
        return multipath_id

    def delete_multipath(self, multipath_id):
        multipath_id=str(multipath_id)
        groups=[item for item in self.data['multipaths'] if str(item.get('id'))!=multipath_id]
        if len(groups)==len(self.data['multipaths']):raise ValueError('multipath not found')
        self.data['multipaths']=groups
        if str(self.data.get('selected_multipath_id') or '')==multipath_id:self.data['selected_multipath_id']=''
        _atomic_json(self.filename,self.data);self.load()

    def compatible_route_ids(self, reference_route_id):
        reference_route_id=str(reference_route_id)
        if reference_route_id not in self.routes:raise ValueError('reference route does not exist')
        base=_waypoints(self.routes[reference_route_id]);result=[]
        for route_id,route in self.routes.items():
            points=_waypoints(route)
            if (meters(base[0],points[0])<=self.endpoint_tolerance and
                    meters(base[-1],points[-1])<=self.endpoint_tolerance):result.append(route_id)
        return result

    def group(self):
        if not self.selected or self.selected not in self.routes:return {}
        base = _waypoints(self.routes[self.selected])
        found = {}
        if self.test_route_ids:
            candidates=self.test_route_ids
        elif self.multipath_enabled and self.selected_multipath in self.multipaths:
            candidates=self.multipaths[self.selected_multipath].get('route_ids',[])
        else:
            candidates=[self.selected]
        for name in candidates:
            if name not in self.routes:continue
            route=self.routes[name]
            pts = _waypoints(route)
            d1, d2 = meters(base[0], pts[0]), meters(base[-1], pts[-1])
            found[name] = {'start_gap_m': round(d1,3), 'end_gap_m': round(d2,3)}
        return found

    def update(self, position, heading=None, now=None):
        now = time.monotonic() if now is None else now
        group = self.group()
        if not group:raise ValueError('no route selected')
        if self.active not in group:
            self.active = self.selected
            self.next_index = self.progress.get(self.active,0)
        # Named Multi-Path membership is explicit. Runtime selection uses the nearest
        # polyline; waypoint progress is kept per subroute so switching does not drive backward.
        distances = {};route_metrics=[]
        for route_id in group:
            points=_waypoints(self.routes[route_id])
            equivalent=int(math.floor(self.progress_fraction*max(0,len(points)-1)))
            floor=max(0,self.progress.get(route_id,0)-1,equivalent)
            waypoint_distance,waypoint_index=nearest_waypoint(position,points,floor)
            route_distance,segment_index,signed_cte=nearest_route(position,points)
            target_index=min(waypoint_index+1,len(points)-1)
            target_heading=bearing(position,points[target_index])
            metric={'route_id':route_id,'route_name':self.routes[route_id].get('name',route_id),
                    'distance_to_route_m':round(route_distance,4),'nearest_segment_index':segment_index,
                    'cross_track_error_m':round(signed_cte,4),'target_waypoint_index':target_index,
                    'target_waypoint_number':target_index+1,'target_lat':points[target_index][0],
                    'target_lon':points[target_index][1],'target_heading_deg':round(target_heading,4),
                    'heading_error_deg':None if heading is None else round(angle_error(target_heading,float(heading)),4)}
            route_metrics.append(metric)
            distances[route_id]=(route_distance,waypoint_index,waypoint_distance)
        current = distances[self.active][0]
        candidate = min(distances, key=lambda k: distances[k][0]); previous = self.active
        candidate_distance = distances[candidate][0]
        threshold_exceeded = current > self.switch_threshold_m
        switched = False
        # Week-7 lecture rule: retain the current Target Path while its relative
        # distance is <= 2 m (configurable). Only after the active-path distance
        # is strictly greater than the threshold may the nearest explicit
        # subroute become the new Target Path.
        if candidate != self.active and threshold_exceeded:
            self.active = candidate
            points=_waypoints(self.routes[candidate])
            equivalent=int(math.ceil(self.progress_fraction*max(0,len(points)-1)))
            self.next_index=max(self.progress.get(candidate,0),equivalent,min(distances[candidate][1]+1,len(points)-1))
            self.progress[candidate]=self.next_index
            switched=True
        if switched:
            switch_decision='SWITCH_TO_NEAREST_AFTER_THRESHOLD'
        elif threshold_exceeded:
            switch_decision='THRESHOLD_EXCEEDED_ACTIVE_ALREADY_NEAREST'
        else:
            switch_decision='KEEP_ACTIVE_WITHIN_THRESHOLD'
        route = self.routes[self.active]
        points = _waypoints(route)
        self.next_index = min(max(self.next_index,self.progress.get(self.active,0)),len(points)-1)
        # Skip passed waypoints while preserving monotonic progress.
        _,nearest_index=nearest_waypoint(position,points,max(0,self.next_index-1))
        if len(points)>1:self.progress_fraction=max(self.progress_fraction,nearest_index/(len(points)-1))
        self.next_index=max(self.next_index,min(nearest_index+1,len(points)-1))
        self.progress[self.active]=self.next_index
        target = points[self.next_index]
        if meters(position,target) <= float(route.get('arrival_radius_m',1.0)) and self.next_index < len(points)-1:
            self.next_index+=1
            self.progress[self.active]=self.next_index
            target=points[self.next_index]
        dwp=meters(position,target)
        cte=nearest_route(position, points)[2]
        self.event = {'type':'ROUTE_SWITCH','previous_route':previous,'candidate_route':candidate,
                      'new_route':self.active,'previous_target_path_distance_m':round(current,4),
                      'candidate_route_distance_m':round(candidate_distance,4),
                      'switch_threshold_m':self.switch_threshold_m,
                      'switch_decision':switch_decision,'monotonic':now} if switched else None
        return {'selected_route_id':self.selected,'active_route_id':self.active,'candidate_route_id':candidate,
                'group_routes':list(group),'endpoint_gaps':group,
                'switch_threshold_m':self.switch_threshold_m,
                'switch_threshold_exceeded':threshold_exceeded,
                'previous_target_path_distance_m':round(current,4),
                'candidate_route_distance_m':round(candidate_distance,4),
                'switch_decision':switch_decision,
                'selection_metric':'ACTIVE_TARGET_DISTANCE_GT_THRESHOLD_THEN_NEAREST',
                'multipath_switch':switched,'previous_route': previous if switched else '',
                'target_waypoint_index':self.next_index,'target_lat':target[0],'target_lon':target[1],
                'path_waypoints':[{'lat':a,'lon':b} for a,b in points],
                'distance_to_waypoint_m':dwp,'cross_track_error_m':cte,'distance_to_route_m':distances[self.active][0],
                'route_candidates':route_metrics,
                'route_complete':self.next_index==len(points)-1 and dwp <= float(route.get('arrival_radius_m',1.0))}

    def choose_nearest_group_route(self, position):
        """Operator-requested closest compatible start; reference route remains selected."""
        group=self.group()
        if not group: raise ValueError('no compatible route group')
        def distance(route_id):
            points=_waypoints(self.routes[route_id])
            equivalent=int(math.floor(self.progress_fraction*max(0,len(points)-1)))
            return nearest_waypoint(position,points,max(0,self.progress.get(route_id,0)-1,equivalent))[0]
        best=min(group,key=distance)
        self.active=best
        points=_waypoints(self.routes[best])
        equivalent=int(math.ceil(self.progress_fraction*max(0,len(points)-1)))
        _,nearest_index=nearest_waypoint(position,points,max(0,self.progress.get(best,0)-1,equivalent))
        self.next_index=max(self.progress.get(best,0),equivalent,min(nearest_index+1,len(points)-1))
        if len(points)>1:self.progress_fraction=max(self.progress_fraction,nearest_index/(len(points)-1))
        self.progress[best]=self.next_index
        return best

    def record_start(self, name, minimum_distance_m=1.0, minimum_interval_s=0.5, arrival_radius_m=3.0):
        if self.recording is not None: raise RuntimeError('recording already active')
        distance=float(minimum_distance_m);interval=float(minimum_interval_s);arrival=float(arrival_radius_m)
        if not .1<=distance<=100:raise ValueError('minimum distance outside 0.1..100 m')
        if not .1<=interval<=60:raise ValueError('minimum interval outside 0.1..60 s')
        if not .5<=arrival<=100:raise ValueError('arrival radius outside 0.5..100 m')
        self.recording={'name':str(name).strip() or 'Recorded route', 'waypoints':[], 'saved_at':None,
                        'minimum_distance_m':distance,'minimum_interval_s':interval,
                        'arrival_radius_m':arrival,'last_point_monotonic':None}

    def record_point(self, lat,lon,heading=None, timestamp=None, minimum_m=1.0, now=None):
        if self.recording is None: return False
        points=self.recording['waypoints']
        now=time.monotonic() if now is None else float(now)
        if self.recording['last_point_monotonic'] is not None and now-self.recording['last_point_monotonic']<self.recording['minimum_interval_s']:return False
        if points and meters((points[-1]['lat'],points[-1]['lon']), (lat,lon)) < self.recording.get('minimum_distance_m',minimum_m): return False
        points.append({'timestamp':timestamp or dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='milliseconds'),
                       'lat':float(lat),'lon':float(lon),'heading_deg': None if heading is None else float(heading)%360})
        self.recording['last_point_monotonic']=now
        return True

    def record_stop(self):
        if self.recording is None: raise RuntimeError('recording was not started')
        if len(self.recording['waypoints']) < 2:
            raise ValueError('need at least 2 distinct waypoints; recording remains active')
        item=dict(self.recording)
        item['waypoints']=list(self.recording['waypoints'])
        item['id']='route_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        item['waypoints']=enrich_waypoints(item['waypoints'])
        item['arrival_radius_m']=item.pop('arrival_radius_m',3.0)
        item.pop('minimum_distance_m',None);item.pop('minimum_interval_s',None);item.pop('last_point_monotonic',None)
        item['recorded_at_start']=item['waypoints'][0]['timestamp']
        item['recorded_at_end']=item['waypoints'][-1]['timestamp']
        item['saved_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        self.data['routes'].append(item)
        try:_atomic_json(self.filename,self.data)
        except Exception:
            self.data['routes'].pop()
            raise
        self.recording=None
        self.load()
        return item['id']

    def record_cancel(self):
        if self.recording is None: raise RuntimeError('recording was not started')
        self.recording = None

    def delete(self, route_id):
        new=[r for r in self.data['routes'] if r['id']!=route_id]
        if len(new)==len(self.data['routes']): raise ValueError('route not found')
        self.data['routes']=new
        groups=[]
        for group in self.data.get('multipaths',[]):
            item=dict(group);item['route_ids']=[value for value in item.get('route_ids',[]) if value!=route_id]
            if item.get('default_route_id')==route_id:item['default_route_id']=item['route_ids'][0] if item['route_ids'] else ''
            if item['route_ids']:groups.append(item)
        self.data['multipaths']=groups
        valid_group_ids={str(item.get('id')) for item in groups}
        if str(self.data.get('selected_multipath_id') or '') not in valid_group_ids:self.data['selected_multipath_id']=''
        if self.selected==route_id:self.data['selected_route_id']=new[0]['id'] if new else ''
        _atomic_json(self.filename,self.data)
        self.load()

    def upsert(self, route_id, name, waypoints, arrival_radius_m=3.0):
        name=' '.join(str(name).split())
        if not name:raise ValueError('route name is required')
        points=enrich_waypoints(waypoints)
        if len(points)<2:raise ValueError('at least 2 waypoints are required')
        radius=float(arrival_radius_m)
        if not .5<=radius<=100:raise ValueError('arrival radius outside 0.5..100 m')
        route_id=str(route_id or '').strip()
        if not route_id:
            slug=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')[:32] or 'route'
            route_id=f'{slug}-{uuid.uuid4().hex[:8]}'
        item={'id':route_id,'name':name,'arrival_radius_m':radius,'waypoints':points,
              'saved_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        routes=[item if str(route.get('id'))==route_id else route for route in self.data['routes']]
        if not any(str(route.get('id'))==route_id for route in self.data['routes']):routes.append(item)
        self.data['routes']=routes
        if not self.data.get('selected_route_id'):self.data['selected_route_id']=route_id
        _atomic_json(self.filename,self.data);self.load()
        return route_id

    def set_test_route_ids(self, route_ids):
        ids=[str(route_id) for route_id in route_ids]
        if len(ids)!=len(set(ids)):raise ValueError('ground test route IDs must be distinct')
        missing=[route_id for route_id in ids if route_id not in self.routes]
        if missing:raise ValueError('unknown routes: '+','.join(missing))
        self.test_route_ids=ids
        if ids and self.selected not in ids:self.select(ids[0])

TRACKING_MODES=('HEADING','HEADING_CTE','LOS','PURE_PURSUIT')

def _route_polyline(route):
    points=route.get('path_waypoints') or []
    try:
        result=[(float(p['lat']),float(p['lon'])) if isinstance(p,dict)
                else (float(p[0]),float(p[1])) for p in points]
        return result if len(result)>=2 else []
    except (ValueError,TypeError,IndexError,KeyError):
        return []

def _ahead_point(position,points,lookahead_m):
    """Project onto the nearest segment, then interpolate a fixed distance forward."""
    _,i,_=nearest_route(position,points)
    a,b=points[i:i+2]
    px,py=local_xy(a,position);ex,ey=local_xy(a,b)
    denom=ex*ex+ey*ey
    fraction=clamp((px*ex+py*ey)/denom,0.0,1.0) if denom>1e-10 else 0.0
    remaining=float(lookahead_m)
    for j in range(i,len(points)-1):
        first=fraction if j==i else 0.0
        start,end=points[j:j+2]
        distance=meters(start,end)
        available=distance*(1-first)
        if remaining<=available and distance>1e-8:
            f=first+remaining/distance
            return (start[0]+(end[0]-start[0])*f,start[1]+(end[1]-start[1])*f)
        remaining-=available
    return points[-1]

def tracking_heading(gps,route,config):
    """Return guidance geometry; CTE > 0 means left of the oriented segment."""
    pos=(float(gps['latitude']),float(gps['longitude']))
    target=(float(route['target_lat']),float(route['target_lon']))
    desired=bearing(pos,target)
    mode=str(config.get('tracking_mode','HEADING')).upper()
    if mode not in TRACKING_MODES:raise ValueError('unsupported tracking_mode: '+mode)
    points=_route_polyline(route)
    lookahead=clamp(float(config.get('lookahead_base_m',2.0))+
                    max(0,float(gps.get('speed_mps') or 0))*float(config.get('lookahead_speed_gain_s',2.5)),
                    float(config.get('lookahead_min_m',2.0)),float(config.get('lookahead_max_m',10.0)))
    correction=0.0;cte=float(route.get('cross_track_error_m') or 0)
    used_target=target
    if mode!='HEADING':
        if not points:raise ValueError('polyline required for experimental tracking mode')
        _,i,cte=nearest_route(pos,points)
        if mode=='HEADING_CTE':
            correction=clamp(math.degrees(math.atan2(cte,lookahead))*0.5,-35,35)
            desired=(desired+correction)%360
        elif mode=='LOS':
            correction=clamp(math.degrees(math.atan2(cte,lookahead)),-60,60)
            desired=(bearing(points[i],points[i+1])+correction)%360
        elif mode=='PURE_PURSUIT':
            used_target=_ahead_point(pos,points,lookahead)
            desired=bearing(pos,used_target)
    return dict(controller_mode=mode,target_heading_deg=desired,
                cross_track_error_m=cte,cte_correction_deg=correction,
                lookahead_m=lookahead,lookahead_target_lat=used_target[0],
                lookahead_target_lon=used_target[1])

def navigation_command(gps, route, config, stopped_once=False):
    """Return steering demand and steady cruise per stable heading-error bands."""
    if not route or not gps or gps.get('heading_deg') is None: raise ValueError('heading and route required')
    pos=(gps['latitude'],gps['longitude'])
    target=(route['target_lat'],route['target_lon'])
    geometry=tracking_heading(gps,route,config)
    desired_heading=geometry['target_heading_deg']
    error=angle_error(desired_heading,float(gps['heading_deg']))
    magnitude=abs(error)
    center=int(config.get('steering_center',6000))
    low=int(config.get('steering_low',4900)); high=int(config.get('steering_high',7300))
    # Positive bearing error = clockwise/right. Calibrated NAV direction is inverse of base mapping.
    right_sign = -1 if bool(config.get('nav_invert_steering',True)) else 1
    demand=int(round(clamp(center+right_sign*error/90*(high-center if error*right_sign>=0 else center-low),low,high)))
    cruise=int(config.get('cruise_pwm',6650))
    stop=int(config.get('throttle_stop',6450))
    delta=cruise-stop
    if delta < 0: raise ValueError('current stable forward calibration expected')
    speed_fraction=1.0 if magnitude <= 35 else (1.0-0.35*(magnitude-35)/65 if magnitude<100 else 0.65)
    first_hard_turn = magnitude >= 150 and not stopped_once
    throttle=stop if first_hard_turn else int(round(stop+delta*speed_fraction))
    if bool(config.get('speed_feedback_enabled',False)) and gps.get('speed_mps') is not None:
        # Disabled by default. This is a bounded PWM experiment, not certified speed control.
        speed_error=float(config.get('target_speed_mps',0.6))-float(gps['speed_mps'])
        correction_pwm=clamp(speed_error*float(config.get('speed_kp_pwm_per_mps',30.0)),-30,30)
        throttle=int(round(clamp(throttle+correction_pwm,stop,int(config.get('throttle_forward_max',7000)))))
    if route.get('route_complete'): throttle=stop
    # desired rudder angle: positive means physical right after inverted NAV mapping.
    angle=(demand-center)/(high-center if demand>=center else center-low)*30
    # Convert to PHYSICAL convention: positive = right; NAV steering polarity is inverted.
    if bool(config.get('nav_invert_steering',True)):
        angle = -angle
    return dict(geometry,heading_error_deg=error,desired_steering_pwm=demand,
                desired_throttle_pwm=throttle,desired_rudder_angle_deg=angle,initial_turn_pause_requested=first_hard_turn)
