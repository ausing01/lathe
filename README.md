# Lathe conversational backend

DXF -> contour -> nose-radius compensation -> LinuxCNC G-code.
Headless-first, validated against real CAM references. GPLv2.

## Modules
- `contour/model.py`        - the Contour object (keystone). Radius-based, part coords.
                              Elements carry `source_id` (DXF entity identity).
- `contour/dxf_import.py`   - DXF parser + CONNECTIVITY-based chain builder + transform.
- `contour/geom2d.py`       - 2D primitives: line/arc offset, intersections. Self-tested.
- `contour/comp.py`         - nose-radius compensation. OD/ID, all tip codes, winding-based.
- `contour/post_linuxcnc.py`- Contour -> LinuxCNC G-code. Configurable via PostConfig.
- `tests/`                  - four parts (DXF + CAM reference): OD turn x2, bore, backface.

## Quick checks
Geometry self-test (expect: 13 passed, 0 failed):
```
python3 contour/geom2d.py
```

All four parts import and chain cleanly:
```
python3 -c "from contour.dxf_import import import_dxf; from contour.model import Side; c,p=import_dxf('tests/backface.dxf',side=Side.OD); print(len(c.elements),'elems',p or 'clean')"
```

## Status
- [x] Contour object with entity identity (source_id)
- [x] DXF import, connectivity-based chaining (all 4 parts correct, no hand-ordering)
- [x] geom2d primitives (validated)
- [x] Nose-radius comp: OD/ID, tip codes #1-8, winding-based material side.
      Matches all four CAM references to 4 decimals. Flags un-fittable features.
- [x] LinuxCNC post: boilerplate, safe trailing decimals, integer spindle words,
      staged approach
- [ ] Operation scope (which span of a profile a cut machines) - NEXT
- [ ] Stock/blank definition
- [ ] Roughing pass generator
- [ ] Facing, drilling, grooving, threading cycles
- [ ] QtVCP UI (incl. graphical DXF segment picker, using source_id)

## Tooling in the references
- OD parts (test_part_1, test_part_2): 1/32" (0.03125") nose, tip #3
- bore: 0.0886" nose, tip #6, ID
- backface: 0.0886" nose, tip #8

## Reading the status docs
- COMP_STATUS.md          - compensation validation detail
- CHAINBUILDER_STATUS.md  - chain builder fix detail
