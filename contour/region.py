"""
region.py - the stock boundary walk, driven by clicking on the stock.

One click does everything:
  - the profile/extension intersection nearest the click becomes the start
  - the direction is whichever way round the loop reaches the click first
  - the walk runs until it meets the NEXT intersection, and stops there

If that is not far enough, click again and it continues from where it stopped,
the same extend-by-clicking behaviour the profile chain already has.

Trimmed pieces are partial elements tagged origin="stock", carrying the
source_id of the stock element they came from.

Together with the extended profile these bound the material region, which is
what roughing removes and what settles the comp side explicitly.
"""

import math

from .model import Contour, Line, Arc, Point, ArcDir
from . import geom2d as G

TOL = 1e-7


# ---------------------------------------------------------------------------
# positions on the closed stock loop
# ---------------------------------------------------------------------------

def _elem_length(e):
    if e.kind == "line":
        return math.hypot(e.end.z - e.start.z, e.end.r - e.start.r)
    a0 = math.atan2(e.start.r - e.center.r, e.start.z - e.center.z)
    a1 = math.atan2(e.end.r - e.center.r, e.end.z - e.center.z)
    if e.direction == ArcDir.CCW:
        while a1 <= a0:
            a1 += 2 * math.pi
    else:
        while a1 >= a0:
            a1 -= 2 * math.pi
    return abs(a1 - a0) * e.radius


def _cumulative(stock):
    lens = [_elem_length(e) for e in stock.contour.elements]
    cum, s = [], 0.0
    for L in lens:
        cum.append(s)
        s += L
    return lens, cum, s


def _point_at(e, t):
    if e.kind == "line":
        return Point(e.start.z + t * (e.end.z - e.start.z),
                     e.start.r + t * (e.end.r - e.start.r))
    c = (e.center.z, e.center.r)
    a0 = math.atan2(e.start.r - c[1], e.start.z - c[0])
    a1 = math.atan2(e.end.r - c[1], e.end.z - c[0])
    if e.direction == ArcDir.CCW:
        while a1 <= a0:
            a1 += 2 * math.pi
    else:
        while a1 >= a0:
            a1 -= 2 * math.pi
    a = a0 + (a1 - a0) * t
    return Point(c[0] + e.radius * math.cos(a), c[1] + e.radius * math.sin(a))


def _param_on(e, pt, tol=1e-4):
    """Parameter 0..1 of pt along e, or None if pt is not on it."""
    if e.kind == "line":
        a = (e.start.z, e.start.r)
        b = (e.end.z, e.end.r)
        d = G.sub(b, a)
        L2 = G.dot(d, d)
        if L2 < 1e-18:
            return None
        t = G.dot(G.sub(pt, a), d) / L2
        if t < -0.001 or t > 1.001:
            return None
        if G.dist(G.add(a, G.scale(d, t)), pt) > tol:
            return None
        return min(1.0, max(0.0, t))
    c = (e.center.z, e.center.r)
    if abs(G.dist(pt, c) - e.radius) > tol:
        return None
    a0 = math.atan2(e.start.r - c[1], e.start.z - c[0])
    a1 = math.atan2(e.end.r - c[1], e.end.z - c[0])
    ap = math.atan2(pt[1] - c[1], pt[0] - c[0])
    if e.direction == ArcDir.CCW:
        while a1 <= a0:
            a1 += 2 * math.pi
        while ap < a0 - 1e-9:
            ap += 2 * math.pi
    else:
        while a1 >= a0:
            a1 -= 2 * math.pi
        while ap > a0 + 1e-9:
            ap -= 2 * math.pi
    span = a1 - a0
    if abs(span) < 1e-12:
        return None
    t = (ap - a0) / span
    if t < -0.001 or t > 1.001:
        return None
    return min(1.0, max(0.0, t))


def loop_position(stock, pt, tol=1e-4):
    """Distance around the loop to pt, or None if pt is not on the stock."""
    lens, cum, total = _cumulative(stock)
    best = None
    for i, e in enumerate(stock.contour.elements):
        t = _param_on(e, pt, tol)
        if t is None:
            continue
        s = cum[i] + t * lens[i]
        d = G.dist((_point_at(e, t).z, _point_at(e, t).r), pt)
        if best is None or d < best[0]:
            best = (d, s)
    return None if best is None else best[1]


def nearest_loop_position(stock, pt):
    """Closest point ON the loop to an arbitrary click, as a loop distance."""
    lens, cum, total = _cumulative(stock)
    best = None
    for i, e in enumerate(stock.contour.elements):
        steps = 200
        for k in range(steps + 1):
            t = k / steps
            p = _point_at(e, t)
            d = G.dist((p.z, p.r), pt)
            if best is None or d < best[0]:
                best = (d, cum[i] + t * lens[i])
    return best[1]


# ---------------------------------------------------------------------------
# intersections between the extended profile and the stock loop
# ---------------------------------------------------------------------------

