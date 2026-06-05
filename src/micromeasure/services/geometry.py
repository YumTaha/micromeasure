from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Pt:
    x: float
    y: float


def distance(a: Pt, b: Pt) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def midpoint(a: Pt, b: Pt) -> Pt:
    return Pt((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def norm180(deg: float) -> float:
    """Wrap an angle in degrees into (-180, 180]."""
    while deg <= -180.0:
        deg += 360.0
    while deg > 180.0:
        deg -= 360.0
    return deg


def line_angle_deg(a: Pt, b: Pt) -> float:
    """Angle of segment a->b in degrees, CCW from +x, with the image y-axis
    flipped so results read like a normal protractor (up is positive)."""
    return math.degrees(math.atan2(-(b.y - a.y), b.x - a.x))


def relative_angle_deg(o1: Pt, o2: Pt, a: Pt, b: Pt) -> float:
    """Signed angle of segment a->b relative to reference segment o1->o2."""
    return norm180(line_angle_deg(a, b) - line_angle_deg(o1, o2))


def fold_to_axis(deg: float) -> float:
    """Fold an angle into [-45, 45], i.e. measure it against whichever is
    nearer: the origin line or its perpendicular. E.g. +78.21 -> -11.79."""
    return ((deg + 45.0) % 90.0) - 45.0


def angle_between_deg(a1: Pt, a2: Pt, b1: Pt, b2: Pt) -> float:
    """Unsigned angle in [0, 180] between the drawn directions a1->a2 and
    b1->b2 (the angle the two lines open by, as drawn)."""
    return abs(norm180(line_angle_deg(b1, b2) - line_angle_deg(a1, a2)))


def angle_at_vertex(p1: Pt, p2: Pt, p3: Pt, p4: Pt) -> float:
    """Angle in [0, 180] at the intersection of lines p1-p2 and p3-p4, measured
    between the rays pointing from the intersection toward each line's far
    endpoint. Independent of the direction each line was drawn."""
    inter = line_intersection(p1, p2, p3, p4)
    if inter is None:
        return angle_between_deg(p1, p2, p3, p4)
    e1 = p1 if distance(inter, p1) >= distance(inter, p2) else p2
    e2 = p3 if distance(inter, p3) >= distance(inter, p4) else p4
    a1 = math.degrees(math.atan2(e1.y - inter.y, e1.x - inter.x))
    a2 = math.degrees(math.atan2(e2.y - inter.y, e2.x - inter.x))
    return abs(norm180(a2 - a1))


def point_line_distance(p: Pt, a: Pt, b: Pt) -> float:
    """Perpendicular distance (pixels) from p to the infinite line a-b."""
    dx = b.x - a.x
    dy = b.y - a.y
    denom = math.hypot(dx, dy)
    if denom == 0.0:
        return math.nan
    return abs(dy * p.x - dx * p.y + b.x * a.y - b.y * a.x) / denom


def project_point(p: Pt, a: Pt, b: Pt) -> Pt:
    """Foot of the perpendicular from p onto the infinite line a-b."""
    abx = b.x - a.x
    aby = b.y - a.y
    denom = abx * abx + aby * aby
    if denom == 0.0:
        return a
    t = ((p.x - a.x) * abx + (p.y - a.y) * aby) / denom
    return Pt(a.x + t * abx, a.y + t * aby)


def line_intersection(a1: Pt, a2: Pt, b1: Pt, b2: Pt) -> Pt | None:
    """Intersection of the two infinite lines, or None if (near-)parallel."""
    x1, y1, x2, y2 = a1.x, a1.y, a2.x, a2.y
    x3, y3, x4, y4 = b1.x, b1.y, b2.x, b2.y
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return Pt(px, py)
