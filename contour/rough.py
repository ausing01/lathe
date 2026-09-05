"""
rough.py - roughing pass generation.

First version, deliberately simple: axial passes at constant radius, stepping
in by depth of cut, each running until it meets the finish profile plus the
stock allowance. That is the classic G71 shape, and it is the right thing to
get correct before adding anything cleverer.

The model is a scanline: `profile_radius_at(z)` gives the part radius at any z.
Everything else falls out of comparing that against the stock.

Not handled yet, by design:
  - undercuts / re-entrant profiles (a scanline cannot see behind an overhang)
  - plunge or face roughing
  - varying depth of cut
Each of those is a separate pass over this once the basic shape is proven.
"""

import math
from dataclasses import dataclass, field

from .model import ArcDir
from . import geom2d as G
from .comp import COMP_LEFT, COMP_RIGHT


@dataclass
class Move:
    kind: str        # "rapid" or "feed"
    z: float
    r: float

    def __repr__(self):
        return f"{self.kind:5} z{self.z:+9.4f} r{self.r:8.4f}"


# ---------------------------------------------------------------------------
# scanline: the profile radius at a given z
# ---------------------------------------------------------------------------

def profile_radius_at(profile, z, default=0.0):
    """
    Largest part radius at this z. Returns `default` where the profile does not
    reach. Uses the OUTERMOST crossing, which is what an OD pass must clear.
    """
    best = None
    lo = (z, -1e6)
    hi = (z, 1e6)
    for e in profile.elements:
        if e.kind == "line":
            z0, z1 = e.start.z, e.end.z
            if abs(z1 - z0) < 1e-12:
                if abs(z0 - z) < 1e-9:
                    for r in (e.start.r, e.end.r):
                        best = r if best is None else max(best, r)
                continue
            t = (z - z0) / (z1 - z0)
            if -1e-9 <= t <= 1 + 1e-9:
                r = e.start.r + t * (e.end.r - e.start.r)
                best = r if best is None else max(best, r)
        else:
            pts = G.intersect_line_circle(lo, hi,
                                          (e.center.z, e.center.r), e.radius)
            for p in pts:
                if _on_arc(e, p):
                    best = p[1] if best is None else max(best, p[1])
    return default if best is None else best


def profile_z_crossings(profile, level):
    """
    Every z where the profile crosses radius `level`, solved exactly rather
    than sampled. Intersects the horizontal line r=level with each element.
    """
    out = []
    a = (-1e6, level)
    b = (1e6, level)
    for e in profile.elements:
        if e.kind == "line":
            r0, r1 = e.start.r, e.end.r
            if abs(r1 - r0) < 1e-12:
                if abs(r0 - level) < 1e-9:
                    out += [e.start.z, e.end.z]
                continue
            t = (level - r0) / (r1 - r0)
            if -1e-9 <= t <= 1 + 1e-9:
                out.append(e.start.z + t * (e.end.z - e.start.z))
        else:
            for p in G.intersect_line_circle(a, b, (e.center.z, e.center.r),
                                             e.radius):
                if _on_arc(e, p):
                    out.append(p[0])
    return sorted(out)


def _on_arc(e, pt, tol=1e-7):
    c = (e.center.z, e.center.r)
    a0 = math.atan2(e.start.r - c[1], e.start.z - c[0])
    a1 = math.atan2(e.end.r - c[1], e.end.z - c[0])
    ap = math.atan2(pt[1] - c[1], pt[0] - c[0])
    if e.direction == ArcDir.CCW:
        while a1 <= a0:
            a1 += 2 * math.pi
        while ap < a0 - tol:
            ap += 2 * math.pi
        return a0 - tol <= ap <= a1 + tol
    while a1 >= a0:
        a1 -= 2 * math.pi
    while ap > a0 + tol:
        ap -= 2 * math.pi
    return a1 - tol <= ap <= a0 + tol


# ---------------------------------------------------------------------------
# comp side, derived rather than told
# ---------------------------------------------------------------------------

def infer_comp_side(profile, stock, tol=1e-9):
    """
    Which side the tool rides, derived from where the material actually is.

    Material sits between the stock and the finished profile. Stock reaching
    beyond the profile's largest radius means OD material; a stock bore inside
    the profile's smallest radius means ID material. Whichever is greater wins.

    Deliberately NOT a comparison of the two gaps: on solid bar both minima are
    zero, so the ID measure is always zero and an undersized stock would flip
    the answer to ID, which is nonsense. ID only applies when the stock really
    has a bore inside the part.
    """
    p_lo, p_hi = profile.r_range()
    s_lo, s_hi = stock.r_range()
    od_material = s_hi - p_hi        # stock outside the part
    id_material = p_lo - s_lo        # stock bore inside the part
    if id_material > tol and id_material > od_material:
        return COMP_LEFT
    return COMP_RIGHT


