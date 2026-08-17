# Lathe conversational backend

DXF -> contour -> LinuxCNC G-code, with a validated 2D geometry primitive layer.
Headless-first, configurable, GPLv2 - built toward a distributable LinuxCNC tool.

## Modules
- `contour/model.py`       - the Contour object (the keystone). Radius-based, part coords.
- `contour/dxf_import.py`  - dependency-free DXF parser + chain builder + coord transform.
- `contour/geom2d.py`      - 2D primitives: line/arc offset, all intersections, root selection.
                             Shared solver for comp, contour calc, and roughing. Has self-tests.
- `contour/post_linuxcnc.py` - Contour -> LinuxCNC G-code. Configurable via PostConfig.
- `tests/`                 - two test parts (DXF), their Fanuc references, generated output.

## Quick checks
Run the geometry self-test (should say 13 passed, 0 failed):
```
python3 contour/geom2d.py
```

Confirm a real reference number comes out of the offset math (should print 0.04125,
the R0.0412 corner from part 2's reference):
```
python3 -c "from contour.geom2d import offset_arc_radius; print(offset_arc_radius(0.010, 0.03125, concave=True))"
```

Import a part and view the chained contour:
```
python3 -c "from contour.dxf_import import import_dxf; from contour.model import Side; c,p=import_dxf('tests/test_part_1.dxf',side=Side.OD,tol=0.05); print(c.describe())"
```

## Status
- [x] Contour object
- [x] DXF import with chain building (tolerates gaps in the real files)
- [x] Coordinate transform (DXF radius -> part radius, x=axial)
- [x] LinuxCNC post: boilerplate (G7/G96/G97/G95/G18), safe trailing decimals,
      integer spindle words, staged approach
- [x] geom2d primitives, arc-offset sign rule validated against BOTH references
      (concave R+nose, convex R-nose; matches 0.0412, 0.1312, 0.1188 exactly)
- [ ] comp.py - apply nose-radius comp per element, re-intersect junctions (NEXT)
- [ ] roughing pass generator
- [ ] facing, drilling, grooving, threading cycles

## Tool for both test parts
1/32" (0.03125") nose radius, tip orientation #3 (OD turning, tool in front,
cutting toward the chuck). References drive the imaginary tip.

## Note on current post output
The post emits the true PART PROFILE, not the offset toolpath - comp is not wired
in yet (that's comp.py, next). Posting a part now traces the correct finished shape
in a backplot but will not match the reference toolpath until comp exists. Expected.
