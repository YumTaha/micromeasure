from __future__ import annotations

import csv
from pathlib import Path

from micromeasure.services.measurements import Measurement

_HEADER = ["Tooth", "#", "Image", "Part", "Kind", "Value", "Unit", "Detail"]


def write_csv(rows: list[Measurement], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for m in rows:
            writer.writerow(
                [m.tooth, m.label, m.image, m.part, m.kind, f"{m.value:.4f}", m.unit, m.detail]
            )
