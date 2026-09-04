# comp.py status - VALIDATED across 4 operations

## Result: nose-radius comp math proven exact against all four references
Fed a correctly-ordered contour, comp reproduces the CAM toolpath to 4 decimals:

| part      | side | tip | nose    | result                          |
|-----------|------|-----|---------|---------------------------------|
| part 1    | OD   | #3  | 0.03125 | matches (cut portion)           |
| part 2    | OD   | #3  | 0.03125 | matches; flags the un-fittable  |
|           |      |     |         | R0.010 corners (correct)        |
| bore      | ID   | #6  | 0.0886  | EXACT, all points               |
| backface  | OD   | #8  | 0.0886  | EXACT key points when ordered   |

One general code path handles OD/ID, four tip orientations, two nose radii.

## What's proven
- Origin-position table (SolidCAM diagram): imaginary tip = per-axis nose corner.
- Material side by profile winding (signed area) + OD/ID flip.
- Concave/convex arc offset (R +/- nose), validated numerically earlier.
- Vanished-element handling for convex features tighter than the nose, with an
  interference warning surfaced in `problems` (operator owns interference).

## The one real bug (NOT in comp - it's in dxf_import)
The greedy chain builder mis-orders some profiles. On the backface DXF it
connected non-adjacent endpoints (produced a diagonal not in the DXF) because
the nearest-neighbour walk + start_hint=origin picked a bad start/order.
Comp is correct; it was fed a bad chain.

### Fix needed in dxf_import.py
Make chain building robust: instead of greedy nearest-neighbour from the origin,
build proper connectivity (match endpoints within tol, follow the unique
continuation at each node, detect the natural open-chain ends). Then validate
all four parts import in correct order and re-run the four-way diff end to end
(DXF -> comp -> compare), which should then match without hand-ordering.

## Also pending
- Operation SCOPE: the backface reference cuts only part of the profile (the
  r1.5 wall + step, not the r2 face). Comp/post needs a way to select which
  contour span an operation cuts - a job/operation concept above the raw contour.
