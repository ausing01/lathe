"""
comp.py - tool nose radius compensation, general form.

Takes a part-profile Contour + nose radius + tool origin position (the
SolidCAM-style code 1-8, matching the origin diagram), returns the driven-tip
toolpath with comp baked in (G40 at the machine).

Model (standard imaginary-tool-tip compensation):
  1. Offset each element by the nose radius to the AIR side (away from material)
     = path of the NOSE CENTER. Air side from profile winding + OD/ID.
  2. Re-intersect consecutive offset elements for true corners; bridge vanished
     convex features (tighter than the nose).
  3. Shift nose-CENTER -> driven TIP:  tip = center + nose * TIP_OFFSET[code].
     The imaginary tip is where the two tool tangent lines meet: an offset of
     nose in EACH axis (per-axis corner), not radially.

Coordinates: (z, r), z+ toward tailstock, r = radius.
"""

import math
from .model import Contour, Line, Arc, Point, ArcDir, Side
from . import geom2d as G

# origin-position table (SolidCAM origin diagram; Z right, radial up)
#   2   6   1     imaginary tip = corner where tool tangent lines meet
#   7  0,9  5     (nose offset in each axis). 0/9 = center (control comps).
#   3   8   4
TIP_OFFSET = {
    1: (+1, +1), 2: (-1, +1), 3: (-1, -1), 4: (+1, -1),
    5: (+1,  0), 7: (-1,  0),
    6: ( 0, +1), 8: ( 0, -1),
    0: ( 0,  0), 9: ( 0,  0),
}


COMP_LEFT = "left"       # G41 - tool to the LEFT of travel   (bore)
COMP_RIGHT = "right"     # G42 - tool to the RIGHT of travel  (turning)
COMP_CENTER = "center"   # G40 - no offset, follow the line exactly


def _signed_area(contour):
    pts = [(e.start.z, e.start.r) for e in contour.elements]
    pts.append((contour.elements[-1].end.z, contour.elements[-1].end.r))
    a = 0.0
    for i in range(len(pts) - 1):
        z0, r0 = pts[i]; z1, r1 = pts[i + 1]
        a += z0 * r1 - z1 * r0
    return a / 2.0


def _tool_normal(p0, p1, comp_side):
    """
    Unit normal pointing to the TOOL side of a segment p0->p1.

    This is the G41/G42 convention, relative to direction of travel:

      left   tool to the LEFT of travel   (G41) - a bore, tool inside
      right  tool to the RIGHT of travel  (G42) - turning, tool outside

    On a line running Z0 to Z-1 at X1, left puts the tool at smaller radius
    (inside the hole) and right at larger radius (outside the diameter), which
    is what those words mean at the machine.

    Travel-relative means reversing the chain swaps which physical side is cut,
    exactly as swapping G41 and G42 would. That is deliberate.

    Replaces the old winding-based inference, which could not tell a front face
    from a back face and was wrong on some profiles.
    """
    n_left = G.left_normal(G.sub(p1, p0))
    if comp_side == COMP_RIGHT:
        return (-n_left[0], -n_left[1])
    return n_left


def _arc_mid_tangent(e):
    """Midpoint of the arc and the unit tangent there, pointing along travel."""
    a0 = math.atan2(e.start.r - e.center.r, e.start.z - e.center.z)
    a1 = math.atan2(e.end.r - e.center.r, e.end.z - e.center.z)
    if e.direction == ArcDir.CCW:
        if a1 <= a0:
            a1 += 2 * math.pi
        am = (a0 + a1) / 2
        tang = (-math.sin(am), math.cos(am))
    else:
        if a1 >= a0:
            a1 -= 2 * math.pi
        am = (a0 + a1) / 2
        tang = (math.sin(am), -math.cos(am))
    R = e.radius
    mid = (e.center.z + R * math.cos(am), e.center.r + R * math.sin(am))
    return mid, tang


def _arc_is_concave(arc, comp_side):
    """
    Concave (offset radius GROWS) vs convex (SHRINKS), decided locally.

    Uses the arc's TRUE TANGENT at its midpoint - not the chord. A chord-based
    normal inverts on the middle arc of an S-curve (part 2's R0.025 between two
    R0.010 notches), which is what broke this before.

    Air side is the same rule as for lines: right of travel when the contour
    walks CCW, left when CW, flipped for ID. If the air normal points along the
    outward bulge (centre -> midpoint), the tool rides outside the arc and the
    swept radius shrinks (convex). If it points inward, the radius grows
    (concave).

    Validated: part1 R0.15 convex -> 0.1188, R0.10 concave -> 0.1312;
               part2 R0.010 concave -> 0.0412 (x2), R0.025 convex (vanishes).
    """
    mid, tang = _arc_mid_tangent(arc)
    n_left = G.left_normal(tang)
    air = (-n_left[0], -n_left[1]) if comp_side == COMP_RIGHT else n_left
    bulge = G.unit(G.sub(mid, (arc.center.z, arc.center.r)))
    # The tool centre offsets along `air` (the tool-side normal). If that points
    # the same way as the outward bulge, the centre rides outside the arc and
    # the swept radius GROWS - that is the concave case (R + nose). Pointing
    # inward shrinks it (R - nose), the convex case.
    return G.dot(air, bulge) > 0


