"""
select.py - choosing which DXF elements make up the part profile.

Two selection modes, matching how a ShopTurn-style picker works:

  AUTO CHAIN   pick a start element and an end element; the chain between them
               is taken automatically. A direction flag decides which way round
               to walk, which matters for a CLOSED profile where there are two
               routes between any two elements.

  MANUAL       pick every element explicitly. Used when the auto chain would
               take the wrong route, or when the wanted elements are not
               contiguous in the imported order.

Both return a new Contour. Elements keep their `source_id`, so a selection made
graphically can be stored and replayed.

Selection happens BEFORE extension and compensation: pick the profile, extend it
to the stock, then compensate.
"""

import math

from .model import Contour, Line, Arc, Point, ArcDir
from . import geom2d as G


def _clone(e):
    if e.kind == "line":
        return Line(Point(e.start.z, e.start.r), Point(e.end.z, e.end.r),
                    source_id=e.source_id, origin=e.origin)
    return Arc(Point(e.start.z, e.start.r), Point(e.end.z, e.end.r),
               Point(e.center.z, e.center.r), e.direction,
               source_id=e.source_id, origin=e.origin)


def _reversed_element(e):
    if e.kind == "line":
        return Line(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
                    source_id=e.source_id, origin=e.origin)
    d = ArcDir.CW if e.direction == ArcDir.CCW else ArcDir.CCW
    return Arc(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
               Point(e.center.z, e.center.r), d,
               source_id=e.source_id, origin=e.origin)


# ---------------------------------------------------------------------------
# auto chaining
# ---------------------------------------------------------------------------

def chain_indices(contour, start_index, end_index, forward=True):
    """
    Indices walked from start_index to end_index inclusive.

    forward=True steps in increasing index order, False in decreasing. On a
    CLOSED contour the walk wraps around the ends, so both directions are valid
    routes and the flag picks which one. On an OPEN contour a walk that would
    need to wrap is an error - the elements simply are not connected that way.
    """
    n = len(contour.elements)
    if n == 0:
        raise ValueError("contour has no elements")
    for label, i in (("start", start_index), ("end", end_index)):
        if not (0 <= i < n):
            raise ValueError(f"{label} index {i} out of range 0..{n-1}")

    idxs = []
    i = start_index
    for _ in range(n + 1):
        idxs.append(i)
        if i == end_index:
            break
        nxt = i + 1 if forward else i - 1
        if not contour.closed and not (0 <= nxt < n):
            raise ValueError(
                f"open profile: cannot walk {'forward' if forward else 'backward'} "
                f"from element {start_index} to {end_index} without wrapping")
        i = nxt % n
    else:
        raise ValueError("chain walk did not terminate")
    return idxs


def auto_chain(contour, start_index, end_index, forward=True, name=None):
    """Select the chain between two elements. Returns a new Contour."""
    idxs = chain_indices(contour, start_index, end_index, forward)
    els = []
    for i in idxs:
        e = contour.elements[i]
        els.append(_clone(e) if forward else _reversed_element(e))
    return Contour(elements=els, side=contour.side, closed=False,
                   name=name or (contour.name + "_sel"))


# ---------------------------------------------------------------------------
# manual selection
# ---------------------------------------------------------------------------

def manual(contour, indices, forward=True, name=None):
    """
    Select exactly the listed elements, in the order given. If the caller passes
    an unordered set, it is sorted into contour order first (and reversed when
    forward is False).

    No continuity is enforced - the caller may deliberately pick a disjoint set.
    Use `check_selection` to find out whether the result is a connected chain.
    """
    if isinstance(indices, (set, frozenset)):
        indices = sorted(indices, reverse=not forward)
    els = []
    for i in indices:
        if not (0 <= i < len(contour.elements)):
            raise ValueError(f"index {i} out of range")
        e = contour.elements[i]
        els.append(_clone(e) if forward else _reversed_element(e))
    return Contour(elements=els, side=contour.side, closed=False,
                   name=name or (contour.name + "_sel"))


def check_selection(sel, tol=1e-4):
    """Continuity problems in a selection; empty list means a clean chain."""
    return sel.check_continuity(tol=tol)


