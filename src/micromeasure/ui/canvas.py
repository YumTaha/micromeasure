from __future__ import annotations

import math
from enum import Enum, auto

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

from micromeasure.services import geometry as g
from micromeasure.services.geometry import Pt
from micromeasure.ui import items
from micromeasure.ui.graphics_measure import (
    Angle4M,
    AngleBetweenM,
    BaseMeasurement,
    DistanceM,
    Handle,
    MeasureContext,
    OriginM,
    PointPerpM,
    RelAngleM,
)
from micromeasure.ui.magnifier import CursorLoupe, Magnifier


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
_TAG_FACTORY: dict[str, type[BaseMeasurement]] = {
    "distance": DistanceM,
    "angle4": Angle4M,
    "rel": RelAngleM,
    "perp": PointPerpM,
}


def _make_dot_cursor() -> QCursor:
    """A small green dot cursor (matches the loupe crosshair color)."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
    painter.setBrush(QColor(60, 220, 60))
    painter.drawEllipse(QPointF(size / 2, size / 2), 2.0, 2.0)
    painter.end()
    return QCursor(pm, size // 2, size // 2)


class MeasureView(QGraphicsView):
    added = Signal(int, str, float, str, str)  # mid, kind, value, unit, detail
    changed = Signal(int, float, str, str)  # mid, value, unit, detail
    removed = Signal(int)  # mid
    status = Signal(str)
    navigate = Signal(int)  # +1 / -1 from arrow keys
    tool_changed = Signal(object)  # Tool, when the view switches tools itself
    origin_changed = Signal()  # origin created or moved
    edit_finished = Signal()  # a snapped-point drag was released

    _SNAP_PX = 12.0  # cursor-to-handle snap radius, in screen pixels

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._tool = Tool.SELECT
        self._mm_per_px = math.nan

        self._pts: list[Pt] = []
        self._preview: list[QGraphicsItem] = []
        self._measurements: dict[int, BaseMeasurement] = {}
        self._origin: OriginM | None = None
        self._next_id = 1
        self._editing = False  # dragging a handle while in Pan mode
        self._snap_handle: Handle | None = None
        self._snap_scene: Pt | None = None
        self._drag_handle: Handle | None = None  # snapped point grabbed for moving
        self._auto_angle = False
        self._last_line_mid: int | None = None
        self._mid_pan = False  # middle-button temporary pan
        self._mid_pan_last = None
        self._lockdown = False  # hardened guided mode
        self._editable_mids: set[int] = set()  # only these handles may be moved

        self._ctx = MeasureContext(
            scale_provider=lambda: self._mm_per_px,
            origin_provider=lambda: self._origin.as_line() if self._origin else None,
        )
        self._mag = Magnifier(self.viewport())
        self._loupe = CursorLoupe(self.viewport())
        self._dot_cursor = _make_dot_cursor()
        self.viewport().setCursor(self._dot_cursor)

    # ----------------------------------------------------------- public api
    def set_image(self, pixmap: QPixmap) -> None:
        self._cancel_in_progress()
        self._scene.clear()
        self._measurements.clear()
        self._origin = None
        self._snap_handle = None
        self._snap_scene = None
        self._last_line_mid = None
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._mag.set_source(pixmap)
        self._loupe.set_source(pixmap)
        self.resetTransform()
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def set_scale(self, mm_per_px: float) -> None:
        self._mm_per_px = mm_per_px
        self._recompute_all()

    def set_magnifier(self, zoom: float, size: int) -> None:
        self._mag.set_zoom(zoom)
        self._mag.setFixedSize(size, size)
        self._loupe.set_zoom(zoom)

    def set_auto_angle(self, enabled: bool) -> None:
        self._auto_angle = enabled
        self._last_line_mid = None

    def set_lockdown(self, enabled: bool) -> None:
        self._lockdown = enabled

    def set_editable_mids(self, mids) -> None:
        """In lockdown, only handles owned by these measurement ids may move."""
        self._editable_mids = set(mids)

    def _lock_handles(self, m: BaseMeasurement) -> None:
        if self._lockdown:
            for h in m.handles:
                h.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)

    def has_origin(self) -> bool:
        return self._origin is not None

    def display_id(self, mid: int) -> str:
        m = self._measurements.get(mid)
        return m.display_id() if m is not None else str(mid)

    def next_id(self) -> int:
        return self._next_id

    def set_next_id(self, value: int) -> None:
        self._next_id = max(self._next_id, value)

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
            self.viewport().setCursor(self._dot_cursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(self._dot_cursor)

    def selected_line_count(self) -> int:
        return len([it for it in self._scene.selectedItems() if isinstance(it, items.MeasureLine)])

    def angle_between_selected(self) -> bool:
        lines = [it for it in self._scene.selectedItems() if isinstance(it, items.MeasureLine)]
        if len(lines) != 2:
            self.status.emit("Select exactly 2 lines first (Select tool), then try again.")
            return False
        self._create_between(lines[0], lines[1])
        lines[0].setSelected(False)
        lines[1].setSelected(False)
        return True

    def _create_between(self, la, lb) -> AngleBetweenM:
        m = AngleBetweenM(self._scene, self._ctx, la, lb)
        m.src_refs = (self._line_ref(la), self._line_ref(lb))
        m.mid = self._next_id
        self._next_id += 1
        m.notify = self._on_handle_moved
        m.recompute()
        self._measurements[m.mid] = m
        self.added.emit(m.mid, m.kind, m.value, m.unit, m.detail)
        return m

    def _line_ref(self, line) -> tuple[int, int]:
        for m in self._measurements.values():
            if line in m.lines:
                return (m.mid, m.lines.index(line))
        if self._origin is not None and line in self._origin.lines:
            return (0, self._origin.lines.index(line))
        return (0, 0)

    def delete_selected(self) -> None:
        removed_lines: set = set()
        for mid, m in list(self._measurements.items()):
            if m.is_selected():
                removed_lines.update(m.lines)
                m.remove()
                del self._measurements[mid]
                self.removed.emit(mid)
        origin_removed = False
        if self._origin is not None and self._origin.is_selected():
            removed_lines.update(self._origin.lines)
            self._origin.remove()
            self._origin = None
            origin_removed = True
        if removed_lines:
            self._remove_dependent_angles(removed_lines)
        if origin_removed:
            self._recompute_all()
            self.status.emit("Origin removed.")

    def _remove_dependent_angles(self, lines: set) -> None:
        """Remove linked angle annotations whose source lines were deleted."""
        for mid, m in list(self._measurements.items()):
            if isinstance(m, AngleBetweenM) and any(s in lines for s in m.sources()):
                m.remove()
                del self._measurements[mid]
                self.removed.emit(mid)

    def remove_origin(self) -> None:
        if self._origin is not None:
            self._origin.remove()
            self._origin = None

    def remove_measurement(self, mid: int) -> None:
        """Remove a single measurement by id (used by guided Undo)."""
        m = self._measurements.pop(mid, None)
        if m is not None:
            m.remove()
            self.removed.emit(mid)

    def clear_measurements(self) -> None:
        for mid, m in list(self._measurements.items()):
            m.remove()
            self.removed.emit(mid)
        self._measurements.clear()
        self._cancel_in_progress()

    # --------------------------------------------------------- measurements
    def _create(self, factory: type[BaseMeasurement], pts: list[Pt]) -> BaseMeasurement:
        m = factory(self._scene, pts, self._ctx)
        self._lock_handles(m)
        m.mid = self._next_id
        self._next_id += 1
        m.notify = self._on_handle_moved
        m.recompute()
        self._measurements[m.mid] = m
        self.added.emit(m.mid, m.kind, m.value, m.unit, m.detail)
        return m

    def _make_origin(self, pts: list[Pt]) -> None:
        if self._origin is not None:
            self._origin.remove()
        self._origin = OriginM(self._scene, pts, self._ctx)
        self._lock_handles(self._origin)
        self._origin.notify = self._on_handle_moved
        self._origin.recompute()
        self.origin_changed.emit()

    def create_between_lines(self, mid_a: int, mid_b: int) -> AngleBetweenM | None:
        a = self._measurements.get(mid_a)
        b = self._measurements.get(mid_b)
        if a is not None and b is not None and a.lines and b.lines:
            return self._create_between(a.lines[0], b.lines[0])
        return None

    def _set_origin(self, pts: list[Pt]) -> None:
        self._make_origin(pts)
        self.status.emit("Origin set. Use 'Angle vs Origin' or 'Point to Origin'.")

    # ---------------------------------------------------- per-image save/load
    def capture_state(self):
        """Snapshot the current drawings + origin so they can be restored."""
        records = [m.to_record() for m in self._measurements.values()]
        origin = self._origin.as_line() if self._origin is not None else None
        return records, origin

    def apply_state(self, records, origin_pts) -> None:
        """Rebuild drawings + origin (after set_image cleared the scene). Reuses
        the stored ids so rows stay linked; emits `changed`, never `added`."""
        if origin_pts is not None:
            self._make_origin([origin_pts[0], origin_pts[1]])
        betweens = []
        for r in records:
            if r.tag == "between":
                betweens.append(r)
            else:
                self._rebuild_one(r)
        for r in betweens:
            self._rebuild_between(r)

    def _track_id(self, mid: int) -> None:
        if mid >= self._next_id:
            self._next_id = mid + 1

    def _rebuild_one(self, r) -> None:
        m = _TAG_FACTORY[r.tag](self._scene, list(r.points), self._ctx)
        self._lock_handles(m)
        m.mid = r.mid
        m.notify = self._on_handle_moved
        m.recompute()
        self._measurements[m.mid] = m
        self._track_id(m.mid)
        self.changed.emit(m.mid, m.value, m.unit, m.detail)

    def _rebuild_between(self, r) -> None:
        la = self._resolve_ref(r.src[0])
        lb = self._resolve_ref(r.src[1])
        if la is None or lb is None:
            return
        m = AngleBetweenM(self._scene, self._ctx, la, lb)
        m.src_refs = r.src
        m.mid = r.mid
        m.notify = self._on_handle_moved
        m.recompute()
        self._measurements[m.mid] = m
        self._track_id(m.mid)
        self.changed.emit(m.mid, m.value, m.unit, m.detail)

    def _resolve_ref(self, ref: tuple[int, int]):
        mid, idx = ref
        if mid == 0:
            lines = self._origin.lines if self._origin is not None else []
        else:
            owner = self._measurements.get(mid)
            lines = owner.lines if owner is not None else []
        return lines[idx] if idx < len(lines) else None

    def _on_handle_moved(self, _changed: BaseMeasurement) -> None:
        self._recompute_all()

    def _recompute_all(self) -> None:
        if self._origin is not None:
            self._origin.recompute()
        # recompute source measurements first, then linked angles that read them
        deferred: list[tuple[int, BaseMeasurement]] = []
        for mid, m in self._measurements.items():
            if isinstance(m, AngleBetweenM):
                deferred.append((mid, m))
                continue
            m.recompute()
            self.changed.emit(mid, m.value, m.unit, m.detail)
        for mid, m in deferred:
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
        if event.button() == Qt.MouseButton.MiddleButton:
            # hold middle button to temporarily pan; release returns to the tool
            self._mid_pan = True
            self._mid_pan_last = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            self._cancel_in_progress()
            self._hide_loupes()
            event.accept()
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
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        # Hovering an existing point (snapped, no Shift) -> grab it to edit
        # instead of starting/continuing a drawing.
        if self._snap_handle is not None and not shift:
            handle = self._snap_handle
            self._cancel_in_progress()
            self._begin_edit_snapped(handle)
            return
        sp = self.mapToScene(event.position().toPoint())
        self._pts.append(Pt(sp.x(), sp.y()))
        if len(self._pts) >= _NEEDED[self._tool]:
            self._finalize()
        else:
            self._draw_preview(Pt(sp.x(), sp.y()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._mid_pan:
            pos = event.position().toPoint()
            if self._mid_pan_last is not None:
                d = pos - self._mid_pan_last
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            self._mid_pan_last = pos
            return
        # Owning a snapped-point drag: move it directly, don't pass to base.
        if self._drag_handle is not None and self._pixmap_item is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                sp = self.mapToScene(event.position().toPoint())
                self._drag_handle.setPos(sp)
                self._show_loupes(sp)
            return
        super().mouseMoveEvent(event)
        if self._pixmap_item is None:
            return
        sp = self.mapToScene(event.position().toPoint())
        if self._tool == Tool.PAN:
            if self._editing and (event.buttons() & Qt.MouseButton.LeftButton):
                self._show_loupes(sp)
            else:
                self._hide_loupes()
            return
        if self._tool == Tool.SELECT:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._show_loupes(sp)
            else:
                self._hide_loupes()
            return
        # a drawing tool is active: snap to nearby points, show loupes + preview
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._update_snap(event.position().toPoint(), shift)
        target = QPointF(self._snap_scene.x, self._snap_scene.y) if self._snap_scene else sp
        self._show_loupes(target)
        self._draw_preview(Pt(target.x(), target.y()))

    def _show_loupes(self, scene_pt) -> None:
        self._mag.update_point(scene_pt)
        self._mag.move(self.viewport().width() - self._mag.width() - 10, 10)
        self._mag.raise_()
        self._mag.show()
        vp = self.mapFromScene(scene_pt)
        self._loupe.update_point(scene_pt)
        x = max(0, min(vp.x() + 18, self.viewport().width() - self._loupe.width()))
        y = max(0, min(vp.y() - self._loupe.height() - 18, self.viewport().height() - self._loupe.height()))
        self._loupe.move(x, y)
        self._loupe.raise_()
        self._loupe.show()

    def _hide_loupes(self) -> None:
        self._mag.hide()
        self._loupe.hide()

    def _restore_cursor(self) -> None:
        if self._tool == Tool.PAN:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().setCursor(self._dot_cursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._mid_pan:
            self._mid_pan = False
            self._mid_pan_last = None
            self._restore_cursor()
            event.accept()
            return
        if self._drag_handle is not None:
            self._drag_handle = None
            self._hide_loupes()
            super().mouseReleaseEvent(event)
            self.edit_finished.emit()
            return
        super().mouseReleaseEvent(event)
        if self._tool == Tool.PAN and self._editing:
            self._editing = False
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._hide_loupes()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hide_loupes()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_in_progress()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self._lockdown:  # deletion is disabled in lockdown
                self.delete_selected()
        elif key == Qt.Key.Key_Left:
            self.navigate.emit(-1)
            return
        elif key == Qt.Key.Key_Right:
            self.navigate.emit(1)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------- snapping
    def _all_handles(self) -> list[Handle]:
        handles: list[Handle] = []
        for m in self._measurements.values():
            handles.extend(m.handles)
        if self._origin is not None:
            handles.extend(self._origin.handles)
        return handles

    def _owner_of_handle(self, handle: Handle) -> BaseMeasurement | None:
        for m in self._measurements.values():
            if handle in m.handles:
                return m
        if self._origin is not None and handle in self._origin.handles:
            return self._origin
        return None

    def _handle_editable(self, handle: Handle) -> bool:
        owner = self._owner_of_handle(handle)
        return owner is not None and owner.mid in self._editable_mids

    def _update_snap(self, vp_pos, shift: bool) -> None:
        self._snap_handle = None
        self._snap_scene = None
        if shift:
            return
        handles = self._all_handles()
        if self._lockdown:
            handles = [h for h in handles if self._handle_editable(h)]
        best: Handle | None = None
        best_d = self._SNAP_PX
        for h in handles:
            hv = self.mapFromScene(h.scenePos())
            d = math.hypot(hv.x() - vp_pos.x(), hv.y() - vp_pos.y())
            if d <= best_d:
                best_d = d
                best = h
        if best is not None:
            self._snap_handle = best
            self._snap_scene = best.point()

    def _begin_edit_snapped(self, handle: Handle) -> None:
        self.set_tool(Tool.SELECT)
        self.tool_changed.emit(Tool.SELECT)
        for it in self._scene.selectedItems():
            it.setSelected(False)
        owner = self._owner_of_handle(handle)
        if owner is not None and owner.lines:
            owner.lines[0].setSelected(True)
        # grab it immediately so the same click-drag moves the point
        self._drag_handle = handle
        self.status.emit("Moving point — release to drop (it stays linked).")

    def _snap_ring(self, p: Pt) -> QGraphicsEllipseItem:
        r = 8
        ring = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(2)
        pen.setCosmetic(True)
        ring.setPen(pen)
        ring.setBrush(Qt.BrushStyle.NoBrush)
        ring.setPos(p.x, p.y)
        ring.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        ring.setZValue(40)
        return ring

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
        if self._snap_scene is not None:
            self._add_preview(self._snap_ring(self._snap_scene))

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
            return
        m = self._create(_FACTORY[tool], pts)
        # auto-angle: pair each new single-line measurement with the previous one
        if self._auto_angle and tool in (Tool.DISTANCE, Tool.LINE_REL):
            prev = self._measurements.get(self._last_line_mid) if self._last_line_mid else None
            if prev is not None and prev.lines and m.lines:
                self._create_between(prev.lines[0], m.lines[0])
            self._last_line_mid = m.mid
