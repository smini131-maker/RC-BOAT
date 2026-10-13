"""ROS beta2 GPS tracking: baseline Heading plus experimental CTE/LOS/Pure Pursuit."""
import datetime as dt
import json
import math
import os
import time
from pathlib import Path
from .common import clamp

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

def _waypoints(route):
    return [(float(w['lat']), float(w['lon'])) for w in route.get('waypoints', [])]

def _atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name('.'+path.name+'.tmp')
    pending.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(pending, path)

class RouteManager:
    def __init__(self, filename, endpoint_tolerance=0.75, off_route=8.0, hold_s=3.0, advantage=2.0, cooldown=5.0):
        self.filename = Path(filename)
        self.endpoint_tolerance = float(endpoint_tolerance)
        self.off_route = float(off_route)
        self.hold_s = float(hold_s)
        self.advantage = float(advantage)
        self.cooldown = float(cooldown)
        self.recording = None
        self.load()
        self.off_since = None
        self.last_switch = None
        self.event = None

    def load(self):
        self.data = json.loads(self.filename.read_text(encoding='utf-8'))
        self.routes = {str(r['id']):r for r in self.data['routes'] if len(r.get('waypoints', [])) >= 1}
        if not self.routes: raise ValueError('no routes available')
        self.selected = self.data.get('selected_route_id') or next(iter(self.routes))
        if self.selected not in self.routes: self.selected = next(iter(self.routes))
        self.active = self.selected
        self.next_index = 0

    def select(self, route_id):
        if route_id not in self.routes: raise ValueError('route does not exist')
        self.data['selected_route_id'] = route_id
        _atomic_json(self.filename, self.data)
        self.selected = self.active = route_id
        self.next_index = 0
        self.off_since = self.last_switch = None

    def group(self):
        base = _waypoints(self.routes[self.selected])
        found = {}
        for name, route in self.routes.items():
            pts = _waypoints(route)
            d1, d2 = meters(base[0], pts[0]), meters(base[-1], pts[-1])
            if d1 <= self.endpoint_tolerance and d2 <= self.endpoint_tolerance:
                found[name] = {'start_gap_m': round(d1,3), 'end_gap_m': round(d2,3)}
        return found

    def update(self, position, now=None):
        now = time.monotonic() if now is None else now
        group = self.group()
        if self.active not in group:
            self.active = self.selected
            self.next_index = 0
        distances = {k:nearest_route(position,_waypoints(self.routes[k])) for k in group}
        current = distances[self.active][0]
        candidate = min(distances, key=lambda k: distances[k][0]); previous = self.active
        switched = False
        if current >= self.off_route and (self.last_switch is None or now-self.last_switch >= self.cooldown):
            if self.off_since is None: self.off_since=now
            if now-self.off_since >= self.hold_s and candidate != self.active and distances[candidate][0] <= current-self.advantage:
                self.active = candidate
                self.next_index = min(distances[candidate][1]+1, len(_waypoints(self.routes[candidate]))-1)
                switched=True
                self.last_switch=now
                self.off_since=None
        else:
            self.off_since = None
        route = self.routes[self.active]
        points = _waypoints(route)
        self.next_index = min(self.next_index, len(points)-1)
        # For dense routes keep at least one segment ahead; avoid repeatedly returning to old points.
        nearest_seg = nearest_route(position, points)[1]
        self.next_index = max(self.next_index, min(nearest_seg+1, len(points)-1))
        target = points[self.next_index]
        if meters(position,target) <= float(route.get('arrival_radius_m',1.0)) and self.next_index < len(points)-1:
            self.next_index+=1
            target=points[self.next_index]
        dwp=meters(position,target)
        cte=nearest_route(position, points)[2]
        self.event = {'type':'ROUTE_SWITCH','previous_route':previous,'candidate_route':candidate,'new_route':self.active,'monotonic':now} if switched else None
        return {'selected_route_id':self.selected,'active_route_id':self.active,'candidate_route_id':candidate,
                'group_routes':list(group),'endpoint_gaps':group,'off_route_time_s':round(now-self.off_since,3) if self.off_since else 0,
                'multipath_switch':switched,'previous_route': previous if switched else '',
                'target_waypoint_index':self.next_index,'target_lat':target[0],'target_lon':target[1],
                'path_waypoints':[{'lat':a,'lon':b} for a,b in points],
                'distance_to_waypoint_m':dwp,'cross_track_error_m':cte,'distance_to_route_m':nearest_route(position,points)[0],
                'route_complete':self.next_index==len(points)-1 and dwp <= float(route.get('arrival_radius_m',1.0))}

    def choose_nearest_group_route(self, position):
        """Operator-requested closest compatible start; reference route remains selected."""
        group=self.group()
        if not group: raise ValueError('no compatible route group')
        best=min(group,key=lambda k:nearest_route(position,_waypoints(self.routes[k]))[0])
        self.active=best
        self.next_index=min(nearest_route(position,_waypoints(self.routes[best]))[1]+1,
                            len(_waypoints(self.routes[best]))-1)
        self.off_since=None
        return best

    def record_start(self, name):
        if self.recording is not None: raise RuntimeError('recording already active')
        self.recording={'name':str(name).strip() or 'Recorded route', 'waypoints':[], 'saved_at':None}

    def record_point(self, lat,lon,heading=None, timestamp=None, minimum_m=1.0):
        if self.recording is None: return False
        points=self.recording['waypoints']
        if points and meters((points[-1]['lat'],points[-1]['lon']), (lat,lon)) < minimum_m: return False
        points.append({'timestamp':timestamp or dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='milliseconds'),
                       'lat':float(lat),'lon':float(lon),'heading_deg': None if heading is None else float(heading)%360})
        return True

    def record_stop(self):
        if self.recording is None: raise RuntimeError('recording was not started')
        item=self.recording; self.recording=None
        if len(item['waypoints']) < 2: raise ValueError('need at least 2 distinct waypoints')
        item['id']='recorded_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        item['arrival_radius_m']=1.5
        item['recorded_at_start']=item['waypoints'][0]['timestamp']
        item['recorded_at_end']=item['waypoints'][-1]['timestamp']
        item['saved_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        self.data['routes'].append(item)
        _atomic_json(self.filename,self.data)
        self.load()
        return item['id']

    def delete(self, route_id):
        if route_id.startswith('training_'): raise ValueError('training route protected')
        new=[r for r in self.data['routes'] if r['id']!=route_id]
        if len(new)==len(self.data['routes']): raise ValueError('route not found')
        if not new: raise ValueError('last route cannot be deleted')
        self.data['routes']=new
        if self.selected==route_id:self.data['selected_route_id']=new[0]['id']
        _atomic_json(self.filename,self.data)
        self.load()

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
