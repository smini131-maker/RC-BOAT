"""Real-time telemetry charts adapted from the existing v1.6.0 mission-control GUI."""
from collections import deque
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

class TelemetryGraph(QWidget):
    def __init__(self,title,min_value,max_value,colors):
        super().__init__()
        self.title=title
        self.min_value=float(min_value);self.max_value=float(max_value)
        self.colors=[QColor(c) for c in colors]
        self.series=[deque(maxlen=180),deque(maxlen=180)]
        self.setMinimumHeight(175)
    def append(self,first,second):
        self.series[0].append(float(first) if first is not None else self.min_value)
        self.series[1].append(float(second) if second is not None else self.min_value)
        self.update()
    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor('#111a2b'))
        area=self.rect().adjusted(49,30,-14,-24)
        painter.setPen(QPen(QColor('#27374e'),1))
        for i in range(5):
            y=area.top()+area.height()*i/4
            painter.drawLine(area.left(),int(y),area.right(),int(y))
        painter.setPen(QColor('#a7b8d0'));painter.setFont(QFont('Segoe UI',9))
        painter.drawText(12,20,self.title)
        painter.drawText(7,area.top()+5,f'{self.max_value:g}')
        painter.drawText(7,area.bottom(),f'{self.min_value:g}')
        span=max(1.,self.max_value-self.min_value)
        for data,color in zip(self.series,self.colors):
            if len(data)<2:continue
            path=QPainterPath()
            for i,v in enumerate(data):
                x=area.left()+area.width()*i/max(1,data.maxlen-1)
                y=area.bottom()-area.height()*(v-self.min_value)/span
                if i==0:path.moveTo(x,y)
                else:path.lineTo(x,y)
            painter.setPen(QPen(color,2))
            painter.drawPath(path)
