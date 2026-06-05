from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from micromeasure.services.geometry import Pt

COLOR_DISTANCE = QColor(0, 220, 180)
COLOR_ANGLE = QColor(255, 210, 0)
COLOR_ORIGIN = QColor(255, 70, 160)
COLOR_REL = QColor(255, 140, 0)
COLOR_PERP = QColor(120, 200, 255)
COLOR_PREVIEW = QColor(160, 200, 255)
COLOR_SELECTED = QColor(255, 255, 255)

ARC_RADIUS = 38.0
_IGNORE_TF = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def make_line(a: Pt, b: Pt, color: QColor, width: int = 2, dashed: bool = False) -> QGraphicsLineItem:
    """A plain, non-interactive line (used for previews and perpendicular feet)."""
    item = QGraphicsLineItem(a.x, a.y, b.x, b.y)
    pen = QPen(color)
    pen.setWidth(width)
    pen.setCosmetic(True)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    item.setPen(pen)
    return item


def make_marker(p: Pt, color: QColor, radius: int = 3) -> QGraphicsEllipseItem:
    item = QGraphicsEllipseItem(-radius, -radius, 2 * radius, 2 * radius)
    item.setBrush(QBrush(color))
    pen = QPen(QColor(0, 0, 0))
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setPos(p.x, p.y)
    item.setFlag(_IGNORE_TF, True)
    return item


def arc_path(center: Pt, v1: Pt, v2: Pt, radius: float = ARC_RADIUS) -> QPainterPath:
    """Path of an arc at `center` sweeping from direction v1 to v2 (screen, y-down)."""
    a1 = math.atan2(v1.y, v1.x)
    a2 = math.atan2(v2.y, v2.x)
    sweep = a2 - a1
    while sweep <= -math.pi:
        sweep += 2 * math.pi
    while sweep > math.pi:
        sweep -= 2 * math.pi
    path = QPainterPath()
    steps = 28
    for i in range(steps + 1):
        t = a1 + sweep * (i / steps)
        x = center.x + radius * math.cos(t)
        y = center.y + radius * math.sin(t)
        if i == 0:
            path.moveTo(QPointF(x, y))
        else:
            path.lineTo(QPointF(x, y))
    return path


def make_arc(center: Pt, v1: Pt, v2: Pt, color: QColor) -> QGraphicsPathItem:
    item = QGraphicsPathItem(arc_path(center, v1, v2))
    pen = QPen(color)
    pen.setWidth(2)
    pen.setCosmetic(True)
    item.setPen(pen)
    return item


class LabelItem(QGraphicsItemGroup):
    """A constant-screen-size text label with a dark background, repositionable
    and re-textable in place."""

    def __init__(self, color: QColor) -> None:
        super().__init__()
        self._bg = QGraphicsRectItem()
        self._bg.setBrush(QBrush(QColor(0, 0, 0, 175)))
        self._bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._txt = QGraphicsSimpleTextItem()
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self._txt.setFont(font)
        self._txt.setBrush(QBrush(color))
        self.addToGroup(self._bg)
        self.addToGroup(self._txt)
        self.setFlag(_IGNORE_TF, True)
        self.setZValue(20)

    def set_text(self, text: str) -> None:
        self._txt.setText(text)
        br = self._txt.boundingRect()
        pad = 3.0
        self._bg.setRect(-pad, -pad, br.width() + 2 * pad, br.height() + 2 * pad)

    def set_anchor(self, p: Pt) -> None:
        self.setPos(p.x, p.y)


class MeasureLine(QGraphicsLineItem):
    """A selectable line that highlights when selected and has a fat hit area so
    it is easy to click."""

    def __init__(self, color: QColor, width: int = 2) -> None:
        super().__init__()
        self._color = color
        self._w = width
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(5)

    def set_pts(self, a: Pt, b: Pt) -> None:
        self.prepareGeometryChange()
        self.setLine(a.x, a.y, b.x, b.y)

    def endpoints(self) -> tuple[Pt, Pt]:
        ln = self.line()
        return Pt(ln.x1(), ln.y1()), Pt(ln.x2(), ln.y2())

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(self.line().p1())
        path.lineTo(self.line().p2())
        stroker = QPainterPathStroker()
        stroker.setWidth(10.0)
        return stroker.createStroke(path)

    def boundingRect(self):  # noqa: ANN201 (Qt override)
        return self.shape().boundingRect()

    def paint(self, painter, option, widget=None) -> None:  # noqa: N802
        selected = self.isSelected()
        pen = QPen(COLOR_SELECTED if selected else self._color)
        pen.setCosmetic(True)
        pen.setWidth(self._w + (2 if selected else 0))
        painter.setPen(pen)
        painter.drawLine(self.line())
