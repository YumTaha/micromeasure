from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from micromeasure.config.settings import AppConfig
from micromeasure.services import export
from micromeasure.services.geometry import Pt
from micromeasure.services.image_folder import list_images
from micromeasure.services.measurements import Measurement
from micromeasure.services.session import read_session, session_path, write_session
from micromeasure.ui.canvas import MeasureView, Tool
from micromeasure.ui.graphics_measure import MRecord


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("MicroMeasure")
        self.resize(1280, 860)

        self._config = config
        self._config_path = config_path
        self._mm_per_px = config.mm_per_pixel
        self._rows: dict[int, Measurement] = {}
        self._row_of: dict[int, int] = {}

        # folder/session state
        self._paths: list[Path] = []
        self._index = -1
        self._docs: dict[int, tuple] = {}  # image index -> (records, origin_pts)
        self._carried_origin = None
        self._csv_path: Path | None = None
        self._folder: Path | None = None
        self._session_file: Path | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._do_autosave)

        self._view = MeasureView()
        self._view.set_magnifier(config.magnifier_zoom, config.magnifier_size)
        self._view.set_scale(self._mm_per_px)
        self._view.added.connect(self._on_added)
        self._view.changed.connect(self._on_changed)
        self._view.removed.connect(self._on_removed)
        self._view.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.setCentralWidget(self._view)

        self._build_toolbar()
        self._build_side_panel()
        self._build_nav_bar()
        self._update_scale_label()
        self._update_nav()
        self.statusBar().showMessage("Open an image or a folder to begin.")

    # ----------------------------------------------------------- ui assembly
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Tools")
        tb.setMovable(False)
        for label, slot in [
            ("Open Image", self._open_image),
            ("Open Folder", self._open_folder),
            ("Set Scale", self._set_scale),
        ]:
            act = QAction(label, self)
            act.triggered.connect(lambda _c=False, s=slot: s())
            tb.addAction(act)
        tb.addSeparator()

        cfg = self._config
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions: dict[Tool, QAction] = {}
        # Select and Pan always shown; the rest are toggled via config.toml [tools].
        for label, tool, show in [
            ("Select / Edit", Tool.SELECT, True),
            ("Pan", Tool.PAN, True),
            ("Distance", Tool.DISTANCE, cfg.show_distance),
            ("Angle (4 pt)", Tool.ANGLE4, cfg.show_angle4),
            ("Set Origin", Tool.SET_ORIGIN, cfg.show_set_origin),
            ("Angle vs Origin", Tool.LINE_REL, cfg.show_angle_vs_origin),
            ("Point to Origin", Tool.POINT_PERP, cfg.show_point_to_origin),
        ]:
            if not show:
                continue
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, t=tool: self._select_tool(t))
            self._tool_group.addAction(act)
            tb.addAction(act)
            self._tool_actions[tool] = act
            if tool == Tool.SELECT:
                act.setChecked(True)

        if cfg.show_angle_of_2_selected:
            tb.addSeparator()
            between_act = QAction("Angle of 2 Selected", self)
            between_act.triggered.connect(lambda: self._angle_between())
            tb.addAction(between_act)

    def _build_side_panel(self) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        form = QFormLayout()
        self._part_edit = QLineEdit("1")
        self._operator_edit = QLineEdit("A")
        form.addRow("Part", self._part_edit)
        form.addRow("Operator", self._operator_edit)
        layout.addLayout(form)

        self._scale_label = QLabel()
        layout.addWidget(self._scale_label)
        self._csv_label = QLabel("CSV: not set (no auto-save)")
        self._csv_label.setWordWrap(True)
        layout.addWidget(self._csv_label)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Part", "Op", "Kind", "Value", "Unit"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        csv_btn = QPushButton("Set Auto-Save CSV…")
        csv_btn.clicked.connect(self._set_csv)
        clear_btn = QPushButton("Clear All Readings")
        clear_btn.clicked.connect(self._clear)
        layout.addWidget(csv_btn)
        layout.addWidget(clear_btn)

        hint = QLabel(
            "Select/Edit: drag a point to fix it; click two lines then "
            "'Angle of 2 Selected'. Del removes selected.\n"
            "Origin carries to the next image — just reposition it.\n"
            "PageUp/PageDown or the arrows move between images.\n"
            "Drawings auto-save into the folder; reopen it to review them."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        dock = QDockWidget("Readings", self)
        dock.setWidget(panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_nav_bar(self) -> None:
        nav = QToolBar("Navigate", self)
        nav.setMovable(False)
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 2, 6, 2)
        self._prev_btn = QPushButton("◀  Prev")
        self._next_btn = QPushButton("Next  ▶")
        self._nav_label = QLabel("No folder open")
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prev_btn.clicked.connect(lambda: self._step(-1))
        self._next_btn.clicked.connect(lambda: self._step(1))
        h.addWidget(self._prev_btn)
        h.addStretch(1)
        h.addWidget(self._nav_label)
        h.addStretch(1)
        h.addWidget(self._next_btn)
        nav.addWidget(bar)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, nav)

        prev_sc = QShortcut(QKeySequence(Qt.Key.Key_PageUp), self)
        prev_sc.activated.connect(lambda: self._step(-1))
        next_sc = QShortcut(QKeySequence(Qt.Key.Key_PageDown), self)
        next_sc.activated.connect(lambda: self._step(1))

    # ----------------------------------------------------------- navigation
    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if path:
            self._folder = None
            self._session_file = None
            self._begin_session([Path(path)])

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open image folder")
        if not folder:
            return
        folder = Path(folder)
        paths = list_images(folder)
        if not paths:
            QMessageBox.information(self, "Open Folder", "No images found in that folder.")
            return
        self._folder = folder
        self._session_file = session_path(folder)
        self._paths = paths
        payload = read_session(self._session_file)
        if payload and payload.get("images"):
            resp = QMessageBox.question(
                self,
                "Saved drawings found",
                "This folder has saved MicroMeasure drawings.\n\n"
                "Load them so you can review what the operator did?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._load_session(payload)
                return
        self._begin_session(paths)

    def _begin_session(self, paths: list[Path]) -> None:
        self._paths = paths
        self._docs = {}
        self._carried_origin = None
        self._index = -1
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self._load_index(0)

    # ------------------------------------------------- session save / restore
    def _session_payload(self) -> dict:
        # make sure the image currently on screen is captured into _docs first
        if 0 <= self._index < len(self._paths):
            records, origin = self._view.capture_state()
            self._docs[self._index] = (records, origin)
            if origin is not None:
                self._carried_origin = origin
        images: dict[str, dict] = {}
        for idx, (records, origin) in self._docs.items():
            name = self._paths[idx].name
            measurements = []
            for r in records:
                row = self._rows.get(r.mid)
                measurements.append(
                    {
                        "mid": r.mid,
                        "tag": r.tag,
                        "points": [[p.x, p.y] for p in r.points],
                        "src": [list(r.src[0]), list(r.src[1])] if r.src else None,
                        "part": row.part if row else name,
                        "operator": row.operator if row else "",
                        "kind": row.kind if row else "",
                        "value": row.value if row else float("nan"),
                        "unit": row.unit if row else "",
                        "detail": row.detail if row else "",
                    }
                )
            images[name] = {
                "origin": [[origin[0].x, origin[0].y], [origin[1].x, origin[1].y]]
                if origin
                else None,
                "measurements": measurements,
            }
        return {
            "version": 1,
            "scale_mm_per_px": self._mm_per_px if math.isfinite(self._mm_per_px) else None,
            "next_id": self._view.next_id(),
            "images": images,
        }

    def _load_session(self, payload: dict) -> None:
        scale = payload.get("scale_mm_per_px")
        if scale:
            self._mm_per_px = float(scale)
            self._view.set_scale(self._mm_per_px)
            self._update_scale_label()
        self._view.set_next_id(int(payload.get("next_id", 1)))

        self._docs = {}
        self._carried_origin = None
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self._index = -1

        name_to_index = {p.name: i for i, p in enumerate(self._paths)}
        for name, entry in payload.get("images", {}).items():
            idx = name_to_index.get(name)
            if idx is None:
                continue  # image no longer in the folder
            origin = None
            o = entry.get("origin")
            if o:
                origin = (Pt(o[0][0], o[0][1]), Pt(o[1][0], o[1][1]))
            records = []
            for m in entry.get("measurements", []):
                pts = [Pt(x, y) for x, y in m["points"]]
                src = (tuple(m["src"][0]), tuple(m["src"][1])) if m.get("src") else None
                records.append(MRecord(mid=m["mid"], tag=m["tag"], points=pts, src=src))
                self._add_session_row(m, name)
            self._docs[idx] = (records, origin)
            if origin is not None:
                self._carried_origin = origin
        self._load_index(0)
        self.statusBar().showMessage("Loaded saved drawings for review.", 6000)

    def _add_session_row(self, m: dict, name: str) -> None:
        mid = int(m["mid"])
        row = Measurement(
            index=mid,
            image=name,
            part=m.get("part", name),
            operator=m.get("operator", ""),
            kind=m.get("kind", ""),
            value=float(m.get("value", float("nan"))),
            unit=m.get("unit", ""),
            detail=m.get("detail", ""),
        )
        self._rows[mid] = row
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._row_of[mid] = r
        self._write_row(r, row)

    def _load_index(self, i: int) -> None:
        if not self._paths or not (0 <= i < len(self._paths)):
            return
        if 0 <= self._index < len(self._paths):
            records, origin = self._view.capture_state()
            self._docs[self._index] = (records, origin)
            if origin is not None:
                self._carried_origin = origin
        path = self._paths[i]
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            QMessageBox.warning(self, "Open image", f"Could not load {path.name}.")
            return
        self._index = i
        self._view.set_image(pixmap)
        self._part_edit.setText(path.name)
        records, origin = self._docs.get(i, ([], self._carried_origin))
        self._view.apply_state(records, origin)
        self._update_nav()
        self._schedule_autosave()

    def _step(self, delta: int) -> None:
        if self._paths:
            self._load_index(self._index + delta)

    def _update_nav(self) -> None:
        if not self._paths or self._index < 0:
            self._nav_label.setText("No folder open")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        path = self._paths[self._index]
        self._nav_label.setText(f"{path.name}    ({self._index + 1} / {len(self._paths)})")
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(self._paths) - 1)

    def _current_image_name(self) -> str:
        if 0 <= self._index < len(self._paths):
            return self._paths[self._index].name
        return ""

    # --------------------------------------------------------------- actions
    def _select_tool(self, tool: Tool) -> None:
        before = self._view.has_origin()
        self._view.set_tool(tool)
        if tool in (Tool.LINE_REL, Tool.POINT_PERP) and not before:
            self._tool_actions[Tool.SELECT].setChecked(True)
            self._view.set_tool(Tool.SELECT)

    def _angle_between(self) -> None:
        count = self._view.selected_line_count()
        if count != 2:
            QMessageBox.information(
                self,
                "Angle of 2 Selected",
                f"You have {count} line(s) selected — you need exactly 2.\n\n"
                "Switch to the Select / Edit tool, click two lines (each turns "
                "white when selected), then click 'Angle of 2 Selected' again.\n\n"
                "The angle stays linked to those lines: move either line and it "
                "updates automatically.",
            )
            return
        self._view.angle_between_selected()

    def _set_scale(self) -> None:
        current = self._mm_per_px if math.isfinite(self._mm_per_px) else 0.006367
        value, ok = QInputDialog.getDouble(self, "Set scale", "mm per pixel:", current, 0.0, 1e6, 7)
        if not ok or value <= 0:
            return
        self._mm_per_px = value
        self._view.set_scale(value)
        self._update_scale_label()
        self.statusBar().showMessage(f"Scale set to {value:.7f} mm/px", 5000)

    def _update_scale_label(self) -> None:
        if math.isfinite(self._mm_per_px):
            self._scale_label.setText(f"Scale: {self._mm_per_px:.7f} mm/px")
        else:
            self._scale_label.setText("Scale: uncalibrated (px)")

    # --------------------------------------------------------------- readings
    def _on_added(self, mid: int, kind: str, value: float, unit: str, detail: str) -> None:
        row = Measurement(
            index=mid,
            image=self._current_image_name(),
            part=self._part_edit.text(),
            operator=self._operator_edit.text(),
            kind=kind,
            value=value,
            unit=unit,
            detail=detail,
        )
        self._rows[mid] = row
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._row_of[mid] = r
        self._write_row(r, row)
        self._table.scrollToBottom()
        self.statusBar().showMessage(f"{kind}: {self._fmt(value)} {unit}", 5000)
        self._schedule_autosave()

    def _on_changed(self, mid: int, value: float, unit: str, detail: str) -> None:
        old = self._rows.get(mid)
        if old is None:
            return
        self._rows[mid] = replace(old, value=value, unit=unit, detail=detail)
        self._write_row(self._row_of[mid], self._rows[mid])
        self._schedule_autosave()

    def _on_removed(self, mid: int) -> None:
        if mid not in self._row_of:
            return
        r = self._row_of.pop(mid)
        self._rows.pop(mid, None)
        self._table.removeRow(r)
        self._row_of = {k: (v - 1 if v > r else v) for k, v in self._row_of.items()}
        self._schedule_autosave()

    def _write_row(self, r: int, m: Measurement) -> None:
        cells = [m.part, m.operator, m.kind, self._fmt(m.value), m.unit]
        for col, text in enumerate(cells):
            self._table.setItem(r, col, QTableWidgetItem(text))

    @staticmethod
    def _fmt(value: float) -> str:
        return "nan" if math.isnan(value) else f"{value:.4f}"

    # ----------------------------------------------------------------- CSV
    def _ordered_rows(self) -> list[Measurement]:
        return [self._rows[mid] for mid in sorted(self._rows)]

    def _set_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Auto-save CSV", "measurements.csv", "CSV (*.csv)")
        if not path:
            return
        self._csv_path = Path(path)
        export.write_csv(self._ordered_rows(), self._csv_path)
        self._csv_label.setText(f"CSV (auto-save): {self._csv_path.name}")
        self.statusBar().showMessage(f"Auto-saving to {path}", 6000)

    def _schedule_autosave(self) -> None:
        if self._csv_path is not None or self._session_file is not None:
            self._save_timer.start()

    def _do_autosave(self) -> None:
        if self._session_file is not None:
            try:
                write_session(self._session_file, self._session_payload())
            except OSError:
                pass
        if self._csv_path is not None:
            export.write_csv(self._ordered_rows(), self._csv_path)

    def _clear(self) -> None:
        self._view.clear_measurements()
        self._docs = {}  # drop saved drawings for every image too
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self._schedule_autosave()
        self.statusBar().showMessage("Cleared all drawings and readings.", 4000)