# ---------------------------------------------------------------------------
# by source id (what a graphical picker stores)
# ---------------------------------------------------------------------------

def indices_for_source_ids(contour, ids):
    return [i for i, e in enumerate(contour.elements) if e.source_id in ids]


def manual_by_source_ids(contour, ids, forward=True, name=None):
    return manual(contour, indices_for_source_ids(contour, ids),
                  forward=forward, name=name)


# ---------------------------------------------------------------------------
# explicit-order assembly, with bridging over disabled elements
# ---------------------------------------------------------------------------

def _dist(a, b):
    return math.hypot(a.z - b.z, a.r - b.r)


def _oriented(e, prev_end, tol):
    """Return e oriented so its start meets prev_end, if flipping helps."""
    if prev_end is None:
        return e
    if _dist(e.start, prev_end) <= _dist(e.end, prev_end):
        return e
    return _reversed_element(e)


def assemble(contour, order, disabled=(), tol=1e-4, name=None, flip=False,
             blends=None):
    """
    Build a chain from an EXPLICIT element order, skipping disabled elements
    and bridging the resulting gaps with straight lines.

    order     list of element indices, in the order they are to be cut. The
              order itself carries the direction - reversing the list reverses
              the cut.
    disabled  indices to leave out. A run of disabled elements is replaced by a
              single line from the previous kept element's end to the next kept
              element's start. Disabled elements at either end are simply
              dropped, since there is nothing to bridge to.

    blends    {(i, j): radius} keyed on the UNORDERED pair of contour indices
              either side of a junction. Because the key is unordered, the same
              entry lands correctly whichever way the chain runs - reversing
              needs no special handling.

    flip      reverse the finished chain end for end. Reversing the `order`
              list already does this for a multi-element chain, but a one-element
              chain has nothing to reorder, so this is what swaps its start and
              end points.

    Elements are oriented automatically so the chain flows: each one is flipped
    if that makes it meet the previous element's end. Bridge lines are tagged
    origin="bridge" and carry no source_id.

    Returns (Contour, notes).
    """
    off = set(disabled)
    kept = [i for i in order if i not in off]
    notes = []
    if not kept:
        return Contour(elements=[], side=contour.side, closed=False,
                       name=name or contour.name + "_sel"), ["nothing kept"]

    els = []
    meta = []          # ('real', idx) or ('bridge', (prev_idx, next_idx))
    prev_end = None
    prev_idx = None
    for pos, i in enumerate(kept):
        e = _clone(contour.elements[i])
        if prev_end is None and len(kept) > 1:
            # No predecessor to orient against, so look AHEAD: the first
            # element must END nearest the second one. Without this a reversed
            # order leaves element one backwards and a spurious bridge appears.
            nxt = contour.elements[kept[1]]
            d_as_is = min(_dist(e.end, nxt.start), _dist(e.end, nxt.end))
            d_flip = min(_dist(e.start, nxt.start), _dist(e.start, nxt.end))
            if d_flip < d_as_is:
                e = _reversed_element(e)
        else:
            e = _oriented(e, prev_end, tol)
        if prev_end is not None and _dist(e.start, prev_end) > tol:
            els.append(Line(Point(prev_end.z, prev_end.r),
                            Point(e.start.z, e.start.r),
                            source_id=None, origin="bridge"))
            meta.append(("bridge", (prev_idx, i)))
        els.append(e)
        meta.append(("real", i))
        prev_end = e.end
        prev_idx = i

    # Blends sit on JUNCTIONS. Every junction between consecutive assembled
    # elements can carry one, including the two ends of a bridge. Keys are
    # direction-neutral so reversing the chain needs no special handling:
    #   real i  <-> real j        ->  blend_key(i, j)          e.g. (2, 3)
    #   real i  <-> bridge(a, b)  ->  "i|far"                  e.g. "1|4"
    # where `far` is the flanking element at the other end of the bridge.
    blend_errors = {}
    if blends:
        new_els = list(els)
        new_meta = list(meta)
        n = 0
        while n < len(new_els) - 1:
            ka, ma = new_meta[n]
            kb, mb = new_meta[n + 1]
            if ka == "real" and kb == "real":
                key = blend_key(ma, mb)
                label = f"{ma}/{mb}"
            elif ka == "real" and kb == "bridge":
                far = mb[1] if mb[0] == ma else mb[0]
                key = f"{ma}|{far}"
                label = f"{ma}/bridge"
            elif ka == "bridge" and kb == "real":
                far = ma[0] if ma[1] == mb else ma[1]
                key = f"{mb}|{far}"
                label = f"bridge/{mb}"
            else:
                n += 1
                continue
            R = blends.get(key)
            if not R:
                n += 1
                continue
            res = make_blend(new_els[n], new_els[n + 1], R, tol=1e-9)
            if res is None:
                mx = max_blend_radius(new_els[n], new_els[n + 1])
                blend_errors[key] = {"asked": R, "max": mx, "where": label}
                notes.append(f"blend R{R} at {label} does not fit "
                             f"(max {mx:.4f})")
                n += 1
                continue
            at, arc, bt = res
            new_els[n] = at
            new_els[n + 1] = bt
            new_els.insert(n + 1, arc)
            new_meta.insert(n + 1, ("blend", key))
            n += 2          # step past the inserted arc and the trimmed element
        els = new_els
        meta = new_meta

    dropped = [i for i in order if i in off]
    if dropped:
        bridges = sum(1 for x in els if getattr(x, "origin", None) == "bridge")
        notes.append(f"skipped {dropped}, bridged with {bridges} line(s)")

    out = Contour(elements=els, side=contour.side, closed=False,
                  name=name or contour.name + "_sel")
    out.meta = list(meta)
    out.blend_errors = blend_errors
    if flip:
        out = Contour(elements=[_reversed_element(e)
                                for e in reversed(out.elements)],
                      side=out.side, closed=False, name=out.name)
        out.meta = list(reversed(meta))
        out.blend_errors = blend_errors
    return out, notes


