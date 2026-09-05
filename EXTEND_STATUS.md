# Profile extensions

Extensions belong to the GEOMETRY definition, not the operation: the extended
contour IS the part profile, and every operation referencing it gets it.

## Segment chain, not a clearance value
Each end takes a single Extension or a LIST of them, applied in order outward
from the profile. Each segment carries its own angle, so a run-out can change
direction partway.

    extend_profile(sel, stock,
                   end=[Extension("+X"),                    # run to the stock
                        Extension(angle=45.0, length=0.2)]) # then off at 45 deg

`Extension(direction, length=None, angle=None)`

| Field | Meaning |
|---|---|
| `direction` | `+Z`, `-Z`, `+X`, `-X`. +z toward tailstock, +r larger diameter. |
| `length` | Fixed distance. Without it the segment runs to the stock boundary, which only makes sense for the FIRST segment - later ones already start outside the stock. |
| `angle` | Degrees from +Z toward +X. Overrides `direction`. |

**Clearance is no longer an extension property.** Standoff belongs to the
toolpath, in `cycles.CycleParams.clearance`. `Extension(..., clearance=...)` now
raises, and verify asserts that.

## Applied to the picker selection
Extensions run from the SELECTION's ends, not the whole imported profile. Chain
part1 elements 2 to 5 and the end extension starts at that chain's end.

## Zero-length segments are dropped
A profile end sitting exactly on the stock boundary gives a zero-length
run-to-stock segment; it is dropped rather than added as a degenerate element.
With stock OD 5.5 the part 1 end already sits on the boundary, so a second
segment with an explicit length is what carries it out.

## Synthetic elements
Extension elements have `source_id = None`. `is_extension(element)` tests for it,
and the element list shows them as "(extension)".
