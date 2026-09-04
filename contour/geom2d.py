"""
geom2d - 2D geometry primitives in the (z, r) plane.

This is the shared solver that underpins three features:
  - nose-radius compensation (offset each element, re-intersect neighbours)
  - the contour calculator (solve chained geometry with tangency/intersection)
  - the roughing generator (trim passes against the finish profile)

Everything here is pure math with no lathe knowledge. Coordinates are (z, r)
tuples. Angles in radians. The module is written to be read and checked by
hand, and every primitive has a self-test at the bottom.

Conventions:
  - A "line" is (p0, p1): two endpoints.
  - An "arc" is (center, radius, a0, a1, ccw): center, radius, start angle,
    end angle, and a ccw flag giving sweep direction.
  - Offsetting: positive distance offsets to the LEFT of travel direction
    (p0 -> p1). Callers decide the sign based on material side.
"""

import math

TOL = 1e-9


# ---------------------------------------------------------------------------
# vector helpers  (a point is just a (z, r) tuple)
# ---------------------------------------------------------------------------

def sub(a, b):   return (a[0] - b[0], a[1] - b[1])
def add(a, b):   return (a[0] + b[0], a[1] + b[1])
def scale(a, s): return (a[0] * s, a[1] * s)
def dot(a, b):   return a[0] * b[0] + a[1] * b[1]
def length(a):   return math.hypot(a[0], a[1])
def dist(a, b):  return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a):
    L = length(a)
    if L < TOL:
        raise ValueError("zero-length vector has no direction")
    return (a[0] / L, a[1] / L)


def left_normal(direction):
    """Unit normal 90deg to the LEFT of a travel direction vector."""
    d = unit(direction)
    return (-d[1], d[0])          # rotate +90deg


# ---------------------------------------------------------------------------
# line offset
# ---------------------------------------------------------------------------

def offset_line(p0, p1, distance):
    """
    Offset a line segment by `distance` to the LEFT of p0->p1.
    Returns the offset (q0, q1). The offset is a parallel line; endpoints
    move perpendicular to the line direction (they'll be re-intersected with
    neighbours later, so their exact along-line position doesn't matter yet).
    """
    n = left_normal(sub(p1, p0))
    shift = scale(n, distance)
    return (add(p0, shift), add(p1, shift))


# ---------------------------------------------------------------------------
# arc offset
# ---------------------------------------------------------------------------

def offset_arc_radius(radius, distance, concave):
    """
    Offset an arc's radius. For a tool rolling on the profile:
      concave arc  -> radius grows by the nose radius   (R + d)
      convex arc   -> radius shrinks by the nose radius (R - d)
    `distance` is the nose radius (positive).

    Returns the new radius, or None if a convex arc is smaller than the offset
    (the tool cannot fit this feature - the element "vanishes" from the tool
    path and the caller must bridge across it by intersecting its neighbours).
    """
    if concave:
        return radius + distance
    new_r = radius - distance
    if new_r < TOL:
        return None            # element vanishes; caller bridges across it
    return new_r


# ---------------------------------------------------------------------------
# intersections
# ---------------------------------------------------------------------------

def intersect_line_line(a0, a1, b0, b1):
    """
    Intersect two infinite lines through (a0,a1) and (b0,b1).
    Returns the intersection point, or None if parallel.
    """
    d1 = sub(a1, a0)
    d2 = sub(b1, b0)
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < TOL:
        return None                      # parallel or coincident
    diff = sub(b0, a0)
    t = (diff[0] * d2[1] - diff[1] * d2[0]) / denom
    return add(a0, scale(d1, t))


def intersect_line_circle(p0, p1, center, radius):
    """
    Intersect an infinite line through (p0,p1) with a circle.
    Returns a list of 0, 1, or 2 points.
    """
    d = sub(p1, p0)
    f = sub(p0, center)
    a = dot(d, d)
    b = 2 * dot(f, d)
    c = dot(f, f) - radius * radius
    disc = b * b - 4 * a * c
    if disc < -TOL:
        return []
    if disc < TOL:
        t = -b / (2 * a)
        return [add(p0, scale(d, t))]
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2 * a)
    t2 = (-b + sq) / (2 * a)
    return [add(p0, scale(d, t1)), add(p0, scale(d, t2))]