def is_bridge(element):
    return getattr(element, "origin", None) == "bridge"


# ---------------------------------------------------------------------------
# blend radii (fillets) at junctions
# ---------------------------------------------------------------------------
# A blend belongs to the JUNCTION between two elements, not to either element.
# Keying it on the unordered pair of contour indices means reversing the chain
# needs no special handling: {1,2} is the same junction whichever way the cut
# runs, so the fillet lands between the same two elements either way.

def blend_key(i, j):
    return (i, j) if i <= j else (j, i)


def _elem_data(e):
    if e.kind == "line":
        return "line", ((e.start.z, e.start.r), (e.end.z, e.end.r))
    return "arc", ((e.center.z, e.center.r), e.radius)


def _tangent_point(e, centre):
    kind, data = _elem_data(e)
    if kind == "line":
        return G.foot_on_line(centre, data[0], data[1])
    return G.point_on_circle_toward(data[0], data[1], centre)


def _trim_to(e, pt, at_end):
    """Copy of e with one endpoint moved to pt."""
    p = Point(pt[0], pt[1])
    if e.kind == "line":
        return (Line(e.start, p, source_id=e.source_id, origin=e.origin)
                if at_end else
                Line(p, e.end, source_id=e.source_id, origin=e.origin))
    return (Arc(e.start, p, e.center, e.direction,
                source_id=e.source_id, origin=e.origin)
            if at_end else
            Arc(p, e.end, e.center, e.direction,
                source_id=e.source_id, origin=e.origin))


