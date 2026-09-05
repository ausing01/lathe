# session.py - editing state in Python

## Why
The geometry modules were always UI-agnostic, but the editing state - chain
order, disabled elements, blends, extensions, stock, boundary clicks - lived in
the browser. That was the part a Qt port would have had to rewrite.

It now lives in `contour/session.py`. The UI is a thin view: it holds nothing
but what is being typed at that moment.

| | before | after |
|---|---|---|
| `serve.py` | 1210 lines | 431 lines |
| JavaScript state logic | 283 lines | none - event forwarding only |
| testable without a display | backend only | everything |

A Qt window replaces `serve.py` and nothing else.

## Shape
State is a plain description of CHOICES - element indices, click points,
parameter values - never derived geometry. `view()` recomputes from them each
time, so reload and replay fall out for free.

    s = Session()
    s.select_all()
    s.click_element(4)
    s.set_blend("2-3", 0.05)
    s.click_stock((0.2, 1.5))
    v = s.view()          # svg, rows, walk_rows, props, info, blend_errors

`verify.py` drives all of this headlessly: chain building by clicks, reverse,
trim, unchecking and bridging, blends and their errors, extensions and cut-end
triangles, the accumulating stock walk, and malformed focus keys.

## Blend keys
The UI sends junction keys as strings. `normalise_blend_key` converts real
junctions ("2-3") to the tuple form `assemble` looks up, and leaves bridge
("1|4") and extension ("s1") keys as strings. Missing this conversion during
the move silently dropped every blend.

## Defect found and fixed during the move: full-circle blends
At a TANGENT junction - an arc meeting a line smoothly, as at part 1's
elements 4/5 - there is no corner to fillet. Every radius is "tangent to both"
at the existing point, so `make_blend` returned an arc from that point back to
itself: a FULL 360 DEGREE CIRCLE, with neither neighbour trimmed. That would
have gone straight into a toolpath.

Two guards added:
- tangent points coincident with the junction, or with each other, mean no
  corner: refused
- a corner fillet always sweeps less than half a turn; anything at or beyond
  180 degrees means the solver took a centre on the wrong side: refused

`max_blend_radius` now reports 0 at a tangent junction, which is correct. It was
previously non-monotonic there - bisection measuring nonsense - which is what
exposed the problem. Real corners are unaffected: junction 2/3 still reports
0.7440, matching the analytic value.
