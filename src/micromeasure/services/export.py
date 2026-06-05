from __future__ import annotations

import csv
from pathlib import Path

from micromeasure.services.measurements import Measurement

_HEADER = ["Index", "Part", "Operator", "Trial", "Kind", "Value", "Unit", "Detail"]


def write_csv(rows: list[Measurement], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for m in rows:
            writer.writerow(
                [m.index, m.part, m.operator, m.trial, m.kind, f"{m.value:.4f}", m.unit, m.detail]
            )
