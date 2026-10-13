from __future__ import annotations

import math
from collections import deque
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


EARTH_RADIUS_M = 6_371_000.0


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


class MetricCard(QFrame):
    """Compact GPS/RTK metric card with a separate readable threshold hint."""

    def __init__(self, title: str, hint: str = ""):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("-")
        self.value_label.setObjectName("metricValue")
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("metricHint")
        self.hint_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        if hint:
            layout.addWidget(self.hint_label)

    def set_value(self, value: str, level: str | None = None) -> None:
        self.value_label.setText(value)
        colors = {
            "GOOD": "#4ee0b0",
            "WARNING": "#f8bd58",
            "BAD": "#ff6474",
            "INFO": "#61caff",
        }
        color = colors.get(str(level or "").upper(), "#edf4ff")
        self.value_label.setStyleSheet(f"color:{color}; font-weight:800;")


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
    """Metric route viewer.

    Lat/lon data is projected to a local tangent plane in metres and rendered
    with one common x/y scale. This avoids the geographic distortion caused by
    independently stretching latitude and longitude to the widget bounds.
    """

    def __init__(self):
        super().__init__()
        self.routes: list[dict] = []
        self.position: tuple[float, float] | None = None
        self.active_id = ""
        self.visible_ids: set[str] = set()
        self._known_ids: set[str] = set()
        self._center_m = QPointF(0.0, 0.0)
        self._pixels_per_meter = 2.0
        self._auto_fit_pending = True
        self._dragging = False
        self._last_mouse = QPointF()
        self.setMinimumHeight(360)
        self.setMouseTracking(True)
        self.setToolTip(
            "마우스 왼쪽 드래그: 지도 이동 · 휠: 확대/축소 · 더블클릭: 전체 경로 맞춤"
        )

    @staticmethod
    def is_training_route(route: dict) -> bool:
        route_id = str(route.get("id") or "").lower()
        name = str(route.get("name") or "")
        return route_id.startswith("training_") or "훈련" in name

    def update_data(self, routes: list[dict], gps: dict, active_id: str) -> None:
        previous_ids = {str(route.get("id") or "") for route in self.routes}
        self.routes = list(routes)
        if gps.get("lat") is not None and gps.get("lon") is not None:
            self.position = (float(gps["lat"]), float(gps["lon"]))
        self.active_id = str(active_id or "")

        incoming_ids = {
            str(route.get("id") or "")
            for route in self.routes
            if route.get("id") and not self.is_training_route(route)
        }
        for route_id in incoming_ids - self._known_ids:
            self.visible_ids.add(route_id)
        self._known_ids |= incoming_ids
        self.visible_ids &= incoming_ids

        if incoming_ids != {
            route_id for route_id in previous_ids if route_id in self._known_ids
        }:
            self._auto_fit_pending = True
        self.update()

    def set_route_visible(self, route_id: str, visible: bool) -> None:
        route_id = str(route_id)
        if visible:
            self.visible_ids.add(route_id)
        else:
            self.visible_ids.discard(route_id)
        self._auto_fit_pending = True
        self.update()

    def set_visible_routes(self, route_ids: Iterable[str]) -> None:
        allowed = {
            str(route.get("id") or "")
            for route in self.routes
            if not self.is_training_route(route)
        }
        self.visible_ids = {str(value) for value in route_ids} & allowed
        self._auto_fit_pending = True
        self.update()

    def visible_route_ids(self) -> set[str]:
        return set(self.visible_ids)

    def fit_to_data(self) -> None:
        self._auto_fit_pending = True
        self.update()

    def _visible_routes(self) -> list[dict]:
        return [
            route
            for route in self.routes
            if not self.is_training_route(route)
            and str(route.get("id") or "") in self.visible_ids
        ]

    def _origin(self) -> tuple[float, float]:
        points: list[tuple[float, float]] = []
        for route in self._visible_routes():
            points.extend(
                (float(p["lat"]), float(p["lon"]))
                for p in route.get("waypoints", [])
                if p.get("lat") is not None and p.get("lon") is not None
            )
        if self.position is not None:
            points.append(self.position)
        if not points:
            return 0.0, 0.0
        return (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )

    @staticmethod
    def _to_local_m(
        lat: float, lon: float, origin: tuple[float, float]
    ) -> QPointF:
        lat0, lon0 = origin
        x = math.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
        y = math.radians(lat - lat0) * EARTH_RADIUS_M
        return QPointF(x, y)

    def _world_points(self, origin: tuple[float, float]) -> list[QPointF]:
        points: list[QPointF] = []
        for route in self._visible_routes():
            points.extend(
                self._to_local_m(float(p["lat"]), float(p["lon"]), origin)
                for p in route.get("waypoints", [])
                if p.get("lat") is not None and p.get("lon") is not None
            )
        if self.position:
            points.append(self._to_local_m(*self.position, origin))
        return points

    def _fit(self, area: QRectF, origin: tuple[float, float]) -> None:
        points = self._world_points(origin)
        if not points:
            self._center_m = QPointF(0.0, 0.0)
            self._pixels_per_meter = 2.0
            self._auto_fit_pending = False
            return

        xs = [point.x() for point in points]
        ys = [point.y() for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 20.0)
        span_y = max(max_y - min_y, 20.0)
        margin = 1.25
        scale_x = area.width() / (span_x * margin)
        scale_y = area.height() / (span_y * margin)
        self._pixels_per_meter = max(0.02, min(40.0, min(scale_x, scale_y)))
        self._center_m = QPointF((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        self._auto_fit_pending = False

    def _screen_point(self, world: QPointF, area: QRectF) -> QPointF:
        return QPointF(
            area.center().x() + (world.x() - self._center_m.x()) * self._pixels_per_meter,
            area.center().y() - (world.y() - self._center_m.y()) * self._pixels_per_meter,
        )

    def _nice_scale_distance(self, target_pixels: float = 110.0) -> float:
        raw = target_pixels / max(self._pixels_per_meter, 1e-9)
        exponent = math.floor(math.log10(max(raw, 1e-9)))
        base = 10 ** exponent
        for multiplier in (1, 2, 5, 10):
            candidate = multiplier * base
            if candidate >= raw:
                return candidate
        return 10 * base

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1423"))
        area = QRectF(self.rect()).adjusted(36, 34, -26, -38)

        origin = self._origin()
        if self._auto_fit_pending:
            self._fit(area, origin)

        visible = self._visible_routes()
        has_data = bool(visible or self.position)
        if not has_data:
            painter.setPen(QColor("#7f90aa"))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "표시할 기록 항로가 없습니다\n훈련 항로는 지도에서 제외됩니다",
            )
            return

        # Metric grid. Both axes use exactly the same pixels-per-metre scale.
        grid_m = self._nice_scale_distance(80.0)
        grid_px = grid_m * self._pixels_per_meter
        if 35.0 <= grid_px <= 260.0:
            painter.setPen(QPen(QColor("#17243a"), 1))
            center = area.center()
            offset_x = ((-self._center_m.x()) * self._pixels_per_meter) % grid_px
            x = area.left() + offset_x
            while x <= area.right():
                painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                x += grid_px
            offset_y = ((self._center_m.y()) * self._pixels_per_meter) % grid_px
            y = area.top() + offset_y
            while y <= area.bottom():
                painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
                y += grid_px

        palette = [
            QColor("#35c9ff"), QColor("#aa86ff"), QColor("#f8bd58"),
            QColor("#ff7fa5"), QColor("#70e08f"), QColor("#ff9a62"),
        ]
        for route in visible:
            route_id = str(route.get("id") or "")
            raw_points = [
                (float(p["lat"]), float(p["lon"]))
                for p in route.get("waypoints", [])
                if p.get("lat") is not None and p.get("lon") is not None
            ]
            world_points = [self._to_local_m(lat, lon, origin) for lat, lon in raw_points]
            screen_points = [self._screen_point(point, area) for point in world_points]
            if not screen_points:
                continue
            palette_index = sum(ord(ch) for ch in route_id) % len(palette)
            color = QColor("#4ee0b0") if route_id == self.active_id else palette[palette_index]
            painter.setPen(QPen(color, 4.0 if route_id == self.active_id else 2.3))
            for start, end in zip(screen_points, screen_points[1:]):
                painter.drawLine(start, end)
            painter.setBrush(color)
            painter.setPen(QPen(color, 1))
            radius = 4.0 if route_id == self.active_id else 3.0
            for point in screen_points:
                painter.drawEllipse(point, radius, radius)
            painter.setPen(QColor("#dbe8fb"))
            painter.setFont(QFont("Malgun Gothic", 9, QFont.DemiBold))
            painter.drawText(screen_points[0] + QPointF(8, -8), str(route.get("name") or route_id))

        if self.position:
            world = self._to_local_m(*self.position, origin)
            point = self._screen_point(world, area)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QColor("#ff6474"))
            painter.drawEllipse(point, 7, 7)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(point + QPointF(11, -9), "현재 보트")

        # North arrow.
        painter.setPen(QPen(QColor("#9fb0c9"), 2))
        north_x = area.right() - 18
        north_y = area.top() + 36
        painter.drawLine(QPointF(north_x, north_y + 22), QPointF(north_x, north_y))
        painter.drawLine(QPointF(north_x, north_y), QPointF(north_x - 5, north_y + 8))
        painter.drawLine(QPointF(north_x, north_y), QPointF(north_x + 5, north_y + 8))
        painter.drawText(QPointF(north_x - 5, north_y - 6), "N")

        # Metric scale bar.
        scale_m = self._nice_scale_distance()
        scale_px = scale_m * self._pixels_per_meter
        x0 = area.left() + 8
        y0 = area.bottom() - 8
        painter.setPen(QPen(QColor("#dbe8fb"), 3))
        painter.drawLine(QPointF(x0, y0), QPointF(x0 + scale_px, y0))
        painter.setPen(QColor("#9fb0c9"))
        label = f"{scale_m:g} m" if scale_m < 1000 else f"{scale_m / 1000:g} km"
        painter.drawText(QPointF(x0, y0 - 7), label)

        painter.setPen(QColor("#6f86a8"))
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.drawText(
            QPointF(area.left(), self.rect().bottom() - 10),
            "동일 축척 미터 좌표 · 드래그 이동 · 휠 확대/축소 · 더블클릭 전체 맞춤",
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_mouse = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            current = event.position()
            delta = current - self._last_mouse
            self._last_mouse = current
            scale = max(self._pixels_per_meter, 1e-9)
            self._center_m = QPointF(
                self._center_m.x() - delta.x() / scale,
                self._center_m.y() + delta.y() / scale,
            )
            self._auto_fit_pending = False
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() == 0:
            return
        area = QRectF(self.rect()).adjusted(36, 34, -26, -38)
        cursor = event.position()
        old_scale = max(self._pixels_per_meter, 1e-9)
        world_x = self._center_m.x() + (cursor.x() - area.center().x()) / old_scale
        world_y = self._center_m.y() - (cursor.y() - area.center().y()) / old_scale
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        new_scale = max(0.02, min(80.0, old_scale * factor))
        self._pixels_per_meter = new_scale
        self._center_m = QPointF(
            world_x - (cursor.x() - area.center().x()) / new_scale,
            world_y + (cursor.y() - area.center().y()) / new_scale,
        )
        self._auto_fit_pending = False
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.fit_to_data()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
