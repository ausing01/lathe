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
    __slots__ = ("kind", "a", "b", "center", "r", "ccw", "entity_id")

    def __init__(self, kind, a, b, center=None, r=None, ccw=None,
                 entity_id=None):
        self.kind = kind
        self.a = a            # (x, y) start in DXF coords
        self.b = b            # (x, y) end
        self.center = center  # (x, y) for arcs
        self.r = r
        self.ccw = ccw        # DXF arcs are always CCW from start_ang to end_ang
        self.entity_id = entity_id  # index into the DXF entity list (identity hook)


def _raw_segments(entities):
    segs = []
    for idx, e in enumerate(entities):
        t = e["type"]
        if t == "LINE":
            a = (_num(e, "10"), _num(e, "20"))
            b = (_num(e, "11"), _num(e, "21"))
            segs.append(_RawSeg("line", a, b, entity_id=idx))
        elif t == "ARC":
            cx, cy = _num(e, "10"), _num(e, "20")
            r = _num(e, "40")
            sa = math.radians(_num(e, "50"))
            ea = math.radians(_num(e, "51"))
            a = (cx + r * math.cos(sa), cy + r * math.sin(sa))
            b = (cx + r * math.cos(ea), cy + r * math.sin(ea))
            # DXF arcs always sweep CCW from start angle to end angle
            segs.append(_RawSeg("arc", a, b, center=(cx, cy), r=r, ccw=True,
                                entity_id=idx))
    return segs


# ---------------------------------------------------------------------------
# 3. Chain building - connect segments end to end, tolerating gaps
# ---------------------------------------------------------------------------

def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def build_chain(segs, tol=1e-3, start_hint=None):
    """
    Order the segments into a connected walk using true endpoint CONNECTIVITY.

    Unlike a greedy nearest-neighbour walk (which will happily invent a
    connection across a gap to whatever endpoint is closest), this builds a
    node graph: endpoints within `tol` of each other are the same node, and
    each segment is an edge between two nodes. The walk then follows only real
    edges - it never bridges a gap that has no entity across it.

    Returns (ordered_segs, problems):
      - segments are oriented so each .b flows into the next .a
      - reversed segments keep their entity_id and flip arc direction
      - problems flags gaps, branches (a node with >2 edges), and any segments
        left unconnected (a separate chain / stray entity)

    start_hint (x,y), optional: of the two natural chain ends, start from the
    one nearer this point. Default (origin) picks the end nearest the face.
    """
    problems = []
    if not segs:
        return [], ["no segments to chain"]

    # --- 1. cluster endpoints into nodes -------------------------------------
    # node_of[(seg_index, 'a'|'b')] = node id
    nodes = []                 # list of representative (x, y) points
    node_of = {}

    def node_for(pt):
        for nid, npt in enumerate(nodes):
            if _dist(pt, npt) <= tol:
                return nid
        nodes.append(pt)
        return len(nodes) - 1

    # adjacency: node id -> list of (seg_index, which_end_is_here)
    adj = {}
    for i, s in enumerate(segs):
        na = node_for(s.a)
        nb = node_for(s.b)
        node_of[(i, "a")] = na
        node_of[(i, "b")] = nb
        adj.setdefault(na, []).append((i, "a"))
        adj.setdefault(nb, []).append((i, "b"))

    # --- 2. classify nodes ---------------------------------------------------
    # degree 1 = a free end; degree 2 = normal interior; >2 = a branch
    ends = [nid for nid, lst in adj.items() if len(lst) == 1]
    branches = [nid for nid, lst in adj.items() if len(lst) > 2]
    for nid in branches:
        problems.append(
            f"branch at ({nodes[nid][0]:.4f},{nodes[nid][1]:.4f}): "
            f"{len(adj[nid])} segments meet here - profile is not a simple chain")

    # --- 3. choose a start segment/end --------------------------------------
    used = [False] * len(segs)

    def start_end_node():
        # prefer a true free end; of the (usually two) ends, pick nearest hint
        if ends:
            if start_hint is not None:
                return min(ends, key=lambda n: _dist(nodes[n], start_hint))
            return ends[0]
        # no free end => closed loop; start at the node nearest the hint
        if start_hint is not None:
            return min(adj.keys(), key=lambda n: _dist(nodes[n], start_hint))
        return next(iter(adj.keys()))

    # --- 4. walk the chain ---------------------------------------------------
    chain = []
    start_node = start_end_node()
    # pick the (unused) segment leaving the start node
    cur_seg, cur_end = adj[start_node][0]
    cur_node = start_node

    while True:
        s = segs[cur_seg]
        used[cur_seg] = True
        # orient so it leaves cur_node: if this seg's 'a' is at cur_node keep it,
        # else reverse it
        if node_of[(cur_seg, "a")] == cur_node:
            oriented = s
            far_node = node_of[(cur_seg, "b")]
        else:
            oriented = _reverse(s)
            far_node = node_of[(cur_seg, "a")]
        chain.append(oriented)

        # find the next unused segment at far_node
        nxt = None
        for (si, se) in adj.get(far_node, []):
            if not used[si]:
                nxt = si
                break
        if nxt is None:
            break
        cur_seg = nxt
        cur_node = far_node

    # --- 5. report anything we didn't reach ---------------------------------
    unused = [i for i, u in enumerate(used) if not u]
    if unused:
        problems.append(
            f"{len(unused)} segment(s) not connected to the main chain "
            f"(entity ids {[segs[i].entity_id for i in unused]}) - "
            f"separate contour or stray geometry")

    return chain, problems


def _reverse(seg):
    if seg.kind == "line":
        return _RawSeg("line", seg.b, seg.a, entity_id=seg.entity_id)
    # reversing an arc flips its sweep direction
    return _RawSeg("arc", seg.b, seg.a, center=seg.center, r=seg.r,
                   ccw=not seg.ccw, entity_id=seg.entity_id)


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
            elements.append(Line(a, b, source_id=s.entity_id))
        else:
            center = _to_part(s.center)
            # DXF ccw in (x,y) maps directly to ccw in (z,r) since the
            # transform is identity-orientation (z=x, r=y). Post decides G2/G3.
            direction = ArcDir.CCW if s.ccw else ArcDir.CW
            elements.append(Arc(a, b, center, direction, source_id=s.entity_id))

    contour = Contour(elements=elements, side=side,
                      name=name or "imported")
    problems += contour.check_continuity(tol=max(tol, 1e-4))
    return contour, problems
