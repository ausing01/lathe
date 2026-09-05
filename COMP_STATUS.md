# comp.py - GREEN. Explicit comp side, winding inference removed.

## The fix
Material side is no longer inferred from contour winding. It is an explicit
G41/G42-style flag, relative to direction of travel:

| `comp_side` | Meaning | G-code equivalent |
|---|---|---|
| `"left"` | tool to the LEFT of travel - boring, tool inside | G41 |
| `"right"` | tool to the RIGHT of travel - turning, tool outside | G42 |
| `"center"` | no offset, follow the geometry exactly | G40 |

On a line running Z0 to Z-1 at X1, left puts the tool at smaller radius (inside
the hole) and right at larger radius (outside the diameter).

Reversing the chain swaps which physical side is cut, exactly as swapping G41
and G42 would. That is deliberate and matches control behaviour.

The offset is baked into the coordinates and the machine stays in G40. Emitting
G41/G42 instead would be a post-processor flag with no geometry consequence,
since the same setting drives both.

## Why the old approach failed
Winding could not distinguish a front face from a back face. Each polarity of
the rule made one group of parts exact and the other wrong by exactly 2 x nose
radius, because the discriminator itself was wrong rather than its sign.

## Validation - all four references
| part | side | result |
|---|---|---|
| part 1 | right | exact; arc radii 0.11875 and 0.13125 |
| part 2 | right | exact on straight moves and arc radii |
| bore | left | EXACT, all points, 0.0000 |
| backface | right | EXACT, all points, 0.0000 |

Arc radii are exactly `0.15 - nose` and `0.10 + nose`. The reference prints
`0.1188` and `0.1312`, which are those same numbers at four decimals.

## Two legitimate differences from the references, not comp errors
1. The reference programs print 4 decimals, so their own quantisation is
   +/-0.00005 in diameter.
2. The references were cut with full DNMG insert geometry (~2 deg face
   clearance), not a pure nose-radius circle. That shifts points ADJACENT TO
   ARCS by up to ~0.00013 in radius, and on part 2 blends the corner into one
   arc where a nose-radius model correctly gives two.

Straight elements away from arcs, and the arc radii themselves, match exactly.
`verify.py` uses REF_TOL = 0.0003 on diameter for CAM comparisons and TOL =
0.0001 for pure geometry, with both figures reported on a pass.

## Relationship to the material region
The stock region (profile + extensions + a walk along the stock boundary) still
has value for roughing extents, retract planes and the simulator. It should
CROSS-CHECK the comp side, not determine it: if the flag says left and the
region says material is on the right, that is worth warning about before cutting.
One mechanism, one source of truth.
