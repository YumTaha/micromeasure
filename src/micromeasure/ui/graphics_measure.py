from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene

from micromeasure.services import geometry as g
from micromeasure.services.geometry import Pt
from micromeasure.services.measurements import KIND_ANGLE, KIND_DISTANCE, KIND_PERP, KIND_REL_ANGLE
from micromeasure.ui import items

_MOVABLE = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
_SENDS_GEOM = QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
_POS_CHANGED = QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged

# A line reference for linked angles: (measurement-id, line-index). The origin
# uses the reserved id 0.
LineRef = tuple[int, int]


@dataclass
class MRecord:
    """Serializable snapshot of one measurement (for per-image save/restore)."""

    mid: int
    tag: str
    points: list[Pt]
    src: tuple[LineRef, LineRef] | None = None


@dataclass
class MeasureContext:
    scale_provider: Callable[[], float]
    origin_provider: Callable[[], tuple[Pt, Pt] | None]


class Handle(QGraphicsEllipseItem):
    """A draggable point. Notifies its owning measurement on every move."""

    # extra clickable padding (scene units) so the small dot is still easy to grab
    _HIT_PAD = 7.0

    def __init__(self, owner: "BaseMeasurement", p: Pt, color: QColor, radius: int = 1) -> None:
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self._owner = owner
        self.setBrush(QBrush(color))
        pen = QPen(QColor(0, 0, 0))
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(30)
        self.setFlag(_MOVABLE, True)
        self.setFlag(_SENDS_GEOM, True)
        self.setPos(p.x, p.y)

    def point(self) -> Pt:
        sp = self.scenePos()
        return Pt(sp.x(), sp.y())

    def boundingRect(self):  # noqa: ANN201 (Qt override)
        return self.rect().adjusted(-self._HIT_PAD, -self._HIT_PAD, self._HIT_PAD, self._HIT_PAD)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self.boundingRect())
        return path

    def itemChange(self, change, value):  # noqa: N802
        if change == _POS_CHANGED:
            self._owner.handle_moved()
        return super().itemChange(change, value)


class BaseMeasurement:
    kind = "?"
    tag = "?"

    def __init__(self, scene: QGraphicsScene, pts: list[Pt], ctx: MeasureContext) -> None:
        self._scene = scene
        self._ctx = ctx
        self.mid = -1
        self.notify: Callable[["BaseMeasurement"], None] | None = None
        self.value = math.nan
        self.unit = ""
        self.detail = ""
        self._items: list[QGraphicsItem] = []
        self.handles: list[Handle] = []
        self.lines: list[items.MeasureLine] = []
        self.selectables: list[QGraphicsItem] = []
        self._build(pts)

    # -- helpers ----------------------------------------------------------
    def _add(self, item: QGraphicsItem) -> QGraphicsItem:
        self._scene.addItem(item)
        self._items.append(item)
        return item

    def _add_handle(self, p: Pt, color: QColor) -> Handle:
        h = Handle(self, p, color)
        self._scene.addItem(h)
        self.handles.append(h)
        return h

    def _add_line(self, color: QColor, width: int = 2) -> items.MeasureLine:
        ln = items.MeasureLine(color, width)
        self._scene.addItem(ln)
        self._items.append(ln)
        self.lines.append(ln)
        self.selectables.append(ln)
        return ln

    def _add_label(self, color: QColor) -> items.LabelItem:
        lbl = items.LabelItem(color)
        self._scene.addItem(lbl)
        self._items.append(lbl)
        return lbl

    def pts(self) -> list[Pt]:
        return [h.point() for h in self.handles]

    def handle_moved(self) -> None:
        if self.notify is not None:
            self.notify(self)

    def is_selected(self) -> bool:
        return any(s.isSelected() for s in self.selectables)

    def remove(self) -> None:
        for it in self._items + self.handles:
            if it.scene() is not None:
                it.scene().removeItem(it)
        self._items.clear()
        self.handles.clear()
        self.lines.clear()

    def line_for_selection(self) -> tuple[Pt, Pt] | None:
        return None

    def to_record(self) -> MRecord:
        return MRecord(mid=self.mid, tag=self.tag, points=self.pts())

    def display_id(self) -> str:
        """Identifier shown next to the drawing and in the CSV `#` column."""
        return str(self.mid)

    # -- subclass hooks ---------------------------------------------------
    def _build(self, pts: list[Pt]) -> None:
        raise NotImplementedError

    def recompute(self) -> None:
        raise NotImplementedError


