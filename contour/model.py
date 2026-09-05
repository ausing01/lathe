"""
The contour model - the single most important object in the system.

A Contour is an ordered chain of Elements (lines and arcs) describing a
turned profile. It is stored in PART coordinates:

    z  = distance along the spindle axis. z=0 at the face, negative into the part.
    r  = RADIUS from the centerline (never diameter). Always >= 0.

Everything downstream consumes this:
    - the DXF importer produces one
    - the G-code post walks one
    - later: the roughing generator, the simulator, the preview renderer

Storing radius (not diameter) internally keeps the geometry math clean.
The post is the only place that doubles r -> diameter for the machine.
"""

from dataclasses import dataclass, field
from enum import Enum
import math


class Side(Enum):
    """Which surface of the part this contour describes."""
    OD = "OD"   # outside diameter - tool approaches from larger radius
    ID = "ID"   # inside diameter (bore) - tool approaches from smaller radius


class ArcDir(Enum):
    """Sweep direction of an arc, in the (z, r) plane as you travel the chain."""
    CW = "CW"    # clockwise  -> emits G2 in a standard lathe post
    CCW = "CCW"  # counter-clockwise -> emits G3


@dataclass
class Point:
    z: float
    r: float

    def __iter__(self):
        yield self.z
        yield self.r

    def close_to(self, other, tol):
        return abs(self.z - other.z) <= tol and abs(self.r - other.r) <= tol


@dataclass
class Line:
    """A straight segment from start to end (both in part coords)."""
    start: Point
    end: Point
    source_id: int = None   # index of the DXF entity this came from (or None)
    origin: str = None      # None = real DXF element, "extension", "bridge"

    @property
    def kind(self):
        return "line"


@dataclass
class Arc:
    """
    A circular segment. Stored by start, end, center and direction.
    Radius is derived from center<->start so it can't disagree with the points.
    """
    start: Point
    end: Point
    center: Point
    direction: ArcDir
    source_id: int = None   # index of the DXF entity this came from (or None)
    origin: str = None      # None = real DXF element, "extension", "bridge"

    @property
    def kind(self):
        return "arc"

    @property
    def radius(self):
        return math.hypot(self.start.z - self.center.z,
                          self.start.r - self.center.r)


@dataclass
class Contour:
    """An ordered chain of elements describing one profile."""
    elements: list = field(default_factory=list)
    side: Side = Side.OD
    closed: bool = False   # does the chain form a closed loop?
    name: str = "contour"

    # --- basic queries -------------------------------------------------

    def start_point(self):
        return self.elements[0].start if self.elements else None

    def end_point(self):
        return self.elements[-1].end if self.elements else None

    def z_range(self):
        zs = [p.z for e in self.elements for p in (e.start, e.end)]
        return (min(zs), max(zs)) if zs else (0.0, 0.0)

    def r_range(self):
        rs = [p.r for e in self.elements for p in (e.start, e.end)]
        return (min(rs), max(rs)) if rs else (0.0, 0.0)

    # --- integrity checks ----------------------------------------------

    def check_continuity(self, tol=1e-4):
        """
        Verify each element's end matches the next element's start.
        Returns a list of human-readable problems (empty == clean chain).
        """
        problems = []
        for i in range(len(self.elements) - 1):
            a_end = self.elements[i].end
            b_start = self.elements[i + 1].start
            if not a_end.close_to(b_start, tol):
                gap = math.hypot(a_end.z - b_start.z, a_end.r - b_start.r)
                problems.append(
                    f"gap of {gap:.5f} between element {i} "
                    f"(ends {a_end.z:.4f},{a_end.r:.4f}) and element {i+1} "
                    f"(starts {b_start.z:.4f},{b_start.r:.4f})"
                )
        return problems

    def describe(self):
        """One-line-per-element human dump, for eyeballing in the terminal."""
        out = [f"Contour '{self.name}'  side={self.side.value}  "
               f"elements={len(self.elements)}"]
        zr = self.z_range(); rr = self.r_range()
        out.append(f"  z: {zr[0]:.4f} .. {zr[1]:.4f}   "
                   f"r: {rr[0]:.4f} .. {rr[1]:.4f}")
        for i, e in enumerate(self.elements):
            if e.kind == "line":
                out.append(f"  [{i}] line  "
                           f"({e.start.z:+.4f},{e.start.r:.4f}) -> "
                           f"({e.end.z:+.4f},{e.end.r:.4f})")
            else:
                out.append(f"  [{i}] arc   "
                           f"({e.start.z:+.4f},{e.start.r:.4f}) -> "
                           f"({e.end.z:+.4f},{e.end.r:.4f})  "
                           f"R{e.radius:.4f} {e.direction.value}")
        return "\n".join(out)


def element_properties(e, index=None):
    """
    Human-readable characteristics of one element, for display.

    Angles are degrees measured from +Z toward +R. Lengths are true lengths in
    the (z, r) plane. X values are DIAMETER, since that is what gets programmed;
    r values are radius, as stored.
    """
    d = {
        "index": index,
        "kind": e.kind,
        "source_id": e.source_id,
        "synthetic": e.source_id is None,
        "origin": e.origin,
        "start_z": e.start.z, "start_r": e.start.r, "start_x": 2 * e.start.r,
        "end_z": e.end.z, "end_r": e.end.r, "end_x": 2 * e.end.r,
    }
    if e.kind == "line":
        dz = e.end.z - e.start.z
        dr = e.end.r - e.start.r
        d["length"] = math.hypot(dz, dr)
        d["angle"] = math.degrees(math.atan2(dr, dz))
        d["dz"] = dz
        d["dr"] = dr
        # Angle off the spindle axis is what gets read off a print: 0 for a
        # straight diameter, 90 for a face, 45 for a 45-degree chamfer.
        # Included angle is the full cone, i.e. twice that.
        off_axis = math.degrees(math.atan2(abs(dr), abs(dz)))
        d["angle_from_axis"] = off_axis
        d["included_angle"] = 2 * off_axis
    else:
        d["radius"] = e.radius
        d["center_z"] = e.center.z
        d["center_r"] = e.center.r
        d["center_x"] = 2 * e.center.r
        d["direction"] = e.direction.value
        a0 = math.atan2(e.start.r - e.center.r, e.start.z - e.center.z)
        a1 = math.atan2(e.end.r - e.center.r, e.end.z - e.center.z)
        if e.direction == ArcDir.CCW:
            while a1 <= a0:
                a1 += 2 * math.pi
        else:
            while a1 >= a0:
                a1 -= 2 * math.pi
        sweep = a1 - a0
        d["start_angle"] = math.degrees(a0)
        d["end_angle"] = math.degrees(a1)
        d["sweep"] = math.degrees(sweep)
        d["length"] = abs(sweep) * e.radius
    return d
