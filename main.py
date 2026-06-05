from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from micromeasure.config.settings import load_config
from micromeasure.ui.main_window import MainWindow


def main() -> None:
    config_path = Path("config.toml")
    config = load_config(config_path)
    app = QApplication(sys.argv)
    window = MainWindow(config, config_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
