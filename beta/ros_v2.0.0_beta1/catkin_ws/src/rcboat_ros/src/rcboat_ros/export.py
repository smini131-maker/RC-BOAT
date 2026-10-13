"""Export experimental CSV, QGIS layers, summary; paths remain relative to experiment."""
import csv
import json
import math
import pathlib
import shutil

CSV_QGIS=['Index','TimeStep','Timestamp','Latitude','Longitude','Heading','ActiveRoute']

def _float(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def export_experiment(folder, routes=None, matlab_source=None):
    folder=pathlib.Path(folder)
    path=folder/'raw/path_tracking.csv'
    with path.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    qgis=folder/'qgis';qgis.mkdir(exist_ok=True)
    with (qgis/'actual_track.csv').open('w',newline='',encoding='utf-8') as out:
        w=csv.writer(out);w.writerow(CSV_QGIS)
        for r in rows:
            if _float(r['latitude']) is None or _float(r['longitude']) is None:continue
            w.writerow([r['index'],r['elapsed_time_s'],r['timestamp'],r['latitude'],r['longitude'],r['heading_deg'],r['active_route_id']])
    routes=routes or []
    for side in ('left','center','right'):
        route=next((r for r in routes if side in r.get('id','').lower() or r.get('name','').lower()==side.upper()),None)
        with (qgis/('target_'+side+'.csv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['Index','Latitude','Longitude'])
            if route:
                for i,p in enumerate(route.get('waypoints',[]),start=1):w.writerow([i,p['lat'],p['lon']])
    if matlab_source and pathlib.Path(matlab_source).is_file():
        mdir=folder/'matlab';mdir.mkdir(exist_ok=True)
        shutil.copy2(matlab_source,mdir/'analyze_path_tracking.m')
    stats=lambda values,default=None:sum(values)/len(values) if values else default
    good=[r for r in rows if str(r.get('gps_fix','')).lower() in ('true','1')]
    err=[abs(x) for r in rows if (x:=_float(r.get('heading_error_deg'))) is not None]
    xt=[abs(x) for r in rows if (x:=_float(r.get('cross_track_error_m'))) is not None]
    sp=[x for r in rows if (x:=_float(r.get('speed_mps'))) is not None]
    stamps=[x for r in rows if (x:=_float(r.get('elapsed_time_s'))) is not None]
    duration=max(stamps)-min(stamps) if len(stamps)>1 else 0
    fixed=sum(1 for r in rows if r.get('rtk_state')=='RTK_FIXED')
    switches=sum(1 for r in rows if str(r.get('multipath_switch','')).lower() in ('true','1'))
    gps_times=sorted(set(x for r in rows if (x:=_float(r.get('gps_update_monotonic'))) is not None and x>0))
    gps_rate=(len(gps_times)-1)/(gps_times[-1]-gps_times[0]) if len(gps_times)>1 and gps_times[-1]>gps_times[0] else None
    summary={'Duration_s':duration,'Samples':len(rows),'Mean_GPS_Rate_Hz':gps_rate,
             'Mean_CSV_Sample_Rate_Hz':(len(rows)-1)/duration if duration>0 else None,
             'Mean_Speed_mps':stats(sp),'Max_Heading_Error_deg':max(err,default=None),
             'Mean_Abs_Heading_Error_deg':stats(err),'Max_Cross_Track_Error_m':max(xt,default=None),
             'Mean_Cross_Track_Error_m':stats(xt),'Multi_Path_Switch_Count':switches,
             'Initial_Route':rows[0].get('active_route_id') if rows else None,
             'Final_Route':rows[-1].get('active_route_id') if rows else None,
             'RTK_Fixed_Ratio':fixed/len(rows) if rows else None,
             'GPS_Dropouts':sum(1 for i,r in enumerate(rows) if i>0 and str(rows[i-1].get('gps_fix','')).lower() in ('true','1') and str(r.get('gps_fix','')).lower() not in ('true','1'))}
    (folder/'summary.txt').write_text('\n'.join(f'{k}: {v}' for k,v in summary.items())+'\n',encoding='utf-8')
    (folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary
