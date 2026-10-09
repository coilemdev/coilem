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

    coilEM winding geometry is described in terms of slot sides. For single-layer
    concentrated windings, summing every slot side directly double-counts the
    series turns seen at the terminals because each physical turn has two active
    sides. Back-EMF / flux-linkage calculations should therefore use half the raw
    slot-side turn count. Parallel branches divide the terminal series turns
    further.
    """

    slot_side_normalization = 0.5 if winding_type == "concentrated" and layers == 1 else 1.0
    return slot_side_normalization / max(1, parallel_paths)


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
    slot-sum extraction applies (flux_linkage_slot_side_turn_factor with the
    distributed normalization of 1.0): for the full-pitch belt layout the
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
