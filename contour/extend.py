"""
extend.py - profile extensions, part of the GEOMETRY definition.

When a part profile is imported from a DXF it usually stops at the finished
shape. The cut needs to start and end in air, outside the stock, so the first
and last elements are extended to reach it. In SolidCAM terms these are the
chain-end extensions, and they belong to the geometry: the extended contour IS
the part profile, reused by every operation that references it.

Applied at definition time:

    c, _   = import_dxf("part.dxf", side=Side.OD)
    st     = parametric(od=5.5, z_face=0.1, z_back=-4.2)
    c      = extend_profile(c, st,
                            start=Extension("+Z"),
                            end=Extension("+X", clearance=0.1))

Direction codes use machine axis names and map to the (z, r) model as:
    +Z -> +z (toward tailstock)     -X -> -r (toward centreline)
    -Z -> -z (toward chuck)         +X -> +r (larger diameter)

`length` overrides the ray-cast, extending a fixed distance instead of running
to the stock. `angle` (degrees, measured from +Z, positive toward +X) overrides
the cardinal direction so an extension can follow a taper rather than run
square. Giving `angle` without `length` casts a ray along that angle.

Extension elements are synthetic: their `source_id` is None, which distinguishes
them from real DXF entities for the graphical picker.
"""

import math
from dataclasses import dataclass
from .model import Contour, Line, Point
from . import geom2d as G

_DIRS = {
    "+Z": (1.0, 0.0), "-Z": (-1.0, 0.0),
    "+X": (0.0, 1.0), "-X": (0.0, -1.0),
}


@dataclass
class Extension:
    """
    One extension segment.

    direction  '+Z','-Z','+X','-X'
    length     fixed distance. Without it the segment runs to the stock
               boundary, which only makes sense for the FIRST segment of a
               chain end - later segments already start outside the stock.
    angle      degrees from +Z toward +X. Overrides `direction`, so a segment
               can run at any angle rather than square.

    Clearance is NOT an extension property. Standoff belongs to the toolpath
    (see cycles.CycleParams.clearance). If a second run-out segment is wanted,
    add a second Extension with its own angle.
    """
    direction: str = "+Z"
    length: float = None
    angle: float = None

    def vector(self):
        """Unit direction in (z, r)."""
        if self.angle is not None:
            a = math.radians(self.angle)
            return (math.cos(a), math.sin(a))
        if self.direction not in _DIRS:
            raise ValueError(f"unknown direction {self.direction!r}; "
                             f"use one of {sorted(_DIRS)}")
        return _DIRS[self.direction]


# ---------------------------------------------------------------------------
# ray casting against the stock boundary
# ---------------------------------------------------------------------------

def _ray_hit_distance(origin, direction, stock):
    """
    Distance from origin along direction to the first stock boundary crossing.
    Returns None if the ray never meets the stock.
    """
    best = None
    far = _far_point(origin, direction, stock)
    for e in stock.contour.elements:
        if e.kind == "line":
            p = G.intersect_line_line(origin, far,
                                      (e.start.z, e.start.r), (e.end.z, e.end.r))
            hits = [p] if p is not None else []
            hits = [h for h in hits if _on_segment(h, e)]
        else:
            hits = G.intersect_line_circle(origin, far,
                                           (e.center.z, e.center.r), e.radius)
        for h in hits:
            t = G.dot(G.sub(h, origin), direction)
            # t == 0 is valid and common: the profile end often sits exactly on
            # the stock boundary (a back face meeting the bar OD). Distance is
            # then zero and only the clearance carries the extension out.
            if t >= -1e-9 and (best is None or t < best):
                best = t
    return best


def _far_point(origin, direction, stock):
    zr = stock.z_range()
    rr = stock.r_range()
    span = max(zr[1] - zr[0], rr[1] - rr[0]) * 10 + 1.0
    return G.add(origin, G.scale(direction, span))


def _on_segment(p, e, tol=1e-7):
    """Is point p within the bounds of line element e?"""
    z0, z1 = sorted((e.start.z, e.end.z))
    r0, r1 = sorted((e.start.r, e.end.r))
    return (z0 - tol <= p[0] <= z1 + tol) and (r0 - tol <= p[1] <= r1 + tol)


# ---------------------------------------------------------------------------
# applying an extension
# ---------------------------------------------------------------------------

def _extension_length(origin, direction, ext, stock):
    if ext.length is not None:
        return ext.length
    if stock is None:
        raise ValueError("extension needs either a length or a stock to run to")
    d = _ray_hit_distance(origin, direction, stock)
    if d is None:
        raise ValueError(f"extension from ({origin[0]:.4f},{origin[1]:.4f}) "
                         f"along {direction} never meets the stock")
    return d


