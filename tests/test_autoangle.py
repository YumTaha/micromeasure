from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from micromeasure.config.settings import load_config  # noqa: E402
from micromeasure.services.geometry import Pt  # noqa: E402
from micromeasure.ui.canvas import Tool  # noqa: E402
from micromeasure.ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    app = QApplication([])
    cfg = load_config(tmp / "config.toml")
    win = MainWindow(cfg, tmp / "config.toml")
    view = win._view
    pm = QPixmap(200, 150)
    pm.fill(QColor(100, 110, 120))
    view.set_image(pm)
    view.set_scale(0.01)

    view.set_auto_angle(True)
    view.set_tool(Tool.DISTANCE)

    # first line: no angle yet
    view._pts = [Pt(0, 0), Pt(100, 0)]
    view._finalize()
    assert sum(1 for m in view._measurements.values() if m.tag == "between") == 0

    # second line: auto angle between the two appears
    view._pts = [Pt(0, 10), Pt(50, -50)]
    view._finalize()
    betweens = [m for m in view._measurements.values() if m.tag == "between"]
    assert len(betweens) == 1, len(betweens)

    # disabling clears the pairing state -> next single line makes no angle
    view.set_auto_angle(False)
    view._pts = [Pt(0, 30), Pt(100, 30)]
    view._finalize()
    assert sum(1 for m in view._measurements.values() if m.tag == "between") == 1

    print("autoangle: all checks passed")
    app.quit()


if __name__ == "__main__":
    main()
