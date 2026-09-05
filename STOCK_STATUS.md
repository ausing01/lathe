# Stock model + cycle params - built, verify green on these

## contour/stock.py
A Stock is a CLOSED contour in (z, r) plus a set of OPEN EDGE element indices -
faces the tool may approach through. Closed edges are chuck, fixture, or
centreline and must not be crossed. Roughing entry/exit and retract planes
derive from these.

Three constructors, all producing the same object:

| Method | Use |
|---|---|
| `parametric(od, z_face, z_back, id_bore=0)` | Bar or tube typed in. No DXF needed. Element order: front face, OD, back face, bore/centreline. Defaults mark front face + OD open, chuck end closed; a bore is open when `id_bore > 0`. |
| `from_dxf(path, open_edges=None)` | Stock profile in its own file (casting, forging, prior op). Warns if the profile is not a closed loop. |
| `from_contour(contour, open_edges=None)` | Wrap an already-imported closed contour. The SolidCAM method. |

`open_edges_by_source_id(stock, ids)` resolves DXF entity ids to element indices
and marks them open - this is what the future graphical picker calls when the
operator clicks segments.

## contour/cycles.py
`CycleParams` holds the shared cycle values so they have one definition:
clearance, doc, stock_to_leave_r/z, feed, retract.

CLEARANCE (default 0.1) is applied NORMAL to the surface: radial on a diameter
(0.1 radial = 0.2 on diameter), axial on a face, perpendicular on an angled
surface. This is what resolves part 1's final-move overtravel - comp stops at
the profile end, the cycle adds clearance beyond it.

## Closed-loop chaining - now tested
`tests/stock_closed.dxf` is a synthetic closed bar profile (4 lines, r1.5,
z +0.1 to -3.0). The chain builder's closed-loop branch had never run on real
data; it now chains correctly and `Contour.closed` is detected on import
(previously always False).

## Clearance vs part 1's reference - one unexplained residual
Part 1's final cut move is X5.6912; profile end r2.75 + 0.1 radial clearance
gives X5.7000. The program's own rapid/retract lines are X5.7, confirming stock
OD r2.75 and clearance 0.1. The cut move stops 0.0044 (radius) short of that.
Treat 0.1 radial as the rule; the 0.0044 needs confirmation before modelling.

## Still red
part1 comp positions - the material-side discriminator (see COMP_STATUS.md).
Unchanged this session. Everything else in verify is green.
