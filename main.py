from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from micromeasure.config.settings import load_config
from micromeasure.ui.main_window import MainWindow


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MicroMeasure")
    parser.add_argument(
        "--lockdown",
        action="store_true",
        help="run the guided teeth lockdown workflow",
    )
    # ignore any Qt/platform args so they don't trip argparse
    args, _ = parser.parse_known_args()
    return args


def main() -> None:
    args = _parse_args()
    config_path = Path("config.toml")
    config = load_config(config_path)
    app = QApplication(sys.argv)
    window = MainWindow(config, config_path, guided=args.lockdown)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
