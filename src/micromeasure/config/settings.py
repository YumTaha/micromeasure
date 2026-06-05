from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TOML = """# MicroMeasure configuration (auto-generated on first run)
# mm per pixel; `nan` means uncalibrated -> measurements are reported in pixels.
mm_per_pixel = nan
unit = "mm"
# Cursor magnifier (loupe) settings.
magnifier_zoom = 5.0
magnifier_size = 170
"""


@dataclass(frozen=True)
class AppConfig:
    mm_per_pixel: float
    unit: str
    magnifier_zoom: float
    magnifier_size: int

    def validate(self) -> None:
        if not math.isnan(self.mm_per_pixel) and self.mm_per_pixel <= 0:
            raise ValueError("mm_per_pixel must be positive (or nan).")
        if self.magnifier_zoom <= 1.0:
            raise ValueError("magnifier_zoom must be > 1.")
        if self.magnifier_size < 50:
            raise ValueError("magnifier_size must be >= 50.")

    @property
    def calibrated(self) -> bool:
        return math.isfinite(self.mm_per_pixel)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        path.write_text(_DEFAULT_TOML, encoding="utf-8")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = AppConfig(
        mm_per_pixel=float(data.get("mm_per_pixel", math.nan)),
        unit=str(data.get("unit", "mm")),
        magnifier_zoom=float(data.get("magnifier_zoom", 5.0)),
        magnifier_size=int(data.get("magnifier_size", 170)),
    )
    cfg.validate()
    return cfg
