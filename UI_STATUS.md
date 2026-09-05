# Viewer - consolidated profile page

Stdlib only, no X display, no QtVCP. `python3 serve.py`, then
`http://localhost:8321/` in a browser on the LinuxCNC machine.

| Page | Content |
|---|---|
| `/` | Parametric stock builder |
| `/profile` | Element picker + extensions, one page, click to select |
| `/parts` | Four reference parts, profile overlaid with comp output |

`/extend` and `/pick` are gone; both are folded into `/profile`.

## Arc direction fixed
Arcs were bulging the wrong way. The cause was the SVG "A" command sweep flag:
it is interpreted in user space, and the drawing applies a y-flip to put radius
upward, which inverts the flag's meaning.

Arcs are now SAMPLED into points computed directly from the start angle, sweep
direction and radius, so no flag is involved and the class of bug is gone.
Verify checks that sampled arcs start and end on the real endpoints and that the
midpoint sits exactly on the radius.

## Click to select
`viz.render_pickable()` emits one `<path>` per element with `data-idx`, plus a
wide transparent hit path so elements are easy to hit. The page attaches click
handlers to those.

| Mode | Clicking does |
|---|---|
| auto chain | First click sets the START element, second sets the END. Clicking again restarts. |
| manual select | Each click toggles that element in or out. |

`reverse direction` picks the other route around a closed profile, or reverses
element order in manual mode. `all` / `none` buttons for bulk selection, and a
`stock on/off` toggle.

The hint line under the checkboxes says what the next click will do, so the two
click modes are not ambiguous.

## Chain direction markers
The selected chain is marked with two dots:

| Dot | Position | Meaning |
|---|---|---|
| green | START of the chain's first element | where the chain begins |
| red | END of the chain's last element | where the chain finishes |

With a single element selected it is both first and last, so it carries both
dots, at opposite ends.

Dots sit on the SELECTION, not on the extended profile, so whatever an extension
adds is visible running beyond them.

On a closed profile the two routes share an entry point, so it is the RED dot
that distinguishes them: forward from element 0 to 2 finishes at r 0.0, reversed
at r 1.5. Verify asserts the two routes end at different points, and that a
single-element selection does not put both dots in the same place.

Both dots show as soon as the start element is clicked, before the end is chosen.
`reset` unpicks it.

## Three-column layout
| Column | Content |
|---|---|
| left | Element list in chain order - start at the top, end at the bottom. Each row has a checkbox; the focused row is outlined. Clicking a row focuses it. Buttons: reverse, del start, del end. |
| centre | The drawing. Clicking an element selects and focuses it. |
| right | Element detail for the focused element. |

Element rows are labelled the way they read off a print: `line 90` for a face,
`line 45` for a chamfer, `line 0` for a straight diameter, `arc R0.150 CW`.

## Element list controls
| Control | Effect |
|---|---|
| **reverse** | Runs the chain the other way. Works on a single element too, swapping its start and end points. The toolpath will follow this order, so this is the cut-direction control. |
| **del start** / **del end** | Trims the first or last element off the chain. Only the ends can be removed, since removing an end shortens the chain rather than splitting it. |
| checkbox | Unchecking an element removes it from the cut and BRIDGES the gap with a straight line from the previous kept element to the next. Unchecking 2 and 3 draws one line from 1 to 4. Unchecked ends are just dropped. |

## Growing the chain by clicking
Once a chain exists, clicking an element OUTSIDE it extends the chain to reach
that element instead of starting over - the fix for misclicking the end element.
Clicking inside the chain just focuses that element. The hint line says so.

## The list shows the whole cut sequence
Rows are the assembled chain in cut order, including synthetic elements:

| Row type | Colour | Checkbox | Label |
|---|---|---|---|
| real DXF element | plain | yes | `line 45` / `arc R0.1500 CW` |
| blend | blue | no | `blend / arc R0.0500 CCW` |
| extension | green | no | `start ext / line 0` or `end ext / line 45` |
| bridge | amber | no | `bridge / line 9` |

Unchecked elements STAY in the list with their checkbox present but cleared, so
they can be ticked back on. The bridge that replaces them is listed immediately BEFORE the run of
unchecked elements, so the list reads in cut order.

Angles are shown to three decimals with trailing zeros dropped.

The auto-chain / manual-select / reverse-direction checkboxes are gone; chaining
is always auto. `reset` now lives with the list buttons.

