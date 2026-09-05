"""
cycles.py - cycle parameter definitions.

Cycles themselves (roughing, facing, grooving, threading) are not built yet.
This holds the parameter block they share, so values like clearance have one
definition rather than being scattered through the post.

CLEARANCE is the value that resolves part 1's final-move mismatch: comp stops
at the profile end, and the cycle adds clearance beyond it. Applied NORMAL to
the surface, so on a diameter it is radial (0.1 radial = 0.2 on diameter), on a
face it is axial, and on an angled surface it is perpendicular to that surface.
"""

from dataclasses import dataclass


@dataclass
class CycleParams:
    clearance: float = 0.1        # normal-to-surface standoff, see note above
    doc: float = 0.05             # depth of cut per roughing pass (radial)
    stock_to_leave_r: float = 0.01   # radial finish allowance
    stock_to_leave_z: float = 0.005  # axial finish allowance
    feed: float = 0.005           # units/rev
    retract: float = 0.1          # retract distance off the cut

    def validate(self):
        problems = []
        if self.doc <= 0:
            problems.append("doc must be positive")
        if self.clearance < 0:
            problems.append("clearance must not be negative")
        if self.stock_to_leave_r < 0 or self.stock_to_leave_z < 0:
            problems.append("stock to leave must not be negative")
        return problems
