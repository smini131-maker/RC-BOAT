"""Actual mixed NMEA / UBX NAV-PVT receiver. No simulated coordinates."""
import datetime as dt
import math
import struct
import time

class MixedGpsParser:
    def __init__(self):
        self.buffer=bytearray()
        self.state={'fix':False,'latitude':None,'longitude':None,'heading_deg':None,'speed_mps':0,
                    'hdop':99.99,'pdop':None,'vdop':None,'hacc_m':None,'rtk_state':'NO_RTK',
                    'satellites':0,'cno_dbhz':None,'fix_type':0,'last_valid_monotonic':0,
                    'last_update_monotonic':0,'utc_time':None,'utc_status':'no_data',
                    'heading_source':'unsupported','ubx_count':0,'nmea_count':0,'error_count':0}
        self.snrs=[]
        self.last_pvt=0.0
    @staticmethod
    def nmea_coord(raw, hemi):
        n=2 if hemi in ('N','S') else 3
        deg=float(raw[:n])+float(raw[n:])/60
        return -deg if hemi in ('W','S') else deg
    def feed(self,data):
        self.buffer.extend(data)
        if len(self.buffer)>65536: del self.buffer[:-65536]
        while self.buffer:
            p=self.buffer.find(b'$'); q=self.buffer.find(b'\xb5\x62')
            starts=[x for x in (p,q) if x>=0]
            if not starts:
                if len(self.buffer)>1: del self.buffer[:-1]
                return
            if min(starts): del self.buffer[:min(starts)]
            if self.buffer[0]==36:
                ending=self.buffer.find(b'\n')
                if ending<0:
                    if len(self.buffer)>200: del self.buffer[:1]
                    return
                chunk=bytes(self.buffer[:ending+1]); del self.buffer[:ending+1]
                try: self._nmea(chunk.strip().decode('ascii'))
                except (ValueError,IndexError,UnicodeError): self.state['error_count']+=1
            else:
                if len(self.buffer)<8:return
                size=int.from_bytes(self.buffer[4:6],'little')
                if size>4096: del self.buffer[0]; continue
                if len(self.buffer)<size+8:return
                frame=bytes(self.buffer[:size+8]); del self.buffer[:size+8]
                a=b=0
                for v in frame[2:-2]: a=(a+v)&255; b=(b+a)&255
                if bytes((a,b))!=frame[-2:]: self.state['error_count']+=1;continue
                self.state['ubx_count']+=1
                if frame[2:4]==b'\x01\x07' and size>=92:self._nav_pvt(frame[6:-2])
    def _valid(self):
        a=self.state
        if a.get('fix') and a['latitude'] is not None and a['longitude'] is not None:
            a['last_valid_monotonic']=time.monotonic()
    def _nmea(self,line):
        if '*' not in line:return
        payload, checksum=line[1:].split('*',1)
        v=0
        for c in payload:v^=ord(c)
        if v!=int(checksum[:2],16): raise ValueError('NMEA checksum')
        cells=payload.split(','); kind=cells[0][-3:]
        a=self.state; a['nmea_count']+=1; a['last_update_monotonic']=time.monotonic()
        if kind=='GGA' and len(cells)>9:
            fix=int(cells[6] or 0)
            use_nmea_solution=(time.monotonic()-self.last_pvt)>1.5
            if use_nmea_solution:a['fix']=fix>0
            a['satellites']=int(cells[7] or 0)
            if cells[8]: a['hdop']=float(cells[8])
            if use_nmea_solution and fix and cells[2] and cells[4]:
                a['latitude']=self.nmea_coord(cells[2],cells[3]); a['longitude']=self.nmea_coord(cells[4],cells[5]); self._valid()
            q={0:'NO_RTK',1:'NO_RTK',2:'DGPS',4:'RTK_FIXED',5:'RTK_FLOAT'}
            if use_nmea_solution:a['rtk_state']=q.get(fix,'NO_RTK')
            if cells[1]:
                try:
                    raw=cells[1];hour=int(raw[0:2]);minute=int(raw[2:4]);second=float(raw[4:])
                    today=dt.datetime.now(dt.timezone.utc).date()
                    stamp=dt.datetime(today.year,today.month,today.day,hour,minute,int(second),
                                      int((second%1)*1000000),tzinfo=dt.timezone.utc)
                    a['utc_time']=stamp.isoformat(timespec='milliseconds').replace('+00:00','Z');a['utc_status']='valid'
                except (ValueError,IndexError):a['utc_status']='invalid'
        elif kind=='RMC' and len(cells)>8:
            if (time.monotonic()-self.last_pvt)>1.5 and cells[2]=='A' and cells[3] and cells[5]:
                a['latitude']=self.nmea_coord(cells[3],cells[4]); a['longitude']=self.nmea_coord(cells[5],cells[6]); a['fix']=True
                if cells[7]:a['speed_mps']=float(cells[7])*0.5144444444
                if cells[8]:a['heading_deg']=float(cells[8])%360
                if cells[8]:a['heading_source']='GNSS_COG_NMEA'
                self._valid()
        elif kind=='GSA' and len(cells)>=17:
            if cells[15]:a['pdop']=float(cells[15])
            if cells[16]:a['hdop']=float(cells[16])
            if len(cells)>17 and cells[17]:a['vdop']=float(cells[17])
        elif kind=='GSV' and len(cells)>7:
            for j in range(7,len(cells),4):
                if cells[j].isdigit():self.snrs.append(int(cells[j]))
            if self.snrs:
                a['cno_dbhz']=sum(self.snrs[-64:])/len(self.snrs[-64:])
                if len(self.snrs)>128:self.snrs=self.snrs[-64:]
    def _nav_pvt(self,p):
        self.last_pvt=time.monotonic()
        a=self.state
        # u-blox UBX-NAV-PVT payload offsets, units from Interface Description.
        fix=p[20]; flags=p[21]; flags2=p[22]; sats=p[23]
        lon=struct.unpack_from('<i',p,24)[0]*1e-7
        lat=struct.unpack_from('<i',p,28)[0]*1e-7
        hacc=struct.unpack_from('<I',p,40)[0]*0.001
        speed=struct.unpack_from('<i',p,60)[0]*0.001
        head=struct.unpack_from('<i',p,64)[0]*1e-5
        pdop=struct.unpack_from('<H',p,76)[0]*0.01
        carr=(flags>>6)&3
        a.update(fix_type=fix,satellites=sats,hacc_m=hacc,pdop=pdop,speed_mps=max(0,speed),last_update_monotonic=time.monotonic())
        try:
            year=struct.unpack_from('<H',p,4)[0];month=p[6];day=p[7];hour=p[8];minute=p[9];second=p[10]
            if (p[11]&3)==3 and 1980<=year<=2200:
                stamp=dt.datetime(year,month,day,hour,minute,second,tzinfo=dt.timezone.utc)
                a['utc_time']=stamp.isoformat(timespec='seconds').replace('+00:00','Z');a['utc_status']='valid'
            else:a['utc_status']='invalid'
        except (ValueError,IndexError,struct.error):a['utc_status']='invalid'
        a['fix']=fix>=2 and bool(flags&1)
        if a['fix']:
            a.update(latitude=lat,longitude=lon,heading_deg=head%360)
            a['heading_source']='GNSS_COG_UBX'
            self._valid()
        a['rtk_state']='RTK_FIXED' if carr==2 else 'RTK_FLOAT' if carr==1 else ('DGPS' if flags&2 else 'NO_RTK')
