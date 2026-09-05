"""
session.py - the editing state, in Python rather than the browser.

Everything the operator has chosen lives here: which elements are in the chain,
which way it runs, what is unchecked, blend radii, extensions, the stock, and
the boundary walk clicks. The UI - the browser page today, a Qt window later -
is a thin view over this. It holds no state of its own beyond what the user is
typing at that moment.

That split is the point. The geometry modules were always UI-agnostic; moving
the editing state here means a port rewrites the view only, and everything
underneath stays testable without a display.

State is deliberately a plain description of choices, not derived geometry:
element indices, click points, parameter values. `view()` recomputes the
geometry from them each time, so undo, reload and replay all fall out for free.
"""

import math
from dataclasses import dataclass, field

from .model import Side, element_properties
from .dxf_import import import_dxf
from .select import (auto_chain, assemble, check_selection, is_bridge,
                     is_blend, blend_key, chain_indices)
from .stock import parametric, from_dxf
from .extend import (Extension, extend_profile, blend_extensions,
                     extension_junctions, is_extension)
from .comp import compensate, COMP_LEFT, COMP_RIGHT, COMP_CENTER
from .region import stock_click
from .viz import render_pickable


PARTS = {
    "part1":        ("tests/test_part_1.dxf", Side.OD, 3, 0.03125),
    "part2":        ("tests/test_part_2.dxf", Side.OD, 3, 0.03125),
    "bore":         ("tests/bore.dxf",        Side.ID, 6, 0.0886),
    "backface":     ("tests/backface.dxf",    Side.OD, 8, 0.0886),
    "stock_closed": ("tests/stock_closed.dxf", Side.OD, 3, 0.03125),
}


def load_profile(name):
    path, side, _tip, _nose = PARTS[name]
    return import_dxf(path, side=side, name=name)[0]


def _seg(spec):
    """Parse one 'dir|len|angle' segment string into an Extension, or None."""
    if not spec:
        return None
    parts = (spec.split("|") + ["", "", ""])[:3]
    d, ln, ang = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not d and not ang:
        return None
    return Extension(direction=d or "+Z",
                     length=float(ln) if ln else None,
                     angle=float(ang) if ang else None)


def _props(e, i):
    from contour.model import element_properties
    return element_properties(e, i)


