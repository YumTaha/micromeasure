from __future__ import annotations

import math

from micromeasure.services import geometry as g
from micromeasure.services.geometry import Pt


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def main() -> None:
    o = Pt(0, 0)
    # image y is DOWN, so a segment going up-right should read as +45 deg.
    assert approx(g.line_angle_deg(o, Pt(10, -10)), 45.0), g.line_angle_deg(o, Pt(10, -10))
    assert approx(g.line_angle_deg(o, Pt(10, 0)), 0.0)
    assert approx(g.line_angle_deg(o, Pt(0, -10)), 90.0)

    assert approx(g.distance(o, Pt(3, 4)), 5.0)

    # angle between a horizontal and a vertical line == 90
    assert approx(g.angle_between_deg(Pt(0, 0), Pt(10, 0), Pt(0, 0), Pt(0, -10)), 90.0)

    # relative angle: line at +30 vs reference at +10 -> +20
    rel = g.relative_angle_deg(Pt(0, 0), Pt(10, 0), Pt(0, 0), Pt(10, -math.tan(math.radians(20)) * 10))
    assert approx(rel, 20.0, 1e-4), rel

    # perpendicular distance from (0,-5) to the x-axis line == 5
    assert approx(g.point_line_distance(Pt(0, -5), Pt(0, 0), Pt(10, 0)), 5.0)

    # intersection of x-axis and y-axis == origin
    inter = g.line_intersection(Pt(-5, 0), Pt(5, 0), Pt(0, -5), Pt(0, 5))
    assert inter is not None and approx(inter.x, 0.0) and approx(inter.y, 0.0)

    # parallel lines -> None
    assert g.line_intersection(Pt(0, 0), Pt(10, 0), Pt(0, 5), Pt(10, 5)) is None

    print("geometry: all checks passed")


if __name__ == "__main__":
    main()