class DistanceM(BaseMeasurement):
    kind = KIND_DISTANCE
    tag = "distance"

    def _build(self, pts: list[Pt]) -> None:
        self._line = self._add_line(items.COLOR_DISTANCE)
        self._add_handle(pts[0], items.COLOR_DISTANCE)
        self._add_handle(pts[1], items.COLOR_DISTANCE)
        self._label = self._add_label(items.COLOR_DISTANCE)

    def recompute(self) -> None:
        a, b = self.pts()
        self._line.set_pts(a, b)
        px = g.distance(a, b)
        scale = self._ctx.scale_provider()
        if math.isfinite(scale):
            self.value, self.unit, self.detail = px * scale, "mm", f"{px:.1f} px"
            self._label.set_text(f"#{self.display_id()}  {self.value:.4f} mm")
        else:
            self.value, self.unit, self.detail = px, "px", "uncalibrated"
            self._label.set_text(f"#{self.display_id()}  {px:.1f} px")
        self._label.set_anchor(g.midpoint(a, b))

    def line_for_selection(self) -> tuple[Pt, Pt] | None:
        return tuple(self.pts())  # type: ignore[return-value]


def _extension(a: Pt, b: Pt, inter: Pt) -> tuple[Pt, Pt] | None:
    """Segment from the near endpoint of a-b out to `inter`, or None if `inter`
    already lies within the drawn segment (no extension needed)."""
    abx = b.x - a.x
    aby = b.y - a.y
    denom = abx * abx + aby * aby
    if denom == 0:
        return None
    t = ((inter.x - a.x) * abx + (inter.y - a.y) * aby) / denom
    if 0.0 <= t <= 1.0:
        return None
    near = a if t < 0 else b
    return near, inter


def _apply_extension(line, a: Pt, b: Pt, inter: Pt | None) -> None:
    ext = _extension(a, b, inter) if inter is not None else None
    if ext is None:
        line.setVisible(False)
    else:
        line.setLine(ext[0].x, ext[0].y, ext[1].x, ext[1].y)
        line.setVisible(True)


def _angle_geometry(a1: Pt, b1: Pt, a2: Pt, b2: Pt):
    """Return (value_deg, center, v1, v2) for the angle between lines a1-b1 and
    a2-b2, using rays from the intersection toward each line's far endpoint."""
    value = g.angle_at_vertex(a1, b1, a2, b2)
    inter = g.line_intersection(a1, b1, a2, b2)
    if inter is None:
        center = g.midpoint(g.midpoint(a1, b1), g.midpoint(a2, b2))
        v1 = Pt(b1.x - a1.x, b1.y - a1.y)
        v2 = Pt(b2.x - a2.x, b2.y - a2.y)
    else:
        center = inter
        e1 = a1 if g.distance(inter, a1) >= g.distance(inter, b1) else b1
        e2 = a2 if g.distance(inter, a2) >= g.distance(inter, b2) else b2
        v1 = Pt(e1.x - inter.x, e1.y - inter.y)
        v2 = Pt(e2.x - inter.x, e2.y - inter.y)
    return value, center, v1, v2, inter


class Angle4M(BaseMeasurement):
    kind = KIND_ANGLE
    tag = "angle4"

    def _build(self, pts: list[Pt]) -> None:
        faded = QColor(items.COLOR_ANGLE)
        faded.setAlpha(110)
        self._ext1 = self._add(items.make_line(pts[0], pts[0], faded, width=1, dashed=True))
        self._ext2 = self._add(items.make_line(pts[0], pts[0], faded, width=1, dashed=True))
        self._l1 = self._add_line(items.COLOR_ANGLE)
        self._l2 = self._add_line(items.COLOR_ANGLE)
        for p in pts:
            self._add_handle(p, items.COLOR_ANGLE)
        self._arc = self._add(items.make_arc(pts[0], Pt(1, 0), Pt(1, 0), items.COLOR_ANGLE))
        self._label = self._add_label(items.COLOR_ANGLE)

    def recompute(self) -> None:
        p1, p2, p3, p4 = self.pts()
        self._l1.set_pts(p1, p2)
        self._l2.set_pts(p3, p4)
        self.unit, self.detail = "°", "angle between 2 lines"
        self.value, center, v1, v2, inter = _angle_geometry(p1, p2, p3, p4)
        _apply_extension(self._ext1, p1, p2, inter)
        _apply_extension(self._ext2, p3, p4, inter)
        self._arc.setPath(items.arc_path(center, v1, v2))
        self._label.set_text(f"#{self.display_id()}  {self.value:.2f}°")
        self._label.set_anchor(center)


class RelAngleM(BaseMeasurement):
    kind = KIND_REL_ANGLE
    tag = "rel"

    def _build(self, pts: list[Pt]) -> None:
        self._line = self._add_line(items.COLOR_REL)
        self._add_handle(pts[0], items.COLOR_REL)
        self._add_handle(pts[1], items.COLOR_REL)
        self._label = self._add_label(items.COLOR_REL)

    def recompute(self) -> None:
        a, b = self.pts()
        self._line.set_pts(a, b)
        origin = self._ctx.origin_provider()
        if origin is None:
            self.value, self.unit, self.detail = math.nan, "°", "no origin"
            self._label.set_text(f"#{self.display_id()}  (no origin)")
        else:
            rel = g.relative_angle_deg(origin[0], origin[1], a, b)
            self.value = -g.fold_to_axis(rel)  # flipped sign convention
            self.unit, self.detail = "°", "vs origin (folded ±45)"
            self._label.set_text(f"#{self.display_id()}  {self.value:+.2f}°")
        self._label.set_anchor(g.midpoint(a, b))

    def line_for_selection(self) -> tuple[Pt, Pt] | None:
        return tuple(self.pts())  # type: ignore[return-value]


