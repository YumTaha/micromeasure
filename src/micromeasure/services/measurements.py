from __future__ import annotations

from dataclasses import dataclass

KIND_DISTANCE = "distance"
KIND_ANGLE = "angle"
KIND_REL_ANGLE = "angle_vs_origin"
KIND_PERP = "perp_to_origin"


@dataclass(frozen=True)
class Measurement:
    index: int
    label: str
    image: str
    part: str
    kind: str
    value: float
    unit: str
    detail: str
    tooth: int = 0