def _fmt_ang(v):
    """Angle to three decimals, trailing zeros dropped."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _label_for(c, i):
    e = c.elements[i]
    pr = _props(e, i)
    return (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0" if e.kind == "line"
            else f"arc R{pr['radius']:.4f} {pr['direction']}")


def _rows_full(c, final, order, off, flip=False, sel=None):
    """
    Rows for the whole chain in true cut order, built from the assembled
    sequence rather than reconstructed, so blends, bridges and extensions land
    exactly where they are in the geometry.

    Unchecked elements are listed immediately AFTER the bridge that replaces
    them, so the bridge reads first and the skipped elements sit with it,
    keeping their checkbox so they can be put back.
    """
    def shape_of(e, pos=0):
        pr = _props(e, pos)
        return (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0"
                if e.kind == "line"
                else f"arc R{pr['radius']:.4f} {pr['direction']}")

    rows = []
    meta = getattr(sel, "meta", None)

    # Leading synthetic run: everything before the first real element. That is
    # the start extensions AND any blends between them, in order.
    reals = [n for n, e in enumerate(final.elements)
             if getattr(e, "origin", None) is None]
    first_real = reals[0] if reals else len(final.elements)
    last_real = reals[-1] if reals else -1
    for n in range(first_real):
        e = final.elements[n]
        o = getattr(e, "origin", None)
        if o == "blend":
            rows.append({"key": f"x{n}",
                         "label": f"blend \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "blend"})
        else:
            rows.append({"key": f"x{n}",
                         "label": f"start ext \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "ext"})

    if meta is None:
        # no assembly metadata (shouldn't happen) - fall back to plain order
        for i in order:
            rows.append({"key": str(i), "label": _label_for(c, i),
                         "check": i not in off, "cls": "real"})
        _annotate_junctions(rows)
        return rows

    # map assembled elements back to positions in `final` (extensions shift it)
    shift = sum(1 for e in final.elements
                if getattr(e, "origin", None) == "extension"
                and final.elements.index(e) < 1)
    base = 0
    for n, e in enumerate(final.elements):
        if getattr(e, "origin", None) != "extension":
            base = n
            break

    off_order = [i for i in order if i in off]
    used_off = set()

    for k, (kind, val) in enumerate(meta):
        pos = base + k
        e = final.elements[pos] if pos < len(final.elements) else None
        if kind == "real":
            rows.append({"key": str(val), "label": _label_for(c, val),
                         "check": True, "cls": "real"})
        elif kind == "blend":
            rows.append({"key": f"x{pos}",
                         "label": f"blend \u00b7 {shape_of(e, pos)}",
                         "check": None, "cls": "blend"})
        elif kind == "bridge":
            rows.append({"key": f"x{pos}",
                         "label": f"bridge \u00b7 {shape_of(e, pos)}",
                         "check": None, "cls": "bridge"})
            # the elements this bridge replaced, listed with it
            a_i, b_i = val
            span = []
            try:
                ia, ib = order.index(a_i), order.index(b_i)
                lo, hi = min(ia, ib), max(ia, ib)
                span = [order[t] for t in range(lo + 1, hi)]
            except ValueError:
                span = []
            for j in span:
                if j in off and j not in used_off:
                    used_off.add(j)
                    rows.append({"key": str(j), "label": _label_for(c, j),
                                 "check": False, "cls": "real"})

    # any unchecked elements not covered by a bridge (they sat at a chain end)
    for j in off_order:
        if j not in used_off:
            rows.append({"key": str(j), "label": _label_for(c, j),
                         "check": False, "cls": "real"})

    # Trailing synthetic run: everything after the last real element.
    for n in range(last_real + 1, len(final.elements)):
        e = final.elements[n]
        o = getattr(e, "origin", None)
        if o == "blend":
            rows.append({"key": f"x{n}",
                         "label": f"blend \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "blend"})
        else:
            rows.append({"key": f"x{n}",
                         "label": f"end ext \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "ext"})

    _annotate_junctions(rows)
    _annotate_extension_junctions(rows)
    return rows


def _annotate_extension_junctions(rows):
    """
    Junction keys for extension rows: s1/s2 counting inward from the start,
    e1/e2 counting outward from the end. s1 is where the innermost start
    extension meets the profile; e1 is where the profile meets the innermost
    end extension.
    """
    firsts = [n for n, r in enumerate(rows)
              if r["cls"] == "ext" and r["label"].startswith("start")]
    lasts = [n for n, r in enumerate(rows)
             if r["cls"] == "ext" and r["label"].startswith("end")]
    # start extensions are listed outermost first, so the innermost carries s1
    for k, n in enumerate(reversed(firsts)):
        rows[n]["jkey"] = f"s{k + 1}"
    # the junction before the innermost end extension belongs to the row above
    for k, n in enumerate(lasts):
        prev = n - 1
        if prev >= 0 and k == 0:
            rows[prev]["jkey"] = "e1"
        rows[n]["jkey"] = f"e{k + 2}" if k + 1 < len(lasts) else None
    return rows


def _annotate_junctions(rows):
    """
    Tag each row with `jkey`: the junction that follows it, or None.

    Junctions run between geometric neighbours - real kept elements and bridges.
    Unchecked rows and blend rows are skipped, so a row whose junction already
    carries a blend still reports the same key and the radius stays editable.

      real i / real j        ->  "i-j"
      real i / bridge        ->  "i|far"     far = real element past the bridge
      bridge / real j        ->  "j|far"     far = real element before it
    """
    geo = [r for r in rows
           if (r["cls"] == "bridge") or (r["cls"] == "real" and r["check"])]
    for r in rows:
        r["jkey"] = None
    for k in range(len(geo) - 1):
        a, b = geo[k], geo[k + 1]
        if a["cls"] == "real" and b["cls"] == "real":
            ia, ib = int(a["key"]), int(b["key"])
            key = f"{min(ia, ib)}-{max(ia, ib)}"
        elif a["cls"] == "real" and b["cls"] == "bridge":
            nxt = geo[k + 2] if k + 2 < len(geo) else None
            if nxt is None or nxt["cls"] != "real":
                continue
            key = f"{int(a['key'])}|{int(nxt['key'])}"
        elif a["cls"] == "bridge" and b["cls"] == "real":
            prv = geo[k - 1] if k >= 1 else None
            if prv is None or prv["cls"] != "real":
                continue
            key = f"{int(b['key'])}|{int(prv['key'])}"
        else:
            continue
        a["jkey"] = key
    return rows


def _walk_rows(walk):
    """One row per element of the chosen boundary walk, in walk order."""
    out = []
    for i, e in enumerate(walk):
        pr = _props(e, i)
        shape = (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0"
                 if e.kind == "line"
                 else f"arc R{pr['radius']:.4f} {pr['direction']}")
        src = "" if e.source_id is None else f" src{e.source_id}"
        out.append({"index": i,
                    "label": f"{shape}  len {pr['length']:.4f}{src}"})
    return out


def _focus_props_row(q, c, final, idx):
    """Properties for the focused row: a contour index, or x<pos> in the
    assembled cut sequence. Stock rows (s...) are handled separately."""
    f = q.get("focus", [None])[0]
    if f is None or (not f.startswith("x") and not f.lstrip("-").isdigit()):
        return None
    if f.startswith("x"):
        pos = int(f[1:])
        if 0 <= pos < len(final.elements):
            return _props(final.elements[pos], pos)
        return None
    i = int(f)
    return _props(c.elements[i], i) if 0 <= i < len(c.elements) else None


def _focus_props(q, c):
    """Properties for a focused PROFILE element. Synthetic keys (x...) and
    stock keys (s...) are handled elsewhere, so ignore them here."""
    f = q.get("focus", [None])[0]
    if f is None or not f.lstrip("-").isdigit():
        return None
    i = int(f)
    return _props(c.elements[i], i) if 0 <= i < len(c.elements) else None


def indices_for_chain(c, si, ei, forward):
    from contour.select import chain_indices
    return chain_indices(c, si, ei, forward)

# ---------------------------------------------------------------------------
# the editing state
# ---------------------------------------------------------------------------

@dataclass
class ExtSeg:
    """One extension segment as the operator set it: direction, length, angle.
    Blank length on the first segment means run to the stock."""
    direction: str = ""
    length: str = ""
    angle: str = ""

    def to_extension(self):
        if not self.direction and not str(self.angle).strip():
            return None
        return Extension(
            direction=self.direction or "+Z",
            length=float(self.length) if str(self.length).strip() else None,
            angle=float(self.angle) if str(self.angle).strip() else None)


@dataclass
class Session:
    # what is being edited
    profile_name: str = "part1"

    # chain state
    order: list = None                    # None until a chain is resolved
    off: set = field(default_factory=set)
    flip: bool = False
    blends: dict = field(default_factory=dict)   # junction key -> radius
    pending_start: int = None             # first click, before the end is set
    pending_end: int = None
    focus: str = None                     # row key, as a string

    # extensions: two segments per end
    start_segs: list = field(default_factory=lambda: [ExtSeg(), ExtSeg()])
    end_segs: list = field(default_factory=lambda: [ExtSeg("+X"), ExtSeg()])

    # stock
    stock_source: str = "param"           # "param", "none", or a DXF name
    stock_od: float = 5.5
    stock_zf: float = 0.15
    stock_zb: float = -4.2
    show_stock: bool = True

    # boundary walk: the click history, replayed
    stock_clicks: list = field(default_factory=list)

    # compensation
    comp_side: str = COMP_RIGHT

    # ---- profile ---------------------------------------------------------

    def profile(self):
        return load_profile(self.profile_name)

    def n_elements(self):
        return len(self.profile().elements)

    def reset(self):
        self.order = None
        self.off = set()
        self.flip = False
        self.blends = {}
        self.pending_start = None
        self.pending_end = None
        self.focus = None
        self.stock_clicks = []

    def load(self, name):
        self.profile_name = name
        self.reset()

    # ---- chain editing ---------------------------------------------------

    def click_element(self, i):
        """Click an element in the drawing or the list."""
        n = self.n_elements()
        if not (0 <= i < n):
            return
        self.focus = str(i)
        if self.order:
            if i in self.order:
                return                     # already in the chain: just focus
            # outside the chain: grow it to reach this element
            lo, hi = min(self.order), max(self.order)
            desc = len(self.order) > 1 and self.order[0] > self.order[-1]
            a, b = (lo, i) if i > hi else ((i, hi) if i < lo else (lo, hi))
            rng = list(range(a, b + 1))
            self.order = list(reversed(rng)) if desc else rng
            self._prune_blends()
            return
        if self.pending_start is None or self.pending_end is not None:
            self.pending_start, self.pending_end = i, None
        else:
            self.pending_end = i
            try:
                self.order = chain_indices(self.profile(), self.pending_start,
                                           self.pending_end, True)
            except ValueError:
                try:
                    self.order = chain_indices(self.profile(),
                                               self.pending_start,
                                               self.pending_end, False)
                except ValueError:
                    self.order = None

    def select_all(self):
        self.order = list(range(self.n_elements()))
        self.off = set()
        self.pending_start, self.pending_end = None, None
        self._prune_blends()

    def toggle(self, i):
        if i in self.off:
            self.off.discard(i)
        else:
            self.off.add(i)
        self._prune_blends()

    def reverse(self):
        self.flip = not self.flip

    def shown_order(self):
        if not self.order:
            return []
        return list(reversed(self.order)) if self.flip else list(self.order)

    def delete_end(self, which):
        """Trim the displayed start or end off the chain."""
        d = self.shown_order()
        if not self.order or len(d) <= 1:
            return
        victim = d[0] if which == "start" else d[-1]
        if victim in self.order:
            self.order.remove(victim)
        self.off.discard(victim)
        if self.focus == str(victim):
            self.focus = None
        self._prune_blends()

    @staticmethod
    def normalise_blend_key(key):
        """
        The UI sends junction keys as strings. Real junctions must become the
        tuple form assemble() looks up; bridge ("i|far") and extension
        ("s1"/"e2") keys stay strings.
        """
        if isinstance(key, tuple):
            return key
        k = str(key)
        if "-" in k and "|" not in k:
            a, b = k.split("-", 1)
            if a.lstrip("-").isdigit() and b.isdigit():
                return blend_key(int(a), int(b))
        return k

    def set_blend(self, key, radius):
        k = self.normalise_blend_key(key)
        if radius and radius > 0:
            self.blends[k] = radius
        else:
            self.blends.pop(k, None)

    def _prune_blends(self):
        """Drop blends whose junction no longer exists."""
        live = {r.get("jkey") for r in self._rows_cache or [] if r.get("jkey")}
        if not live:
            return
        for k in list(self.blends):
            if k not in live:
                self.blends.pop(k)

    _rows_cache = None

    # ---- stock -----------------------------------------------------------

    def stock(self):
        if not self.show_stock or self.stock_source == "none":
            return None
        if self.stock_source == "param":
            return parametric(od=self.stock_od, z_face=self.stock_zf,
                              z_back=self.stock_zb)
        return from_dxf(f"tests/{self.stock_source}.dxf",
                        name=self.stock_source)[0]

    def click_stock(self, pt):
        self.stock_clicks.append((float(pt[0]), float(pt[1])))

    def clear_walk(self):
        self.stock_clicks = []

    # ---- derived geometry -------------------------------------------------

    def extensions(self):
        s = [e.to_extension() for e in self.start_segs]
        e = [x.to_extension() for x in self.end_segs]
        s = [x for x in s if x is not None] or None
        e = [x for x in e if x is not None] or None
        return s, e

    def build(self):
        """
        Recompute everything from the stored choices.

        Returns a dict of geometry: selection, extended profile, boundary walk,
        compensated path, and any notes. Pure - no state is changed.
        """
        notes = []
        c = self.profile()
        st = self.stock()

        if not self.order:
            return {"profile": c, "stock": st, "sel": None, "ext": None,
                    "walk": [], "walk_end": None, "comp": None,
                    "idx": [], "notes": notes, "how": self._how()}

        sel, anotes = assemble(c, self.order, self.off, flip=self.flip,
                               blends=self.blends)
        notes += anotes
        idx = [i for i in self.order if i not in self.off]

        ext = None
        s_ext, e_ext = self.extensions()
        if sel.elements and (s_ext or e_ext):
            try:
                ext = extend_profile(sel, st, start=s_ext, end=e_ext)
                ext, xn = blend_extensions(ext, self.blends)
                notes += xn
            except ValueError as err:
                notes.append(f"extension: {err}")
                ext = None

        walk, walk_end = [], None
        src = ext if ext is not None else sel
        if st is not None and src.elements:
            for pt in self.stock_clicks:
                seg, walk_end, wn = stock_click(st, src, pt,
                                                chain_end_s=walk_end)
                notes += wn
                if not seg:
                    break
                walk += seg

        return {"profile": c, "stock": st, "sel": sel, "ext": ext,
                "walk": walk, "walk_end": walk_end, "comp": None,
                "idx": idx, "notes": notes, "how": self._how()}

    def _how(self):
        if not self.order:
            if self.pending_start is None:
                return "click a start element"
            return f"start {self.pending_start} - click the end element"
        bits = [f"chain of {len(self.order)} element(s)"]
        if self.off:
            bits.append(f"{len(self.off)} skipped")
        if self.flip:
            bits.append("reversed")
        return ", ".join(bits)

    def hint(self):
        if self.order:
            return "top = start \u00b7 bottom = end \u00b7 click outside to extend"
        if self.pending_start is None:
            return "click the START element"
        return f"start = {self.pending_start} \u00b7 click the END element"

    # ---- the view payload -------------------------------------------------

    def view(self, width=860):
        g = self.build()
        c, st, sel, ext = g["profile"], g["stock"], g["sel"], g["ext"]
        notes = list(g["notes"])

        if sel is None or not sel.elements:
            svg = render_pickable(c, selected=(), stock=st, width=width,
                                  title=f"{self.profile_name} - {g['how']}")
            self._rows_cache = []
            return {"svg": svg, "rows": [], "walk_rows": [],
                    "props": None, "info": g["how"], "hint": self.hint(),
                    "blend_errors": {}, "notes": notes,
                    "n_elements": self.n_elements()}

        final = ext if ext is not None else sel
        rows = _rows_full(c, final, self.order, set(self.off),
                          flip=self.flip, sel=sel)
        self._rows_cache = rows

        # focus can be a profile index, a synthetic x-key, or a walk s-key
        props = None
        f = self.focus
        if f is not None:
            if f.startswith("s") and f[1:].isdigit():
                i = int(f[1:])
                if 0 <= i < len(g["walk"]):
                    props = _props(g["walk"][i], i)
            elif f.startswith("x") and f[1:].isdigit():
                i = int(f[1:])
                if 0 <= i < len(final.elements):
                    props = _props(final.elements[i], i)
            elif f.lstrip("-").isdigit():
                i = int(f)
                if 0 <= i < len(c.elements):
                    props = _props(c.elements[i], i)

        f_idx, f_el = None, None
        if f is not None:
            if f.startswith("s") and f[1:].isdigit() and \
                    int(f[1:]) < len(g["walk"]):
                f_el = g["walk"][int(f[1:])]
            elif f.startswith("x") and f[1:].isdigit() and \
                    int(f[1:]) < len(final.elements):
                f_el = final.elements[int(f[1:])]
            elif f.lstrip("-").isdigit() and int(f) < len(c.elements):
                f_idx = int(f)

        stri = etri = None
        if ext is not None and ext.elements:
            a, b = ext.elements[0], ext.elements[-1]
            if is_extension(a):
                stri = (a.start.z, a.start.r,
                        a.end.z - a.start.z, a.end.r - a.start.r)
            if is_extension(b):
                etri = (b.end.z, b.end.r,
                        b.end.z - b.start.z, b.end.r - b.start.r)

        svg = render_pickable(c, selected=g["idx"], extended=ext, stock=st,
                              width=width,
                              title=f"{self.profile_name} - {g['how']}",
                              start_dot=(sel.elements[0].start.z,
                                         sel.elements[0].start.r),
                              end_dot=(sel.elements[-1].end.z,
                                       sel.elements[-1].end.r),
                              focus=f_idx, focus_element=f_el,
                              start_tri=stri, end_tri=etri, walk=g["walk"])

        errs = {}
        for src in (getattr(sel, "blend_errors", {}) or {},
                    getattr(ext, "blend_errors", {}) or {}):
            for k, v in src.items():
                wire = f"{k[0]}-{k[1]}" if isinstance(k, tuple) else str(k)
                errs[wire] = {"asked": v["asked"], "max": round(v["max"], 4),
                              "where": v.get("where", wire)}

        nbridge = sum(1 for e in sel.elements if is_bridge(e))
        p0 = final.elements[0].start
        p1 = final.elements[-1].end
        info = "\n".join([
            g["how"],
            f"kept {len(sel.elements)} element(s)"
            + (f", {nbridge} bridge line(s)" if nbridge else ""),
            f"continuity: {check_selection(sel) or 'clean chain'}",
            f"profile start  z={p0.z:+.4f}  X={2*p0.r:.4f}",
            f"profile end    z={p1.z:+.4f}  X={2*p1.r:.4f}",
        ] + notes)

        return {"svg": svg, "rows": rows, "walk_rows": _walk_rows(g["walk"]),
                "props": props, "info": info, "hint": self.hint(),
                "blend_errors": errs, "notes": notes,
                "n_elements": self.n_elements()}
