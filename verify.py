#!/usr/bin/env python3
"""
verify.py - one-command health check. Run after every update: python3 verify.py
Exits 0 + "ALL OK" if healthy; non-zero on any failure.

RULE: never commit/push when this is red.

Position tolerance: TOL (default 0.0001). ShopTurn exposes this as a
user-settable value; fixed here for now.
"""
import sys

TOL = 0.0001          # geometry tolerance (radius space)

# Position tolerance when comparing against a CAM reference, in DIAMETER.
# Two sources of legitimate difference, neither of them comp errors:
#   1. the reference program prints 4 decimals, so its own quantisation is
#      +/-0.00005 in diameter
#   2. the references were cut with full DNMG insert geometry (~2 deg face
#      clearance), not a pure nose-radius circle, which shifts points adjacent
#      to arcs by up to ~0.00013 in radius
# Straight elements away from arcs, and the arc radii themselves, match exactly.
REF_TOL = 0.0003

def main():
    fails = []
    try:
        from contour import (model, dxf_import, geom2d, comp,
                             post_linuxcnc, scope, stock, cycles, viz, extend, select,
                             rough)
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
            if abs(mx - rx) > REF_TOL or abs(mz - rz) > REF_TOL:
                fails.append(f"{label}[{i}]: X{mx:.4f} Z{mz:.4f} "
                             f"vs ref X{rx:.4f} Z{rz:.4f}")

    # PART 1 - OD turn, tip #3, nose 1/32, comp side RIGHT (turning).
    # Element 8 (last) omitted: the CAM reference runs the final move PAST the
    # profile end (operation overtravel), which is a scope/operation parameter,
    # not comp geometry. Comp correctly stops at the profile end.
    from contour.comp import COMP_LEFT, COMP_RIGHT, COMP_CENTER
    c, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    cm, _ = compensate(c, 0.03125, 3, comp_side=COMP_RIGHT)
    check_points("part1", cm.elements,
                 [(1.6372, 0.0), (1.7736, -0.0683), (1.7736, -1.3201),
                  (1.3196, -1.5472), (1.4876, -1.75), (1.9742, -1.75),
                  (2.2014, -1.8156), (4.7236, -4.0), (5.6912, -4.0)],
                 skip=(8,))
    # Arc radii are EXACT: 0.15 - nose and 0.10 + nose. The reference prints
    # 0.1188 / 0.1312, which is these same numbers at 4 decimals.
    r1 = sorted(round(e.radius, 6) for e in cm.elements if e.kind == 'arc')
    if r1 != [0.11875, 0.13125]:
        fails.append(f"part1 arc radii {r1}, want [0.11875, 0.13125] "
                     f"(= 0.15-nose and 0.10+nose)")

    # PART 2 - OD turn, comp side RIGHT. Two deviations from the CAM reference
    # are EXPECTED and not comp errors:
    #   elements 3-4: the reference was cut with full DNMG insert geometry, so
    #     it blends the corner into one arc. A nose-radius model correctly
    #     produces two R0.0412 arcs there.
    #   element 5: operation overtravel past the profile end, as on part 1.
    c, _ = import_dxf('tests/test_part_2.dxf', side=Side.OD)
    cm, probs = compensate(c, 0.03125, 3, comp_side=COMP_RIGHT)
    check_points("part2", cm.elements,
                 [(0.8634, 0.0), (1.0, -0.0683), (1.0, -0.9977),
                  (0.9998, -1.0), (1.0046, -1.0), (2.1912, -1.0)],
                 skip=(3, 5))
    r2 = [round(e.radius, 4) for e in cm.elements if e.kind == 'arc']
    if not any(abs(r - 0.0412) <= 0.0002 for r in r2):
        fails.append(f"part2 comp arcs {r2}, want an R~0.0412")
    if not any('tighter than nose' in p for p in probs):
        fails.append("part2: expected an un-fittable-feature warning")

    # BORE - ID, tip #6, nose 0.0886. All four points must be exact.
    # BORE - ID, tip #6, comp side LEFT (tool inside the hole)
    c, _ = import_dxf('tests/bore.dxf', side=Side.ID)
    cm, _ = compensate(c, 0.0886, 6, comp_side=COMP_LEFT)
    check_points("bore", cm.elements,
                 [(1.0, -0.3386), (1.75, -0.3386), (1.75, -1.1614),
                  (0.1772, -1.1614)])

    # BACKFACE - scope span + end extend, tip #8
    c, _ = import_dxf('tests/backface.dxf', side=Side.OD)
    sc = apply_scope(c, OperationScope(start_index=1, end_index=2,
                                       end_limit=Limit('z', -2.1659)))
    cm, _ = compensate(sc, 0.0886, 8, comp_side=COMP_RIGHT)
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

    # comp side is explicit and travel-relative: "center" applies no offset,
    # and reversing the chain swaps which physical side is cut
    cc0, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    cen, _ = compensate(cc0, 0.03125, 3, comp_side=COMP_CENTER)
    for a, b in zip(cen.elements, cc0.elements):
        if abs(a.end.z - b.end.z) > TOL or abs(a.end.r - b.end.r) > TOL:
            fails.append("comp_side=center must not move the geometry")
            break
    from contour.select import assemble as _as2
    fwd = _as2(cc0, list(range(len(cc0.elements))))[0]
    rev = _as2(cc0, list(range(len(cc0.elements))), flip=True)[0]
    cf, _ = compensate(fwd, 0.03125, 3, comp_side=COMP_RIGHT)
    cr, _ = compensate(rev, 0.03125, 3, comp_side=COMP_RIGHT)
    # Same physical geometry, opposite travel. On the straight diameter the
    # tool must land on opposite sides, i.e. 2 x nose apart.
    def _dia_radius(ch):
        for e in ch.elements:
            if (e.kind == "line" and abs(e.start.r - e.end.r) < 1e-9
                    and abs(e.start.z - e.end.z) > 0.5):
                return e.start.r
        return None
    rf, rr = _dia_radius(cf), _dia_radius(cr)
    if rf is None or rr is None:
        fails.append("could not find the straight diameter to test reversal")
    elif abs(abs(rf - rr) - 2 * 0.03125) > 0.001:
        fails.append(f"reversing should flip the cut side by 2x nose; "
                     f"got {abs(rf - rr):.5f}, want {2*0.03125:.5f}")
    try:
        compensate(cc0, 0.03125, 3, comp_side="sideways")
        fails.append("an unknown comp_side should raise")
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

    # ROUGHING
    from contour.rough import (rough, profile_z_crossings, infer_comp_side,
                               profile_radius_at)
    from contour.select import assemble as _as3
    rc, _ = import_dxf('tests/test_part_1.dxf', side=Side.OD)
    rsel, _ = _as3(rc, list(range(len(rc.elements))))
    rst = parametric(od=6.0, z_face=0.2, z_back=-4.3)

    # comp side is derived, not told
    if infer_comp_side(rsel, rst) != COMP_RIGHT:
        fails.append("OD roughing should infer comp side right")

    # crossings are solved exactly - check against the taper by hand
    lvl = 2.24
    xs = profile_z_crossings(rsel, lvl)
    z_hand = -1.8 + (lvl - 1.1048) / (2.375 - 1.1048) * (-2.2)
    if not xs or abs(max(xs) - z_hand) > 0.0005:
        fails.append(f"profile_z_crossings at r{lvl}: {xs}, want ~{z_hand:.4f}")

    mv, rnotes = rough(rsel, rst, doc=0.5, min_cut=0.5)
    if not mv:
        fails.append("roughing produced no moves")
    else:
        # SAFETY: every rapid must clear the stock face, or a radial move
        # between passes drives through uncut material
        z_face = rst.z_range()[1]
        for m in mv:
            if m.kind == "rapid" and m.z <= z_face + 1e-9 and \
                    abs(m.z - mv[1].z) > 1e-9:
                pass
        if mv[0].z <= z_face:
            fails.append(f"roughing approach z{mv[0].z:.4f} is inside the "
                         f"stock (face at z{z_face:.4f})")
        # passes must step monotonically inward and stop at the profile
        levels = [mv[i].r for i in range(0, len(mv), 4)]
        if levels != sorted(levels, reverse=True):
            fails.append("OD roughing levels should step inward")
        for i in range(0, len(mv), 4):
            lvl_i = mv[i].r
            zs = mv[i + 1].z
            pr = profile_radius_at(rsel, zs, default=0.0)
            if pr - 1e-6 > lvl_i:
                fails.append(f"roughing pass at r{lvl_i:.4f} cuts past the "
                             f"profile (r{pr:.4f} at z{zs:.4f})")

    # ambiguity is reported, not silently guessed: a partial selection on tube
    # stock has material both inside and outside
    from contour.rough import comp_side_ambiguous
    cbo, _ = import_dxf('tests/bore.dxf', side=Side.ID)
    bwall, _ = _as3(cbo, [0, 1, 2])
    tube = parametric(od=3.0, id_bore=0.6, z_face=0.1, z_back=-1.5)
    if not comp_side_ambiguous(bwall, tube):
        fails.append("bore wall in tube stock should be an ambiguous side")
    _m, nb = rough(bwall, tube, doc=0.1)
    if not any("ambiguous" in x for x in nb):
        fails.append("an ambiguous side should be reported")
    mL, nL = rough(bwall, tube, doc=0.1, comp_side=COMP_LEFT)
    if not mL or "ID" not in nL[0]:
        fails.append("explicit comp_side=left should give ID roughing")
    # a full-part profile is NOT ambiguous
    if comp_side_ambiguous(rsel, rst):
        fails.append("a full-part profile on solid bar should be unambiguous")

    # stock that does not enclose the part must warn - the part cannot clean up
    small = parametric(od=2 * (rsel.r_range()[1] - 0.5), z_face=0.2, z_back=-4.3)
    _mv3, n3 = rough(rsel, small, doc=0.5)
    if not any("will not clean up" in x for x in n3):
        fails.append("undersized stock should warn that the part will not "
                     "clean up")
    # degenerate: stock entirely inside the profile yields no passes
    tiny = parametric(od=0.005, z_face=0.2, z_back=-4.3)
    mv2, _n2 = rough(rsel, tiny, doc=0.5)
    if mv2:
        fails.append("stock with nothing to remove should yield no passes")

    # STOCK BOUNDARY WALK - one click sets start and direction, and the walk
    # stops at the next profile/stock intersection
    from contour.region import (stock_click, profile_stock_intersections,
                                loop_position)
    from contour.extend import Extension as _Ext, extend_profile as _extp
    rex = _extp(rsel, rst, start=[_Ext('+Z')], end=[_Ext('+X')])
    ints = profile_stock_intersections(rex, rst)
    if len(ints) < 2:
        fails.append(f"expected at least two profile/stock intersections, "
                     f"got {ints}")

    # clicking up the face walks the face then the OD, trimmed to the extension
    w1, end1, n1 = stock_click(rst, rex, (0.2, 1.5))
    if len(w1) != 2:
        fails.append(f"face-side click should walk 2 elements, got {len(w1)}")
    else:
        import math as _m
        L = [_m.hypot(e.end.z - e.start.z, e.end.r - e.start.r) for e in w1]
        if abs(L[0] - 3.0) > 0.001:
            fails.append(f"first walk element length {L[0]:.4f}, want 3.0")
        # the OD element is 4.5 long but must be TRIMMED at the extension
        if abs(L[1] - 4.2) > 0.001:
            fails.append(f"walk should trim the OD to 4.2, got {L[1]:.4f}")
        if any(getattr(e, "origin", None) != "stock" for e in w1):
            fails.append("walk elements should be tagged origin='stock'")

    # the other side gives a different route
    w2, _e2, _n2 = stock_click(rst, rex, (-2.0, 0.0))
    if not w2 or abs(w2[0].end.z - w1[0].end.z) < 1e-9:
        fails.append("clicking the other side should take a different route")

    # clicking again continues from where it stopped
    w3, end3, _n3 = stock_click(rst, rex, (-4.3, 1.5), chain_end_s=end1)
    if not w3:
        fails.append("a second click should continue the walk")
    elif abs(w3[0].start.z - w1[-1].end.z) > 1e-6 or \
            abs(w3[0].start.r - w1[-1].end.r) > 1e-6:
        fails.append("the continued walk should start where the first ended")
    if end3 is None or abs(end3 - end1) < 1e-9:
        fails.append("the continued walk should end somewhere new")

    # A profile that never reaches the stock has no region. Note a solid bar
    # will not do here: its bottom edge IS the centreline, which the profile
    # touches. A tube whose bore clears the part touches nothing.
    tube_far = parametric(od=40.0, id_bore=10.0, z_face=9.0, z_back=-9.0)
    if profile_stock_intersections(rsel, tube_far):
        fails.append("profile should not meet stock it lies entirely inside")
    _w4, _e4, n4 = stock_click(tube_far, rsel, (0.0, 20.0))
    if not any("does not meet the stock" in x for x in n4):
        fails.append(f"a profile that misses the stock should report it, "
                     f"got {n4}")

    if fails:
        print("\nFAILURES:")
        for f in fails: print("  -", f)
        return 1
    print(f"\nALL OK  (geometry {TOL}, CAM reference {REF_TOL})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
