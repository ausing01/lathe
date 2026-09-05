"""
stock.py - the stock (blank) model.

Everything about material removal derives from this: roughing extents, retract
planes, the eventual simulator. A Stock is a CLOSED contour in part coords
(z, r) plus per-element access flags.

Three ways to define one, all producing the same object:

  1. parametric()   - bar / tube dimensions typed in. Covers most manual-lathe
                      work with no DXF at all.
  2. from_dxf()     - a separate DXF file holding the stock profile (casting,
                      forging, prior-op shape).
  3. from_contour() - an already-imported closed contour, with open edges
                      marked. The SolidCAM method.

OPEN EDGES
An element flagged open is a face the tool may approach through (bar stock
sticking out of the chuck: the front face and the OD are open, the chuck end is
not). Closed edges are fixture, chuck, or centreline and must not be crossed.
Roughing uses these for entry/exit; retract planes derive from the open extents.

Element flags are held by index so the Contour model stays unchanged; the
`source_id` on each element is what a future graphical picker will toggle.
"""

from dataclasses import dataclass, field
from .model import Contour, Line, Point, Side


@dataclass
class Stock:
    contour: Contour                       # closed profile in (z, r)
    open_edges: set = field(default_factory=set)   # element indices tool may enter through
    name: str = "stock"

    # --- queries used by roughing / retract ------------------------------

    def z_range(self):
        return self.contour.z_range()

    def r_range(self):
        return self.contour.r_range()

    @property
    def od(self):
        return self.r_range()[1]

    @property
    def face_z(self):
        """Frontmost z (largest, i.e. nearest the tailstock)."""
        return self.z_range()[1]

    def is_open(self, index):
        return index in self.open_edges

    def describe(self):
        zr, rr = self.z_range(), self.r_range()
        out = [f"Stock '{self.name}'  {len(self.contour.elements)} elements  "
               f"closed={self.contour.closed}",
               f"  z {zr[0]:.4f} .. {zr[1]:.4f}   r {rr[0]:.4f} .. {rr[1]:.4f}"]
        for i, e in enumerate(self.contour.elements):
            tag = "OPEN " if self.is_open(i) else "fixed"
            out.append(f"  [{i}] {tag} {e.kind:4} "
                       f"({e.start.z:+.4f},{e.start.r:.4f})->"
                       f"({e.end.z:+.4f},{e.end.r:.4f})")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# 1. parametric
# ---------------------------------------------------------------------------

def parametric(od, z_face, z_back, id_bore=0.0, open_face=True,
               open_od=True, open_back=False, name="stock"):
    """
    Bar or tube stock as a closed profile.

    od      - outside DIAMETER of the blank (not radius; this is the one place
              a diameter is accepted, because that's how bar stock is bought)
    z_face  - z of the front face (usually 0 or a small positive stickout)
    z_back  - z of the back end (negative, into the chuck)
    id_bore - bore DIAMETER for tube stock; 0 for solid bar
    open_*  - which faces the tool may approach through. Defaults suit bar held
              in a chuck: front face and OD open, chuck end closed.

    Element order is front face -> OD -> back face -> return (bore or centre).
    """
    if z_back >= z_face:
        raise ValueError("z_back must be less than z_face")
    r_o = od / 2.0
    r_i = id_bore / 2.0

    p = [Point(z_face, r_i), Point(z_face, r_o),
         Point(z_back, r_o), Point(z_back, r_i)]
    els = [
        Line(p[0], p[1]),   # [0] front face (outward)
        Line(p[1], p[2]),   # [1] OD
        Line(p[2], p[3]),   # [2] back face (inward)
        Line(p[3], p[0]),   # [3] bore wall, or the centreline for solid bar
    ]
    c = Contour(elements=els, side=Side.OD, closed=True, name=name)

    openset = set()
    if open_face:
        openset.add(0)
    if open_od:
        openset.add(1)
    if open_back:
        openset.add(2)
    if id_bore > 0:
        openset.add(3)      # a through bore is approachable
    return Stock(contour=c, open_edges=openset, name=name)


# ---------------------------------------------------------------------------
# 2. from a separate DXF
# ---------------------------------------------------------------------------

def from_dxf(path, open_edges=None, tol=1e-3, name="stock"):
    """
    Load stock geometry from its own DXF. Returns (Stock, problems).
    open_edges: set of element indices the tool may approach through; if None,
    nothing is marked open and the caller must set them.
    """
    from .dxf_import import import_dxf
    c, problems = import_dxf(path, side=Side.OD, tol=tol, name=name)
    if not c.closed:
        problems.append("stock profile is not a closed loop - "
                        "material extents are ambiguous")
    return Stock(contour=c, open_edges=set(open_edges or ()), name=name), problems


# ---------------------------------------------------------------------------
# 3. from an existing contour (the SolidCAM method)
# ---------------------------------------------------------------------------

def from_contour(contour, open_edges=None, name="stock"):
    """Wrap an already-imported closed contour, marking its open edges."""
    return Stock(contour=contour, open_edges=set(open_edges or ()), name=name)


def open_edges_by_source_id(stock, ids):
    """Resolve DXF entity ids to element indices and mark them open. This is
    what a graphical picker calls when the operator clicks segments."""
    idx = {i for i, e in enumerate(stock.contour.elements)
           if e.source_id in ids}
    stock.open_edges |= idx
    return idx
