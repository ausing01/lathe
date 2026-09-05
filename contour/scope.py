"""
scope.py - operation scope: which span of a profile a cut actually machines.

A Contour is the whole part profile. A real operation often cuts only part of
it - the backface reference cuts the step + one wall, not the whole thing, and
it runs the wall PAST the profile end to a cutoff plane. This module carves a
sub-contour out of a full contour so the rest of the pipeline (comp, post) can
consume it unchanged.

Design (driven by the four reference parts):
  - element span: an inclusive [start, end] run of elements (by index), or the
    whole contour by default. Contiguous only - a turned operation cuts a
    connected span, not scattered elements.
  - end limits: optional z= or r= planes that TRIM (clip shorter) or EXTEND
    (project longer) the first/last element to a cutoff. This is the backface
    case: the r1.5 wall extends from z-2.0 to the cutoff at z-2.1659.
  - direction: which end is the cut entry. Defaults to contour order; reverse
    for e.g. cutting a bore mouth-inward when the contour was walked the other
    way.

Selection can also be given as a set of source_ids (the DXF entity identity
hook), which the future graphical picker will use - resolved to an index span.
"""

from dataclasses import dataclass, field
from .model import Contour, Line, Arc, Point, ArcDir


@dataclass
class Limit:
    """A cutoff plane trimming/extending an end of the span.
    axis 'z' or 'r'; value the plane position. The affected end element is
    projected along its own direction to meet this plane."""
    axis: str          # 'z' or 'r'
    value: float


@dataclass
class OperationScope:
    start_index: int = 0            # first element of the span (inclusive)
    end_index: int = None           # last element (inclusive); None = last
    start_limit: Limit = None       # optional trim/extend of the first element
    end_limit: Limit = None         # optional trim/extend of the last element
    reverse: bool = False           # cut the span in reverse (entry at far end)

    @classmethod
    def from_source_ids(cls, contour, ids, **kw):
        """Build a span from a set of DXF source_ids. Requires the selected
        ids to form one contiguous run in the contour (raises otherwise)."""
        idxs = sorted(i for i, e in enumerate(contour.elements)
                      if e.source_id in ids)
        if not idxs:
            raise ValueError("no elements match the given source_ids")
        if idxs != list(range(idxs[0], idxs[-1] + 1)):
            raise ValueError("selected source_ids are not a contiguous span")
        return cls(start_index=idxs[0], end_index=idxs[-1], **kw)


def _project_line_to_limit(a, b, limit, move_end):
    """Return a new endpoint for a line a->b, projecting the moved end onto the
    limit plane along the line's own direction. move_end True moves b, else a."""
    dz = b.z - a.z
    dr = b.r - a.r
    if limit.axis == 'z':
        if abs(dz) < 1e-12:
            return b if move_end else a         # parallel; can't project
        t = (limit.value - a.z) / dz
    else:
        if abs(dr) < 1e-12:
            return b if move_end else a
        t = (limit.value - a.r) / dr
    return Point(z=a.z + t * dz, r=a.r + t * dr)


def apply_scope(contour, scope):
    """Return a new Contour containing just the scoped span, ends trimmed/
    extended to any limits, reversed if requested. Elements keep source_id."""
    els = contour.elements
    lo = scope.start_index
    hi = scope.end_index if scope.end_index is not None else len(els) - 1
    if not (0 <= lo <= hi < len(els)):
        raise ValueError(f"span [{lo},{hi}] out of range 0..{len(els)-1}")

    span = [_clone(e) for e in els[lo:hi + 1]]

    # apply end limits (only lines can be projected simply; arcs to a plane are
    # a future extension - flag if attempted)
    if scope.start_limit is not None:
        span[0] = _apply_limit_to_end(span[0], scope.start_limit, move_end=False)
    if scope.end_limit is not None:
        span[-1] = _apply_limit_to_end(span[-1], scope.end_limit, move_end=True)

    out = Contour(elements=span, side=contour.side,
                  name=contour.name + "_scoped")
    if scope.reverse:
        out = _reverse_contour(out)
    return out


def _apply_limit_to_end(e, limit, move_end):
    if e.kind == "line":
        if move_end:
            new_end = _project_line_to_limit(e.start, e.end, limit, True)
            return Line(e.start, new_end, source_id=e.source_id)
        else:
            new_start = _project_line_to_limit(e.start, e.end, limit, False)
            return Line(new_start, e.end, source_id=e.source_id)
    # arc-to-limit: not yet needed by any reference; return unchanged and let
    # the caller notice. (Projecting an arc onto a plane = line/circle intersect,
    # a straightforward future addition using geom2d.)
    return e


def _clone(e):
    if e.kind == "line":
        return Line(Point(e.start.z, e.start.r), Point(e.end.z, e.end.r),
                    source_id=e.source_id)
    return Arc(Point(e.start.z, e.start.r), Point(e.end.z, e.end.r),
               Point(e.center.z, e.center.r), e.direction, source_id=e.source_id)


def _reverse_contour(contour):
    new = []
    for e in reversed(contour.elements):
        if e.kind == "line":
            new.append(Line(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
                            source_id=e.source_id))
        else:
            d = ArcDir.CW if e.direction == ArcDir.CCW else ArcDir.CCW
            new.append(Arc(Point(e.end.z, e.end.r), Point(e.start.z, e.start.r),
                           Point(e.center.z, e.center.r), d, source_id=e.source_id))
    return Contour(elements=new, side=contour.side, name=contour.name)