Extensions, bridges and blends have no contour index, so they carry a positional key
(`x0`, `x11`) and no checkbox - they are consequences of the chain, not things to
pick. They can still be clicked to show their properties on the right.

Real elements keep their contour index as the row number, so the checkbox,
delete and reverse controls are unaffected.

## Blends and bridges interact
Extensions are junction-bearing too, keyed by which end they belong to and how
far out they sit: `s1` where the innermost start extension meets the profile,
`s2` between the two start segments, `e1` where the profile meets the innermost
end extension, `e2` beyond it. Extensions are applied after any flip, so start
and end already mean what the operator sees.

Bridges are junction-bearing: each end can take its own blend. The server tags
every row with the junction that follows it (`jkey`), and the blend box works off
that tag, so real-to-real, real-to-bridge and bridge-to-real all behave the same
from the operator's side.

Re-checking an element closes the gap and removes the bridge; any blend that sat
on that bridge is pruned, because the server no longer reports those junctions.
Blends are never remembered across a change.

Rows are built from the assembly metadata rather than reconstructed, so the list
reads in true cut order: `1, blend, bridge, [2 and 3 unchecked], 4`.

## Focus highlighting
Clicking a row in the list highlights that element in the drawing with an amber
halo, and clicking an element in the drawing focuses its row. This works for
synthetic rows too - blends, bridges and extensions are highlighted from their
own geometry, since they are not in the source DXF.

## Markers
| Marker | Meaning |
|---|---|
| green dot | start of the PROFILE (the selected chain) |
| red dot | end of the profile |
| green triangle | start of the CUT, i.e. the outermost start extension |
| red triangle | end of the cut, the outermost end extension |

Triangles point along the direction of travel and appear only on the first and
last element of the whole chain, not on every extension segment. Keeping the dots
on the profile means the extension is visible as the run beyond them.

## Blend radius control
The detail panel carries a blend field whenever the focused element is a real one
with a real element after it. Type a radius and press apply to fillet that
junction; clear removes it. The note names the junction, e.g. `junction 2 / 3`.

The blend is stored against the junction, not the element, so reversing the chain
keeps it between the same two elements.

## When a blend does not fit
| What | Behaviour |
|---|---|
| geometry | Nothing is inserted; the chain is left exactly as it was, still continuous |
| element list | NO blend row is added |
| radius field | Turns yellow, keeping the value so it can be adjusted |
| note | Names the junction, the radius asked for, and the largest that WOULD fit |
| readout | `blend R1.0 at 2/3 does not fit (max 0.7440)` |

The maximum is found by bisection on the fillet solver, so it works for any
element pair - line/line, line/arc, arc/arc - without a closed-form limit per
combination. Verify checks the reported figure really is the boundary: just below
it fits, just above it does not.

The limit is the TANGENT DISTANCE, not the radius. At a 45 degree corner the
tangent runs back R x tan(22.5) into each neighbour, so the shorter neighbour
sets the limit. That is why a radius can be refused at one end of a bridge and
accepted at the other.

## Element detail panel
| Group | Fields |
|---|---|
| identity | element index, kind, origin (`DXF element`, `extension`, `bridge`), DXF entity id |
| start | Z, X diameter, radius |
| end | Z, X diameter, radius |
| line geometry | length, angle from axis, included angle, dZ, dR |
| arc geometry | length, radius, centre Z, centre X diameter, direction, sweep |

Angles are measured OFF THE SPINDLE AXIS, which is how a print reads them: 0 for
a straight diameter, 90 for a face, 45 for a 45-degree chamfer. Included angle is
the full cone, twice that. Verify asserts all three.

## Extensions on the same page
Each end has TWO extension segments. Segment 1 has a direction and can run to
the stock. Segment 2 is a manual nudge - length and angle only, no direction,
since it always continues from where segment 1 finished. Clearance is gone from here - it belongs to the toolpath. The controls
apply to the CURRENT PICKER SELECTION, not the whole imported profile, so
extending a chain that stops mid-part runs from that chain's own end, so the whole geometry pipeline - select, then extend to
stock - is visible in one view. The readout gives the resulting profile start and
end in X diameter, plus how many extension elements were added, and says when a
zero-length extension was dropped.

Errors are shown rather than thrown: walking an open profile the wrong way
reports the problem and suggests ticking `reverse direction`.

## Drawing conventions
Radius space, not diameter. Z increases right, radius up, centreline dashed at
r=0. Blue is unselected, red is selected and extended, grey dashed is stock,
green marks stock open edges.
