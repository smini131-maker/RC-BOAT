from __future__ import annotations

from collections import deque
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class StatusCard(QFrame):
    def __init__(self, title: str, value: str = "-"):
        super().__init__()
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("cardValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str, ok: bool | None = None) -> None:
        self.value_label.setText(value)
        if ok is None:
            color = "#e8eef8"
        else:
            color = "#38d996" if ok else "#ff6474"
        self.value_label.setStyleSheet(f"color: {color};")


class TelemetryGraph(QWidget):
    def __init__(self, title: str, min_value: float, max_value: float, colors: tuple[str, str]):
        super().__init__()
        self.title = title
        self.min_value = min_value
        self.max_value = max_value
        self.colors = [QColor(c) for c in colors]
        self.series = [deque(maxlen=180), deque(maxlen=180)]
        self.setMinimumHeight(180)

    def append(self, first: float | None, second: float | None) -> None:
        self.series[0].append(float(first) if first is not None else self.min_value)
        self.series[1].append(float(second) if second is not None else self.min_value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111a2b"))
        area = self.rect().adjusted(48, 30, -14, -24)
        painter.setPen(QPen(QColor("#26334a"), 1))
        for i in range(5):
            y = area.top() + area.height() * i / 4
            painter.drawLine(area.left(), int(y), area.right(), int(y))
        painter.setPen(QColor("#9fb0c9"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(14, 20, self.title)
        painter.drawText(8, area.top() + 5, f"{self.max_value:g}")
        painter.drawText(8, area.bottom(), f"{self.min_value:g}")
        span = max(1.0, self.max_value - self.min_value)
        for series, color in zip(self.series, self.colors):
            if len(series) < 2:
                continue
            path = QPainterPath()
            for idx, value in enumerate(series):
                x = area.left() + area.width() * idx / max(1, series.maxlen - 1)
                y = area.bottom() - area.height() * (value - self.min_value) / span
                if idx == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)


class RoutePlot(QWidget):
    def __init__(self):
        super().__init__()
        self.routes: list[dict] = []
        self.position: tuple[float, float] | None = None
        self.active_id = ""
        self.setMinimumHeight(250)

    def update_data(self, routes: list[dict], gps: dict, active_id: str) -> None:
        self.routes = routes
        if gps.get("lat") is not None and gps.get("lon") is not None:
            self.position = (float(gps["lat"]), float(gps["lon"]))
        self.active_id = active_id
        self.update()

    def _all_points(self) -> list[tuple[float, float]]:
        result = []
        for route in self.routes:
            result.extend((float(p["lat"]), float(p["lon"])) for p in route.get("waypoints", []))
        if self.position:
            result.append(self.position)
        return result

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0e1727"))
        area = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        points = self._all_points()
        if not points:
            painter.setPen(QColor("#7f90aa"))
            painter.drawText(self.rect(), Qt.AlignCenter, "표시할 항로 정보가 없습니다")
            return
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        lat_span = max(max(lats) - min(lats), 0.00005)
        lon_span = max(max(lons) - min(lons), 0.00005)

        def map_point(lat: float, lon: float) -> QPointF:
            x = area.left() + (lon - min(lons)) / lon_span * area.width()
            y = area.bottom() - (lat - min(lats)) / lat_span * area.height()
            return QPointF(x, y)

        palette = [QColor("#35c9ff"), QColor("#aa86ff"), QColor("#f8bd58")]
        for idx, route in enumerate(self.routes):
            pts = [map_point(float(p["lat"]), float(p["lon"])) for p in route.get("waypoints", [])]
            if len(pts) < 1:
                continue
            color = QColor("#38d996") if route.get("id") == self.active_id else palette[idx % len(palette)]
            painter.setPen(QPen(color, 3 if route.get("id") == self.active_id else 1.5))
            for a, b in zip(pts, pts[1:]):
                painter.drawLine(a, b)
            painter.setBrush(color)
            for pt in pts:
                painter.drawEllipse(pt, 4, 4)
        if self.position:
            pt = map_point(*self.position)
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(QColor("#ff6474"))
            painter.drawEllipse(pt, 7, 7)
            painter.drawText(pt + QPointF(10, -8), "현재 보트")