def make_blend(a, b, radius, tol=1e-6):
    """
    Fillet of `radius` tangent to element a (at its end) and b (at its start).

    Returns (a_trimmed, arc, b_trimmed) or None if no valid fillet fits - the
    radius may be too large for the geometry, or the elements may be tangent
    already.
    """
    if radius <= tol:
        return None
    joint = (a.end.z, a.end.r)
    ka, da = _elem_data(a)
    kb, db = _elem_data(b)
    cands = G.blend_centres(ka, da, kb, db, radius)
    if not cands:
        return None

    best = None
    for cpt in cands:
        ta = _tangent_point(a, cpt)
        tb = _tangent_point(b, cpt)
        # both tangent points must lie on the actual segments, not their
        # infinite extensions, and the centre should sit near the junction
        if not (_on_element(a, ta, tol) and _on_element(b, tb, tol)):
            continue
        d = G.dist(cpt, joint)
        if best is None or d < best[0]:
            best = (d, cpt, ta, tb)
    if best is None:
        return None

    _, centre, ta, tb = best

    # A fillet needs an actual CORNER. Where the two elements already meet
    # tangentially there is nothing to round: every radius is "tangent to both"
    # at the existing point, and the result is a full circle sitting in the
    # toolpath. Reject that rather than emit it.
    if G.dist(ta, joint) <= tol * 10 and G.dist(tb, joint) <= tol * 10:
        return None
    if G.dist(ta, tb) <= tol * 10:
        return None

    # sweep direction: cross product of centre->ta and centre->tb
    va = G.sub(ta, centre)
    vb = G.sub(tb, centre)
    cross = va[0] * vb[1] - va[1] * vb[0]
    direction = ArcDir.CCW if cross > 0 else ArcDir.CW
    arc = Arc(Point(ta[0], ta[1]), Point(tb[0], tb[1]),
              Point(centre[0], centre[1]), direction,
              source_id=None, origin="blend")

    # A corner fillet always sweeps less than half a turn. More than that means
    # the solver took a centre on the wrong side.
    a0 = math.atan2(ta[1] - centre[1], ta[0] - centre[0])
    a1 = math.atan2(tb[1] - centre[1], tb[0] - centre[0])
    d = a1 - a0
    while d <= -math.pi:
        d += 2 * math.pi
    while d > math.pi:
        d -= 2 * math.pi
    if abs(math.degrees(d)) >= 179.0 or abs(math.degrees(d)) < 1e-6:
        return None

    return _trim_to(a, ta, True), arc, _trim_to(b, tb, False)


def _on_element(e, pt, tol=1e-6):
    """Is pt within the extent of element e (not its infinite extension)?"""
    if e.kind == "line":
        d = G.sub((e.end.z, e.end.r), (e.start.z, e.start.r))
        L2 = G.dot(d, d)
        if L2 < tol:
            return False
        t = G.dot(G.sub(pt, (e.start.z, e.start.r)), d) / L2
        return -tol <= t <= 1 + tol
    # arc: the point must fall inside the swept angle
    c = (e.center.z, e.center.r)
    a0 = math.atan2(e.start.r - c[1], e.start.z - c[0])
    a1 = math.atan2(e.end.r - c[1], e.end.z - c[0])
    ap = math.atan2(pt[1] - c[1], pt[0] - c[0])
    if e.direction == ArcDir.CCW:
        while a1 <= a0:
            a1 += 2 * math.pi
        while ap < a0:
            ap += 2 * math.pi
        return a0 - tol <= ap <= a1 + tol
    while a1 >= a0:
        a1 -= 2 * math.pi
    while ap > a0:
        ap -= 2 * math.pi
    return a1 - tol <= ap <= a0 + tol


def is_blend(element):
    return getattr(element, "origin", None) == "blend"


def max_blend_radius(a, b, lo=0.0, hi=None, iters=40, tol=1e-9):
    """
    Largest radius that will still fit at this junction, found by bisection on
    make_blend. Works for any element pair - line/line, line/arc, arc/arc -
    without needing a closed-form limit for each combination.

    Returns 0.0 if even a vanishingly small blend will not fit.
    """
    if hi is None:
        def _len(e):
            if e.kind == "line":
                return math.hypot(e.end.z - e.start.z, e.end.r - e.start.r)
            a0 = math.atan2(e.start.r - e.center.r, e.start.z - e.center.z)
            a1 = math.atan2(e.end.r - e.center.r, e.end.z - e.center.z)
            return abs(a1 - a0) * e.radius
        hi = max(_len(a), _len(b)) * 4.0 + 1.0

    if make_blend(a, b, hi, tol=tol) is not None:
        return hi
    if make_blend(a, b, 1e-6, tol=tol) is None:
        return 0.0

    lo = 1e-6
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if make_blend(a, b, mid, tol=tol) is not None:
            lo = mid
        else:
            hi = mid
    return lo
