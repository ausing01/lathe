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


def _signed_area(contour):
    pts = [(e.start.z, e.start.r) for e in contour.elements]
    pts.append((contour.elements[-1].end.z, contour.elements[-1].end.r))
    a = 0.0
    for i in range(len(pts) - 1):
        z0, r0 = pts[i]; z1, r1 = pts[i + 1]
        a += z0 * r1 - z1 * r0
    return a / 2.0


def _air_normal(p0, p1, contour_ccw, side):
    n_left = G.left_normal(G.sub(p1, p0))
    n_right = (-n_left[0], -n_left[1])
    air = n_right if contour_ccw else n_left
    if side == Side.ID:
        air = (-air[0], -air[1])
    return air


def _arc_is_concave(arc, contour_ccw, side):
    ccw_arc = (arc.direction == ArcDir.CCW)
    concave = (ccw_arc == contour_ccw)
    if side == Side.ID:
        concave = not concave
    return concave


def _offset_element(e, nose, contour_ccw, side):
    if e.kind == "line":
        n = _air_normal((e.start.z, e.start.r), (e.end.z, e.end.r),
                        contour_ccw, side)
        shift = G.scale(n, nose)
        return {'kind': 'line',
                'p0': G.add((e.start.z, e.start.r), shift),
                'p1': G.add((e.end.z, e.end.r), shift)}
    else:
        concave = _arc_is_concave(e, contour_ccw, side)
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


def compensate(contour, nose_radius, tip):
    if tip not in TIP_OFFSET:
        raise ValueError(f"unknown tip code {tip}")
    problems = []
    nose = nose_radius
    ccw = _signed_area(contour) > 0

    raw = [_offset_element(e, nose, ccw, contour.side)
           for e in contour.elements]

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

    corners = [offs[0]['p0']]
    for i in range(len(offs) - 1):
        p = _reintersect(offs[i], offs[i + 1])
        if p is None:
            problems.append(
                f"could not re-intersect near "
                f"z={offs[i]['p1'][0]:.4f} r={offs[i]['p1'][1]:.4f}")
            p = offs[i]['p1']
        corners.append(p)
    corners.append(offs[-1]['p1'])

    tv = TIP_OFFSET[tip]
    tip_shift = (nose * tv[0], nose * tv[1])
    def to_tip(pt):
        return Point(z=pt[0] + tip_shift[0], r=pt[1] + tip_shift[1])

    new = []
    for i, o in enumerate(offs):
        c0, c1 = corners[i], corners[i + 1]
        if o['kind'] == 'line':
            new.append(Line(to_tip(c0), to_tip(c1)))
        else:
            new.append(Arc(to_tip(c0), to_tip(c1), to_tip(o['center']),
                           ArcDir.CCW if o['ccw'] else ArcDir.CW))
    return (Contour(elements=new, side=contour.side,
                    name=contour.name + "_comp"), problems)
