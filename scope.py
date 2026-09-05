# Operation scope - DONE

## What it solves
A Contour is the whole part profile, but a real operation cuts only part of it.
The backface reference cuts the step + one wall (not the r2 face) AND runs that
wall past the profile end (z-2.0) to a cutoff plane (z-2.1659). Operation scope
carves the cut span out of the full contour so comp/post consume it unchanged.

## Module: contour/scope.py
- `OperationScope(start_index, end_index, start_limit, end_limit, reverse)`
- `OperationScope.from_source_ids(contour, {ids})` - select by DXF entity
  identity (the hook added in the chain-builder pass); must be a contiguous span.
- `Limit(axis='z'|'r', value)` - a cutoff plane that trims (clips) or extends
  (projects) the first/last element of the span to that plane.
- `apply_scope(contour, scope)` -> new sub-Contour, ends trimmed/extended,
  optionally reversed, source_id preserved.

## Validated
Backface, full pipeline, NO hand-editing:
  DXF -> chain -> scope(elems 1-2, end_limit z=-2.1659) -> comp(tip#8) ->
    X3.0000 Z-0.5886   (step - reference exact)
    X3.0000 Z-2.1659   (wall extended to cutoff - reference exact)
Both cut moves match the CAM reference to 4 decimals.

Also verified: default scope = whole profile (part1/part2 unchanged, no
regression); source_id selection resolves to the correct span; reverse works;
non-contiguous id selection is rejected.

## Deferred (not needed by any reference yet)
- Arc projected onto a limit plane (line/circle intersect via geom2d) - only
  lines are trimmed/extended so far, which covers all four parts.
- The graphical picker itself (QtVCP era) - will call from_source_ids under the
  hood, so the selection logic already exists and is tested headless.

## Next
- Stock/blank definition (keystone for roughing, retract planes, simulator)
- Roughing pass generator
