"""Winding helpers shared across geometry, preview, and solver adapters.

This module is the SINGLE SOURCE OF TRUTH for the distributed-winding slot
map: an integer-slot, 60-degree phase-belt layout for three-phase distributed
windings, with optional two-layer short-pitch/chorded returns. Both the drawn geometry
(geometry_drawer._compute_slot_placements / femm_geometry excitation) and
the UI preview (preview._generate_winding_layout) consume this module, and
solvers/magneto2d/src/sources.rs distributed_winding_assignment mirrors it
exactly — change them together.

Layout definition (q = slot_count / (3 * pole_count), an integer >= 1;
validate_geometry enforces integrality before any of this runs):

  belt      = slot_idx // q                 q consecutive slots per belt
  phase     = (A, C, B)[belt % 3]           belt sequence A+, C-, B+, A-, C+, B-
  direction = "in" if belt % 2 == 0         sign alternates per BELT

Properties (verified by tests/test_distributed_fixtures.py and the Rust
phasor test in sources.rs):
  - all slots in a belt share phase AND direction;
  - phase A repeats with flipped sign exactly one pole pitch (3q slots) later;
  - the fundamental winding factor of the map equals kd * kp, where
    kd = sin(q*g/2) / (q*sin(g/2)) with g = 2*pi*pole_pairs/slot_count
    (electrical slot pitch), and
    kp = sin(pi * coil_span / (2 * full_pitch_slots)).
    Full pitch keeps kp = 1: 0.966 for 48s/8p (q=2), 1.0 for q=1.

The previous map (phase blocks repeating per pole PAIR with per-slot sign
alternation) was physically invalid: its fundamental winding factor measured
0.224 at q=2 and 0.50 at q=1, which is why the native Prius probe read
~22 V rms L-N against the ~269 V L-L ORNL anchor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_BELT_PHASE_ORDER = ("A", "C", "B")


@dataclass(frozen=True)
class SlotLayerAssignment:
    """Winding assignment for one physical layer inside a slot."""

    layer: int
    phase: str
    direction: str
    turn_fraction: float


@dataclass(frozen=True)
class SlotWindingTableRow:
    """Winding assignment row with its physical slot index."""

    slot_index: int
    layer: int
    phase: str
    direction: str
    turn_fraction: float


def flux_linkage_slot_side_turn_factor(
    winding_type: str,
    layers: int,
    parallel_paths: int,
) -> float:
    """Return the multiplier from slot-side turns to series turns per branch.

    The flux-linkage extractors sum turns_per_coil * A_z over every slot side,
    signed by its direction. A coil's two sides enter with opposite signs, so
    the sum is each coil's linkage N * L * (A_go - A_return), counted once, for
    every winding type and layer count: the same turns the source excites with
    J = turns_per_coil * I / A_slot (see series_turns_per_path). Only parallel
    branches divide the terminal series turns.

    Concentrated single-layer windings used to be credited half the turns
    here, which halved their flux linkage, back-EMF and Ke against the
    excitation (#80); winding_type and layers are kept for callers.
    """

    return 1.0 / max(1, parallel_paths)


def series_turns_per_path(
    slot_count: int,
    turns_per_coil: int,
    parallel_paths: int,
    winding_factor: float = 1.0,
) -> float:
    """Effective series turns per parallel path (kw-weighted) at the terminals.

    Turns convention: throughout coilEM,
    ``winding.turns_per_coil`` is the number of conductors in one slot's
    homogenized winding bundle — both solver lanes excite each slot with
    J = turns_per_coil * I_branch / A_slot (backend.geometry_drawer
    compute_3phase_current_density and magneto2d sources.rs), and both
    flux-linkage extractors credit turns_per_coil per physical slot.
    ``layers`` split that slot's conductors into upper/lower regions
    (see distributed_slot_layer_assignments): with layers = 2 the slot's
    turns_per_coil conductors are split into two coil sides of turns_per_coil/2
    turns each, so the machine's terminal turns do NOT change with ``layers``.

    Derivation: total slot-side conductors per phase = slot_count *
    turns_per_coil / 3. Each physical turn has two active sides, so series
    turns per phase = slot_count * turns_per_coil / 6, and parallel branches
    divide the terminal series turns:

        N_path = kw * slot_count * turns_per_coil / (6 * parallel_paths)

    independent of ``layers``. This is exactly the credit the solver-lane
    slot-sum extraction applies (flux_linkage_slot_side_turn_factor, 1.0 per
    path for every winding type): for the full-pitch belt layout the
    signed per-slot A_z sum counts every coil's flux linkage exactly once,
    verified analytically in tests/test_winding_bookkeeping_crosslane.py for
    (layers, paths) in {1,2}x{1,2} on 24s8p and the Prius 48s8p case.

    Anchors: ORNL Prius 2004 (48s, 9 turns per slot, 1 path) gives
    48*9/6 = 72 series turns per phase — the documented real machine.
    """
    return (
        winding_factor
        * slot_count
        * turns_per_coil
        / (6.0 * max(1, parallel_paths))
    )


def distributed_slots_per_pole_per_phase(slot_count: int, pole_count: int) -> int:
    """Integer q (slots per pole per phase) for a distributed layout.

    Legacy compatibility helper for integer-q callers. New code that needs to
    reason about fractional q should use
    distributed_slots_per_pole_per_phase_value().
    """
    return max(1, slot_count // (3 * max(1, pole_count)))


def distributed_slots_per_pole_per_phase_value(slot_count: int, pole_count: int) -> float:
    """Return q = slots per pole per phase as a float."""

    return slot_count / (3.0 * max(1, pole_count))


def distributed_slot_assignment(
    slot_idx: int, slot_count: int, pole_count: int
) -> tuple[str, str]:
    """Return (phase, direction) for one slot of the star-of-slots layout.

    phase is "A" | "B" | "C"; direction is "in" (positive) | "out".
    """
    sector = ((int(slot_idx) * 3 * max(1, int(pole_count))) // max(1, int(slot_count))) % 6
    phase = _BELT_PHASE_ORDER[sector % 3]
    direction = "in" if sector % 2 == 0 else "out"
    return phase, direction


def distributed_full_pitch_slots(slot_count: int, pole_count: int) -> float:
    """Full-pitch coil span in slot pitches."""

    return max(1.0, slot_count / max(1, pole_count))


def resolve_distributed_coil_span(
    slot_count: int,
    pole_count: int,
    coil_span: int | None = None,
) -> float:
    """Return the configured coil span, defaulting to full pitch (3q slots)."""

    if coil_span is None:
        return distributed_full_pitch_slots(slot_count, pole_count)
    return int(coil_span)


def distributed_distribution_factor(
    slot_count: int,
    pole_count: int,
    harmonic: int = 1,
) -> float:
    """Textbook distribution factor kd_n for the integer-q phase-belt layout."""

    q = distributed_slots_per_pole_per_phase_value(slot_count, pole_count)
    pole_pairs = max(1, pole_count // 2)
    g = 2.0 * math.pi * pole_pairs / slot_count
    denominator = q * math.sin(harmonic * g / 2.0)
    if abs(denominator) < 1e-12:
        return 1.0
    return abs(math.sin(harmonic * q * g / 2.0) / denominator)


def distributed_pitch_factor(
    slot_count: int,
    pole_count: int,
    harmonic: int = 1,
    coil_span: int | None = None,
) -> float:
    """Textbook pitch factor kp_n for the configured distributed coil span."""

    full_pitch_slots = distributed_full_pitch_slots(slot_count, pole_count)
    span = resolve_distributed_coil_span(slot_count, pole_count, coil_span)
    return abs(math.sin(harmonic * math.pi * span / (2.0 * full_pitch_slots)))


def distributed_winding_factor(
    slot_count: int,
    pole_count: int,
    harmonic: int = 1,
    coil_span: int | None = None,
) -> float:
    """Winding factor kw_n measured from the generated slot table."""

    layers = 2 if coil_span is not None else 1
    factors = _phase_winding_factors(
        slot_count,
        pole_count,
        harmonic,
        layers=layers,
        coil_span=coil_span,
    )
    nonzero = [factor for factor in factors.values() if factor > 0.0]
    if not nonzero:
        return 0.0
    return sum(nonzero) / len(nonzero)


def distributed_winding_table(
    slot_count: int,
    pole_count: int,
    layers: int = 1,
    coil_span: int | None = None,
) -> tuple[SlotWindingTableRow, ...]:
    """Generate the distributed winding table for all physical slot layers."""

    rows: list[SlotWindingTableRow] = []
    for slot_idx in range(max(0, slot_count)):
        for assignment in distributed_slot_layer_assignments(
            slot_idx,
            slot_count,
            pole_count,
            layers,
            coil_span=coil_span,
        ):
            rows.append(
                SlotWindingTableRow(
                    slot_index=slot_idx,
                    layer=assignment.layer,
                    phase=assignment.phase,
                    direction=assignment.direction,
                    turn_fraction=assignment.turn_fraction,
                )
            )
    return tuple(rows)


def _phase_winding_factors(
    slot_count: int,
    pole_count: int,
    harmonic: int = 1,
    layers: int = 1,
    coil_span: int | None = None,
) -> dict[str, float]:
    """Return per-phase phasor winding factors for the generated table."""

    pole_pairs = max(1, pole_count // 2)
    accum = {phase: 0j for phase in ("A", "B", "C")}
    weights = {phase: 0.0 for phase in ("A", "B", "C")}
    h = max(1, harmonic)
    for row in distributed_winding_table(slot_count, pole_count, layers, coil_span):
        sign = 1.0 if row.direction == "in" else -1.0
        theta = h * 2.0 * math.pi * pole_pairs * row.slot_index / max(1, slot_count)
        accum[row.phase] += row.turn_fraction * sign * complex(math.cos(theta), math.sin(theta))
        weights[row.phase] += row.turn_fraction

    return {
        phase: (abs(accum[phase]) / weights[phase] if weights[phase] > 0.0 else 0.0)
        for phase in ("A", "B", "C")
    }


def distributed_winding_balance_report(
    slot_count: int,
    pole_count: int,
    layers: int = 1,
    coil_span: int | None = None,
) -> dict[str, dict[str, float]]:
    """Return phase balance diagnostics for a generated distributed table."""

    rows = distributed_winding_table(slot_count, pole_count, layers, coil_span)
    turn_totals = {phase: 0.0 for phase in ("A", "B", "C")}
    signed_turn_totals = {phase: 0.0 for phase in ("A", "B", "C")}
    phasors = {phase: 0j for phase in ("A", "B", "C")}
    pole_pairs = max(1, pole_count // 2)

    for row in rows:
        sign = 1.0 if row.direction == "in" else -1.0
        theta = 2.0 * math.pi * pole_pairs * row.slot_index / max(1, slot_count)
        turn_totals[row.phase] += row.turn_fraction
        signed_turn_totals[row.phase] += row.turn_fraction * sign
        phasors[row.phase] += row.turn_fraction * sign * complex(math.cos(theta), math.sin(theta))

    magnitudes = {
        phase: (abs(phasors[phase]) / turn_totals[phase] if turn_totals[phase] else 0.0)
        for phase in ("A", "B", "C")
    }
    angles = {
        phase: math.degrees(math.atan2(phasors[phase].imag, phasors[phase].real)) % 360.0
        for phase in ("A", "B", "C")
    }
    return {
        "turn_totals": turn_totals,
        "signed_turn_totals": signed_turn_totals,
        "winding_factors": magnitudes,
        "axis_angles_deg": angles,
    }


def distributed_winding_is_balanced(
    slot_count: int,
    pole_count: int,
    layers: int = 1,
    coil_span: int | None = None,
    *,
    tolerance: float = 1e-9,
) -> bool:
    """Return true when the generated table is a balanced 3-phase layout."""

    report = distributed_winding_balance_report(slot_count, pole_count, layers, coil_span)
    turn_totals = list(report["turn_totals"].values())
    winding_factors = list(report["winding_factors"].values())
    angles = report["axis_angles_deg"]

    if min(turn_totals) <= 0.0:
        return False
    if max(turn_totals) - min(turn_totals) > tolerance:
        return False
    if max(winding_factors) - min(winding_factors) > tolerance:
        return False

    phase_angles = [angles["A"], angles["B"], angles["C"]]
    deltas = [
        (phase_angles[1] - phase_angles[0]) % 360.0,
        (phase_angles[2] - phase_angles[1]) % 360.0,
        (phase_angles[0] - phase_angles[2]) % 360.0,
    ]
    return all(abs(delta - 120.0) <= 1e-7 for delta in deltas)


def distributed_layer_tag(slot_idx: int, layers: int) -> int:
    """Legacy whole-slot layer tag for consumers that cannot render sublayers.

    Producers should prefer distributed_slot_layer_assignments(), which
    emits one assignment per physical slot layer. This tag remains for older
    whole-slot preview/diagnostic consumers and does not feed excitation.
    """
    if layers <= 1:
        return 1
    return 1 if ((slot_idx // 2) % 2) == 0 else 2


def distributed_slot_layer_assignments(
    slot_idx: int,
    slot_count: int,
    pole_count: int,
    layers: int,
    coil_span: int | None = None,
) -> tuple[SlotLayerAssignment, ...]:
    """Return the per-layer winding assignment for a distributed slot.

    Conductors-per-slot convention: ``turns_per_coil``
    is the total conductor bundle in one physical slot. A two-layer full-pitch
    slot therefore has two regions that carry the same phase/direction, each
    representing half of that bundle.

    Chording shifts the upper layer by ``full_pitch - coil_span`` slots:
    layer 1 keeps the base slot-side assignment; layer 2 carries the return-side
    assignment that would have occupied the full-pitch return slot. Full pitch
    resolves to a zero shift and stays layer-invariant.
    """

    n_layers = 2 if layers >= 2 else 1
    fraction = 1.0 / n_layers
    layer2_shift_slots = 0
    if coil_span is not None:
        full_pitch = distributed_full_pitch_slots(slot_count, pole_count)
        span = resolve_distributed_coil_span(slot_count, pole_count, coil_span)
        layer2_shift_slots = int(round(full_pitch - span))

    assignments: list[SlotLayerAssignment] = []
    for layer in range(1, n_layers + 1):
        source_slot = slot_idx
        if layer == 2:
            source_slot = (slot_idx + layer2_shift_slots) % max(1, slot_count)
        phase, direction = distributed_slot_assignment(
            source_slot,
            slot_count,
            pole_count,
        )
        assignments.append(
            SlotLayerAssignment(
                layer=layer,
                phase=phase,
                direction=direction,
                turn_fraction=fraction,
            )
        )
    return tuple(assignments)


def distributed_fundamental_winding_factor(
    slot_count: int,
    pole_count: int,
    coil_span: int | None = None,
) -> float:
    """Fundamental winding factor of the layout this module actually builds.

    Integer-slot layout, so kw = kd * kp. With ``coil_span`` omitted, the
    resolved full-pitch span makes kp = 1 and preserves the historical kd-only
    value bit-for-bit for existing configs.
    """
    return distributed_winding_factor(slot_count, pole_count, 1, coil_span)


# ---------------------------------------------------------------------------
# Concentrated windings (#91)
#
# Fractional-slot concentrated windings (q = slot_count / (3 * pole_count) < 1)
# are real tooth coils: coil t wraps tooth t, with its go side in slot t and its
# return side in slot t + 1. Each coil's phase comes from its EMF phasor
# e^{j a t} - e^{j a (t+1)} (a = electrical slot pitch) in coilEM's 60-degree
# sector order (A+, C-, B+, A-, C+, B-). layers = 1 winds alternate teeth (one
# coil side per slot); layers = 2 winds every tooth (two coil sides per slot,
# split into the same two layer regions distributed windings use).
#
# The turns convention is unchanged: ``turns_per_coil`` is the conductor bundle
# of one slot, so with layers = 2 each tooth coil has turns_per_coil / 2 turns.
#
# The previous layout gave every slot one phase from its own electrical angle.
# For q = 1/2 that put A, B, C in consecutive slots all in one direction: no
# phase had a return side, its fundamental winding factor read 1.0 instead of
# 0.866, and its 5th and 7th harmonics were inverted against a real machine
# (#91, measured on the CREATOR PMSM, #90). Concentrated windings with q >= 1
# keep that layout, which there draws full-pitch phase belts.
# ---------------------------------------------------------------------------

_CONCENTRATED_SECTORS: tuple[tuple[str, str], ...] = (
    ("A", "in"),
    ("C", "out"),
    ("B", "in"),
    ("A", "out"),
    ("C", "in"),
    ("B", "out"),
)
# Coil phasors of the q = 1/2 family sit exactly on sector boundaries; a fixed,
# tiny bias keeps their assignment independent of floating-point rounding.
_SECTOR_BOUNDARY_BIAS_DEG = 1e-7


def _electrical_slot_pitch_rad(slot_count: int, pole_count: int) -> float:
    return 2.0 * math.pi * (pole_count / 2.0) / max(1, slot_count)


def legacy_concentrated_slot_phase(slot_idx: int, slot_count: int, pole_pairs: int) -> tuple[str, str]:
    """Whole-slot phase and direction from the slot's own electrical angle (q >= 1 layout)."""

    if slot_count <= 0:
        return _CONCENTRATED_SECTORS[0]
    elec_angle_deg = (slot_idx * 360.0 * pole_pairs / slot_count) % 360.0
    return _CONCENTRATED_SECTORS[int(elec_angle_deg / 60) % 6]


def concentrated_uses_tooth_coils(slot_count: int, pole_count: int) -> bool:
    """Fractional-slot concentrated windings (q < 1) are drawn as tooth coils (#91).

    Slot counts the three phases cannot share keep the legacy map; validation
    rejects them as unbalanced either way.
    """

    return slot_count > 0 and slot_count % 3 == 0 and pole_count > 0 and slot_count < 3 * pole_count


def tooth_coil_assignments(slot_count: int, pole_count: int, layers: int) -> tuple[tuple[int, str, str], ...]:
    """(tooth, phase, direction) for every wound tooth; coil t has its go side in slot t."""

    pitch = _electrical_slot_pitch_rad(slot_count, pole_count)
    teeth = range(slot_count) if layers >= 2 else range(0, slot_count, 2)
    coils = []
    for tooth in teeth:
        phasor = complex(math.cos(pitch * tooth), math.sin(pitch * tooth)) - complex(
            math.cos(pitch * (tooth + 1)), math.sin(pitch * (tooth + 1))
        )
        angle = (math.degrees(math.atan2(phasor.imag, phasor.real)) + _SECTOR_BOUNDARY_BIAS_DEG) % 360.0
        phase, direction = _CONCENTRATED_SECTORS[int(angle // 60.0) % 6]
        coils.append((tooth, phase, direction))
    return tuple(coils)


def _opposite(direction: str) -> str:
    return "out" if direction == "in" else "in"


def tooth_coil_slot_layer_assignments(
    slot_idx: int, slot_count: int, pole_count: int, layers: int
) -> tuple[SlotLayerAssignment, ...]:
    """Coil sides in one slot of a tooth-coil layout.

    Single layer: an even slot holds the go side of the coil on its own tooth, an
    odd slot the return side of the coil on the tooth before it. Double layer:
    layer 1 holds the return side of the coil on the tooth before the slot,
    layer 2 the go side of the coil on the slot's own tooth, half the slot's
    conductors each.
    """

    coils = {tooth: (phase, direction) for tooth, phase, direction in tooth_coil_assignments(slot_count, pole_count, layers)}
    slot = slot_idx % slot_count
    previous_tooth = (slot - 1) % slot_count
    if layers >= 2:
        back_phase, back_direction = coils[previous_tooth]
        go_phase, go_direction = coils[slot]
        return (
            SlotLayerAssignment(layer=1, phase=back_phase, direction=_opposite(back_direction), turn_fraction=0.5),
            SlotLayerAssignment(layer=2, phase=go_phase, direction=go_direction, turn_fraction=0.5),
        )
    if slot in coils:
        phase, direction = coils[slot]
        return (SlotLayerAssignment(layer=1, phase=phase, direction=direction, turn_fraction=1.0),)
    phase, direction = coils[previous_tooth]
    return (SlotLayerAssignment(layer=1, phase=phase, direction=_opposite(direction), turn_fraction=1.0),)


def concentrated_slot_layer_assignments(
    slot_idx: int, slot_count: int, pole_count: int, layers: int
) -> tuple[SlotLayerAssignment, ...]:
    """Per-layer winding assignment of one concentrated slot: tooth coils for q < 1, else the legacy whole-slot map."""

    if concentrated_uses_tooth_coils(slot_count, pole_count):
        return tooth_coil_slot_layer_assignments(slot_idx, slot_count, pole_count, layers)
    phase, direction = legacy_concentrated_slot_phase(slot_idx, slot_count, int(pole_count // 2))
    return (SlotLayerAssignment(layer=1, phase=phase, direction=direction, turn_fraction=1.0),)


def concentrated_phase_phasors(slot_count: int, pole_count: int, layers: int, harmonic: int = 1) -> dict[str, complex]:
    """Sum of sign * turn_fraction * e^{j n a s} over each phase's coil sides (winding-factor phasor)."""

    pitch = _electrical_slot_pitch_rad(slot_count, pole_count)
    totals = {"A": 0j, "B": 0j, "C": 0j}
    for slot in range(slot_count):
        for side in concentrated_slot_layer_assignments(slot, slot_count, pole_count, layers):
            sign = 1.0 if side.direction == "in" else -1.0
            angle = harmonic * pitch * slot
            totals[side.phase] += sign * side.turn_fraction * complex(math.cos(angle), math.sin(angle))
    return totals


def concentrated_winding_factor(slot_count: int, pole_count: int, layers: int, harmonic: int = 1) -> float:
    """Winding factor of the drawn concentrated layout: |phase phasor| / (slot_count / 3) whole-slot bundles."""

    return abs(concentrated_phase_phasors(slot_count, pole_count, layers, harmonic)["A"]) / (slot_count / 3.0)


def tooth_coil_layout_error(slot_count: int, pole_count: int, layers: int) -> str | None:
    """Why this tooth-coil layout cannot be wound as a balanced three-phase winding, or None."""

    if not concentrated_uses_tooth_coils(slot_count, pole_count):
        return None
    if layers < 2 and slot_count % 2:
        return f"a single-layer tooth-coil winding needs an even slot count; {slot_count} slots needs layers = 2"
    coils = tooth_coil_assignments(slot_count, pole_count, layers)
    counts = {phase: sum(1 for _, p, _ in coils if p == phase) for phase in "ABC"}
    if len(set(counts.values())) != 1:
        return f"tooth coils split unevenly between phases ({counts})"
    phasors = concentrated_phase_phasors(slot_count, pole_count, layers)
    magnitude = abs(phasors["A"])
    if magnitude < 1e-9 or any(abs(abs(phasors[p]) - magnitude) > 1e-9 * max(1.0, magnitude) for p in "BC"):
        return "the phases' fundamental EMFs differ in size"
    angles = [math.degrees(math.atan2(phasors[p].imag, phasors[p].real)) for p in "ABC"]
    if any(abs(((angles[(i + 1) % 3] - angles[i]) % 360.0) - 120.0) > 1e-6 for i in range(3)):
        return "the phases' fundamental EMFs are not 120 degrees apart"
    return None


def winding_phase_phasors(
    winding_type: str, slot_count: int, pole_count: int, layers: int, coil_span: int | None = None
) -> dict[str, complex]:
    """Fundamental phasor of each phase over the slot sides the solver winds, for any winding type."""

    if winding_type != "distributed":
        return concentrated_phase_phasors(slot_count, pole_count, layers)
    pitch = _electrical_slot_pitch_rad(slot_count, pole_count)
    totals = {"A": 0j, "B": 0j, "C": 0j}
    for slot in range(slot_count):
        for side in distributed_slot_layer_assignments(slot, slot_count, pole_count, layers, coil_span):
            sign = 1.0 if side.direction == "in" else -1.0
            totals[side.phase] += sign * side.turn_fraction * complex(math.cos(pitch * slot), math.sin(pitch * slot))
    return totals


def winding_phase_axis_offset_elec_deg(
    winding_type: str, slot_count: int, pole_count: int, layers: int, coil_span: int | None = None
) -> float:
    """Electrical angle of phase A's axis, which the current-angle convention absorbs (#91).

    The convention (source angle rotor_elec - 90 + gamma) puts phase A's axis at 0
    degrees, where a one-slot phase belt has it. Wider belts put it at their centre
    (15 degrees for q = 2, 20 for q = 3; 5/6 chording at q = 2 brings it back to 0)
    and tooth coils on a tooth (+30 degrees for q = 1/2). Subtracting it keeps gamma
    measured from the q-axis for every layout. Rounded to 1e-9 degrees so a layout
    whose axis is at 0 keeps its source angles bit for bit. Mirrors
    solvers/magneto2d/src/sources.rs winding_phase_axis_offset_elec_deg.
    """

    if slot_count <= 0 or pole_count <= 0:
        return 0.0
    phasor = winding_phase_phasors(winding_type, slot_count, pole_count, layers, coil_span)["A"]
    if abs(phasor) < 1e-9:
        return 0.0
    return round(math.degrees(math.atan2(phasor.imag, phasor.real)), 9) + 0.0
