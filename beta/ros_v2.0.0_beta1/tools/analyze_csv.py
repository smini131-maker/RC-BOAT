#!/usr/bin/env python3
"""Optional Python QA plots; MATLAB script remains the required primary analysis."""
import argparse
import csv
import pathlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def graph(t,y,label,title,output,switches=None,zero=False,ylims=None):
    fig,ax=plt.subplots(figsize=(9,4.5))
    if title=='Time vs Rudder Angle':
        ax.plot(t,y,color='#aaaaaa',linewidth=.9, label='Rudder desired')
        ax.plot(t,[v if v<=0 else float('nan') for v in y],color='blue',label='Left',linewidth=1.5)
        ax.plot(t,[v if v>=0 else float('nan') for v in y],color='red',label='Right',linewidth=1.5)
        ax.legend()
    else:
        ax.plot(t,y,label=label,linewidth=1.6)
    if zero:ax.axhline(0,linestyle='--',linewidth=.9)
    for s in switches or []:ax.axvline(s,linestyle=':',linewidth=.8)
    if ylims:ax.set_ylim(*ylims)
    ax.set_xlabel('Time [s]');ax.set_ylabel(label);ax.set_title(title);ax.grid(True,alpha=.3)
    fig.tight_layout();fig.savefig(output,dpi=150);plt.close(fig)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('csv');ap.add_argument('--plots',default=None)
    args=ap.parse_args()
    rows=list(csv.DictReader(open(args.csv,encoding='utf-8-sig',newline='')))
    if not rows:raise SystemExit('No samples')
    out=pathlib.Path(args.plots) if args.plots else pathlib.Path(args.csv).parent.parent/'plots'
    out.mkdir(parents=True,exist_ok=True)
    numeric=lambda key:[float(x[key]) if x.get(key) not in ('',None,'None') else float('nan') for x in rows]
    ts=numeric('elapsed_time_s');switch=[float(x['elapsed_time_s']) for x in rows if x.get('multipath_switch','').lower() in ('true','1')]
    for col,label,title,file,axis in [
      ('desired_rudder_angle_deg','Rudder Angle [deg]','Time vs Rudder Angle','steering_angle.png',None),
      ('heading_error_deg','Heading Error [deg]','Time vs Heading Error','heading_error.png',(-180,180)),
      ('speed_mps','Speed [m/s]','Time vs Speed','speed.png',None),
      ('cross_track_error_m','Cross Track Error [m]','Cross Track Error','cross_track_error.png',None)]:
        graph(ts,numeric(col),label,title,out/file,switch,zero=col not in ('speed_mps',),ylims=axis)
if __name__=='__main__':main()
