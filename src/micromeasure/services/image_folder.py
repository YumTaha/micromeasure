from __future__ import annotations

import re
from pathlib import Path

_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}


def _natural_key(name: str) -> list[object]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_images(folder: Path) -> list[Path]:
    """All image files directly in `folder`, natural-sorted by name."""
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _EXTS]
    return sorted(files, key=lambda p: _natural_key(p.name))
