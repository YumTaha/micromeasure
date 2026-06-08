from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from micromeasure.services.measurements import KIND_PERP, KIND_REL_ANGLE, Measurement
from micromeasure.services.schedule import block_offset, global_tooth, present_local
from micromeasure.services.session import read_session, session_path, write_session
from micromeasure.ui.canvas import MeasureView, Tool
from micromeasure.ui.graphics_measure import MRecord


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, config_path: Path, guided: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("MicroMeasure — Lockdown" if guided else "MicroMeasure")
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

        # guided "teeth" lockdown mode (enabled with the --lockdown flag)
        self._guided = guided
        self._guided_step = "idle"  # idle / line1 / line2 / point / done
        self._part_lines: list[int] = []
        self._tooth_stack: list[int] = []  # mids created for the in-progress tooth
        self._current_local: int | None = None  # painted tooth number the op picked
        self._cleared_snapshot = None  # (records, rows) to undo a frame clear
        self._clear_mode = "readings"  # normal-mode clear toggle: readings | origins

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
        self._view.navigate.connect(self._step)
        self._view.tool_changed.connect(self._sync_tool_action)
        self._view.origin_changed.connect(self._guided_begin_part)
        self._view.edit_finished.connect(self._guided_rearm)
        self._view.set_lockdown(self._guided)
        self._build_central()

        self._build_toolbar()
        self._build_side_panel()
        self._build_nav_bar()
        self._update_scale_label()
        self._update_nav()
        self.statusBar().showMessage("Open an image or a folder to begin.")

    # ----------------------------------------------------------- ui assembly
    def _build_central(self) -> None:
        if not self._guided:
            self.setCentralWidget(self._view)
            return
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        banner = QWidget()
        banner.setStyleSheet("background-color: #eef1f0;")
        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 8, 12, 8)
        self._guided_label = QLabel("Open a folder to start measuring teeth.")
        banner_font = QFont()
        banner_font.setPointSize(14)
        banner_font.setBold(True)
        self._guided_label.setFont(banner_font)
        self._guided_label.setStyleSheet("color: #1c9c5e;")
        self._undo_btn = QPushButton("⟲  Undo")
        self._undo_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold;"
            " padding: 7px 18px; border-radius: 5px; }"
            " QPushButton:disabled { background-color: #d9a7a1; }"
        )
        self._undo_btn.clicked.connect(self._guided_undo)
        self._undo_btn.setEnabled(False)
        row.addWidget(self._guided_label, 1)
        row.addWidget(self._undo_btn)

        col.addWidget(banner)
        col.addWidget(self._view, 1)
        self.setCentralWidget(central)

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
        guided = self._guided
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions: dict[Tool, QAction] = {}
        # In guided mode only Select, Pan and Set Origin are exposed; the drawing
        # sequence is driven automatically. Otherwise honour config.toml [tools].
        for label, tool, show in [
            ("Select / Edit", Tool.SELECT, not guided),
            ("Pan", Tool.PAN, not guided),
            ("Distance", Tool.DISTANCE, cfg.show_distance and not guided),
            ("Angle (4 pt)", Tool.ANGLE4, cfg.show_angle4 and not guided),
            ("Set Origin", Tool.SET_ORIGIN, cfg.show_set_origin and not guided),
            ("Angle vs Origin", Tool.LINE_REL, cfg.show_angle_vs_origin and not guided),
            ("Point to Origin", Tool.POINT_PERP, cfg.show_point_to_origin and not guided),
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

        if cfg.show_angle_of_2_selected and not guided:
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

        self._auto_angle_cb = QCheckBox("Auto-angle between consecutive lines")
        self._auto_angle_cb.toggled.connect(self._view.set_auto_angle)
        layout.addWidget(self._auto_angle_cb)

        if self._guided:
            self._auto_angle_cb.setVisible(False)
            tooth_row = QFormLayout()
            self._tooth_combo = QComboBox()
            combo_font = QFont()
            combo_font.setPointSize(12)
            combo_font.setBold(True)
            self._tooth_combo.setFont(combo_font)
            self._tooth_combo.setStyleSheet("QComboBox { color: #c0392b; }")
            self._tooth_combo.currentIndexChanged.connect(self._on_tooth_selected)
            tooth_row.addRow("Tooth", self._tooth_combo)
            layout.addLayout(tooth_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Tooth", "#", "Kind", "Value", "Unit"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        csv_btn = QPushButton("Set Auto-Save CSV…")
        csv_btn.clicked.connect(self._set_csv)
        layout.addWidget(csv_btn)
        if self._guided:
            self._clear_btn = QPushButton("Clear All")
            self._clear_btn.clicked.connect(self._on_clear_button)
            self._clear_tooth_btn = QPushButton("Clear Tooth")
            self._clear_tooth_btn.clicked.connect(self._clear_tooth)
            crow = QHBoxLayout()
            crow.addWidget(self._clear_btn)
            crow.addWidget(self._clear_tooth_btn)
            layout.addLayout(crow)
        else:
            self._clear_all_btn = QPushButton("Clear All Readings")
            self._clear_all_btn.clicked.connect(self._on_clear_all_button)
            layout.addWidget(self._clear_all_btn)

        if not self._guided:
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
        if self._guided:
            if payload and self._payload_has_origin(payload):
                self._load_session(payload)  # auto-load origins (+ any prior drawings)
            else:
                QMessageBox.critical(
                    self,
                    "No origins found",
                    "This folder has no saved origins.\n\n"
                    "Origins must be set in the pre-measurement pass before using "
                    "lockdown mode. Set them first, then reopen here.",
                )
                self._begin_session(paths)
            return
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

    @staticmethod
    def _payload_has_origin(payload: dict) -> bool:
        return any(entry.get("origin") for entry in payload.get("images", {}).values())

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
                        "label": row.label if row else str(r.mid),
                        "tooth": row.tooth if row else 0,
                        "part": row.part if row else name,
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
            "operator": self._operator_edit.text(),
            "next_id": self._view.next_id(),
            "images": images,
        }

    def _load_session(self, payload: dict) -> None:
        scale = payload.get("scale_mm_per_px")
        if scale:
            self._mm_per_px = float(scale)
            self._view.set_scale(self._mm_per_px)
            self._update_scale_label()
        if payload.get("operator"):
            self._operator_edit.setText(str(payload["operator"]))
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
        self._rebuild_table()
        self._load_index(0)
        self.statusBar().showMessage("Loaded saved drawings for review.", 6000)

    def _add_session_row(self, m: dict, name: str) -> None:
        mid = int(m["mid"])
        row = Measurement(
            index=mid,
            label=m.get("label", str(mid)),
            image=name,
            part=m.get("part", name),
            kind=m.get("kind", ""),
            value=float(m.get("value", float("nan"))),
            unit=m.get("unit", ""),
            detail=m.get("detail", ""),
            tooth=int(m.get("tooth", 0)),
        )
        self._rows[mid] = row

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
        if self._guided:
            self._guided_step = "idle"
            self._part_lines = []
            self._tooth_stack = []
            self._cleared_snapshot = None  # clearing can't be undone after leaving the frame
            self._refresh_clear_button()
            self._guided_refresh_combo()
            self._guided_begin_part()
            self._sync_guided_locks()

    def _step(self, delta: int) -> None:
        if not self._paths:
            return
        if self._guided and self._tooth_in_progress():
            self._guided_status("Finish or Undo the current tooth before changing frames.")
            return
        if self._guided and delta > 0 and not self._image_complete():
            self._guided_status("Finish every tooth on this frame before moving on.")
            return
        self._load_index(self._index + delta)

    def _tooth_in_progress(self) -> bool:
        return bool(self._tooth_stack)

    def _image_complete(self) -> bool:
        present = set(self._present_teeth())
        return present.issubset(self._measured_local())

    def _update_nav(self) -> None:
        if not self._paths or self._index < 0:
            self._nav_label.setText("No folder open")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        path = self._paths[self._index]
        self._nav_label.setText(f"{path.name}    ({self._index + 1} / {len(self._paths)})")
        can_prev = self._index > 0
        can_next = self._index < len(self._paths) - 1
        if self._guided:
            if self._tooth_in_progress():
                can_prev = False  # don't leave a half-drawn tooth
                can_next = False
            else:
                can_next = can_next and self._image_complete()
        self._prev_btn.setEnabled(can_prev)
        self._next_btn.setEnabled(can_next)

    def _current_image_name(self) -> str:
        if 0 <= self._index < len(self._paths):
            return self._paths[self._index].name
        return ""

    # --------------------------------------------------------------- actions
    def _sync_tool_action(self, tool: Tool) -> None:
        act = self._tool_actions.get(tool)
        if act is not None:
            act.setChecked(True)

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

    # ------------------------------------------------------- guided (teeth)
    def _present_teeth(self) -> list[int]:
        """Painted (local) tooth numbers visible on the current frame."""
        if not self._paths or self._index < 0:
            return []
        return present_local(self._index)

    def _measured_local(self) -> set[int]:
        """Painted numbers of teeth already COMPLETED (have a height point) here."""
        name = self._current_image_name()
        offset = block_offset(self._index)
        return {
            r.tooth - offset
            for r in self._rows.values()
            if r.image == name and r.kind == KIND_PERP and r.tooth > 0
        }

    def _global_tooth(self) -> int:
        return global_tooth(self._index, self._current_local or 0)

    def _guided_status(self, msg: str) -> None:
        if hasattr(self, "_guided_label"):
            self._guided_label.setText(msg)

    def _sync_guided_locks(self) -> None:
        """Keep the Undo button, the tooth-picker lock, and which handles are
        editable in sync with the current step — the core of the lockdown."""
        if not self._guided:
            return
        self._undo_btn.setEnabled(bool(self._tooth_stack))
        in_progress = bool(self._tooth_stack)
        self._tooth_combo.setEnabled(not in_progress)  # can't switch teeth mid-tooth
        self._view.set_editable_mids(set(self._tooth_stack))  # only this tooth's points move

    def _guided_refresh_combo(self, keep_current: bool = False) -> None:
        present = self._present_teeth()
        measured = self._measured_local()
        self._tooth_combo.blockSignals(True)
        self._tooth_combo.clear()
        for t in present:
            g = global_tooth(self._index, t)
            self._tooth_combo.addItem(f"{t}  →  #{g}" + ("  ✓" if t in measured else ""), t)
        if not keep_current or self._current_local not in present:
            self._current_local = next((t for t in present if t not in measured),
                                       present[0] if present else None)
        if self._current_local in present:
            self._tooth_combo.setCurrentIndex(present.index(self._current_local))
        self._tooth_combo.blockSignals(False)

    def _on_tooth_selected(self, _idx: int) -> None:
        data = self._tooth_combo.currentData()
        if data is None:
            return
        self._current_local = int(data)
        self._guided_step = "idle"
        self._part_lines = []
        self._tooth_stack = []
        self._sync_guided_locks()
        self._guided_begin_part()

    def _guided_begin_part(self) -> None:
        if not self._guided or self._index < 0:
            return
        if self._guided_step not in ("idle",):
            return  # mid-draw: leave the active tool alone
        if self._current_local is None:
            self._view.set_tool(Tool.SELECT)
            self._guided_status("No teeth on this frame.")
            return
        if not self._view.has_origin():
            self._view.set_tool(Tool.SELECT)
            self._guided_status("No origin loaded for this frame.")
            return
        if self._current_local in self._measured_local():
            # already-measured tooth: don't let them keep drawing onto it
            self._view.set_tool(Tool.SELECT)
            if self._image_complete():
                self._guided_status("All teeth on this frame are done — you can go Next.")
            else:
                self._guided_status(f"Tooth {self._current_local} is done. Pick an unmeasured tooth.")
            return
        self._guided_step = "line1"
        self._part_lines = []
        self._tooth_stack = []
        self._sync_guided_locks()
        self._view.set_tool(Tool.LINE_REL)
        self._guided_status(f"Tooth {self._current_local} (→ #{self._global_tooth()}): draw LINE 1.")

    def _guided_rearm(self) -> None:
        if not self._guided:
            return
        if self._guided_step in ("line1", "line2"):
            self._view.set_tool(Tool.LINE_REL)
        elif self._guided_step == "point":
            self._view.set_tool(Tool.POINT_PERP)

    def _guided_on_added(self, mid: int, kind: str) -> None:
        if self._guided_step == "line1" and kind == KIND_REL_ANGLE:
            self._part_lines = [mid]
            self._tooth_stack.append(mid)
            self._guided_step = "line2"
            self._guided_status(f"Tooth {self._current_local}: draw LINE 2.")
        elif self._guided_step == "line2" and kind == KIND_REL_ANGLE:
            self._part_lines.append(mid)
            self._tooth_stack.append(mid)
            self._guided_step = "point"
            between = self._view.create_between_lines(self._part_lines[0], self._part_lines[1])
            if between is not None:
                self._tooth_stack.append(between.mid)
            self._view.set_tool(Tool.POINT_PERP)
            self._guided_status(f"Tooth {self._current_local}: click the HEIGHT point.")
        elif self._guided_step == "point" and kind == KIND_PERP:
            done_local = self._current_local
            done_global = self._global_tooth()
            self._guided_step = "idle"
            self._part_lines = []
            self._tooth_stack = []
            self._guided_refresh_combo()  # auto-advance to the next unmeasured tooth
            if self._current_local is not None and self._current_local not in self._measured_local():
                self._guided_begin_part()  # auto-start the next tooth
            else:
                self._view.set_tool(Tool.SELECT)
                self._guided_status(f"Tooth {done_local} (#{done_global}) done ✓ — frame complete, go Next.")
        self._sync_guided_locks()
        self._update_nav()

    def _guided_undo(self) -> None:
        if not self._guided or not self._tooth_stack:
            return
        if self._guided_step == "point":
            if self._tooth_stack:  # the between
                self._view.remove_measurement(self._tooth_stack.pop())
            if self._tooth_stack:  # line 2
                self._view.remove_measurement(self._tooth_stack.pop())
            self._part_lines = self._part_lines[:1]
            self._guided_step = "line2"
            self._view.set_tool(Tool.LINE_REL)
            self._guided_status(f"Tooth {self._current_local}: re-draw LINE 2.")
        elif self._guided_step == "line2":
            self._view.remove_measurement(self._tooth_stack.pop())  # line 1
            self._part_lines = []
            self._guided_step = "line1"
            self._view.set_tool(Tool.LINE_REL)
            self._guided_status(f"Tooth {self._current_local}: re-draw LINE 1.")
        self._guided_refresh_combo(keep_current=True)
        self._sync_guided_locks()
        self._update_nav()

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
        tooth = self._global_tooth() if (self._guided and self._current_local) else 0
        row = Measurement(
            index=mid,
            label=self._view.display_id(mid),
            image=self._current_image_name(),
            part=self._part_edit.text(),
            kind=kind,
            value=value,
            unit=unit,
            detail=detail,
            tooth=tooth,
        )
        self._rows[mid] = row
        self._rebuild_table()
        item = self._table.item(self._row_of.get(mid, 0), 0)
        if item is not None:
            self._table.scrollToItem(item)
        self.statusBar().showMessage(f"{kind}: {self._fmt(value)} {unit}", 5000)
        self._schedule_autosave()
        if not self._guided and self._clear_mode == "origins":
            self._clear_mode = "readings"  # drew again -> stop offering origin-clear
            self._refresh_clear_all_button()
        if self._guided:
            if self._cleared_snapshot is not None:  # drawing resumed -> can't undo the clear
                self._cleared_snapshot = None
                self._refresh_clear_button()
            self._guided_on_added(mid, kind)

    def _on_changed(self, mid: int, value: float, unit: str, detail: str) -> None:
        old = self._rows.get(mid)
        if old is None:
            return
        self._rows[mid] = replace(old, value=value, unit=unit, detail=detail)
        self._write_row(self._row_of[mid], self._rows[mid])
        self._schedule_autosave()

    def _on_removed(self, mid: int) -> None:
        if mid not in self._rows:
            return
        self._rows.pop(mid, None)
        self._rebuild_table()
        self._schedule_autosave()

    def _write_row(self, r: int, m: Measurement) -> None:
        cells = [str(m.tooth), f"#{m.label}", m.kind, self._fmt(m.value), m.unit]
        for col, text in enumerate(cells):
            self._table.setItem(r, col, QTableWidgetItem(text))

    @staticmethod
    def _fmt(value: float) -> str:
        return "nan" if math.isnan(value) else f"{value:.4f}"

    # ----------------------------------------------------------------- CSV
    def _order_key(self, m: Measurement) -> tuple[int, int, int]:
        # Angle-between rows ("a-b") sort right after their higher source line;
        # normal rows sort by their own number.
        parts = m.label.split("-")
        if len(parts) == 2:
            nums = [0 if p == "O" else int(p) for p in parts]
            return (max(nums), 1, m.index)
        return (m.index, 0, m.index)

    def _ordered_rows(self) -> list[Measurement]:
        return sorted(self._rows.values(), key=self._order_key)

    def _rebuild_table(self) -> None:
        self._table.setRowCount(0)
        self._row_of = {}
        for r, m in enumerate(self._ordered_rows()):
            self._table.insertRow(r)
            self._row_of[m.index] = r
            self._write_row(r, m)

    def _set_csv(self) -> None:
        op = self._operator_edit.text().strip().replace(" ", "_") or "X"
        default = f"measurements_{op}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Auto-save CSV", default, "CSV (*.csv)")
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

    # -- normal mode: clear toggles between measurements and origins ----------
    def _on_clear_all_button(self) -> None:
        if self._clear_mode == "readings":
            self._clear_all_readings()
        else:
            self._clear_all_origins()

    def _refresh_clear_all_button(self) -> None:
        if self._guided:
            return
        self._clear_all_btn.setText(
            "Clear All Origins" if self._clear_mode == "origins" else "Clear All Readings"
        )

    def _clear_all_readings(self) -> None:
        self._view.clear_measurements()  # current frame measurements; origin kept
        for idx, (records, origin) in list(self._docs.items()):
            self._docs[idx] = ([], origin)
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self._clear_mode = "origins"
        self._refresh_clear_all_button()
        self._schedule_autosave()
        self.statusBar().showMessage("Cleared all measurements (origins kept).", 5000)

    def _clear_all_origins(self) -> None:
        self._view.remove_origin()
        self._carried_origin = None
        for idx, (records, origin) in list(self._docs.items()):
            self._docs[idx] = (records, None)
        self._schedule_autosave()
        self.statusBar().showMessage("Cleared all origins.", 5000)

    # -- guided mode: clear a single tooth ------------------------------------
    def _clear_tooth(self) -> None:
        if not self._guided or self._current_local is None:
            return
        target = self._global_tooth()
        name = self._current_image_name()
        mids = [mid for mid, r in self._rows.items() if r.image == name and r.tooth == target]
        if not mids:
            self._guided_status(f"Tooth {self._current_local} has nothing to clear.")
            return
        for mid in mids:
            self._view.remove_measurement(mid)
        self._guided_step = "idle"
        self._part_lines = []
        self._tooth_stack = []
        self._guided_refresh_combo(keep_current=True)
        self._guided_begin_part()
        self._sync_guided_locks()
        self._update_nav()
        self._schedule_autosave()
        self._guided_status(f"Cleared tooth {self._current_local} — draw it again.")

    def _on_clear_button(self) -> None:
        if self._cleared_snapshot is not None:
            self._undo_clear()
        else:
            self._clear_current_image()

    def _refresh_clear_button(self) -> None:
        if not self._guided:
            return
        if self._cleared_snapshot is not None:
            self._clear_btn.setText("⟲  Undo the Clearing")
            self._clear_btn.setStyleSheet(
                "QPushButton { background-color: #e67e22; color: white; font-weight: bold; }"
            )
        else:
            self._clear_btn.setText("Clear All")
            self._clear_btn.setStyleSheet("")

    def _clear_current_image(self) -> None:
        # snapshot this frame's drawings + rows so the clear can be undone
        records, _origin = self._view.capture_state()
        name = self._current_image_name()
        rows = [self._rows[mid] for mid in sorted(self._rows) if self._rows[mid].image == name]
        self._view.clear_measurements()  # origin and other frames stay
        self._guided_step = "idle"
        self._part_lines = []
        self._tooth_stack = []
        self._cleared_snapshot = (records, rows)
        self._guided_refresh_combo()
        self._guided_begin_part()
        self._sync_guided_locks()
        self._refresh_clear_button()
        self._update_nav()
        self._schedule_autosave()
        self.statusBar().showMessage("Cleared this frame — use 'Undo the Clearing' if it was a mistake.", 6000)

    def _undo_clear(self) -> None:
        if self._cleared_snapshot is None:
            return
        records, rows = self._cleared_snapshot
        self._cleared_snapshot = None
        self._view.set_tool(Tool.SELECT)  # cancel any fresh in-progress click
        self._guided_step = "idle"
        self._part_lines = []
        self._tooth_stack = []
        for row in rows:
            self._rows[row.index] = row
        self._rebuild_table()
        self._view.apply_state(records, None)  # rebuild drawings; origin untouched
        self._guided_refresh_combo()
        self._refresh_clear_button()
        self._guided_begin_part()
        self._sync_guided_locks()
        self._update_nav()
        self._schedule_autosave()
        self.statusBar().showMessage("Restored the cleared drawings.", 4000)
