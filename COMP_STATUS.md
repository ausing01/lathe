# comp.py status - ARC CONCAVITY REBUILD PENDING (known regression)

## Current state: verify.py is RED on the two arc parts
The chain-builder fix (last session) changed element ordering/direction to the
CORRECT tight-tolerance chaining. comp's arc concave/convex test was written
against the OLD (loose-tolerance) ordering and is now wrong for arcs.

verify.py reports:
  - part1 comp arc radii [0.0688, 0.1813], want [0.1188, 0.1312]
  - part2 comp arcs [0.0562], want an R~0.0412
Both are the SAME bug: `_arc_is_concave` uses global contour winding, which only
worked by coincidence for the old ordering. Concavity is a LOCAL property.

IMPORTANT: this regression is already in the committed repo (it went in with the
chain-builder commit, before verify.py existed to catch it). The line-only parts
(bore, backface) are unaffected and remain correct.

## What still works (verify green on these)
- All module imports, geom2d self-test (13/13).
- All four parts CHAIN correctly.
- comp on LINE-only profiles: bore (ID tip#6) and backface (tip#8) exact.
- Operation scope: backface span + end-extend -> reference exact.

## The fix (next session)
Rebuild arc concavity as a LOCAL geometric test, not winding-based. The method
is already identified and works: offset the arc midpoint along the air-side
normal by the nose radius; if the resulting tool-center is FARTHER from the arc
center than the arc radius, the arc is concave (R+nose), else convex (R-nose).

The weak link found in-session: `_air_normal` returns the wrong side when fed a
short chord around an arc midpoint. So the rebuild is:
  1. compute the correct air-side normal AT the arc (from material side, done
     right for arcs, not via a chord approximation)
  2. apply the tool-center-distance test above
Validate against BOTH arc parts at once (part1: one convex R0.15->0.1188 + one
concave R0.10->0.1312; part2: two concave R0.010->0.0412 + one convex R0.025
that vanishes). Lock both in verify.py. Only then is verify green and we push.

## Lesson captured in the update system
verify.py now exists and gates every push (see UPDATE_SYSTEM.md). This regression
is exactly what it's for - it surfaced the moment we had a smoke test.