def profile_stock_intersections(extended, stock):
    """
    Loop distances of every point where the extended profile meets the stock.
    Endpoints of the profile that lie on the stock count, which is the normal
    case once extensions have been run out to it.
    """
    out = []
    for e in extended.elements:
        for pt in ((e.start.z, e.start.r), (e.end.z, e.end.r)):
            s = loop_position(stock, pt)
            if s is not None:
                out.append(s)
    # crossings partway along an element, for profiles that pass through
    for pe in extended.elements:
        if pe.kind != "line":
            continue
        a = (pe.start.z, pe.start.r)
        b = (pe.end.z, pe.end.r)
        for se in stock.contour.elements:
            if se.kind != "line":
                continue
            p = G.intersect_line_line(a, b, (se.start.z, se.start.r),
                                      (se.end.z, se.end.r))
            if p is None:
                continue
            if _param_on(pe, p) is None or _param_on(se, p) is None:
                continue
            s = loop_position(stock, p)
            if s is not None:
                out.append(s)
    # de-duplicate
    uniq = []
    for s in sorted(out):
        if not uniq or abs(s - uniq[-1]) > 1e-6:
            uniq.append(s)
    return uniq


# ---------------------------------------------------------------------------
# the walk
# ---------------------------------------------------------------------------

def _sub_element(e, t0, t1):
    p0, p1 = _point_at(e, t0), _point_at(e, t1)
    if e.kind == "line":
        return Line(p0, p1, source_id=e.source_id, origin="stock")
    return Arc(p0, p1, Point(e.center.z, e.center.r), e.direction,
               source_id=e.source_id, origin="stock")


def _slice_loop(stock, s_from, s_to, forward):
    """Elements covering the loop from s_from to s_to in the given direction."""
    lens, cum, total = _cumulative(stock)
    els = stock.contour.elements
    n = len(els)
    out = []

    def split(i, ta, tb):
        if abs(tb - ta) < 1e-9:
            return
        out.append(_sub_element(els[i], min(ta, tb), max(ta, tb))
                   if forward else
                   _sub_element(els[i], min(ta, tb), max(ta, tb)))

    span = (s_to - s_from) % total if forward else (s_from - s_to) % total
    if span < 1e-9:
        span = total

    walked = 0.0
    s = s_from
    guard = 0
    while walked < span - 1e-9 and guard < 4 * n + 8:
        guard += 1
        i = 0
        while i < n - 1 and s >= cum[i + 1] - 1e-12:
            i += 1
        t = (s - cum[i]) / lens[i] if lens[i] > 0 else 0.0
        if forward:
            room = lens[i] * (1.0 - t)
            take = min(room, span - walked)
            t2 = t + take / lens[i] if lens[i] > 0 else 1.0
            split(i, t, t2)
            walked += take
            s = (cum[i] + t2 * lens[i]) % total
            if take >= room - 1e-12:
                s = (cum[i] + lens[i]) % total
        else:
            room = lens[i] * t
            if room < 1e-12:
                i = (i - 1) % n
                s = (cum[i] + lens[i]) % total
                continue
            take = min(room, span - walked)
            t2 = t - take / lens[i] if lens[i] > 0 else 0.0
            split(i, t2, t)
            walked += take
            s = (cum[i] + t2 * lens[i]) % total
    if not forward:
        out = [_reverse_el(e) for e in reversed(out)]
    return out


def _reverse_el(e):
    if e.kind == "line":
        return Line(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
                    source_id=e.source_id, origin=e.origin)
    d = ArcDir.CW if e.direction == ArcDir.CCW else ArcDir.CCW
    return Arc(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
               Point(e.center.z, e.center.r), d,
               source_id=e.source_id, origin=e.origin)


def stock_click(stock, extended, click_pt, chain_end_s=None):
    """
    Advance the stock boundary walk by one click.

    click_pt      (z, r) of the click, in part coordinates
    chain_end_s   loop distance where the current walk ends, or None to start

    Returns (elements, end_s, notes). `end_s` feeds the next click.
    """
    notes = []
    lens, cum, total = _cumulative(stock)
    stops = profile_stock_intersections(extended, stock)
    if not stops:
        return [], None, ["the profile does not meet the stock anywhere - "
                          "extend it to the stock first"]

    s_click = nearest_loop_position(stock, click_pt)

    if chain_end_s is None:
        # start at the intersection nearest the click
        s_start = min(stops, key=lambda s: min((s - s_click) % total,
                                               (s_click - s) % total))
    else:
        s_start = chain_end_s

    fwd = (s_click - s_start) % total
    bwd = (s_start - s_click) % total
    forward = fwd <= bwd

    # first stop strictly ahead in that direction
    ahead = []
    for s in stops:
        d = (s - s_start) % total if forward else (s_start - s) % total
        if d > 1e-6:
            ahead.append((d, s))
    if not ahead:
        return [], None, ["no further intersection in that direction"]
    _, s_end = min(ahead)

    els = _slice_loop(stock, s_start, s_end, forward)
    if not els:
        return [], None, ["that click produced an empty walk"]
    return els, s_end, notes
