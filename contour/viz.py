"""
viz.py - render contours and stock to SVG. Zero dependencies.

Purpose is inspection, not pretty pictures: overlay a part profile, a stock
profile and a compensated toolpath in one view so geometry errors are visible
at a glance. A material-side error shows immediately as the toolpath sitting on
the wrong side of the profile.

Drawing convention matches the machine view: Z increases to the RIGHT, radius
increases UP, centreline drawn at r=0. Diameters are NOT doubled here - this is
a radius-space view, same as the Contour model.
"""

import math

# layer styles: (stroke, width, dash)
STYLES = {
    "stock":   ("#888888", 1.0, "4,3"),
    "profile": ("#1060c0", 1.8, None),
    "tool":    ("#c02020", 1.4, None),
    "open":    ("#20a020", 3.0, None),
    "axis":    ("#c0c0c0", 0.8, "6,4"),
}


def _arc_points(e, max_step_deg=3.0):
    """
    Sample points along an arc, start to end, in the sweep direction.

    Computed directly rather than emitted as an SVG "A" command. The SVG sweep
    flag is interpreted in user space, and this drawing applies a y-flip to put
    radius upward, which makes the flag easy to get backwards - arcs then bulge
    the wrong way. Sampling the points removes that class of bug entirely.
    """
    cz, cr = e.center.z, e.center.r
    R = e.radius
    a0 = math.atan2(e.start.r - cr, e.start.z - cz)
    a1 = math.atan2(e.end.r - cr, e.end.z - cz)
    if e.direction.value == "CCW":
        while a1 <= a0:
            a1 += 2 * math.pi
    else:
        while a1 >= a0:
            a1 -= 2 * math.pi
    sweep = a1 - a0
    n = max(2, int(abs(math.degrees(sweep)) / max_step_deg) + 1)
    pts = []
    for k in range(n + 1):
        a = a0 + sweep * (k / n)
        pts.append((cz + R * math.cos(a), cr + R * math.sin(a)))
    return pts


def _element_points(e):
    """Polyline points for any element, start to end."""
    if e.kind == "line":
        return [(e.start.z, e.start.r), (e.end.z, e.end.r)]
    return _arc_points(e)


def _contour_path(contour):
    if not contour.elements:
        return ""
    d = []
    for i, e in enumerate(contour.elements):
        pts = _element_points(e)
        if i == 0:
            d.append(f"M {pts[0][0]:.5f} {pts[0][1]:.5f}")
        for p in pts[1:]:
            d.append(f"L {p[0]:.5f} {p[1]:.5f}")
    return " ".join(d)


def _element_path(e):
    """Standalone path data for a single element (used by pickable render)."""
    pts = _element_points(e)
    d = [f"M {pts[0][0]:.5f} {pts[0][1]:.5f}"]
    for p in pts[1:]:
        d.append(f"L {p[0]:.5f} {p[1]:.5f}")
    return " ".join(d)


def _bounds(layers, pad_frac=0.08):
    zs, rs = [], []
    for _, c, _ in layers:
        for e in c.elements:
            for p in (e.start, e.end):
                zs.append(p.z)
                rs.append(p.r)
    if not zs:
        return (-1, 1, -1, 1)
    z0, z1, r0, r1 = min(zs), max(zs), min(rs), max(rs)
    r0 = min(r0, 0.0)
    dz, dr = max(z1 - z0, 1e-6), max(r1 - r0, 1e-6)
    pad = max(dz, dr) * pad_frac
    return z0 - pad, z1 + pad, r0 - pad, r1 + pad


