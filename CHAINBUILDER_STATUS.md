# Chain builder fix - DONE

## What was wrong
The old build_chain used a greedy nearest-neighbour walk: from the current
point it jumped to the closest unused endpoint and BRIDGED any gap. On the
backface DXF this invented a diagonal line that wasn't in the file, because the
nearest unused endpoint wasn't actually connected to the current one.

## The fix
build_chain now uses true endpoint CONNECTIVITY:
  1. Cluster endpoints within tol into shared nodes.
  2. Treat each entity as an edge between two nodes.
  3. Walk following only real edges - never bridges a gap with no entity across it.
  4. Detect natural chain ends (degree-1 nodes), branches (degree >2), and any
     segments not connected to the main chain - all reported in `problems`.

## Entity-identity hook (added same pass)
Every contour element now carries `source_id` = the index of the DXF entity it
came from. Preserved through reversal and chaining. This is the hook the future
graphical DXF segment-picker (ShopTurn-style selection) will select by.

## Validation - all four parts, default tolerance, no hand-ordering
| part      | elems | chained order | end-to-end comp |
|-----------|-------|---------------|-----------------|
| part 1    | 9     | correct       | matches         |
| part 2    | 7     | correct (incl 3 tiny corner arcs) | matches, flags un-fittable corners |
| bore      | 4     | correct       | EXACT           |
| backface  | 3     | correct (was broken) | EXACT key points |

Backface now runs DXF -> chain -> comp -> X3.0000 Z-0.5886 (reference exact),
with NO manual ordering. The loop is closed.

## Note on tolerance
Use the default tol (1e-3) or tighter for real DXFs. An earlier loose value
(0.05) was coarser than part 2's ~0.01 corner features and merged distinct
endpoints into a false branch - the new builder correctly FLAGS that rather
than silently mis-connecting. Tight tolerance = correct nodes.

## Still pending (unchanged)
- Operation SCOPE: which span of a profile an operation cuts (backface cuts only
  the r1.5 wall + step, not the r2 face). The source_id hook will serve the
  graphical picker; a headless index/layer filter is the near-term version.
- Roughing generator; facing/drilling/grooving/threading cycles; QtVCP UI.
