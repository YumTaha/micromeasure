from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from micromeasure.config.settings import load_config  # noqa: E402
from micromeasure.services.geometry import Pt  # noqa: E402
from micromeasure.ui.canvas import Tool  # noqa: E402
from micromeasure.ui.graphics_measure import Angle4M, DistanceM, PointPerpM, RelAngleM  # noqa: E402
from micromeasure.ui.main_window import MainWindow  # noqa: E402


def approx(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) < tol


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    cfg = load_config(tmp / "config.toml")
    app = QApplication([])

    win = MainWindow(cfg, tmp / "config.toml")
    view = win._view
    pm = QPixmap(400, 300)
    pm.fill(QColor(120, 120, 120))
    view.set_image(pm)
    view.set_scale(0.006367)

    # --- distance: 100 px -> 0.6367 mm ----------------------------------
    view._create(DistanceM, [Pt(10, 10), Pt(110, 10)])
    dist = next(iter(view._measurements.values()))
    assert approx(dist.value, 0.6367, 1e-3), dist.value
    assert win._table.rowCount() == 1

    # --- dragging a handle recomputes the value -------------------------
    dist.handles[1].setPos(QPointF(210, 10))  # now 200 px -> 1.2734 mm
    assert approx(dist.value, 1.2734, 1e-3), dist.value
    assert win._rows[dist.mid].value == dist.value  # table row synced

    # --- origin + angle vs origin ---------------------------------------
    view._set_origin([Pt(0, 200), Pt(100, 200)])  # horizontal origin
    assert view.has_origin()
    view._create(RelAngleM, [Pt(0, 200), Pt(100, 150)])  # +26.565 (< 45, unchanged)
    rel = [m for m in view._measurements.values() if isinstance(m, RelAngleM)][0]
    assert approx(rel.value, 26.565), rel.value
    assert rel.unit == "°"

    # moving the origin updates the dependent relative angle
    view._origin.handles[1].setPos(QPointF(100, 150))  # origin now +26.565 itself
    assert approx(rel.value, 0.0, 0.1), rel.value
    view._origin.handles[1].setPos(QPointF(100, 200))  # restore

    # fold past 45 deg: a 60-deg line vs horizontal origin -> -30 (to perpendicular)
    view._create(RelAngleM, [Pt(0, 200), Pt(50, 200 - 86.60254)])
    folded = max(view._measurements.values(), key=lambda m: m.mid)
    assert approx(folded.value, -30.0, 0.1), folded.value

    # --- point -> perpendicular distance to origin ----------------------
    view._create(PointPerpM, [Pt(50, 150)])  # 50 px above origin -> 0.31835 mm
    perp = [m for m in view._measurements.values() if isinstance(m, PointPerpM)][0]
    assert approx(perp.value, 0.31835, 1e-3), perp.value

    # --- angle between two selected lines -------------------------------
    view._create(DistanceM, [Pt(0, 0), Pt(100, 0)])  # horizontal
    view._create(DistanceM, [Pt(0, 0), Pt(0, -100)])  # vertical
    lines = sorted(view._measurements.values(), key=lambda m: m.mid)[-2:]
    lines[0].lines[0].setSelected(True)
    lines[1].lines[0].setSelected(True)
    n_before = len(view._measurements)
    assert view.angle_between_selected()
    assert len(view._measurements) == n_before + 1
    new = max(view._measurements.values(), key=lambda m: m.mid)
    assert approx(new.value, 90.0), new.value

    # --- delete selected -------------------------------------------------
    rows_before = win._table.rowCount()
    for ln in view._scene.selectedItems():
        ln.setSelected(False)
    new.lines[0].setSelected(True)
    view.delete_selected()
    assert win._table.rowCount() == rows_before - 1
    assert new.mid not in view._measurements

    # --- 4-point angle is direction-independent (~60 deg, not 120) ------
    import math as _m

    arm = Pt(_m.cos(_m.radians(60)) * 100, -_m.sin(_m.radians(60)) * 100)
    view._create(Angle4M, [Pt(0, 0), Pt(100, 0), Pt(0, 0), arm])
    a1 = max(view._measurements.values(), key=lambda m: m.mid)
    assert approx(a1.value, 60.0, 0.1), a1.value
    view._create(Angle4M, [Pt(100, 0), Pt(0, 0), arm, Pt(0, 0)])  # both reversed
    a2 = max(view._measurements.values(), key=lambda m: m.mid)
    assert approx(a2.value, 60.0, 0.1), a2.value

    # far-apart lines -> dashed extensions to the intersection are shown
    view._create(Angle4M, [Pt(0, 0), Pt(10, 0), Pt(100, -50), Pt(100, -60)])
    far = max(view._measurements.values(), key=lambda m: m.mid)
    assert far._ext1.isVisible() and far._ext2.isVisible()
    # overlapping intersection (shared vertex) -> no extensions
    assert not a1._ext1.isVisible() and not a1._ext2.isVisible()

    print("smoke: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
