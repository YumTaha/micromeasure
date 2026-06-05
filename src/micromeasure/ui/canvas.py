from __future__ import annotations

import math
from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from micromeasure.services import geometry as g
from micromeasure.services.geometry import Pt
from micromeasure.ui import items
from micromeasure.ui.graphics_measure import (
    Angle4M,
    BaseMeasurement,
    DistanceM,
    Handle,
    MeasureContext,
    OriginM,
    PointPerpM,
    RelAngleM,
)
from micromeasure.ui.magnifier import Magnifier


class Tool(Enum):
    SELECT = auto()
    PAN = auto()
    DISTANCE = auto()
    ANGLE4 = auto()
    LINE_REL = auto()
    POINT_PERP = auto()
    SET_ORIGIN = auto()


_NEEDED = {
    Tool.DISTANCE: 2,
    Tool.ANGLE4: 4,
    Tool.LINE_REL: 2,
    Tool.POINT_PERP: 1,
    Tool.SET_ORIGIN: 2,
}
_FACTORY: dict[Tool, type[BaseMeasurement]] = {
    Tool.DISTANCE: DistanceM,
    Tool.ANGLE4: Angle4M,
    Tool.LINE_REL: RelAngleM,
    Tool.POINT_PERP: PointPerpM,
}


class MeasureView(QGraphicsView):
    added = Signal(int, str, float, str, str)  # mid, kind, value, unit, detail
    changed = Signal(int, float, str, str)  # mid, value, unit, detail
    removed = Signal(int)  # mid
    status = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._tool = Tool.SELECT
        self._mm_per_px = math.nan

        self._pts: list[Pt] = []
        self._preview: list[QGraphicsItem] = []
        self._measurements: dict[int, BaseMeasurement] = {}
        self._origin: OriginM | None = None
        self._next_id = 1
        self._editing = False  # dragging a handle while in Pan mode

        self._ctx = MeasureContext(
            scale_provider=lambda: self._mm_per_px,
            origin_provider=lambda: self._origin.as_line() if self._origin else None,
        )
        self._mag = Magnifier(self.viewport())

    # ----------------------------------------------------------- public api
    def set_image(self, pixmap: QPixmap) -> None:
        self._scene.clear()
        self._measurements.clear()
        self._origin = None
        self._pts.clear()
        self._preview.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._mag.set_source(pixmap)
        self.resetTransform()
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def set_scale(self, mm_per_px: float) -> None:
        self._mm_per_px = mm_per_px
        self._recompute_all()

    def set_magnifier(self, zoom: float, size: int) -> None:
        self._mag.set_zoom(zoom)
        self._mag.setFixedSize(size, size)

    def has_origin(self) -> bool:
        return self._origin is not None

    def set_tool(self, tool: Tool) -> None:
        if tool in (Tool.LINE_REL, Tool.POINT_PERP) and self._origin is None:
            self.status.emit("Set an origin line first (Set Origin tool).")
            return
        self._cancel_in_progress()
        self._tool = tool
        if tool == Tool.PAN:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif tool == Tool.SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def angle_between_selected(self) -> bool:
        lines = [it for it in self._scene.selectedItems() if isinstance(it, items.MeasureLine)]
        if len(lines) != 2:
            self.status.emit("Select exactly 2 lines first (Select tool), then try again.")
            return False
        a1, b1 = lines[0].endpoints()
        a2, b2 = lines[1].endpoints()
        self._create(Angle4M, [a1, b1, a2, b2])
        return True

    def delete_selected(self) -> None:
        for mid, m in list(self._measurements.items()):
            if m.is_selected():
                m.remove()
                del self._measurements[mid]
                self.removed.emit(mid)
        if self._origin is not None and self._origin.is_selected():
            self._origin.remove()
            self._origin = None
            self._recompute_all()
            self.status.emit("Origin removed.")

    def clear_measurements(self) -> None:
        for mid, m in list(self._measurements.items()):
            m.remove()
            self.removed.emit(mid)
        self._measurements.clear()
        self._cancel_in_progress()

    # --------------------------------------------------------- measurements
    def _create(self, factory: type[BaseMeasurement], pts: list[Pt]) -> None:
        m = factory(self._scene, pts, self._ctx)
        m.mid = self._next_id
        self._next_id += 1
        m.notify = self._on_handle_moved
        m.recompute()
        self._measurements[m.mid] = m
        self.added.emit(m.mid, m.kind, m.value, m.unit, m.detail)

    def _set_origin(self, pts: list[Pt]) -> None:
        if self._origin is not None:
            self._origin.remove()
        self._origin = OriginM(self._scene, pts, self._ctx)
        self._origin.notify = self._on_handle_moved
        self._origin.recompute()
        self.status.emit("Origin set. Use 'Angle vs Origin' or 'Point to Origin'.")

    def _on_handle_moved(self, _changed: BaseMeasurement) -> None:
        self._recompute_all()

    def _recompute_all(self) -> None:
        if self._origin is not None:
            self._origin.recompute()
        for mid, m in self._measurements.items():
            m.recompute()
            self.changed.emit(mid, m.value, m.unit, m.detail)

    # ---------------------------------------------------------------- input
    def _cancel_in_progress(self) -> None:
        self._pts.clear()
        self._clear_preview()

    def _clear_preview(self) -> None:
        for it in self._preview:
            if it.scene() is self._scene:
                self._scene.removeItem(it)
        self._preview.clear()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._pixmap_item is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._pixmap_item is None:
            super().mousePressEvent(event)
            return
        if self._tool == Tool.SELECT:
            # Click a line to toggle its selection (additive: pick two easily);
            # click empty space to clear; click a handle to drag it.
            if event.button() == Qt.MouseButton.LeftButton:
                hit = self.itemAt(event.position().toPoint())
                if isinstance(hit, items.MeasureLine):
                    hit.setSelected(not hit.isSelected())
                    event.accept()
                    return
            super().mousePressEvent(event)
            return
        if self._tool == Tool.PAN:
            # grabbing a handle drags the point; empty space pans
            if event.button() == Qt.MouseButton.LeftButton and isinstance(
                self.itemAt(event.position().toPoint()), Handle
            ):
                self._editing = True
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        sp = self.mapToScene(event.position().toPoint())
        self._pts.append(Pt(sp.x(), sp.y()))
        if len(self._pts) >= _NEEDED[self._tool]:
            self._finalize()
        else:
            self._draw_preview(Pt(sp.x(), sp.y()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        if self._pixmap_item is None:
            return
        sp = self.mapToScene(event.position().toPoint())
        if self._tool == Tool.PAN:
            if self._editing and (event.buttons() & Qt.MouseButton.LeftButton):
                self._show_mag(sp)
            else:
                self._mag.hide()
            return
        if self._tool == Tool.SELECT:
            # show the loupe while dragging a handle so endpoints can be placed precisely
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._show_mag(sp)
            else:
                self._mag.hide()
            return
        self._show_mag(sp)
        if self._pts:
            self._draw_preview(Pt(sp.x(), sp.y()))

    def _show_mag(self, scene_pt) -> None:
        self._mag.update_point(scene_pt)
        self._mag.move(self.viewport().width() - self._mag.width() - 10, 10)
        self._mag.raise_()
        self._mag.show()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._tool == Tool.PAN and self._editing:
            self._editing = False
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._mag.hide()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._mag.hide()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_in_progress()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        super().keyPressEvent(event)

    # -------------------------------------------------------------- preview
    def _add_preview(self, item: QGraphicsItem) -> None:
        self._scene.addItem(item)
        self._preview.append(item)

    def _draw_preview(self, cursor: Pt) -> None:
        self._clear_preview()
        pts = self._pts
        tool = self._tool
        if tool == Tool.DISTANCE and len(pts) == 1:
            self._add_preview(items.make_line(pts[0], cursor, items.COLOR_PREVIEW))
            self._add_preview(self._dist_preview_label(pts[0], cursor))
        elif tool in (Tool.SET_ORIGIN, Tool.LINE_REL) and len(pts) == 1:
            color = items.COLOR_ORIGIN if tool == Tool.SET_ORIGIN else items.COLOR_REL
            self._add_preview(items.make_line(pts[0], cursor, color))
            if tool == Tool.LINE_REL and self._origin is not None:
                o = self._origin.as_line()
                rel = g.fold_to_axis(g.relative_angle_deg(o[0], o[1], pts[0], cursor))
                lbl = items.LabelItem(color)
                lbl.set_text(f"{rel:+.2f}°")
                lbl.set_anchor(g.midpoint(pts[0], cursor))
                self._add_preview(lbl)
        elif tool == Tool.ANGLE4:
            for p in pts:
                self._add_preview(items.make_marker(p, items.COLOR_ANGLE))
            if len(pts) == 1:
                self._add_preview(items.make_line(pts[0], cursor, items.COLOR_PREVIEW))
            elif len(pts) == 2:
                self._add_preview(items.make_line(pts[0], pts[1], items.COLOR_ANGLE))
                self._add_preview(items.make_line(pts[1], cursor, items.COLOR_PREVIEW))
            elif len(pts) == 3:
                self._add_preview(items.make_line(pts[0], pts[1], items.COLOR_ANGLE))
                self._add_preview(items.make_line(pts[2], cursor, items.COLOR_PREVIEW))
                ang = g.angle_at_vertex(pts[0], pts[1], pts[2], cursor)
                lbl = items.LabelItem(items.COLOR_ANGLE)
                lbl.set_text(f"{ang:.2f}°")
                lbl.set_anchor(cursor)
                self._add_preview(lbl)

    def _dist_preview_label(self, a: Pt, b: Pt) -> items.LabelItem:
        px = g.distance(a, b)
        lbl = items.LabelItem(items.COLOR_PREVIEW)
        if math.isfinite(self._mm_per_px):
            lbl.set_text(f"{px * self._mm_per_px:.4f} mm")
        else:
            lbl.set_text(f"{px:.1f} px")
        lbl.set_anchor(g.midpoint(a, b))
        return lbl

    def _finalize(self) -> None:
        pts = list(self._pts)
        tool = self._tool
        self._cancel_in_progress()
        if tool == Tool.SET_ORIGIN:
            self._set_origin(pts)
        else:
            self._create(_FACTORY[tool], pts)
