from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

_BASE_TOML = """# MicroMeasure configuration (auto-generated on first run)
# mm per pixel; `nan` means uncalibrated -> measurements are reported in pixels.
mm_per_pixel = nan
unit = "mm"
# Cursor magnifier (loupe) settings.
magnifier_zoom = 5.0
magnifier_size = 170
"""

_TOOLS_BLOCK = """# Show/hide measurement tools in the toolbar. Set any to false to hide it.
[tools]
distance = true
angle_4pt = true
set_origin = true
angle_vs_origin = true
point_to_origin = true
angle_of_2_selected = true
"""

_DEFAULT_TOML = _BASE_TOML + "\n" + _TOOLS_BLOCK


@dataclass(frozen=True)
class AppConfig:
    mm_per_pixel: float
    unit: str
    magnifier_zoom: float
    magnifier_size: int
    show_distance: bool
    show_angle4: bool
    show_set_origin: bool
    show_angle_vs_origin: bool
    show_point_to_origin: bool
    show_angle_of_2_selected: bool

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
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    if "tools" not in data:
        # migrate older config files so the flags are present and editable
        path.write_text(text.rstrip() + "\n\n" + _TOOLS_BLOCK, encoding="utf-8")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    tools = data.get("tools", {})
    cfg = AppConfig(
        mm_per_pixel=float(data.get("mm_per_pixel", math.nan)),
        unit=str(data.get("unit", "mm")),
        magnifier_zoom=float(data.get("magnifier_zoom", 5.0)),
        magnifier_size=int(data.get("magnifier_size", 170)),
        show_distance=bool(tools.get("distance", True)),
        show_angle4=bool(tools.get("angle_4pt", True)),
        show_set_origin=bool(tools.get("set_origin", True)),
        show_angle_vs_origin=bool(tools.get("angle_vs_origin", True)),
        show_point_to_origin=bool(tools.get("point_to_origin", True)),
        show_angle_of_2_selected=bool(tools.get("angle_of_2_selected", True)),
    )
    cfg.validate()
    return cfg
