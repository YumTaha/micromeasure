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


def approx(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) < tol


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    app = QApplication([])

    # create 3 images on disk
    for i in range(3):
        pm = QPixmap(200, 150)
        pm.fill(QColor(90 + i * 20, 100, 110))
        pm.save(str(tmp / f"img{i + 1}.png"))
    paths = list_images(tmp)
    assert [p.name for p in paths] == ["img1.png", "img2.png", "img3.png"], paths

    cfg = load_config(tmp / "config.toml")
    win = MainWindow(cfg, tmp / "config.toml")
    view = win._view
    win._begin_session(paths)
    view.set_scale(0.01)  # 1 px = 0.01 mm
    assert win._index == 0

    # image 1: set origin + one distance (100 px -> 1.0 mm)
    view._set_origin([Pt(10, 120), Pt(190, 120)])
    view._create(DistanceM, [Pt(10, 10), Pt(110, 10)])
    d0 = next(iter(view._measurements.values()))
    assert approx(d0.value, 1.0), d0.value
    assert win._rows[d0.mid].image == "img1.png"
    assert win._table.rowCount() == 1

    # -> image 2: origin carried, canvas otherwise empty
    win._step(1)
    assert win._index == 1
    assert view.has_origin()  # origin carried over
    assert len(view._measurements) == 0  # fresh image, no drawings
    view._create(DistanceM, [Pt(0, 0), Pt(50, 0)])  # 50 px -> 0.5 mm
    d1 = max(view._measurements.values(), key=lambda m: m.mid)
    assert win._rows[d1.mid].image == "img2.png"
    assert win._table.rowCount() == 2  # accumulating, not replaced

    # <- back to image 1: drawings restored, no duplicate rows
    win._step(-1)
    assert win._index == 0
    assert view.has_origin()
    assert len(view._measurements) == 1
    restored = next(iter(view._measurements.values()))
    assert restored.mid == d0.mid
    assert approx(restored.value, 1.0), restored.value
    assert win._table.rowCount() == 2  # still 2, nothing duplicated

    # autosave CSV includes the Image column with the right names
    csv = tmp / "out.csv"
    win._csv_path = csv
    win._do_autosave()
    lines = csv.read_text(encoding="utf-8-sig").strip().splitlines()
    assert lines[0].split(",")[:2] == ["Index", "Image"], lines[0]
    assert "img1.png" in lines[1] and "img2.png" in lines[2]

    print("navigation: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
