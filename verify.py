#!/usr/bin/env python3
"""
verify.py - one-command health check. Run after every update: python3 verify.py
Exits 0 + "ALL OK" if healthy; non-zero on any failure.

RULE: never commit/push when this is red.

Position tolerance: TOL (default 0.0001). ShopTurn exposes this as a
user-settable value; fixed here for now.
"""
import sys

TOL = 0.0001

def main():
    fails = []
    try:
        from contour import (model, dxf_import, geom2d, comp,
                             post_linuxcnc, scope, stock, cycles, viz, extend, select)
    except Exception as e:
        print("FAIL: module import:", e); return 1

    from contour.geom2d import _selftest
    if not _selftest():
        fails.append("geom2d self-test")

    from contour.dxf_import import import_dxf
    from contour.model import Side
    from contour.comp import compensate
    from contour.scope import OperationScope, Limit, apply_scope

    for f, side, n in [('tests/test_part_1.dxf', Side.OD, 9),
                       ('tests/test_part_2.dxf', Side.OD, 7),
                       ('tests/bore.dxf',        Side.ID, 4),
                       ('tests/backface.dxf',    Side.OD, 3)]:
        try:
            c, probs = import_dxf(f, side=side)
            if len(c.elements) != n:
                fails.append(f"{f}: expected {n} elems, got {len(c.elements)}")
            if probs:
                fails.append(f"{f}: chain problems {probs}")
        except Exception as e:
            fails.append(f"{f}: import raised {e}")

    def check_points(label, elements, ref, skip=()):
        """Compare (Xdia, Z) of each element end against reference."""
        for i, e in enumerate(elements):
            if i in skip or i >= len(ref):
                continue
            mx, mz = 2 * e.end.r, e.end.z
            rx, rz = ref[i]
            if abs(mx - rx) > TOL or abs(mz - rz) > TOL:
                fails.append(f"{label}[{i}]: X{mx:.4f} Z{mz:.4f} "
                             f"vs ref X{rx:.4f} Z{rz:.4f}")

    # PART 1 - OD turn, tip #3, nose 1/32.
    # Element 8 (last) omitted: the CAM reference runs the final move PAST the
    # profile end (operation overtravel), which is a scope/operation parameter,
    # not comp geometry. Comp correctly stops at the profile end.
    c, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    cm, _ = compensate(c, 0.03125, 3)
    check_points("part1", cm.elements,
                 [(1.6372, 0.0), (1.7736, -0.0683), (1.7736, -1.3201),
                  (1.3196, -1.5472), (1.4876, -1.75), (1.9742, -1.75),
                  (2.2014, -1.8156), (4.7236, -4.0), (5.6912, -4.0)],
                 skip=(8,))
    r1 = sorted(round(e.radius, 4) for e in cm.elements if e.kind == 'arc')
    if r1 != [0.1187, 0.1313]:
        fails.append(f"part1 arc radii {r1}, want [0.1187, 0.1313] "
                     f"(ref 0.1188/0.1312)")

    # PART 2 - OD turn with sub-nose corner arcs that must vanish
    c, _ = import_dxf('tests/test_part_2.dxf', side=Side.OD)
    cm, probs = compensate(c, 0.03125, 3)
    r2 = [round(e.radius, 4) for e in cm.elements if e.kind == 'arc']
    if not any(abs(r - 0.0412) <= 0.0002 for r in r2):
        fails.append(f"part2 comp arcs {r2}, want an R~0.0412")
    if not any('tighter than nose' in p for p in probs):
        fails.append("part2: expected an un-fittable-feature warning")

    # BORE - ID, tip #6, nose 0.0886. All four points must be exact.
    c, _ = import_dxf('tests/bore.dxf', side=Side.ID)
    cm, _ = compensate(c, 0.0886, 6)
    check_points("bore", cm.elements,
                 [(1.0, -0.3386), (1.75, -0.3386), (1.75, -1.1614),
                  (0.1772, -1.1614)])

    # BACKFACE - scope span + end extend, tip #8
    c, _ = import_dxf('tests/backface.dxf', side=Side.OD)
    sc = apply_scope(c, OperationScope(start_index=1, end_index=2,
                                       end_limit=Limit('z', -2.1659)))
    cm, _ = compensate(sc, 0.0886, 8)
    check_points("backface", cm.elements,
                 [(3.0, -0.5886), (3.0, -2.1659)])

    # STOCK - parametric, DXF, open-edge marking, closed-loop chaining
    from contour.stock import parametric, from_dxf, open_edges_by_source_id
    st = parametric(od=3.0, z_face=0.1, z_back=-3.0)
    if not st.contour.closed or len(st.contour.elements) != 4:
        fails.append("stock parametric: expected 4-element closed contour")
    if abs(st.od - 1.5) > TOL or abs(st.face_z - 0.1) > TOL:
        fails.append(f"stock parametric: od {st.od} face_z {st.face_z}")
    if st.open_edges != {0, 1}:
        fails.append(f"stock parametric open_edges {st.open_edges}, want {{0,1}}")
    tu = parametric(od=3.0, z_face=0.0, z_back=-2.0, id_bore=1.0)
    if 3 not in tu.open_edges:
        fails.append("tube stock: bore should be an open edge")
    sd, sp = from_dxf('tests/stock_closed.dxf')
    if sp:
        fails.append(f"stock_closed.dxf problems: {sp}")
    if not sd.contour.closed:
        fails.append("stock_closed.dxf: closed loop not detected")
    if open_edges_by_source_id(sd, {0, 1}) != {0, 1}:
        fails.append("open_edges_by_source_id did not resolve correctly")

    from contour.cycles import CycleParams
    if CycleParams().validate():
        fails.append("CycleParams defaults fail validation")

    # EXTEND - ray-cast to stock, fixed length, angle, error cases
    from contour.extend import Extension, extend_profile, is_extension
    cp, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    sk = parametric(od=5.5, z_face=0.15, z_back=-4.2)
    # profile end sits exactly on stock OD: distance 0, clearance carries it out
    # stock OD 5.5 puts the profile end ON the boundary, so a run-to-stock
    # segment is zero length and drops; a second segment carries it out
    ex = extend_profile(cp, sk, end=[Extension('+X'), Extension('+X', length=0.1)])
    if abs(ex.elements[-1].end.r - 2.85) > TOL:
        fails.append(f"extend +X two segments: r {ex.elements[-1].end.r:.4f}, want 2.85")
    if not is_extension(ex.elements[-1]):
        fails.append("extension element should have source_id None")
    # fixed length reproduces the CAM reference exactly
    ex = extend_profile(cp, None, end=Extension('+X', length=0.0956))
    if abs(2 * ex.elements[-1].end.r - 5.6912) > TOL:
        fails.append(f"extend fixed length: X {2*ex.elements[-1].end.r:.4f}, want 5.6912")
    # angle override
    ex = extend_profile(cp, None, end=Extension(angle=30.0, length=0.25))
    if abs(ex.elements[-1].end.z - (-3.7835)) > 0.001:
        fails.append("extend angle override wrong")
    # no stock and no length must raise
    try:
        extend_profile(cp, None, end=Extension('+X'))
        fails.append("extend: expected ValueError with no stock and no length")
    except ValueError:
        pass

    # SELECT - auto chain, direction, closed wrap, manual, error cases
    from contour.select import (auto_chain, manual, check_selection,
                                chain_indices)
    cs, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    sel = auto_chain(cs, 2, 5)
    if [e.source_id for e in sel.elements] != [4, 5, 0, 6]:
        fails.append("auto_chain 2->5 wrong source ids")
    if check_selection(sel):
        fails.append("auto_chain 2->5 should be a clean chain")
    if check_selection(auto_chain(cs, 5, 2, forward=False)):
        fails.append("auto_chain 5->2 backward should be a clean chain")
    try:
        auto_chain(cs, 5, 2)
        fails.append("auto_chain forward on open profile should raise")
    except ValueError:
        pass
    if check_selection(manual(cs, {0, 1, 2})):
        fails.append("manual {0,1,2} should be a clean chain")
    if not check_selection(manual(cs, {0, 5})):
        fails.append("manual {0,5} is disjoint and should report a problem")
    # assemble: explicit order carries direction; unchecked elements bridge
    from contour.select import assemble, is_bridge
    order = list(range(len(cs.elements)))
    a_fwd, _ = assemble(cs, order)
    a_rev, _ = assemble(cs, list(reversed(order)))
    if a_fwd.check_continuity(1e-4) or a_rev.check_continuity(1e-4):
        fails.append("assemble produced a discontinuous chain")
    if any(is_bridge(e) for e in a_rev.elements):
        fails.append("reversing the order should not need bridge lines")
    if (abs(a_fwd.elements[0].start.z - a_rev.elements[-1].end.z) > TOL or
            abs(a_fwd.elements[-1].end.z - a_rev.elements[0].start.z) > TOL):
        fails.append("reversed chain should swap start and end")
    a_skip, notes = assemble(cs, order, [2, 3])
    nb = sum(1 for e in a_skip.elements if is_bridge(e))
    if nb != 1:
        fails.append(f"skipping 2,3 should insert exactly one bridge, got {nb}")
    if a_skip.check_continuity(1e-4):
        fails.append("bridged chain should still be continuous")
    if len(a_skip.elements) != len(order) - 2 + 1:
        fails.append("bridged chain element count wrong")
    # dropping an END element needs no bridge
    a_end, _ = assemble(cs, order, [len(order) - 1])
    if any(is_bridge(e) for e in a_end.elements):
        fails.append("dropping the last element should not bridge")
    a_none, n_none = assemble(cs, order, order)
    if a_none.elements:
        fails.append("assemble with everything disabled should be empty")

    # blends are keyed on the UNORDERED junction pair, so reversing the chain
    # puts the fillet between the same two elements with no special handling
    from contour.select import make_blend, is_blend, blend_key
    bl = {blend_key(2, 3): 0.05}
    b_fwd, _ = assemble(cs, order, blends=bl)
    b_rev, _ = assemble(cs, list(reversed(order)), blends=bl)
    b_flip, _ = assemble(cs, order, blends=bl, flip=True)
    for label, ch in (("forward", b_fwd), ("reversed", b_rev), ("flip", b_flip)):
        arcs = [e for e in ch.elements if is_blend(e)]
        if len(arcs) != 1:
            fails.append(f"blend {label}: expected one fillet, got {len(arcs)}")
        elif abs(arcs[0].radius - 0.05) > TOL:
            fails.append(f"blend {label}: radius {arcs[0].radius:.4f}, want 0.05")
        if ch.check_continuity(1e-4):
            fails.append(f"blend {label}: chain not continuous after filleting")
    # the fillet must sit between the same two real elements either way
    def _around(ch):
        p = [i for i, e in enumerate(ch.elements) if is_blend(e)][0]
        return (ch.elements[p - 1].source_id, ch.elements[p + 1].source_id)
    if set(_around(b_fwd)) != set(_around(b_rev)):
        fails.append("blend sits between different elements when reversed")
    # bridges can carry a blend at either end, keyed "touching|far"
    for key, where in (("1|4", "entry"), ("4|1", "exit")):
        bb, _ = assemble(cs, order, [2, 3], blends={key: 0.05})
        arcs = [e for e in bb.elements if is_blend(e)]
        if len(arcs) != 1:
            fails.append(f"bridge blend {where}: expected one fillet, "
                         f"got {len(arcs)}")
        if bb.check_continuity(1e-4):
            fails.append(f"bridge blend {where}: chain not continuous")
    both, _ = assemble(cs, order, [2, 3], blends={"1|4": 0.04, "4|1": 0.04})
    if sum(1 for e in both.elements if is_blend(e)) != 2:
        fails.append("a bridge should take a blend at both ends")
    if both.check_continuity(1e-4):
        fails.append("bridge blended both ends: chain not continuous")
    # a refused blend reports the largest radius that WOULD fit, and that
    # radius must actually be at the boundary
    from contour.select import max_blend_radius
    fail_ch, fail_notes = assemble(cs, order, blends={blend_key(2, 3): 1.0})
    errs = getattr(fail_ch, "blend_errors", {})
    if blend_key(2, 3) not in errs:
        fails.append("a refused blend should record an error entry")
    else:
        mx = errs[blend_key(2, 3)]["max"]
        if make_blend(cs.elements[2], cs.elements[3], mx * 0.99) is None:
            fails.append("reported max blend radius does not actually fit")
        if make_blend(cs.elements[2], cs.elements[3], mx * 1.05) is not None:
            fails.append("radius above the reported max still fits")
    if any(is_blend(e) for e in fail_ch.elements):
        fails.append("a refused blend must not appear in the chain")
    # a fitting blend records no error
    ok_ch, _ = assemble(cs, order, blends={blend_key(2, 3): 0.5})
    if getattr(ok_ch, "blend_errors", {}):
        fails.append("a fitting blend should record no error")

    # a radius too large for the short neighbour is reported, not forced
    big_b, bn = assemble(cs, order, [2, 3], blends={"1|4": 0.3})
    if not any("does not fit" in n for n in bn):
        fails.append("an unfittable bridge blend should be reported")
    if big_b.check_continuity(1e-4):
        fails.append("chain should stay continuous when a blend is refused")
    # assembly metadata drives the row ordering, so it must be present
    m = getattr(both, "meta", None)
    if not m or len(m) != len(both.elements):
        fails.append("assemble should expose one meta entry per element")

    # an oversized radius must be reported, not silently mangled
    big, bnotes = assemble(cs, order, blends={blend_key(2, 3): 5.0})
    if any(is_blend(e) for e in big.elements):
        fails.append("an unfittable blend should not be inserted")
    if not any("does not fit" in n for n in bnotes):
        fails.append("an unfittable blend should be reported")

    # flip: a ONE-element chain has nothing to reorder, so the flip flag is
    # what swaps its start and end points
    one_f, _ = assemble(cs, [4], flip=False)
    one_r, _ = assemble(cs, [4], flip=True)
    if (abs(one_f.elements[0].start.z - one_r.elements[-1].end.z) > TOL or
            abs(one_f.elements[-1].end.z - one_r.elements[0].start.z) > TOL):
        fails.append("flip should swap a single element's start and end")
    if abs(one_f.elements[0].start.z - one_r.elements[0].start.z) < TOL:
        fails.append("flip on a single element did nothing")
    # flip on a multi-element chain matches reversing the order list
    m_flip, _ = assemble(cs, [2, 3, 4], flip=True)
    m_rev, _ = assemble(cs, [4, 3, 2], flip=False)
    if (abs(m_flip.elements[0].start.z - m_rev.elements[0].start.z) > TOL or
            abs(m_flip.elements[-1].end.z - m_rev.elements[-1].end.z) > TOL):
        fails.append("flip and reversed order should agree on a multi chain")
    if m_flip.check_continuity(1e-4):
        fails.append("flipped chain should stay continuous")

    cc, _ = import_dxf('tests/stock_closed.dxf', side=Side.OD)
    if chain_indices(cc, 0, 2, True) != [0, 1, 2]:
        fails.append("closed forward route wrong")
    if chain_indices(cc, 0, 2, False) != [0, 3, 2]:
        fails.append("closed backward route wrong")

    # EXTEND - zero-length extension must be dropped, not added degenerate
    sk55 = parametric(od=5.5, z_face=0.15, z_back=-4.2)
    base = import_dxf('tests/test_part_1.dxf', side=Side.OD)[0]
    z0 = extend_profile(base, sk55, end=Extension('+X'))
    if len(z0.elements) != len(base.elements):
        fails.append("zero-length extension should be dropped")
    z1 = extend_profile(base, sk55, end=Extension('+X', length=0.1))
    if len(z1.elements) != len(base.elements) + 1:
        fails.append("non-zero extension should be added")
    # a chain of two segments, each with its own angle
    sk60 = parametric(od=6.0, z_face=0.2, z_back=-4.3)
    z2 = extend_profile(base, sk60,
                        end=[Extension('+X'), Extension(angle=45.0, length=0.2)])
    if len(z2.elements) != len(base.elements) + 2:
        fails.append("two-segment extension should add two elements")
    seg2 = z2.elements[-1]
    if abs(seg2.start.r - 3.0) > TOL:
        fails.append("second segment should start where the first ended")
    # Extension must no longer take clearance - that lives in CycleParams
    try:
        Extension('+X', clearance=0.1)
        fails.append("Extension should not accept clearance any more")
    except TypeError:
        pass

    # every element carries an origin, and properties expose it, so the UI can
    # list extensions and bridges alongside real DXF elements
    from contour.model import element_properties as _ep
    from contour.select import assemble as _asm, is_bridge as _isb
    _o = list(range(len(base.elements)))
    _br, _ = _asm(base, _o, [2, 3])
    _bridges = [e for e in _br.elements if _isb(e)]
    if len(_bridges) != 1:
        fails.append("expected one bridge element to inspect")
    else:
        pb = _ep(_bridges[0], 0)
        if pb.get("origin") != "bridge":
            fails.append(f"bridge origin is {pb.get('origin')!r}, want 'bridge'")
        if pb["source_id"] is not None:
            fails.append("bridge should carry no source_id")
    _ex = extend_profile(base, sk60,
                         end=[Extension('+X'), Extension(angle=45.0, length=0.2)])
    pe = _ep(_ex.elements[-1], 0)
    if pe.get("origin") != "extension":
        fails.append(f"extension origin is {pe.get('origin')!r}, want 'extension'")
    pr_real = _ep(base.elements[0], 0)
    if pr_real.get("origin") is not None:
        fails.append("a real DXF element should have origin None")

    # extensions accept blends at their junctions, keyed s1/s2 and e1/e2
    from contour.extend import blend_extensions, extension_junctions
    ex_b = extend_profile(base, sk60,
                          start=[Extension('+Z')],
                          end=[Extension('+X'), Extension(angle=45.0, length=0.2)])
    jm = extension_junctions(ex_b)
    for k in ("s1", "e1", "e2"):
        if k not in jm:
            fails.append(f"extension junction {k} not found")
    b1, n1 = blend_extensions(ex_b, {"s1": 0.02})
    if sum(1 for e in b1.elements if is_blend(e)) != 1:
        fails.append("extension blend s1 not inserted")
    if b1.check_continuity(1e-4):
        fails.append("extension blend s1 broke continuity")
    b2, n2 = blend_extensions(ex_b, {"s1": 0.02, "e2": 0.03})
    if sum(1 for e in b2.elements if is_blend(e)) != 2:
        fails.append("two extension blends should both insert")
    if b2.check_continuity(1e-4):
        fails.append("two extension blends broke continuity")
    b3, n3 = blend_extensions(ex_b, {"s1": 99.0})
    if any(is_blend(e) for e in b3.elements):
        fails.append("an unfittable extension blend should not be inserted")
    if not any("does not fit" in n for n in n3):
        fails.append("an unfittable extension blend should be reported")

    # element properties: angles read off the spindle axis
    from contour.model import element_properties
    pr = element_properties(base.elements[1], 1)      # the 45 deg chamfer
    if abs(pr['angle_from_axis'] - 45.0) > 0.01:
        fails.append(f"chamfer angle_from_axis {pr['angle_from_axis']:.2f}, want 45")
    pr = element_properties(base.elements[2], 2)      # straight diameter
    if abs(pr['angle_from_axis']) > 0.01:
        fails.append("straight diameter should read 0 deg off axis")
    pr = element_properties(base.elements[0], 0)      # face
    if abs(pr['angle_from_axis'] - 90.0) > 0.01:
        fails.append("face should read 90 deg off axis")
    pr = element_properties(base.elements[4], 4)      # arc
    for k in ('radius', 'center_z', 'center_x', 'direction', 'sweep', 'length'):
        if k not in pr:
            fails.append(f"arc properties missing {k}")

    # VIZ - SVG renders, and arc direction is sampled correctly
    from contour.viz import render, render_pickable, _arc_points
    import math as _m
    ca, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    for e in ca.elements:
        if e.kind != 'arc':
            continue
        pts = _arc_points(e)
        if abs(pts[0][0] - e.start.z) > 1e-9 or abs(pts[0][1] - e.start.r) > 1e-9:
            fails.append("arc sampling start point wrong")
        if abs(pts[-1][0] - e.end.z) > 1e-9 or abs(pts[-1][1] - e.end.r) > 1e-9:
            fails.append("arc sampling end point wrong")
        mid = pts[len(pts) // 2]
        d = _m.hypot(mid[0] - e.center.z, mid[1] - e.center.r)
        if abs(d - e.radius) > 1e-9:
            fails.append(f"arc sample off radius by {abs(d-e.radius):.2e}")
    pk = render_pickable(ca, selected={2, 3}, stock=st)
    if pk.count('class="hit"') != len(ca.elements):
        fails.append("render_pickable: one hit path per element expected")
    if 'data-idx="0"' not in pk:
        fails.append("render_pickable: missing data-idx attributes")

    # Direction markers: green at the START of the first element (the chain's
    # entry point), red at the END of the last. The two routes round a closed
    # profile share an entry point, so it is the RED dot that distinguishes them.
    sel_f = auto_chain(cc, 0, 2, forward=True)
    sel_b = auto_chain(cc, 0, 2, forward=False)
    gf = (sel_f.elements[0].start.z, sel_f.elements[0].start.r)
    rf = (sel_f.elements[-1].end.z, sel_f.elements[-1].end.r)
    rb = (sel_b.elements[-1].end.z, sel_b.elements[-1].end.r)
    if abs(rf[0] - rb[0]) < TOL and abs(rf[1] - rb[1]) < TOL:
        fails.append("forward and reverse routes end at the same point - "
                     "red dot must distinguish the two routes")
    # a single-element selection is both first and last: dots at opposite ends
    one = manual(cs, [4])
    g1 = (one.elements[0].start.z, one.elements[0].start.r)
    r1 = (one.elements[-1].end.z, one.elements[-1].end.r)
    if abs(g1[0] - r1[0]) < TOL and abs(g1[1] - r1[1]) < TOL:
        fails.append("single-element selection: green and red dots coincide")
    dotted = render_pickable(cc, selected={0, 1, 2},
                             start_dot=gf,
                             end_dot=(sel_f.elements[-1].end.z,
                                      sel_f.elements[-1].end.r))
    if dotted.count("<circle") != 2:
        fails.append("render_pickable: expected two direction dots")
    if "#12a012" not in dotted or "#d01818" not in dotted:
        fails.append("render_pickable: green/red direction dots missing")
    svg = render([("profile", ca, "p")], stock=st)
    if not svg.startswith("<svg") or "<path" not in svg:
        fails.append("viz.render did not produce an SVG with geometry")

    if fails:
        print("\nFAILURES:")
        for f in fails: print("  -", f)
        return 1
    print(f"\nALL OK (position tolerance {TOL})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