def comp_side_ambiguous(profile, stock, tol=1e-6):
    """
    True when the geometry cannot decide the side on its own.

    That happens with a PARTIAL selection on hollow stock: pick just the bore
    wall out of a tube and there is material both outside and inside the
    chosen profile, so boring and OD turning are equally consistent with the
    geometry. The operator has to say which. A profile spanning the whole part
    is unambiguous.
    """
    p_lo, p_hi = profile.r_range()
    s_lo, s_hi = stock.r_range()
    return (s_hi - p_hi) > tol and (p_lo - s_lo) > tol


# ---------------------------------------------------------------------------
# pass generation
# ---------------------------------------------------------------------------

def rough(profile, stock, doc=0.05, stock_to_leave_r=0.01,
          stock_to_leave_z=0.005, clearance=0.1, retract=0.05,
          min_cut=None, comp_side=None):
    """
    Axial roughing passes from the stock down to the profile.

    Returns (moves, notes). Moves alternate rapid and feed, ready for the post.
    """
    notes = []
    if doc <= 0:
        return [], ["depth of cut must be positive"]

    z0, z1 = profile.z_range()          # z0 = deepest (most negative)
    p_lo, p_hi = profile.r_range()
    s_lo, s_hi = stock.r_range()

    if comp_side is None:
        comp_side = infer_comp_side(profile, stock)
        if comp_side_ambiguous(profile, stock):
            notes.append(
                f"side inferred as {comp_side} but the geometry is ambiguous - "
                f"material lies both outside and inside this profile. Pass "
                f"comp_side explicitly if you meant the other one.")
    outside = comp_side == COMP_RIGHT
    if outside:
        # OD: work from the stock outside diameter DOWN to the smallest radius
        # the profile reaches. Stopping at the profile's largest radius would
        # leave everything inboard of it uncut.
        start_level, end_level = s_hi, p_lo + stock_to_leave_r
        step = -doc
        retract_dir = +1.0
    else:
        # ID: work from the bore outwards
        start_level, end_level = s_lo, p_hi - stock_to_leave_r
        step = +doc
        retract_dir = -1.0

    if (outside and start_level <= end_level) or \
       (not outside and start_level >= end_level):
        return [], ["stock leaves nothing to rough against this profile"]

    # Machining check, not a geometry error: if the stock does not enclose the
    # finished profile, those features cannot clean up.
    if outside and s_hi < p_hi - 1e-9:
        notes.append(f"WARNING stock r{s_hi:.4f} is smaller than the profile "
                     f"r{p_hi:.4f} - the part will not clean up")
    if not outside and s_lo > p_lo + 1e-9:
        notes.append(f"WARNING bore stock r{s_lo:.4f} is larger than the "
                     f"profile r{p_lo:.4f} - the bore will not clean up")

    # Approach must clear the STOCK, not the part. The stock face sits proud
    # of the finished face, so clearing only the part would put the radial
    # rapids between passes inside uncut material.
    z_start = max(stock.z_range()[1], z1) + clearance
    moves = []
    level = start_level
    n = 0
    short = 0
    facing = 0
    while True:
        level += step
        if (outside and level <= end_level) or \
           (not outside and level >= end_level):
            level = end_level
            done = True
        else:
            done = False

        # walk in from the start until the profile (plus allowance) blocks us
        # Exact stop: the profile crossing nearest the face, at the radius
        # this pass is cutting once the finish allowance is taken off.
        cut_r = level - stock_to_leave_r if outside else level + stock_to_leave_r
        xs = [z for z in profile_z_crossings(profile, cut_r) if z <= z1 + 1e-9]
        z_stop = max(xs) + stock_to_leave_z if xs else z0
        if z_stop > z1:
            z_stop = z1

        cut_len = abs(z_start - z_stop)
        if min_cut is not None and cut_len < min_cut:
            short += 1
            n += 1
            if done or n > 500:
                break
            continue

        moves.append(Move("rapid", z_start, level))
        moves.append(Move("feed", z_stop, level))
        moves.append(Move("feed", z_stop, level + retract * retract_dir))
        moves.append(Move("rapid", z_start, level + retract * retract_dir))
        if abs(z_stop - z1) < 1e-6:
            facing += 1
        n += 1
        if done or n > 500:
            break

    notes.insert(0, f"{n} roughing pass(es) from r{start_level:.4f} to "
                    f"r{end_level:.4f} at {doc} doc, "
                    f"{'OD' if outside else 'ID'}")
    if facing:
        notes.append(f"{facing} pass(es) stop at the face - that is facing "
                     f"stock being taken axially; a facing cycle would be "
                     f"the right tool for it")
    if short:
        notes.append(f"{short} pass(es) skipped as shorter than min_cut")
    return moves, notes