def _as_list(x):
    if x is None:
        return []
    if isinstance(x, Extension):
        return [x]
    return list(x)


def extend_profile(contour, stock=None, start=None, end=None):
    """
    Return a new Contour with synthetic extension elements added at the start
    and/or end. The original contour is not modified.

    `start` and `end` each take a single Extension or a LIST of them, applied
    in order outward from the profile. The first may run to the stock; later
    ones need an explicit length, since they begin outside it. Each carries its
    own angle, so a run-out can change direction partway.

    An extension resolving to zero length is DROPPED rather than added as a
    degenerate element - that happens when the profile end already sits on the
    stock boundary.
    """
    els = list(contour.elements)
    if not els:
        return contour

    ZERO = 1e-9

    for ext in _as_list(start):
        p0 = els[0].start
        v = ext.vector()
        L = _extension_length((p0.z, p0.r), v, ext, stock)
        if L > ZERO:
            new_pt = Point(z=p0.z + v[0] * L, r=p0.r + v[1] * L)
            # runs INTO the profile start, so it is prepended
            els.insert(0, Line(new_pt, Point(p0.z, p0.r), source_id=None,
                               origin="extension"))

    for ext in _as_list(end):
        p1 = els[-1].end
        v = ext.vector()
        L = _extension_length((p1.z, p1.r), v, ext, stock)
        if L > ZERO:
            new_pt = Point(z=p1.z + v[0] * L, r=p1.r + v[1] * L)
            els.append(Line(Point(p1.z, p1.r), new_pt, source_id=None,
                            origin="extension"))

    out = Contour(elements=els, side=contour.side, closed=False,
                  name=contour.name + "_ext")
    return out


def is_extension(element):
    """True for synthetic extension elements."""
    return getattr(element, "origin", None) == "extension"


# ---------------------------------------------------------------------------
# blends at extension junctions
# ---------------------------------------------------------------------------
# Extensions are added AFTER the chain is assembled and after any flip, so
# "start" and "end" already mean what the operator sees. Their junctions are
# keyed by which end they belong to and how far out they sit:
#
#   s1  innermost start extension  <->  first profile element
#   s2  second start extension     <->  the innermost one
#   e1  last profile element       <->  innermost end extension
#   e2  innermost end extension    <->  the one beyond it
#
# Extensions carry no contour index, so this positional naming is what makes the
# junction addressable.

def extension_junctions(contour):
    """
    Map junction key -> position in contour.elements of the element BEFORE it.
    Only junctions that actually exist are returned.
    """
    els = contour.elements
    n = len(els)
    lead, trail = 0, 0
    while lead < n and getattr(els[lead], "origin", None) == "extension":
        lead += 1
    while trail < n - lead and \
            getattr(els[n - 1 - trail], "origin", None) == "extension":
        trail += 1

    out = {}
    # leading run is outermost-first, so the innermost is at lead-1
    for k in range(lead):
        inner_first = lead - 1 - k      # k=0 -> innermost
        out[f"s{k + 1}"] = inner_first
    # trailing run is innermost-first
    for k in range(trail):
        pos = n - trail + k             # k=0 -> innermost end extension
        out[f"e{k + 1}"] = pos - 1
    return out


def blend_extensions(contour, blends, tol=1e-9):
    """
    Apply blends at extension junctions. Returns (Contour, notes).

    `blends` may contain keys for other junctions too; only s*/e* are used here.
    """
    from .select import make_blend, max_blend_radius

    notes = []
    errors = {}
    if not blends:
        contour.blend_errors = {}
        return contour, notes
    keys = [k for k in blends
            if isinstance(k, str) and len(k) >= 2 and k[0] in "se"
            and k[1:].isdigit()]
    if not keys:
        contour.blend_errors = {}
        return contour, notes

    els = list(contour.elements)
    # work outward-in on each end so earlier positions stay valid
    for key in sorted(keys, reverse=True):
        cur = Contour(elements=els, side=contour.side, closed=False,
                      name=contour.name)
        jmap = extension_junctions(cur)
        if key not in jmap:
            continue
        pa = jmap[key]
        pb = pa + 1
        if pb >= len(els):
            continue
        res = make_blend(els[pa], els[pb], blends[key], tol=tol)
        if res is None:
            mx = max_blend_radius(els[pa], els[pb])
            errors[key] = {"asked": blends[key], "max": mx,
                           "where": f"extension {key}"}
            notes.append(f"blend R{blends[key]} at extension {key} "
                         f"does not fit (max {mx:.4f})")
            continue
        at, arc, bt = res
        els[pa] = at
        els[pb] = bt
        els.insert(pb, arc)

    out = Contour(elements=els, side=contour.side, closed=False,
                  name=contour.name)
    out.blend_errors = errors
    return out, notes
