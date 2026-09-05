"""
Contour -> LinuxCNC finish-turn G-code.

This is the ONLY place radius becomes diameter. The contour is in radius;
the machine (in G7 diameter mode) wants diameter, so X = 2*r everywhere.

The post is deliberately explicit long-hand G-code - no O-word subs, no
canned cycles - so the output reads exactly like the hand-written Fanuc
reference and can be diffed against it.

Machine config is passed in as a PostConfig so nothing is hardcoded; this is
the "configurable from day one" requirement for later distribution.
"""

from dataclasses import dataclass, field
from .model import ArcDir, Side


@dataclass
class PostConfig:
    units: str = "inch"          # "inch" -> G20, "mm" -> G21
    diameter_mode: bool = True    # G7 diameter (True) vs G8 radius (False)
    css: bool = True              # G96 constant surface speed vs G97 rpm
    surface_speed: float = 1492   # SFM (or m/min in metric) for G96
    css_max_rpm: float = 1000     # clamp for G96 (the old Fanuc G50 value)
    feed_per_rev: float = 0.005   # finish feedrate, units/rev (G95)
    rpm: float = 1200             # used only when css is False (G97)
    coolant: bool = True
    tool: int = 1                 # tool number; offset assumed = tool number
    safe_z: float = 0.15          # rapid clearance in front of the face
    retract_r: float = 2.85       # radius to pull out to at end (clear of part)
    program_name: str = "PART"


def _fmt(v):
    """
    Format a coordinate word.

    ALWAYS keeps a trailing decimal point. On many controls (Fanuc especially)
    a value with no decimal is read in the control's least increment, so a bare
    'Z-4' means -0.0004", not -4". Emitting 'Z-4.' is the safe convention and
    matches standard practice. Trailing zeros after the point are stripped for
    readability, but the point itself is never dropped.
      -4.0    -> "-4."
      -1.276  -> "-1.276"
      0.0     -> "0."
      1.6737  -> "1.6737"
    """
    s = f"{v:.4f}"
    if "." in s:
        s = s.rstrip("0")          # trim trailing zeros
        if s.endswith("."):
            pass                    # keep the bare point, e.g. "-4."
    # normalise negative zero
    if s in ("-0.", "-0"):
        s = "0."
    return s


def _ifmt(v):
    """
    Format a NON-positional word (spindle S, rpm clamp D). These are integer
    quantities, not axis coordinates, so they get no decimal point - some
    controls reject a decimal on an S word. Rounded to whole units.
    """
    return str(int(round(v)))


def _x(r, cfg):
    """Convert part radius to the X word the machine expects."""
    return 2.0 * r if cfg.diameter_mode else r


def post_finish(contour, cfg, out=None):
    """
    Emit a finish pass that follows the contour exactly as given.
    Tool-nose compensation is assumed already baked into the contour
    (G40 on the machine) - matching how the CAM reference works.
    """
    L = []
    def emit(s=""):
        L.append(s)

    r_start = contour.start_point()
    # header ---------------------------------------------------------------
    emit(f"({cfg.program_name} - LinuxCNC finish turn)")
    emit("G20" if cfg.units == "inch" else "G21")
    emit("G18")                                  # ZX plane (lathe)
    emit("G7" if cfg.diameter_mode else "G8")    # diameter/radius mode
    emit("G40 G54")                              # comp off, work offset
    emit("G95")                                  # feed per revolution
    if cfg.css:
        emit(f"G96 D{_ifmt(cfg.css_max_rpm)} S{_ifmt(cfg.surface_speed)} M3")
    else:
        emit(f"G97 S{_ifmt(cfg.rpm)} M3")
    if cfg.coolant:
        emit("M8")
    emit()

    # approach -------------------------------------------------------------
    # Stage the approach so we never rapid close to the face:
    #   1. rapid clear of the part at the safe Z standoff
    #   2. rapid to the start X, STILL holding the safe Z (no diving to the face)
    #   3. feed axially from the standoff onto the start point
    emit(f"G0 X{_fmt(_x(contour.r_range()[1] + 0.05, cfg))} "
         f"Z{_fmt(cfg.safe_z)}")
    emit(f"G0 X{_fmt(_x(r_start.r, cfg))} Z{_fmt(cfg.safe_z)}")

    # contour --------------------------------------------------------------
    emit("(--- contour ---)")
    # feed from the safe standoff onto the start point (Z of the first element)
    emit(f"G1 Z{_fmt(r_start.z)} F{_fmt(cfg.feed_per_rev)}")
    for e in contour.elements:
        if e.kind == "line":
            emit(f"G1 X{_fmt(_x(e.end.r, cfg))} Z{_fmt(e.end.z)}")
        else:
            g = "G3" if e.direction == ArcDir.CCW else "G2"
            # LinuxCNC lathe arcs: R form is supported and matches Fanuc style
            emit(f"{g} X{_fmt(_x(e.end.r, cfg))} Z{_fmt(e.end.z)} "
                 f"R{_fmt(e.radius)}")

    # retract & end --------------------------------------------------------
    emit("(--- retract ---)")
    emit(f"G0 X{_fmt(_x(cfg.retract_r, cfg))}")
    if cfg.coolant:
        emit("M9")
    emit("M5")
    emit(f"G53 G0 X{_fmt(0.0)} Z{_fmt(0.0)}")
    emit("M2")

    text = "\n".join(L) + "\n"
    if out:
        open(out, "w").write(text)
    return text


def post_rough(moves, cfg, notes=(), out=None):
    """
    Emit roughing moves as LinuxCNC G-code.

    `moves` come from rough.rough(): alternating rapids and feeds in (z, r).
    Radius becomes diameter here, as everywhere else in the post - this stays
    the only place that conversion happens.
    """
    L = []
    def emit(s=""):
        L.append(s)

    emit(f"({cfg.program_name} - LinuxCNC roughing)")
    for n in notes:
        emit(f"({n})")
    emit("G20" if cfg.units == "inch" else "G21")
    emit("G18")
    emit("G7" if cfg.diameter_mode else "G8")
    emit("G40 G54")
    emit("G95")
    if cfg.css:
        emit(f"G96 D{_ifmt(cfg.css_max_rpm)} S{_ifmt(cfg.surface_speed)} M3")
    else:
        emit(f"G97 S{_ifmt(cfg.rpm)} M3")
    if cfg.coolant:
        emit("M8")
    emit()

    feeding = False
    for m in moves:
        x = _fmt(_x(m.r, cfg))
        z = _fmt(m.z)
        if m.kind == "rapid":
            emit(f"G0 X{x} Z{z}")
            feeding = False
        else:
            if not feeding:
                emit(f"G1 X{x} Z{z} F{_fmt(cfg.feed_per_rev)}")
                feeding = True
            else:
                emit(f"G1 X{x} Z{z}")

    emit()
    emit(f"G0 X{_fmt(_x(cfg.retract_r, cfg))}")
    if cfg.coolant:
        emit("M9")
    emit("M5")
    emit(f"G53 G0 X{_fmt(0.0)} Z{_fmt(0.0)}")
    emit("M2")

    text = "\n".join(L) + "\n"
    if out:
        open(out, "w").write(text)
    return text
