# rough.py - first roughing pass generator

Deliberately simple: axial passes at constant radius, stepping in by depth of
cut, each running until it meets the finish profile plus the stock allowance.
That is the classic G71 shape, and worth getting right before anything cleverer.

## API
    rough(profile, stock, doc, stock_to_leave_r, stock_to_leave_z,
          clearance, retract, min_cut=None, comp_side=None)
      -> (moves, notes)

`moves` are `Move(kind, z, r)` with kind "rapid" or "feed", ready for
`post_linuxcnc.post_rough()`.

## Exact, not sampled
`profile_z_crossings(profile, level)` solves where the profile crosses a radius
by intersecting a horizontal line with each element - lines parametrically, arcs
via circle intersection. An earlier sampled version carried resolution error.
Verified against a hand-computed taper crossing to four decimals.

## Comp side is derived where it can be
`infer_comp_side` compares where material actually is: stock beyond the
profile's largest radius means OD, a stock bore inside the smallest radius means
ID, larger wins.

It is NOT a comparison of the two gaps. On solid bar both minima are zero, so an
ID measure of zero would flip an undersized stock to ID, which is nonsense.

**It is not always decidable.** `comp_side_ambiguous()` reports the case: a
PARTIAL selection on hollow stock - just the bore wall of a tube - has material
both outside and inside, so boring and OD turning are equally consistent with
the geometry. The operator must choose. `rough()` notes this and takes an
explicit `comp_side` override. A profile spanning the whole part is unambiguous.

## Safety
The approach plane clears the STOCK, not the part. The stock face sits proud of
the finished face, so clearing only the part put every radial rapid between
passes inside uncut material. `verify.py` guards this, and also checks that no
pass cuts past the profile at its own radius.

## Warnings
- stock smaller than the profile: the part will not clean up
- passes that stop at the face: facing stock being taken axially, which a
  facing cycle would do properly
- `min_cut` skips passes shorter than a given length and reports the count

## Not handled yet, by design
- undercuts and re-entrant profiles - a scanline cannot see behind an overhang
- plunge and face roughing
- varying depth of cut
- the adaptive stock-to-finish morph discussed earlier
