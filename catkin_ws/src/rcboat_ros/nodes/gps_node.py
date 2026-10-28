#!/usr/bin/env python3
"""Single GPS read/write owner; RTCM is forwarded into this process."""
import threading
import time
import datetime as dt
import rospy
from std_msgs.msg import String, UInt8MultiArray
from rcboat_ros.gps_mix import MixedGpsParser
from rcboat_ros.common import pack,gps_is_healthy,cno_quality
from rcboat_ros.geo import latlon_to_utm

def main():
    rospy.init_node('gps_node')
    import serial
    dev=rospy.get_param('/rcboat/gps_port')
    serial_port=serial.Serial(dev,int(rospy.get_param('/rcboat/gps_baudrate',115200)),timeout=.08,exclusive=True)
    io_lock=threading.Lock()
    parser=MixedGpsParser()
    def rtcm(msg):
        try:
            with io_lock:serial_port.write(bytes(msg.data))
        except (OSError,ValueError) as exc:rospy.logerr('RTCM forwarding failed: %s',exc)
    rospy.Subscriber('/rcboat/gps/rtcm',UInt8MultiArray,rtcm,queue_size=20)
    pub=rospy.Publisher('/rcboat/gps/status',String,queue_size=5)
    last_publish=0
    last_poll=0
    try:
        while not rospy.is_shutdown():
            try:
                with io_lock:data=serial_port.read(max(1,min(serial_port.in_waiting,4096)))
                parser.feed(data)
            except Exception as exc:
                rospy.logerr('GPS read fault %s',exc)
                pub.publish(pack(fix=False,healthy=False,data_validity='invalid',error=str(exc)))
                raise  # roslaunch respawns GPS only; manual RC control stays alive.
            now=time.monotonic()
            if now-last_poll>=1.0:
                try:
                    with io_lock:serial_port.write(b'\xb5\x62\x01\x07\x00\x00\x08\x19')
                except Exception as exc:rospy.logwarn('NAV-PVT polling failed %s',exc)
                last_poll=now
            if now-last_publish>=.25:
                result=dict(parser.state)
                update=float(result.get('last_update_monotonic') or 0)
                result['gps_data_age_s']=round(now-update,3) if update and now>=update else None
                result['age_s']=result['gps_data_age_s']
                result['received_time_utc']=dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
                result['measurement_time_utc']=result.get('utc_time')
                result['healthy']=gps_is_healthy(result,now,rospy.get_param('/rcboat/gps_stale_s',2.0))
                receiver_fix=bool(result.get('fix'))
                result['cno_quality']=cno_quality(result.get('cno_dbhz'))
                # A GNSS course-over-ground estimate is not actual hull heading.
                # This flag is diagnostic only; do not produce stop/go chatter.
                min_speed=float(rospy.get_param('/rcboat/course_min_speed_mps',0.35))
                if result.get('heading_deg') is None:
                    result['course_quality']='UNAVAILABLE'
                elif float(result.get('speed_mps') or 0)<min_speed:
                    result['course_quality']='LOW_SPEED'
                elif result.get('hacc_m') is not None and float(result['hacc_m'])>2.0:
                    result['course_quality']='LOW_POSITION_QUALITY'
                else:
                    result['course_quality']='MOVING_COG'
                # Only a missing/invalid/stale FIX clears navigation availability.
                # HDOP, hAcc, C/N0, speed and course quality are diagnostic only.
                if not result['healthy']:result['fix']=False
                result['data_validity']='valid' if result['healthy'] else ('stale' if receiver_fix else 'invalid')
                result['utm_easting_m']=None;result['utm_northing_m']=None;result['utm_zone']=None
                result['utm_status']='no_data'
                if result.get('latitude') is not None and result.get('longitude') is not None:
                    try:
                        easting,northing,zone=latlon_to_utm(result['latitude'],result['longitude'])
                        result.update(utm_easting_m=round(easting,3),utm_northing_m=round(northing,3),
                                      utm_zone=zone,utm_status='valid')
                    except (ValueError,TypeError):result['utm_status']='invalid'
                pub.publish(pack(**result));last_publish=now
    finally:serial_port.close()
if __name__=='__main__':main()
