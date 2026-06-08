from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from micromeasure.config.settings import load_config  # noqa: E402
from micromeasure.services.geometry import Pt  # noqa: E402
from micromeasure.services.image_folder import list_images  # noqa: E402
from micromeasure.ui.canvas import Tool  # noqa: E402
from micromeasure.ui.main_window import MainWindow  # noqa: E402


def _draw(view, pts):
    view._pts = list(pts)
    view._finalize()


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    app = QApplication([])
    for i in range(20):
        pm = QPixmap(300, 200)
        pm.fill(QColor(90, 100, 110))
        pm.save(str(tmp / f"frame_{i:02d}.png"))
    cfg = load_config(tmp / "config.toml")

    win = MainWindow(cfg, tmp / "config.toml", guided=True)
    view = win._view
    assert win._guided
    win._begin_session(list_images(tmp))
    win._mm_per_px = 0.01
    view.set_scale(0.01)

    # frame 0: painted tooth 1 only
    assert win._present_teeth() == [1]
    assert win._current_local == 1
    view._set_origin([Pt(0, 120), Pt(200, 120)])
    assert win._guided_step == "line1"

    # draw line 1, then UNDO it
    _draw(view, [Pt(10, 100), Pt(60, 60)])
    assert win._guided_step == "line2"
    assert win._undo_btn.isEnabled()
    assert not win._tooth_combo.isEnabled()  # can't switch teeth mid-tooth
    assert win._tooth_in_progress()
    assert not win._next_btn.isEnabled()  # can't leave the frame mid-tooth
    win._guided_undo()
    assert win._guided_step == "line1"
    assert not win._undo_btn.isEnabled()
    assert win._tooth_combo.isEnabled()  # nothing drawn -> free to switch again
    assert not win._tooth_in_progress()
    assert sum(1 for m in view._measurements.values() if m.tag == "rel") == 0

    # full tooth: line1, line2 (auto angle), point
    _draw(view, [Pt(10, 100), Pt(60, 60)])
    _draw(view, [Pt(10, 100), Pt(60, 110)])
    assert win._guided_step == "point"
    assert sum(1 for m in view._measurements.values() if m.tag == "between") == 1
    _draw(view, [Pt(40, 50)])
    # only tooth on this frame -> nothing to advance to
    assert win._guided_step == "idle"

    # 4 rows, all real tooth #1, frame complete
    assert len(win._rows) == 4, len(win._rows)
    assert {r.tooth for r in win._rows.values()} == {1}
    assert win._measured_local() == {1}
    assert win._image_complete()

    # re-selecting an already-measured tooth must NOT re-enable drawing
    win._on_tooth_selected(0)
    assert win._view._tool == Tool.SELECT, win._view._tool

    # Clear Frame Measurements can be undone (until you draw again)
    win._on_clear_button()
    assert win._cleared_snapshot is not None and "Undo" in win._clear_btn.text()
    assert len(win._rows) == 0 and win._measured_local() == set()
    win._on_clear_button()  # undo the clear
    assert win._cleared_snapshot is None and "Clear" in win._clear_btn.text()
    assert len(win._rows) == 4 and win._measured_local() == {1}

    # move to frame 1 (two teeth) and verify auto-advance
    win._step(1)
    assert win._index == 1
    assert win._present_teeth() == [1, 2]
    assert win._current_local == 1 and win._guided_step == "line1"
    _draw(view, [Pt(10, 100), Pt(60, 60)])
    _draw(view, [Pt(10, 100), Pt(60, 110)])
    _draw(view, [Pt(40, 50)])
    assert win._current_local == 2, win._current_local  # auto-advanced to tooth 2
    assert win._guided_step == "line1"

    # clear a single finished tooth (tooth 1) and be ready to redraw it
    win._tooth_combo.setCurrentIndex(0)  # select painted tooth 1 (measured)
    assert win._current_local == 1
    win._clear_tooth()
    assert 1 not in win._measured_local()
    assert win._guided_step == "line1"

    print("guided: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
