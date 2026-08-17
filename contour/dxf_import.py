"""
DXF -> Contour importer.

Two jobs:
  1. CHAIN BUILDING - a DXF is an unordered bag of LINE/ARC entities.
     We connect them end-to-end into an ordered walk, tolerating small gaps.
  2. COORDINATE TRANSFORM - map the DXF's drawing frame into part coords
     (z along axis, r = radius). This part IS machine/CAM specific and is
     isolated here so it's easy to change.

This intentionally does NOT use ezdxf yet - it hand-parses the tagged format
so it runs anywhere with zero dependencies. Swapping in ezdxf later only
changes read_entities(); everything downstream stays identical.
"""

import math
from .model import Contour, Line, Arc, Point, ArcDir, Side


# ---------------------------------------------------------------------------
# 1. Raw entity reading (dependency-free tagged-pair parser)
# ---------------------------------------------------------------------------

def read_entities(path):
    """Return a list of raw entity dicts from the DXF ENTITIES section."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    lines = [l.strip() for l in raw.replace("\r", "").split("\n")]
    i = lines.index("ENTITIES")
    try:
        j = lines.index("ENDSEC", i)
    except ValueError:
        j = len(lines)
    body = lines[i + 1:j]
    pairs = [(body[k], body[k + 1]) for k in range(0, len(body) - 1, 2)]

    entities = []
    cur = None
    for code, val in pairs:
        if code == "0":
            if cur:
                entities.append(cur)
            cur = {"type": val, "codes": {}}
        elif cur is not None:
            cur["codes"].setdefault(code, []).append(val)
    if cur:
        entities.append(cur)
    return entities


def _num(entity, code, idx=0, default=None):
    v = entity["codes"].get(code)
    return float(v[idx]) if v else default


# ---------------------------------------------------------------------------
# 2. Convert raw entities to geometry in DXF coordinates
# ---------------------------------------------------------------------------
# We keep a lightweight (kind, endpoints, arc-info) tuple here - not the final
# Contour elements yet, because chaining may need to REVERSE an element, and
# arcs carry direction that flips when reversed.

class _RawSeg:
    __slots__ = ("kind", "a", "b", "center", "r", "ccw")

    def __init__(self, kind, a, b, center=None, r=None, ccw=None):
        self.kind = kind
        self.a = a            # (x, y) start in DXF coords
        self.b = b            # (x, y) end
        self.center = center  # (x, y) for arcs
        self.r = r
        self.ccw = ccw        # DXF arcs are always CCW from start_ang to end_ang


def _raw_segments(entities):
    segs = []
    for e in entities:
        t = e["type"]
        if t == "LINE":
            a = (_num(e, "10"), _num(e, "20"))
            b = (_num(e, "11"), _num(e, "21"))
            segs.append(_RawSeg("line", a, b))
        elif t == "ARC":
            cx, cy = _num(e, "10"), _num(e, "20")
            r = _num(e, "40")
            sa = math.radians(_num(e, "50"))
            ea = math.radians(_num(e, "51"))
            a = (cx + r * math.cos(sa), cy + r * math.sin(sa))
            b = (cx + r * math.cos(ea), cy + r * math.sin(ea))
            # DXF arcs always sweep CCW from start angle to end angle
            segs.append(_RawSeg("arc", a, b, center=(cx, cy), r=r, ccw=True))
    return segs


# ---------------------------------------------------------------------------
# 3. Chain building - connect segments end to end, tolerating gaps
# ---------------------------------------------------------------------------

def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def build_chain(segs, tol=1e-3, start_hint=None):
    """
    Order the segments into a single connected walk.

    tol: two endpoints within this distance are treated as the same point.
    start_hint: optional (x,y); the endpoint nearest this becomes the chain
                start. Handy to force a known starting end (e.g. the face).

    Returns (ordered_segs, problems). Each ordered seg is oriented so its
    .a flows into the next seg's .a. Arcs get their .ccw flag flipped when
    the segment is walked in reverse.
    """
    problems = []
    remaining = list(segs)

    # choose a starting segment/endpoint
    if start_hint is not None:
        # find the endpoint (over all segs) closest to the hint
        best = None
        for idx, s in enumerate(remaining):
            for end, pt in (("a", s.a), ("b", s.b)):
                d = _dist(pt, start_hint)
                if best is None or d < best[0]:
                    best = (d, idx, end)
        _, idx, end = best
        first = remaining.pop(idx)
        if end == "b":
            first = _reverse(first)
    else:
        first = remaining.pop(0)

    chain = [first]
    cursor = first.b  # the open end we need to extend from

    while remaining:
        # find the segment whose nearest endpoint is closest to cursor
        best = None
        for idx, s in enumerate(remaining):
            da, db = _dist(s.a, cursor), _dist(s.b, cursor)
            d, end = (da, "a") if da <= db else (db, "b")
            if best is None or d < best[0]:
                best = (d, idx, end)

        d, idx, end = best
        nxt = remaining.pop(idx)
        if end == "b":
            nxt = _reverse(nxt)

        if d > tol:
            problems.append(
                f"gap of {d:.5f} bridged between "
                f"({cursor[0]:.4f},{cursor[1]:.4f}) and "
                f"({nxt.a[0]:.4f},{nxt.a[1]:.4f})"
            )
            # snap: move this segment's start exactly onto the cursor so the
            # resulting contour is continuous. The far end is left as drawn.
            nxt = _snap_start(nxt, cursor)

        chain.append(nxt)
        cursor = nxt.b

    return chain, problems


def _reverse(seg):
    if seg.kind == "line":
        return _RawSeg("line", seg.b, seg.a)
    # reversing an arc flips its sweep direction
    return _RawSeg("arc", seg.b, seg.a, center=seg.center, r=seg.r,
                   ccw=not seg.ccw)


def _snap_start(seg, new_a):
    """Return a copy of seg with its start point moved to new_a."""
    if seg.kind == "line":
        return _RawSeg("line", new_a, seg.b)
    # for an arc we keep center/radius/dir and just move the start endpoint;
    # tiny snaps (sub-tol) don't meaningfully distort the arc.
    return _RawSeg("arc", new_a, seg.b, center=seg.center, r=seg.r, ccw=seg.ccw)


# ---------------------------------------------------------------------------
# 4. Coordinate transform: DXF frame -> part coords (z axial, r radial)
# ---------------------------------------------------------------------------
# For THIS CAM/drawing: DXF x is the axial axis (already negative into part),
# DXF y is the radius. So the mapping is simply z = x, r = y.
# Isolated here so a different drawing convention is a one-function change.

def _to_part(pt):
    x, y = pt
    return Point(z=x, r=y)


# ---------------------------------------------------------------------------
# 5. Top-level: DXF file -> Contour
# ---------------------------------------------------------------------------

def import_dxf(path, side=Side.OD, tol=1e-3, start_hint=None, name=None):
    """
    Read a DXF and return (Contour, problems).

    start_hint is given in DXF coords. Default picks the endpoint nearest the
    origin (the face, z=0) as the chain start, which matches lathe convention.
    """
    entities = read_entities(path)
    segs = _raw_segments(entities)
    if start_hint is None:
        start_hint = (0.0, 0.0)

    chain, problems = build_chain(segs, tol=tol, start_hint=start_hint)

    elements = []
    for s in chain:
        a, b = _to_part(s.a), _to_part(s.b)
        if s.kind == "line":
            elements.append(Line(a, b))
        else:
            center = _to_part(s.center)
            # DXF ccw in (x,y) maps directly to ccw in (z,r) since the
            # transform is identity-orientation (z=x, r=y). Post decides G2/G3.
            direction = ArcDir.CCW if s.ccw else ArcDir.CW
            elements.append(Arc(a, b, center, direction))

    contour = Contour(elements=elements, side=side,
                      name=name or "imported")
    problems += contour.check_continuity(tol=max(tol, 1e-4))
    return contour, problems