def _offset_element(e, nose, comp_side):
    if e.kind == "line":
        n = _tool_normal((e.start.z, e.start.r), (e.end.z, e.end.r), comp_side)
        shift = G.scale(n, nose)
        return {'kind': 'line',
                'p0': G.add((e.start.z, e.start.r), shift),
                'p1': G.add((e.end.z, e.end.r), shift)}
    else:
        concave = _arc_is_concave(e, comp_side)
        new_r = G.offset_arc_radius(e.radius, nose, concave)
        if new_r is None:
            return {'kind': 'vanished', 'orig': e}
        c = (e.center.z, e.center.r)
        def move(pt):
            u = G.unit(G.sub((pt.z, pt.r), c))
            return G.add(c, G.scale(u, new_r))
        return {'kind': 'arc', 'center': c, 'radius': new_r,
                'ccw': e.direction == ArcDir.CCW,
                'p0': move(e.start), 'p1': move(e.end)}


def _reintersect(a, b):
    joint = a['p1']
    if a['kind'] == 'line' and b['kind'] == 'line':
        return G.intersect_line_line(a['p0'], a['p1'], b['p0'], b['p1'])
    if a['kind'] == 'line' and b['kind'] == 'arc':
        pts = G.intersect_line_circle(a['p0'], a['p1'], b['center'], b['radius'])
        return G.choose_nearest(pts, joint)
    if a['kind'] == 'arc' and b['kind'] == 'line':
        pts = G.intersect_line_circle(b['p0'], b['p1'], a['center'], a['radius'])
        return G.choose_nearest(pts, joint)
    if a['kind'] == 'arc' and b['kind'] == 'arc':
        pts = G.intersect_circle_circle(a['center'], a['radius'],
                                        b['center'], b['radius'])
        return G.choose_nearest(pts, joint)
    return None


def compensate(contour, nose_radius, tip, comp_side=COMP_RIGHT):
    """
    Offset a contour by the tool nose radius onto the driven tip.

    comp_side is the G41/G42 convention, relative to direction of travel:
      "left"    tool left of travel  (G41) - boring
      "right"   tool right of travel (G42) - turning
      "center"  no offset (G40) - follow the geometry exactly

    Reversing the chain swaps which physical side is cut, exactly as swapping
    G41 and G42 would. The offset is baked into the coordinates; the machine
    stays in G40.
    """
    if tip not in TIP_OFFSET:
        raise ValueError(f"unknown tip code {tip}")
    if comp_side not in (COMP_LEFT, COMP_RIGHT, COMP_CENTER):
        raise ValueError(f"comp_side must be left, right or center, "
                         f"got {comp_side!r}")
    problems = []
    nose = nose_radius

    if comp_side == COMP_CENTER:
        out = Contour(elements=list(contour.elements), side=contour.side,
                      closed=contour.closed, name=contour.name + "_comp")
        return out, problems

    raw = [_offset_element(e, nose, comp_side) for e in contour.elements]

    offs = []
    for i, o in enumerate(raw):
        if o['kind'] == 'vanished':
            problems.append(
                f"element {i} (convex R{o['orig'].radius:.4f}) tighter than nose "
                f"{nose:.4f}; tool rolls through - CHECK INTERFERENCE")
        else:
            offs.append(o)

    if not offs:
        return (Contour(elements=[], side=contour.side,
                        name=contour.name + "_comp"),
                problems + ["nothing left after compensation"])

    # Per-element start/end. A shared corner list cannot express a convex-corner
    # GAP (where element i ends at one point and i+1 starts at another), so keep
    # each element's own endpoints.
    starts = [o['p0'] for o in offs]
    ends = [o['p1'] for o in offs]

    for i in range(len(offs) - 1):
        p = _reintersect(offs[i], offs[i + 1])
        if p is not None:
            # concave / crossing corner: both elements meet at the intersection
            ends[i] = p
            starts[i + 1] = p
        else:
            # CONVEX corner: offset elements have separated. The tool rolls
            # around the corner; each element keeps its own offset endpoint and
            # the post emits a direct move between them. Do not force a shared
            # point - that corrupts the arc geometry.
            # A convex corner separates the offsets by up to ~2x nose radius as
            # a matter of geometry; only warn beyond that.
            gap = G.dist(offs[i]['p1'], offs[i + 1]['p0'])
            if gap > nose * 2.5:
                problems.append(
                    f"offset elements {i}/{i+1} separated by {gap:.4f} "
                    f"- check corner")

    tv = TIP_OFFSET[tip]
    tip_shift = (nose * tv[0], nose * tv[1])
    def to_tip(pt):
        return Point(z=pt[0] + tip_shift[0], r=pt[1] + tip_shift[1])

    new = []
    for i, o in enumerate(offs):
        c0, c1 = starts[i], ends[i]
        if o['kind'] == 'line':
            new.append(Line(to_tip(c0), to_tip(c1)))
        else:
            new.append(Arc(to_tip(c0), to_tip(c1), to_tip(o['center']),
                           ArcDir.CCW if o['ccw'] else ArcDir.CW))
    return (Contour(elements=new, side=contour.side,
                    name=contour.name + "_comp"), problems)
