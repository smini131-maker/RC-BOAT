"""Persist the supported GNSS diagnostic setting outside the source checkout."""
import json
import math
import os
from pathlib import Path


def validate_hdop(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .5<=value<=20:
        raise ValueError('HDOP reference must be a finite number in 0.5..20')
    return float(value)


def load_hdop(path,default=3.0):
    path=Path(path)
    if not path.exists():return validate_hdop(default)
    return validate_hdop(json.loads(path.read_text(encoding='utf-8'))['navigation_max_hdop'])


def save_hdop(path,value):
    value=validate_hdop(value)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps({'navigation_max_hdop':value},indent=2)+'\n',encoding='utf-8')
    os.replace(str(temporary),str(path))
