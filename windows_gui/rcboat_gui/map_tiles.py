"""Opt-in OSM raster background, bounded asynchronous requests and native disk cache."""
import math
from collections import OrderedDict
from PySide6.QtCore import QUrl,QRectF,QStandardPaths
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkDiskCache

class TileLayer:
    def __init__(self,widget):
        self.widget=widget;self.enabled=False;self.pending={};self.tiles=OrderedDict();self.failed=set()
        self.network=QNetworkAccessManager(widget);cache=QNetworkDiskCache(widget)
        cache.setCacheDirectory(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)+'/map_tiles')
        cache.setMaximumCacheSize(32*1024*1024);self.network.setCache(cache)

    def set_enabled(self,value):
        self.enabled=bool(value)
        if self.enabled:self.failed.clear()
        if not self.enabled:
            for reply in list(self.pending.values()):reply.abort()
        self.widget.update()

    def request(self,key):
        if key in self.pending or key in self.failed or len(self.pending)>=4:return
        z,x,y=key;req=QNetworkRequest(QUrl(f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'))
        req.setRawHeader(b'User-Agent',b'RCBoatControl/2.4.5 (desktop mission map; no prefetch)')
        req.setTransferTimeout(4000);req.setAttribute(QNetworkRequest.CacheLoadControlAttribute,QNetworkRequest.PreferCache)
        reply=self.network.get(req);self.pending[key]=reply
        reply.finished.connect(lambda:self.finished(key,reply))

    def finished(self,key,reply):
        self.pending.pop(key,None);raw=bytes(reply.readAll());pix=QPixmap()
        if len(raw)<=512000 and pix.loadFromData(raw):
            self.tiles[key]=pix
            while len(self.tiles)>32:self.tiles.popitem(last=False)
        else:self.failed.add(key)
        reply.deleteLater();self.widget.update()

    def draw(self,painter,area,origin,center,ppm):
        if not self.enabled or not self.widget.isVisible():return
        radius=6371000.;lat0,lon0=origin;cos=max(.01,math.cos(math.radians(lat0)))
        lat=max(-85,min(85,lat0+math.degrees(center.y()/radius)));lon=lon0+math.degrees(center.x()/(radius*cos))
        zoom=max(2,min(19,round(math.log2(max(.001,ppm)*2*math.pi*radius*cos/256))))
        n=2**zoom;cx=(lon+180)/360*n;cy=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
        tile_pixels=max(1,2*math.pi*radius*cos/n*ppm)
        rx=min(5,math.ceil(area.width()/tile_pixels/2)+1);ry=min(4,math.ceil(area.height()/tile_pixels/2)+1)
        painter.save();painter.setClipRect(area)
        for x in range(int(cx)-rx,int(cx)+rx+1):
            for y in range(max(0,int(cy)-ry),min(n,int(cy)+ry+1)):
                key=(zoom,x%n,y)
                a=self.widget._to_local_m(math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n)))),x/n*360-180,origin)
                b=self.widget._to_local_m(math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+1)/n)))),(x+1)/n*360-180,origin)
                aa=self.widget._screen_point(a,area);bb=self.widget._screen_point(b,area);rect=QRectF(aa,bb).normalized()
                if not rect.intersects(area):continue
                if key in self.tiles:painter.drawPixmap(rect,self.tiles[key],QRectF(self.tiles[key].rect()))
                else:self.request(key)
        painter.restore();painter.setPen(QColor('#b8c7d8'))
        painter.drawText(area.adjusted(4,0,-4,-3),0x22,'© OpenStreetMap contributors')
