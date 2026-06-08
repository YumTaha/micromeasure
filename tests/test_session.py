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
from micromeasure.services.session import read_session, session_path, write_session  # noqa: E402
from micromeasure.ui.graphics_measure import DistanceM  # noqa: E402
from micromeasure.ui.main_window import MainWindow  # noqa: E402


def approx(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) < tol


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    app = QApplication([])
    for i in range(2):
        pm = QPixmap(200, 150)
        pm.fill(QColor(90 + i * 30, 100, 110))
        pm.save(str(tmp / f"img{i + 1}.png"))
    paths = list_images(tmp)
    cfg = load_config(tmp / "config.toml")

    # --- session 1: draw on both images, then write the session file --------
    win = MainWindow(cfg, tmp / "config.toml")
    win._guided = False  # exercise the generic navigation/session engine
    win._begin_session(paths)
    win._mm_per_px = 0.01
    win._view.set_scale(0.01)
    win._view._set_origin([Pt(10, 120), Pt(190, 120)])
    win._view._create(DistanceM, [Pt(10, 10), Pt(110, 10)])  # 100 px -> 1.0 mm
    win._step(1)  # image 2
    win._view._create(DistanceM, [Pt(0, 0), Pt(0, 80)])  # 80 px -> 0.8 mm

    payload = win._session_payload()
    spath = session_path(tmp)
    write_session(spath, payload)
    assert spath.exists()

    # --- session 2: fresh window, reopen the folder, load the session -------
    win2 = MainWindow(cfg, tmp / "config.toml")
    win2._guided = False
    win2._folder = tmp
    win2._session_file = spath
    win2._paths = paths
    loaded = read_session(spath)
    assert loaded is not None
    win2._load_session(loaded)

    # scale restored, both images' drawings restored as docs, rows recreated
    assert approx(win2._mm_per_px, 0.01), win2._mm_per_px
    assert set(win2._docs.keys()) == {0, 1}, win2._docs.keys()
    assert win2._table.rowCount() == 2

    # image 1 is shown -> its distance is rebuilt live and reads 1.0 mm
    assert win2._index == 0
    d0 = next(iter(win2._view._measurements.values()))
    assert approx(d0.value, 1.0), d0.value
    assert win2._view.has_origin()

    # navigate to image 2 -> its distance is restored too (0.8 mm)
    win2._step(1)
    assert win2._index == 1
    d1 = next(iter(win2._view._measurements.values()))
    assert approx(d1.value, 0.8), d1.value

    print("session: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
