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
from micromeasure.ui.graphics_measure import DistanceM  # noqa: E402
from micromeasure.ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    app = QApplication([])
    pm = QPixmap(200, 150)
    pm.fill(QColor(100, 110, 120))
    pm.save(str(tmp / "img1.png"))
    cfg = load_config(tmp / "config.toml")

    win = MainWindow(cfg, tmp / "config.toml")
    win._begin_session(list_images(tmp))
    win._mm_per_px = 0.01
    win._view.set_scale(0.01)

    # three lines -> #1 #2 #3
    win._view._create(DistanceM, [Pt(0, 0), Pt(50, 0)])
    win._view._create(DistanceM, [Pt(0, 20), Pt(50, 20)])
    win._view._create(DistanceM, [Pt(0, 40), Pt(50, 40)])
    ms = sorted(win._view._measurements.values(), key=lambda m: m.mid)
    line1, line2, _line3 = ms

    # angle between #1 and #2 -> should land right after #2, before #3
    line1.lines[0].setSelected(True)
    line2.lines[0].setSelected(True)
    assert win._view.angle_between_selected()

    labels = [m.label for m in win._ordered_rows()]
    assert labels[0] == "1" and labels[1] == "2", labels
    assert labels[2] in ("1-2", "2-1"), labels  # inserted after line 2
    assert labels[3] == "3", labels  # not pushed below line 3

    print("ordering: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