class PointPerpM(BaseMeasurement):
    kind = KIND_PERP
    tag = "perp"

    def _build(self, pts: list[Pt]) -> None:
        self._foot = self._add(items.make_line(pts[0], pts[0], items.COLOR_PERP, dashed=True))
        self._add_handle(pts[0], items.COLOR_PERP)
        self._label = self._add_label(items.COLOR_PERP)

    def recompute(self) -> None:
        (p,) = self.pts()
        origin = self._ctx.origin_provider()
        if origin is None:
            self.value, self.unit, self.detail = math.nan, "px", "no origin"
            self._foot.setLine(p.x, p.y, p.x, p.y)
            self._label.set_text(f"#{self.display_id()}  (no origin)")
            self._label.set_anchor(p)
            return
        foot = g.project_point(p, origin[0], origin[1])
        self._foot.setLine(p.x, p.y, foot.x, foot.y)
        px = g.distance(p, foot)
        scale = self._ctx.scale_provider()
        if math.isfinite(scale):
            self.value, self.unit, self.detail = px * scale, "mm", f"{px:.1f} px"
            self._label.set_text(f"#{self.display_id()}  {self.value:.4f} mm")
        else:
            self.value, self.unit, self.detail = px, "px", "uncalibrated"
            self._label.set_text(f"#{self.display_id()}  {px:.1f} px")
        self._label.set_anchor(g.midpoint(p, foot))


class OriginM(BaseMeasurement):
    """The reference line. Editable, but not reported as a reading."""

    kind = "origin"
    tag = "origin"

    def _build(self, pts: list[Pt]) -> None:
        self._line = self._add_line(items.COLOR_ORIGIN, width=3)
        self._add_handle(pts[0], items.COLOR_ORIGIN)
        self._add_handle(pts[1], items.COLOR_ORIGIN)
        self._label = self._add_label(items.COLOR_ORIGIN)

    def recompute(self) -> None:
        a, b = self.pts()
        self._line.set_pts(a, b)
        self._label.set_text("ORIGIN")
        self._label.set_anchor(g.midpoint(a, b))

    def as_line(self) -> tuple[Pt, Pt]:
        a, b = self.pts()
        return a, b

    def line_for_selection(self) -> tuple[Pt, Pt] | None:
        return tuple(self.pts())  # type: ignore[return-value]


class AngleBetweenM(BaseMeasurement):
    """Angle between two EXISTING lines. Creates no new draggable points; it
    reads the two source lines live, so moving an original endpoint updates it.
    The arc itself is selectable (for deletion)."""

    kind = KIND_ANGLE
    tag = "between"

    def __init__(self, scene: QGraphicsScene, ctx: MeasureContext, la, lb) -> None:
        self._la = la
        self._lb = lb
        self.src_refs: tuple[LineRef, LineRef] | None = None
        super().__init__(scene, [], ctx)

    def to_record(self) -> MRecord:
        return MRecord(mid=self.mid, tag=self.tag, points=[], src=self.src_refs)

    def display_id(self) -> str:
        if self.src_refs is None:
            return str(self.mid)
        a = "O" if self.src_refs[0][0] == 0 else str(self.src_refs[0][0])
        b = "O" if self.src_refs[1][0] == 0 else str(self.src_refs[1][0])
        return f"{a}-{b}"

    def _build(self, pts: list[Pt]) -> None:
        faded = QColor(items.COLOR_ANGLE)
        faded.setAlpha(110)
        self._ext1 = self._add(items.make_line(Pt(0, 0), Pt(0, 0), faded, width=1, dashed=True))
        self._ext2 = self._add(items.make_line(Pt(0, 0), Pt(0, 0), faded, width=1, dashed=True))
        self._arc = items.MeasureArc(items.COLOR_ANGLE)
        self._scene.addItem(self._arc)
        self._items.append(self._arc)
        self.selectables.append(self._arc)
        self._label = self._add_label(items.COLOR_ANGLE)

    def sources(self) -> tuple[object, object]:
        return self._la, self._lb

    def alive(self) -> bool:
        try:
            return self._la.scene() is not None and self._lb.scene() is not None
        except RuntimeError:
            return False

    def recompute(self) -> None:
        if not self.alive():
            return
        a1, b1 = self._la.endpoints()
        a2, b2 = self._lb.endpoints()
        self.unit, self.detail = "°", "angle between 2 lines (linked)"
        self.value, center, v1, v2, inter = _angle_geometry(a1, b1, a2, b2)
        _apply_extension(self._ext1, a1, b1, inter)
        _apply_extension(self._ext2, a2, b2, inter)
        self._arc.set_arc(center, v1, v2)
        self._label.set_text(f"#{self.display_id()}  {self.value:.2f}°")
        self._label.set_anchor(center)
