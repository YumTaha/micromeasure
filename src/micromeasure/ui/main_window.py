from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from micromeasure.config.settings import AppConfig
from micromeasure.services import export
from micromeasure.services.measurements import Measurement
from micromeasure.ui.canvas import MeasureView, Tool


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("MicroMeasure")
        self.resize(1280, 820)

        self._config = config
        self._config_path = config_path
        self._mm_per_px = config.mm_per_pixel
        self._rows: dict[int, Measurement] = {}
        self._row_of: dict[int, int] = {}  # mid -> table row

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
        self._update_scale_label()
        self.statusBar().showMessage("Open an image to begin.")

    # ----------------------------------------------------------- ui assembly
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Tools")
        tb.setMovable(False)

        open_act = QAction("Open Image", self)
        open_act.triggered.connect(self._open_image)
        tb.addAction(open_act)
        scale_act = QAction("Set Scale", self)
        scale_act.triggered.connect(self._set_scale)
        tb.addAction(scale_act)
        tb.addSeparator()

        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions: dict[Tool, QAction] = {}
        for label, tool in [
            ("Select / Edit", Tool.SELECT),
            ("Pan", Tool.PAN),
            ("Distance", Tool.DISTANCE),
            ("Angle (4 pt)", Tool.ANGLE4),
            ("Set Origin", Tool.SET_ORIGIN),
            ("Angle vs Origin", Tool.LINE_REL),
            ("Point to Origin", Tool.POINT_PERP),
        ]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, t=tool: self._select_tool(t))
            self._tool_group.addAction(act)
            tb.addAction(act)
            self._tool_actions[tool] = act
            if tool == Tool.SELECT:
                act.setChecked(True)
        tb.addSeparator()

        between_act = QAction("Angle of 2 Selected", self)
        between_act.triggered.connect(lambda: self._view.angle_between_selected())
        tb.addAction(between_act)

    def _build_side_panel(self) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        form = QFormLayout()
        self._part_edit = QLineEdit("1")
        self._operator_edit = QLineEdit("A")
        self._trial_spin = QSpinBox()
        self._trial_spin.setRange(1, 9999)
        form.addRow("Part", self._part_edit)
        form.addRow("Operator", self._operator_edit)
        form.addRow("Trial", self._trial_spin)
        layout.addLayout(form)

        self._scale_label = QLabel()
        layout.addWidget(self._scale_label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Part", "Op", "Trial", "Kind", "Value", "Unit"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear)
        layout.addWidget(export_btn)
        layout.addWidget(clear_btn)

        hint = QLabel(
            "Select/Edit: drag a point to fix it (loupe shows while dragging).\n"
            "Click two lines to select both, then 'Angle of 2 Selected'.\n"
            "Click empty space to deselect. Del removes selected."
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

    # --------------------------------------------------------------- actions
    def _select_tool(self, tool: Tool) -> None:
        before = self._view.has_origin()
        self._view.set_tool(tool)
        # If the tool needed an origin and was refused, revert to Select.
        if tool in (Tool.LINE_REL, Tool.POINT_PERP) and not before:
            self._tool_actions[Tool.SELECT].setChecked(True)
            self._view.set_tool(Tool.SELECT)

    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Open image", "Could not load that image.")
            return
        self._view.set_image(pixmap)
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self.statusBar().showMessage(f"Loaded {Path(path).name}", 5000)

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

    def _on_added(self, mid: int, kind: str, value: float, unit: str, detail: str) -> None:
        row = Measurement(
            index=mid,
            part=self._part_edit.text(),
            operator=self._operator_edit.text(),
            trial=self._trial_spin.value(),
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
        self._trial_spin.setValue(self._trial_spin.value() + 1)
        self.statusBar().showMessage(f"{kind}: {self._fmt(value)} {unit}", 5000)

    def _on_changed(self, mid: int, value: float, unit: str, detail: str) -> None:
        old = self._rows.get(mid)
        if old is None:
            return
        from dataclasses import replace

        self._rows[mid] = replace(old, value=value, unit=unit, detail=detail)
        self._write_row(self._row_of[mid], self._rows[mid])

    def _on_removed(self, mid: int) -> None:
        if mid not in self._row_of:
            return
        r = self._row_of.pop(mid)
        self._rows.pop(mid, None)
        self._table.removeRow(r)
        # rows below shifted up by one
        self._row_of = {k: (v - 1 if v > r else v) for k, v in self._row_of.items()}

    def _write_row(self, r: int, m: Measurement) -> None:
        cells = [m.part, m.operator, str(m.trial), m.kind, self._fmt(m.value), m.unit]
        for col, text in enumerate(cells):
            self._table.setItem(r, col, QTableWidgetItem(text))

    @staticmethod
    def _fmt(value: float) -> str:
        return "nan" if math.isnan(value) else f"{value:.4f}"

    def _export_csv(self) -> None:
        if not self._rows:
            QMessageBox.information(self, "Export CSV", "No measurements to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "measurements.csv", "CSV (*.csv)")
        if not path:
            return
        ordered = [self._rows[mid] for mid in sorted(self._rows)]
        export.write_csv(ordered, Path(path))
        self.statusBar().showMessage(f"Exported {len(ordered)} rows to {path}", 6000)

    def _clear(self) -> None:
        self._view.clear_measurements()
        self._rows.clear()
        self._row_of.clear()
        self._table.setRowCount(0)
        self.statusBar().showMessage("Cleared.", 4000)