def intersect_circle_circle(c0, r0, c1, r1):
    """
    Intersect two circles. Returns a list of 0, 1, or 2 points.
    """
    d = dist(c0, c1)
    if d < TOL:
        return []                        # concentric
    if d > r0 + r1 + TOL:
        return []                        # too far apart
    if d < abs(r0 - r1) - TOL:
        return []                        # one inside the other
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h2 = r0 * r0 - a * a
    h = math.sqrt(h2) if h2 > 0 else 0.0
    base = add(c0, scale(sub(c1, c0), a / d))
    if h < TOL:
        return [base]
    n = scale((-(c1[1] - c0[1]), c1[0] - c0[0]), h / d)
    return [add(base, n), sub(base, n)]


def choose_nearest(candidates, reference):
    """Pick the candidate point closest to a reference point (root selection)."""
    if not candidates:
        return None
    return min(candidates, key=lambda p: dist(p, reference))


# ---------------------------------------------------------------------------
# self-tests: run `python3 geom2d.py`
# ---------------------------------------------------------------------------

def _approx(a, b, tol=1e-6):
    if isinstance(a, tuple):
        return all(abs(x - y) < tol for x, y in zip(a, b))
    return abs(a - b) < tol


def _selftest():
    ok = 0
    fail = 0
    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL: {name}")

    # left normal of +z axis is +r
    check("left_normal(+z)=+r", _approx(left_normal((1, 0)), (0, 1)))

    # offset a horizontal line (z axis at r=1) upward by 0.5 -> r=1.5
    q0, q1 = offset_line((0, 1), (2, 1), 0.5)
    check("offset_line up", _approx(q0, (0, 1.5)) and _approx(q1, (2, 1.5)))

    # arc offset: concave grows, convex shrinks - the numbers from the real parts
    NOSE = 0.03125
    # part 2 concave R0.010 -> 0.0412
    check("concave R0.010 -> 0.04125",
          _approx(offset_arc_radius(0.010, NOSE, concave=True), 0.04125))
    # part 1 concave R0.10 -> 0.13125 (ref shows 0.1312)
    check("concave R0.10 -> 0.13125",
          _approx(offset_arc_radius(0.10, NOSE, concave=True), 0.13125))
    # part 1 convex R0.15 -> 0.11875 (ref shows 0.1188)
    check("convex R0.15 -> 0.11875",
          _approx(offset_arc_radius(0.15, NOSE, concave=False), 0.11875))

    # convex arc smaller than nose radius should signal a vanished element
    check("convex-too-small -> None",
          offset_arc_radius(0.02, NOSE, concave=False) is None)

    # line/line intersection
    p = intersect_line_line((0, 0), (1, 0), (0, 1), (1, 1))
    check("parallel lines -> None", p is None)
    p = intersect_line_line((0, 0), (1, 0), (1, -1), (1, 1))
    check("line/line cross at (1,0)", _approx(p, (1, 0)))

    # line/circle: horizontal line r=0 through unit circle at origin -> (±1,0)
    pts = intersect_line_circle((-2, 0), (2, 0), (0, 0), 1.0)
    check("line/circle 2 pts", len(pts) == 2)
    xs = sorted(p[0] for p in pts)
    check("line/circle at ±1", _approx(xs[0], -1) and _approx(xs[1], 1))

    # circle/circle: unit circles at (0,0) and (1,0) meet at (0.5, ±sqrt(3)/2)
    pts = intersect_circle_circle((0, 0), 1.0, (1, 0), 1.0)
    check("circle/circle 2 pts", len(pts) == 2)
    check("circle/circle x=0.5", all(_approx(p[0], 0.5) for p in pts))

    # root selection picks nearest
    near = choose_nearest(pts, (0.5, 1.0))
    check("choose_nearest upper", near[1] > 0)

    print(f"geom2d self-test: {ok} passed, {fail} failed")
    return fail == 0


if __name__ == "__main__":
    _selftest()
