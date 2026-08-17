# Lathe conversational backend - phase 0

DXF -> contour -> LinuxCNC G-code, proven end to end on test_part_1.

## Files
- `contour/model.py`      - the Contour object (the keystone). Radius-based, part coords.
- `contour/dxf_import.py` - DXF parser + chain builder + coord transform.
- `contour/post_linuxcnc.py` - Contour -> LinuxCNC G-code. Configurable via PostConfig.
- `tests/` - the test DXF, your Fanuc reference, and my generated output.

## Run it
```
cd lathe
python3 -c "from contour.dxf_import import import_dxf; from contour.model import Side; c,p=import_dxf('tests/test_part_1.dxf',side=Side.OD,tol=0.05); print(c.describe())"
```

## Status
- [x] Contour object
- [x] DXF import with chain building (tolerates the gap in this file)
- [x] Coordinate transform (DXF radius -> part radius, x=axial)
- [x] LinuxCNC post with correct boilerplate (G7/G96/G95/G18)
- [ ] Tool-nose-radius compensation offset (NEXT - makes output match the Fanuc reference)
- [ ] Roughing pass generator
- [ ] Facing, drilling, grooving, threading cycles

## Note on the current output
The post emits the true PART PROFILE, not the offset toolpath. It will trace the
correct finished shape in a backplot but will not yet match Finish_Turn_reference.NC,
because nose-radius comp is not applied yet. That is the next module.
