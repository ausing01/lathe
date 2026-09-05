# Element selection

Runs BEFORE extension and compensation: pick the profile, extend it to the
stock, then compensate.

## Explicit order is the working model
Once a chain is resolved, the ORDER LIST itself is the source of truth. It
carries the cut direction, so reversing the list reverses the cut. The toolpath
will later follow this order, starting at the first element and finishing at the
last, plus whatever extensions are attached.

    assemble(contour, order, disabled=(), tol=1e-4)  ->  (Contour, notes)

| Argument | Meaning |
|---|---|
| `order` | Element indices in cut order. Reversing it reverses the cut. |
| `flip` | Reverse the finished chain end for end. Reversing the `order` list already does this for a multi-element chain, but a ONE-element chain has nothing to reorder, so this is what swaps its start and end points. |
| `disabled` | Indices to leave out. A run of disabled elements is replaced by ONE straight line from the previous kept element's end to the next kept element's start. Disabled elements at either end are simply dropped - nothing to bridge to. |

Elements are oriented automatically so the chain flows: each is flipped if that
makes it meet the previous element's end, and arc directions flip with it. The
FIRST element is oriented by looking ahead at the second, which is what stops a
reversed order leaving element one backwards and inserting a spurious bridge.

Bridge lines are tagged `origin="bridge"`; `is_bridge(element)` tests for them.

## Element origin
`Line` and `Arc` now carry an `origin` field:

| Value | Meaning |
|---|---|
| `None` | a real DXF element |
| `"extension"` | added by `extend_profile` |
| `"bridge"` | added by `assemble` across disabled elements |

`is_extension` and `is_bridge` test this rather than guessing from a missing
`source_id`.

## Auto chain and manual (initial resolution)
`auto_chain(contour, start, end, forward=True)` walks between two elements. On a
CLOSED contour the walk wraps, so both directions are valid routes and `forward`
picks one; on an OPEN contour a walk needing to wrap raises.

`manual(contour, indices)` takes exactly the listed elements without enforcing
continuity.

Both produce an initial order which the client then owns.

## Blend radii at junctions
A blend belongs to the JUNCTION between two elements, not to either element, so
it is keyed on the UNORDERED pair of contour indices:

    assemble(c, order, blends={blend_key(2, 3): 0.05})

Bridges can carry a blend too, at either end. A bridge has no contour index, so
its ends are keyed by the elements it spans:

| Junction | Key | Example |
|---|---|---|
| real i / real j | `blend_key(i, j)` | `(2, 3)` |
| real i / bridge | `"i\|far"` | `"1\|4"` |
| bridge / real j | `"j\|far"` | `"4\|1"` |

`far` is the flanking element at the other end of the bridge, which makes the key
direction-neutral and stable for as long as that bridge exists.

Because the keys are unordered, reversing the chain needs no special handling.
The fillet lands between the same two elements whichever way the cut runs -
`2, blend, 3` forward and `3, blend, 2` reversed - and the arc direction flips
with it. Verify asserts this for both reversal mechanisms.

`make_blend(a, b, radius)` builds the fillet: offset both elements by the radius
(a line becomes two parallel lines, an arc two concentric circles), intersect for
candidate centres, keep the one whose tangent points land on BOTH actual
segments, then trim both neighbours back to those points. This works uniformly
for line/line, line/arc and arc/arc.

A radius too large for the geometry is reported in the notes and not inserted,
rather than producing a mangled chain. Note the limit is usually the SHORT
NEIGHBOUR, not the bridge: on part 1, R0.3 at the bridge entry is refused because
element 1 is only 0.0707 long, while the same radius fits at the exit.

`assemble` exposes `contour.meta`, one entry per element - `("real", i)`,
`("bridge", (a, b))` or `("blend", key)` - so the UI can list the chain in true
cut order rather than reconstructing it.

Blend arcs are tagged `origin="blend"`; `is_blend(element)` tests for them.

## Growing the chain
Clicking an element outside the current chain extends the chain to reach it,
rather than starting over. The new span runs from the lower to the upper index,
keeping the existing direction. Clicking inside the chain just focuses that
element. This is the fix for misclicking the end element.

## Verify covers
Reversal produces a continuous chain with no bridges and swapped ends; skipping
two middle elements inserts exactly one bridge and stays continuous; dropping the
last element inserts none; disabling everything yields an empty chain; `flip`
swaps a single element's ends, and on a multi-element chain agrees with simply
reversing the order list.