def render(layers, width=900, title=None, stock=None):
    """
    layers: list of (style_name, Contour, label)
    stock:  optional Stock, whose open edges are highlighted
    Returns an SVG string.
    """
    if stock is not None:
        layers = [("stock", stock.contour, "stock")] + list(layers)

    z0, z1, r0, r1 = _bounds(layers)
    dz, dr = z1 - z0, r1 - r0
    height = max(140, int(width * dr / dz))
    scale = width / dz

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fdfdfd"/>',
        # transform: z -> x, r -> flipped y
        f'<g transform="translate({-z0*scale:.3f},{r1*scale:.3f}) '
        f'scale({scale:.5f},{-scale:.5f})">',
    ]

    # centreline
    s, w, dash = STYLES["axis"]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(f'<line x1="{z0:.4f}" y1="0" x2="{z1:.4f}" y2="0" '
                 f'stroke="{s}" stroke-width="{w/scale:.5f}"{da}/>')

    for style, c, _label in layers:
        s, w, dash = STYLES.get(style, STYLES["profile"])
        da = f' stroke-dasharray="{dash}"' if dash else ""
        d = _contour_path(c)
        if d:
            parts.append(f'<path d="{d}" fill="none" stroke="{s}" '
                         f'stroke-width="{w/scale:.5f}" stroke-linecap="round" '
                         f'stroke-linejoin="round"{da}/>')

    # highlight stock open edges
    if stock is not None:
        s, w, _ = STYLES["open"]
        for i, e in enumerate(stock.contour.elements):
            if not stock.is_open(i):
                continue
            if e.kind == "line":
                parts.append(
                    f'<line x1="{e.start.z:.5f}" y1="{e.start.r:.5f}" '
                    f'x2="{e.end.z:.5f}" y2="{e.end.r:.5f}" stroke="{s}" '
                    f'stroke-width="{w/scale:.5f}" stroke-linecap="round"/>')

    parts.append("</g>")

    # legend / title in screen space
    y = 16
    if title:
        parts.append(f'<text x="10" y="{y}" font-family="monospace" '
                     f'font-size="13" fill="#222">{title}</text>')
        y += 16
    for style, _c, label in layers:
        col = STYLES.get(style, STYLES["profile"])[0]
        parts.append(f'<text x="10" y="{y}" font-family="monospace" '
                     f'font-size="11" fill="{col}">{label}</text>')
        y += 13
    if stock is not None:
        parts.append(f'<text x="10" y="{y}" font-family="monospace" '
                     f'font-size="11" fill="{STYLES["open"][0]}">'
                     f'open edges (tool may enter)</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def write(path, layers, **kw):
    open(path, "w").write(render(layers, **kw))
    return path


# ---------------------------------------------------------------------------
# pickable rendering - one path per element, clickable in the browser
# ---------------------------------------------------------------------------

def render_pickable(contour, selected=(), extended=None, stock=None,
                    width=900, title=None, height_cap=520,
                    start_dot=None, end_dot=None,
                    focus=None, focus_element=None,
                    start_tri=None, end_tri=None, walk=None):
    """
    Draw a contour with each element as its own <path data-idx="i">, so the page
    can attach click handlers and toggle selection.

    selected   iterable of element indices drawn as selected
    extended   optional Contour (the extended profile) drawn underneath
    stock      optional Stock, drawn dashed with open edges highlighted
    start_dot  (z, r) marked GREEN - the end of the chain's START element,
               showing which way the chain heads
    end_dot    (z, r) marked RED - the end of the chain's END element
    focus      index into `contour` to highlight (the element picked in the list)
    focus_element  a synthetic element (blend, bridge, extension) to highlight,
               since those are not in `contour` and have no index
    start_tri  (z, r, dz, dr) GREEN triangle at the very start of the cut,
               i.e. the outermost start extension. Points along travel.
    end_tri    (z, r, dz, dr) RED triangle at the very end of the cut.
               Only the outermost extension at each end is marked.
    """
    sel = set(selected)
    layers = []
    if stock is not None:
        layers.append(("stock", stock.contour, "stock"))
    if extended is not None:
        layers.append(("tool", extended, "extended"))
    layers.append(("profile", contour, "profile"))

    z0, z1, r0, r1 = _bounds(layers)
    dz, dr = z1 - z0, r1 - r0
    scale = width / dz
    height = max(140, min(height_cap, int(width * dr / dz)))
    if width * dr / dz > height_cap:          # refit so nothing is clipped
        scale = height_cap / dr
        width = max(320, int(dz * scale))
        height = height_cap

    P = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
         f'height="{height}" viewBox="0 0 {width} {height}" id="pickfig">',
         '<rect width="100%" height="100%" fill="#fdfdfd"/>',
         f'<g id="modelspace" transform="translate({-z0*scale:.3f},'
         f'{r1*scale:.3f}) scale({scale:.5f},{-scale:.5f})">']

    def sw(px):
        return px / scale

    # centreline
    s, w, dash = STYLES["axis"]
    P.append(f'<line x1="{z0:.4f}" y1="0" x2="{z1:.4f}" y2="0" stroke="{s}" '
             f'stroke-width="{sw(w):.5f}" stroke-dasharray="{dash}"/>')

    # stock, with a hit target per element so it can be clicked
    if stock is not None:
        s, w, dash = STYLES["stock"]
        d = _contour_path(stock.contour)
        if d:
            P.append(f'<path d="{d}" fill="none" stroke="{s}" '
                     f'stroke-width="{sw(w):.5f}" stroke-dasharray="{dash}"/>')
        for i, e in enumerate(stock.contour.elements):
            P.append(f'<path d="{_element_path(e)}" fill="none" '
                     f'stroke="transparent" stroke-width="{sw(14):.5f}" '
                     f'stroke-linecap="round" class="shit" data-sidx="{i}" '
                     f'style="cursor:crosshair"/>')

    # extended profile (drawn under the pickable elements)
    if extended is not None:
        s, w, _ = STYLES["tool"]
        d = _contour_path(extended)
        if d:
            P.append(f'<path d="{d}" fill="none" stroke="{s}" '
                     f'stroke-width="{sw(w):.5f}" stroke-linecap="round" '
                     f'stroke-linejoin="round" opacity="0.55"/>')

    # the chosen stock boundary walk
    if walk:
        for e in walk:
            P.append(f'<path d="{_element_path(e)}" fill="none" '
                     f'stroke="#1d9b1d" stroke-width="{sw(3.4):.5f}" '
                     f'stroke-linecap="round" style="pointer-events:none"/>')

    # focus halo, drawn under everything so the element still reads normally
    halo = None
    if focus is not None and 0 <= focus < len(contour.elements):
        halo = _element_path(contour.elements[focus])
    elif focus_element is not None:
        halo = _element_path(focus_element)
    if halo:
        P.append(f'<path d="{halo}" fill="none" stroke="#ffb020" '
                 f'stroke-width="{sw(11):.5f}" stroke-linecap="round" '
                 f'stroke-linejoin="round" opacity="0.85" '
                 f'style="pointer-events:none"/>')

    # pickable elements: a fat invisible hit path, then the visible one
    for i, e in enumerate(contour.elements):
        d = _element_path(e)
        on = i in sel
        col = "#c02020" if on else "#1060c0"
        wpx = 3.2 if on else 1.6
        P.append(f'<path d="{d}" fill="none" stroke="transparent" '
                 f'stroke-width="{sw(14):.5f}" stroke-linecap="round" '
                 f'class="hit" data-idx="{i}" style="cursor:pointer"/>')
        P.append(f'<path d="{d}" fill="none" stroke="{col}" '
                 f'stroke-width="{sw(wpx):.5f}" stroke-linecap="round" '
                 f'stroke-linejoin="round" data-vis="{i}" '
                 f'style="pointer-events:none"/>')

    # triangles at the extreme ends of the CUT (outermost extensions), pointing
    # along travel. Only the first and last element of the whole chain gets one.
    for tri, col in ((start_tri, "#12a012"), (end_tri, "#d01818")):
        if tri is None:
            continue
        pz, pr, dz, dr = tri
        L = math.hypot(dz, dr)
        if L < 1e-12:
            continue
        ux, uy = dz / L, dr / L
        nx, ny = -uy, ux
        sz = sw(9)
        tip = (pz + ux * sz, pr + uy * sz)
        b1 = (pz - ux * sz * 0.35 + nx * sz * 0.62,
              pr - uy * sz * 0.35 + ny * sz * 0.62)
        b2 = (pz - ux * sz * 0.35 - nx * sz * 0.62,
              pr - uy * sz * 0.35 - ny * sz * 0.62)
        pts = f"{tip[0]:.5f},{tip[1]:.5f} {b1[0]:.5f},{b1[1]:.5f} " \
              f"{b2[0]:.5f},{b2[1]:.5f}"
        P.append(f'<polygon points="{pts}" fill="{col}" stroke="#ffffff" '
                 f'stroke-width="{sw(1.2):.5f}" style="pointer-events:none"/>')

    # direction markers: green where the chain sets off, red where it finishes
    for pt, col in ((start_dot, "#12a012"), (end_dot, "#d01818")):
        if pt is None:
            continue
        P.append(f'<circle cx="{pt[0]:.5f}" cy="{pt[1]:.5f}" '
                 f'r="{sw(5.5):.5f}" fill="{col}" stroke="#ffffff" '
                 f'stroke-width="{sw(1.4):.5f}" style="pointer-events:none"/>')

    P.append("</g>")
    y = 16
    if title:
        P.append(f'<text x="10" y="{y}" font-family="monospace" font-size="13" '
                 f'fill="#222">{title}</text>')
        y += 15
    P.append(f'<text x="10" y="{y}" font-family="monospace" font-size="11" '
             f'fill="#1060c0">unselected</text>')
    P.append(f'<text x="92" y="{y}" font-family="monospace" font-size="11" '
             f'fill="#c02020">selected / extended</text>')
    if start_dot is not None or end_dot is not None:
        y += 13
        P.append(f'<text x="10" y="{y}" font-family="monospace" font-size="11" '
                 f'fill="#12a012">\u25cf profile start</text>')
        P.append(f'<text x="120" y="{y}" font-family="monospace" font-size="11" '
                 f'fill="#d01818">\u25cf profile end</text>')
    if start_tri is not None or end_tri is not None:
        y += 13
        P.append(f'<text x="10" y="{y}" font-family="monospace" font-size="11" '
                 f'fill="#12a012">\u25b2 cut start</text>')
        P.append(f'<text x="120" y="{y}" font-family="monospace" font-size="11" '
                 f'fill="#d01818">\u25b2 cut end</text>')
    P.append("</svg>")
    return "\n".join(P)
