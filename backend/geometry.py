"""Pyleecan-based geometry generation for electric motors.

This module provides functionality to create Pyleecan Machine objects from
coilEM MotorConfig specifications, supporting both IPM (Interior Permanent Magnet)
and SPM (Surface Permanent Magnet) topologies.

The module includes validation of geometric constraints and graceful degradation
if Pyleecan is not available (e.g., in sandboxed environments).
"""

import math
from dataclasses import dataclass
from typing import Optional

from backend.geometry_drawer import (
    MIN_SLOT_BODY_WIDTH_MM,
    _slot_mouth_width_mm,
    compute_flat_buried_magnet_placements,
    compute_pyleecan_holem50_placements,
    compute_v_shape_magnet_placements,
    concentrated_slot_phase,
    magnet_radial_center_mm,
    narrowest_tooth_width_mm,
    point_in_polygon,
    slot_body_pitch_mm,
    tooth_width_at_yoke_mm,
    tooth_width_geometry_limit_mm,
)
from backend.models import ErrorResponse, MotorConfig
from backend.models.config import (
    MIN_STATOR_SLOT_OPENING_MM,
    MIN_STATOR_TOOTH_WIDTH_MM,
)
from backend.winding_utils import (
    distributed_full_pitch_slots,
    distributed_slots_per_pole_per_phase_value,
    distributed_winding_is_balanced,
)

# "Does this fit" comparisons are against arcs computed through pi, so a part
# sitting exactly on its limit — magnets just touching, a tooth leaving exactly
# the minimum slot — must not be rejected by the last bit of the mantissa.
GEOMETRY_FIT_TOLERANCE_MM = 1e-6

# Public geometry dimensions are entered and displayed to 0.1mm. Do not warn that
# a field and the rendered dimension disagree when both still display the same
# value; half a display increment is the meaningful advisory boundary.
GEOMETRY_WARNING_TOLERANCE_MM = 0.05

# A tooth normally tapers a little between the bore and yoke. Treating every
# measurable taper as a saturation warning made harmless sub-millimetre
# differences look like design faults. Relative thresholds scale with the motor:
# a 0.2mm difference matters very differently on a 4mm tooth and a 25mm tooth.
TOOTH_WIDTH_INFO_RELATIVE_NARROWING = 0.02
TOOTH_WIDTH_WARNING_RELATIVE_NARROWING = 0.05

# Mirrors StatorConfig.slot_count's ge/le, so a suggested slot count is one the
# model will actually accept. tests/test_concentrated_balance_advice.py asserts
# these stay in step with the model.
SLOT_COUNT_MIN = 6
SLOT_COUNT_MAX = 96


def concentrated_belt_counts(slot_count: int, pole_count: int) -> dict[str, int]:
    """Coils per phase for a concentrated (one coil per tooth) winding."""

    pole_pairs = max(1, pole_count // 2)
    counts: dict[str, int] = {}
    for slot_idx in range(slot_count):
        phase, _direction = concentrated_slot_phase(slot_idx, slot_count, pole_pairs)
        counts[phase] = counts.get(phase, 0) + 1
    return counts


def concentrated_winding_is_balanced(slot_count: int, pole_count: int) -> bool:
    """True when all three phases get coils, and the same number of them."""

    counts = concentrated_belt_counts(slot_count, pole_count)
    return set(counts) == {"A", "B", "C"} and len(set(counts.values())) == 1


@dataclass(frozen=True)
class WindingLayoutProblem:
    """Why a slot/pole/winding combination cannot carry a 3-phase layout.

    ``kind`` lets the caller pick its own wording and field: ``validate_geometry``
    turns it into a blocking error with a suggestion, the preview payload into an
    advisory string. Both ask this one function, so the two can never disagree about
    whether a combination is workable — they used to, in both directions.
    """

    kind: str
    detail: str


@dataclass(frozen=True)
class ToothWidthAdvisory:
    """Severity and measurements for a meaningfully tapered stator tooth."""

    severity: str
    kind: str
    narrowest_width_mm: float
    yoke_tooth_width_mm: float
    relative_narrowing: float
    message: str | None = None


def winding_layout_problem(
    slot_count: int,
    pole_count: int,
    winding_type: str,
    *,
    layers: int = 1,
    coil_span: int | None = None,
) -> WindingLayoutProblem | None:
    """The single decision on whether a 3-phase winding layout is workable."""

    if winding_type != "distributed":
        belt_counts = concentrated_belt_counts(slot_count, pole_count)
        missing = sorted({"A", "B", "C"} - belt_counts.keys())
        if missing:
            return WindingLayoutProblem(
                "missing_phase", f"phase {', '.join(missing)} would carry no coils"
            )
        if len(set(belt_counts.values())) > 1:
            return WindingLayoutProblem(
                "unequal_coils",
                "the phases would carry unequal coil counts "
                + str({key: belt_counts[key] for key in sorted(belt_counts)}),
            )
        return None

    pole_pairs = pole_count // 2
    q_value = distributed_slots_per_pole_per_phase_value(slot_count, pole_count)
    if pole_pairs > 0 and q_value < 1.0:
        return WindingLayoutProblem(
            "q_below_one",
            f"q = slot_count / (3*pole_count) must be at least 1, got q={q_value:g}",
        )
    if not distributed_winding_is_balanced(slot_count, pole_count, layers, coil_span):
        return WindingLayoutProblem(
            "unbalanced_star",
            f"the star-of-slots table comes out unbalanced (q={q_value:g})",
        )
    return None


def balanced_concentrated_slot_counts(
    pole_count: int, *, near: int, limit: int = 3
) -> list[int]:
    """Supported slot counts that do balance at this pole count, nearest `near` first.

    Searched with the same belt assignment ``validate_geometry`` rejects on, so a
    suggestion cannot name a count the check would refuse. Whether a concentrated
    winding balances is a property of the slot/pole pair — at 12 poles the workable
    counts are multiples of 9, while 12 and 24 slots leave phase B empty — so there
    is no slot-only rule of thumb to offer instead.
    """

    candidates = [
        slots
        for slots in range(SLOT_COUNT_MIN, SLOT_COUNT_MAX + 1)
        if slots != near and concentrated_winding_is_balanced(slots, pole_count)
    ]
    candidates.sort(key=lambda slots: (abs(slots - near), slots))
    return sorted(candidates[:limit])

# Attempt to import Pyleecan - gracefully degrade if not available
try:
    from pyleecan.Classes.HoleM50 import HoleM50
    from pyleecan.Classes.Machine import Machine
    from pyleecan.Classes.MachineIPMSM import MachineIPMSM
    from pyleecan.Classes.MachineSIPMSM import MachineSIPMSM
    from pyleecan.Classes.Rotor import Rotor
    from pyleecan.Classes.SlotM13 import SlotM13
    from pyleecan.Classes.SlotW11 import SlotW11
    from pyleecan.Classes.Stator import Stator
    from pyleecan.Classes.WindingCW2LT import WindingCW2LT
    from pyleecan.Classes.WindingDW2L import WindingDW2L

    PYLEECAN_AVAILABLE = True
except ImportError:
    PYLEECAN_AVAILABLE = False


def tooth_width_advisory(config: MotorConfig) -> ToothWidthAdvisory | None:
    """Classify a meaningful tooth taper without treating normal variation as bad.

    Less than 2% is normal display-only taper, 2–5% is useful context, and more
    than 5% is a pre-solve warning. This remains geometric only: actual saturation
    severity comes from the solved tooth flux density and the selected steel curve.
    """

    stator = config.stator

    # tooth_width_mm is subtracted at the slot body, so it describes the tooth at
    # the yoke. The bore is a second, independently derived section because its
    # mouth is pinned to slot_opening_mm:
    #
    #     tooth at the bore = bore pitch - slot mouth
    #
    # Both arcs shrink with slot count, but the pitch shrinks faster than the mouth
    # (which is fixed), so raising the slot count eventually makes the bore the
    # narrowest section. This first compared the slot *body* against the mouth, which
    # is the same inequality shifted out to the body pitch — a strict subset. It went
    # quiet exactly where the field was wrong but the slot had not inverted yet:
    # 24 slots, 120mm bore, 2mm mouth, an 18mm tooth draws 13.7mm and said nothing.
    mouth_width_mm = _slot_mouth_width_mm(config)
    bore_pitch_mm = math.pi * stator.ID_mm / stator.slot_count
    tooth_width_limit_mm = tooth_width_geometry_limit_mm(config)
    narrowest_width_mm = narrowest_tooth_width_mm(config)
    yoke_tooth_width_mm = tooth_width_at_yoke_mm(config)
    if yoke_tooth_width_mm <= GEOMETRY_FIT_TOLERANCE_MM:
        return None
    relative_narrowing = max(
        0.0,
        (yoke_tooth_width_mm - narrowest_width_mm) / yoke_tooth_width_mm,
    )
    if relative_narrowing < TOOTH_WIDTH_INFO_RELATIVE_NARROWING:
        return None

    # With a tooth shoe enabled, narrowest_tooth_width_mm samples the shoulder
    # transition rather than the widened bore tip. Name that physical section in
    # the UI even when its width happens to be close to the unshoed bore formula.
    shoe_constrained = stator.tooth_shoe_enabled
    kind = "tooth_shoe_shoulder" if shoe_constrained else "bore_tooth"
    severity = (
        "warning"
        if relative_narrowing > TOOTH_WIDTH_WARNING_RELATIVE_NARROWING
        else "info"
    )
    if severity == "info":
        return ToothWidthAdvisory(
            severity=severity,
            kind=kind,
            narrowest_width_mm=narrowest_width_mm,
            yoke_tooth_width_mm=yoke_tooth_width_mm,
            relative_narrowing=relative_narrowing,
        )

    # Floored, not rounded: a value printed as advice has to be one that actually
    # clears the warning, and `:.1f` rounds up half the time. Include the public
    # display tolerance so a suggested 0.1mm value cannot immediately re-warn.
    suggested_mm = (
        math.floor(
            (tooth_width_limit_mm + GEOMETRY_WARNING_TOLERANCE_MM) * 10.0
        )
        / 10.0
    )
    actions: list[str] = []
    if suggested_mm >= MIN_STATOR_TOOTH_WIDTH_MM:
        actions.append(f"reduce Yoke Tooth Width to {suggested_mm:g}mm")

    # For an unshoed tooth this equation names an opening that actually clears
    # the warning. Do not recommend narrowing below the schema's 2mm minimum.
    if not stator.tooth_shoe_enabled:
        opening_limit_mm = (
            bore_pitch_mm
            - stator.tooth_width_mm
            + GEOMETRY_WARNING_TOLERANCE_MM
        )
        suggested_opening_mm = math.floor(opening_limit_mm * 10.0) / 10.0
        if (
            suggested_opening_mm >= MIN_STATOR_SLOT_OPENING_MM
            and suggested_opening_mm
            < stator.slot_opening_mm - GEOMETRY_FIT_TOLERANCE_MM
        ):
            actions.append(
                f"narrow the Bore Slot Opening to {suggested_opening_mm:g}mm"
            )
    actions.extend(("use fewer slots", "increase the bore diameter"))
    if len(actions) == 2:
        advice = f"{actions[0]} or {actions[1]}"
    else:
        advice = f"{', '.join(actions[:-1])}, or {actions[-1]}"
    advice = advice[0].upper() + advice[1:]

    if stator.tooth_shoe_enabled:
        message = (
            f"The tooth-shoe shoulder is substantially narrower than the tooth at "
            f"the yoke: about {narrowest_width_mm:.1f}mm versus "
            f"{yoke_tooth_width_mm:.1f}mm. {advice} to reduce the saturation "
            "risk at the shoulder."
        )
    else:
        message = (
            f"The bore tooth is substantially narrower than the tooth at the yoke: "
            f"{narrowest_width_mm:.1f}mm versus {yoke_tooth_width_mm:.1f}mm. "
            f"The {mouth_width_mm:.2f}mm Bore Slot Opening leaves that width in "
            f"the {bore_pitch_mm:.1f}mm bore pitch. {advice} to reduce the "
            "saturation risk at the bore."
        )

    return ToothWidthAdvisory(
        severity=severity,
        kind=kind,
        narrowest_width_mm=narrowest_width_mm,
        yoke_tooth_width_mm=yoke_tooth_width_mm,
        relative_narrowing=relative_narrowing,
        message=message,
    )


def geometry_warnings(config: MotorConfig) -> list[str]:
    """Return only actionable (>5%) non-blocking geometry warnings."""

    advisory = tooth_width_advisory(config)
    if advisory is None or advisory.severity != "warning" or advisory.message is None:
        return []
    return [advisory.message]


def validate_geometry(config: MotorConfig) -> list[ErrorResponse]:
    """Validate motor geometry against physical constraints.

    This function checks for common design issues such as:
    - Rotor too large for stator (violates airgap)
    - Invalid magnet dimensions
    - Incompatible pole-slot combinations
    - Slot geometry constraints

    Args:
        config: Motor configuration to validate

    Returns:
        List of ErrorResponse objects for any validation failures.
        Empty list means configuration is geometrically valid.
    """
    errors = []

    # Extract convenience references
    stator = config.stator
    rotor = config.rotor
    winding = config.winding

    # Minimum airgap is 0.3mm
    MIN_AIRGAP_MM = 0.3
    airgap = (stator.ID_mm - rotor.OD_mm) / 2

    if airgap < MIN_AIRGAP_MM:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=f"Airgap {airgap:.2f}mm is less than minimum {MIN_AIRGAP_MM}mm",
                field="rotor.OD_mm",
                suggestion=f"Decrease rotor OD_mm by at least {MIN_AIRGAP_MM*2 - (stator.ID_mm - rotor.OD_mm):.2f}mm or increase stator ID_mm",
            )
        )

    # Magnet thickness should not exceed quarter of rotor OD
    max_magnet_thickness = rotor.OD_mm / 4
    if rotor.magnet_thickness_mm > max_magnet_thickness:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=f"Magnet thickness {rotor.magnet_thickness_mm}mm exceeds max {max_magnet_thickness:.2f}mm (OD/4)",
                field="rotor.magnet_thickness_mm",
                suggestion=f"Reduce magnet thickness to <= {max_magnet_thickness:.2f}mm",
            )
        )

    # Neighbouring magnets must not overlap. This has to be measured where the
    # builder converts magnet_width_mm into an angle, which is the magnet's radial
    # centre, not the rotor core radius: an SPM magnet rides *outside* the core, so
    # the core pitch is a smaller number and rejected designs that do not overlap
    # (4 poles, OD 25, 3mm thick: limit read 19.63mm when the magnets fit to
    # 21.99mm). Only SPM is checked here — flat-buried IPM has its own limit below
    # that also accounts for side bridges and pocket clearance, and V-shape treats
    # magnet_width_mm as a slab length with its own containment checks.
    if config.topology != "IPM" and rotor.pole_count > 0:
        magnet_center_r_mm = magnet_radial_center_mm(config)
        if magnet_center_r_mm > 0:
            max_magnet_width_mm = magnet_center_r_mm * (2 * math.pi / rotor.pole_count)
            # Explicit tolerance so a width sitting exactly on the pitch — magnets
            # just touching — is not rejected by floating-point noise.
            if rotor.magnet_width_mm > max_magnet_width_mm + GEOMETRY_FIT_TOLERANCE_MM:
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=(
                            f"Magnet width {rotor.magnet_width_mm}mm exceeds the pole pitch "
                            f"{max_magnet_width_mm:.2f}mm at the magnet radius "
                            f"{magnet_center_r_mm:.2f}mm, so neighbouring magnets overlap"
                        ),
                        field="rotor.magnet_width_mm",
                        suggestion=f"Reduce magnet width to <= {max_magnet_width_mm:.2f}mm",
                    )
                )

    # Slot opening should not exceed tooth pitch
    tooth_pitch_mm = (3.14159 * stator.ID_mm) / stator.slot_count
    if stator.slot_opening_mm > tooth_pitch_mm:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=f"Slot opening {stator.slot_opening_mm}mm exceeds tooth pitch {tooth_pitch_mm:.2f}mm",
                field="stator.slot_opening_mm",
                suggestion=f"Reduce slot opening to <= {tooth_pitch_mm:.2f}mm",
            )
        )

    # The tooth has to leave a slot behind it. tooth_width_mm is subtracted from
    # the slot-body pitch and floored at MIN_SLOT_BODY_WIDTH_MM, so once it reaches
    # that arc the drawer quietly emits a 0.5mm slot instead of the geometry the
    # fields describe (a 49mm tooth on a 42.94mm pitch used to validate clean).
    body_pitch_mm = slot_body_pitch_mm(config)
    max_tooth_width_mm = body_pitch_mm - MIN_SLOT_BODY_WIDTH_MM
    if stator.tooth_width_mm > max_tooth_width_mm + GEOMETRY_FIT_TOLERANCE_MM:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=(
                    f"Tooth width {stator.tooth_width_mm}mm leaves no slot: the pitch at the "
                    f"slot body is {body_pitch_mm:.2f}mm across {stator.slot_count} slots"
                ),
                field="stator.tooth_width_mm",
                suggestion=(
                    # Floored so the printed value is one that actually validates.
                    f"Reduce tooth width to <= {math.floor(max_tooth_width_mm * 100.0) / 100.0:g}mm, "
                    "or add slots/stator depth"
                ),
            )
        )

    # A concentrated winding has to reach all three phases. Some slot/pole
    # combinations never do: 16 slots with 8 poles steps 90 electrical degrees per
    # slot, so only the A and C belts are ever entered and phase B gets no coils at
    # all. Nothing checked this, so the app drew an A/C-only winding, showed three
    # colours in the cross-section from a different per-tooth pattern, and reported
    # "Geometry valid — ready to solve" for a two-phase machine.
    if winding.type != "distributed" and stator.slot_count > 0:
        problem = winding_layout_problem(
            stator.slot_count, rotor.pole_count, winding.type
        )
        if problem is not None:
            detail = problem.detail
            alternatives = balanced_concentrated_slot_counts(
                rotor.pole_count, near=stator.slot_count
            )
            # Balance depends on the slot/pole *pair*, not on the slot count alone, so
            # the alternatives are searched with the same belt assignment the check
            # above uses. The old advice ("a multiple of 3, such as 9, 12, 18, 24")
            # was both wrong as a rule and self-contradicting: at 12 poles only 9, 18,
            # 27, 36 and 45 balance, and it recommended the very 24 it was rejecting.
            if alternatives:
                listed = [str(count) for count in alternatives]
                joined = (
                    listed[0]
                    if len(listed) == 1
                    else f"{', '.join(listed[:-1])} or {listed[-1]}"
                )
                slot_advice = f"At {rotor.pole_count} poles, use {joined} slots"
            else:
                slot_advice = "No slot count in the supported range balances at this pole count"
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=f"{stator.slot_count} slots with {rotor.pole_count} poles cannot carry a "
                    f"balanced three-phase concentrated winding: {detail}.",
                    field="stator.slot_count",
                    suggestion=f"{slot_advice}, or change the pole count.",
                )
            )

    # Parallel paths have to divide the coils per phase for any winding type. The
    # check below covers the distributed case; a concentrated winding has one coil
    # per tooth, so slot_count / 3 coils per phase rather than slot_count / 6, and it
    # used to go unchecked entirely — a 12-slot machine accepted 3 paths and reported
    # valid geometry for a winding nobody can wind, because 4 coils per phase do not
    # split into 3 equal branches. Unequal branches have unequal EMF in a real
    # machine and circulate current between themselves, heating the winding for no
    # torque.
    if winding.type != "distributed" and stator.slot_count % 3 == 0:
        coils_per_phase = stator.slot_count // 3
        if winding.parallel_paths > 1 and coils_per_phase % winding.parallel_paths != 0:
            divisors = [p for p in range(1, coils_per_phase + 1) if coils_per_phase % p == 0]
            errors.append(
                ErrorResponse(
                    # INVALID_GEOMETRY to match the distributed sibling; ErrorResponse
                    # only permits five codes and widening that is a schema change.
                    error_code="INVALID_GEOMETRY",
                    message=f"parallel_paths={winding.parallel_paths} does not evenly divide the "
                    f"{coils_per_phase} coils per phase of this concentrated layout "
                    f"({stator.slot_count} slots, one coil per tooth).",
                    field="winding.parallel_paths",
                    suggestion=f"Use one of: {divisors}",
                )
            )

    # Validate pole-slot combination for distributed windings (all topologies).
    # Use a generated star-of-slots table instead of the integer-q belt map:
    # balanced integer and fractional q >= 1 layouts are supported, while q < 1
    # remains concentrated-winding territory.
    if winding.type == "distributed":
        pole_pairs = rotor.pole_count // 2
        q_value = distributed_slots_per_pole_per_phase_value(
            stator.slot_count,
            rotor.pole_count,
        )
        is_integer_q = abs(q_value - round(q_value)) < 1e-12
        # Same decision the preview advisory asks, so the two cannot drift apart.
        problem = winding_layout_problem(
            stator.slot_count,
            rotor.pole_count,
            winding.type,
            layers=winding.layers,
            coil_span=getattr(winding, "coil_span", None),
        )
        if problem is not None and problem.kind == "q_below_one":
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=f"For a distributed winding with {rotor.pole_count} poles ({pole_pairs} pole-pairs), "
                    f"q = slot_count / (3*pole_count) must be at least 1. Got q={q_value:g} "
                    f"from slot_count={stator.slot_count}.",
                    field="stator.slot_count",
                    suggestion="Increase slot_count or switch to a concentrated winding for q < 1 combinations.",
                )
            )
        elif problem is not None and problem.kind == "unbalanced_star":
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=(
                        f"slot_count={stator.slot_count} and pole_count={rotor.pole_count} "
                        f"produce an unbalanced distributed star-of-slots table (q={q_value:g})."
                    ),
                    field="stator.slot_count",
                    suggestion=(
                        "Choose a balanced 3-phase distributed slot/pole combination "
                        "(for example integer-q layouts or validated fractional q >= 1), "
                        "or switch to a concentrated winding."
                    ),
                )
            )
        else:
            q = int(round(q_value))
            full_pitch = distributed_full_pitch_slots(
                stator.slot_count,
                rotor.pole_count,
            )
            coil_span = getattr(winding, "coil_span", None)
            if coil_span is not None:
                if not is_integer_q:
                    errors.append(
                        ErrorResponse(
                            error_code="INVALID_GEOMETRY",
                            message=(
                                f"explicit coil_span is not yet supported for fractional-q "
                                f"distributed layouts (q={q_value:g})."
                            ),
                            field="winding.coil_span",
                            suggestion=(
                                "Omit winding.coil_span for the generated fractional star-of-slots "
                                "layout, or use an integer-q slot/pole combination for short pitch."
                            ),
                        )
                    )
                    min_span = None
                    max_span = None
                else:
                    min_span = 2 * q
                    max_span = 3 * q
                if min_span is None or max_span is None:
                    pass
                elif coil_span < min_span or coil_span > max_span:
                    errors.append(
                        ErrorResponse(
                            error_code="INVALID_GEOMETRY",
                            message=(
                                f"coil_span={coil_span} is outside the supported "
                                f"short-pitch range [{min_span}, {max_span}] slots "
                                f"for this distributed layout (q={q}, full pitch={full_pitch:g})."
                            ),
                            field="winding.coil_span",
                            suggestion=(
                                f"Omit coil_span for full pitch ({full_pitch:g}) or choose "
                                f"an integer span from {min_span} to {max_span} slots."
                            ),
                        )
                    )
                elif winding.layers < 2 and coil_span != full_pitch:
                    errors.append(
                        ErrorResponse(
                            error_code="INVALID_GEOMETRY",
                            message=(
                                f"short-pitch coil_span={coil_span} requires layers=2; "
                                "a single-layer distributed winding has no upper-layer "
                                "return side to shift."
                            ),
                            field="winding.coil_span",
                            suggestion=(
                                f"Set winding.layers to 2, or omit coil_span/use "
                                f"full pitch ({full_pitch:g}) for a single-layer layout."
                            ),
                        )
                    )

            # Parallel paths must evenly divide the terminal coils available
            # per phase. Layers split one physical slot's
            # conductor bundle and do not multiply terminal coils.
            coils_per_phase = stator.slot_count // 6
            if winding.parallel_paths > 1 and coils_per_phase % winding.parallel_paths != 0:
                divisors = [p for p in range(1, 7) if coils_per_phase % p == 0]
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=f"parallel_paths={winding.parallel_paths} does not evenly divide the "
                        f"{coils_per_phase} coils per phase of this distributed layout "
                        f"({stator.slot_count} slots, {winding.layers} layer(s)).",
                        field="winding.parallel_paths",
                        suggestion=f"Use one of: {divisors}",
                    )
                )

    elif getattr(winding, "coil_span", None) is not None:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=(
                    "coil_span is only supported for distributed windings; "
                    "concentrated windings use tooth-wound coils."
                ),
                field="winding.coil_span",
                suggestion="Remove winding.coil_span or switch winding.type to 'distributed'.",
            )
        )

    # Bridge thickness should be positive for IPM (negative for SPM)
    if config.topology == "IPM" and rotor.bridge_thickness_mm <= 0:
        errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message="IPM topology requires positive bridge thickness",
                field="rotor.bridge_thickness_mm",
                suggestion="Set bridge_thickness_mm to a positive value (e.g., 1.5mm)",
            )
        )

    if config.topology == "IPM" and getattr(rotor, "ipm_topology", "flat_buried") == "pyleecan_holem50":
        rotor_outer_radius = rotor.OD_mm / 2
        rotor_inner_radius = (rotor.ID_mm or 0.0) / 2
        try:
            magnets, pockets = compute_pyleecan_holem50_placements(config)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=f"Pyleecan HoleM50 dimensions are invalid: {exc}",
                    field="rotor.holem50_w0_mm",
                    suggestion=(
                        "Reduce W0/W3 or adjust H0/H1 so pocket arcs and magnet faces "
                        "stay inside the rotor."
                    ),
                )
            )
        else:
            max_pocket_r = max(
                (math.hypot(x, y) for pocket in pockets for x, y in pocket.corners_mm),
                default=0.0,
            )
            min_pocket_r = min(
                (math.hypot(x, y) for pocket in pockets for x, y in pocket.corners_mm),
                default=rotor_outer_radius,
            )
            if max_pocket_r > rotor_outer_radius + 1.0e-6:
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=(
                            "Pyleecan HoleM50 pocket extends outside the rotor OD: "
                            f"outer pocket radius {max_pocket_r:.2f}mm exceeds "
                            f"{rotor_outer_radius:.2f}mm"
                        ),
                        field="rotor.holem50_h1_mm",
                        suggestion="Increase H1 or reduce W0/W3 so the pocket stays inside the rotor.",
                    )
                )
            if min_pocket_r <= rotor_inner_radius + 0.5:
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=(
                            "Pyleecan HoleM50 pocket overlaps the shaft/inner-rotor margin: "
                            f"inner pocket radius {min_pocket_r:.2f}mm, "
                            f"shaft margin needs > {rotor_inner_radius + 0.5:.2f}mm"
                        ),
                        field="rotor.ID_mm",
                        suggestion="Reduce rotor ID_mm or use a shallower HoleM50 pocket.",
                    )
                )
            if len(magnets) != rotor.pole_count * 2:
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message="Pyleecan HoleM50 generator did not produce two magnets per pole",
                        field="rotor.ipm_topology",
                        suggestion="Check HoleM50 dimensions and pole count.",
                    )
                )

    elif config.topology == "IPM" and getattr(rotor, "ipm_topology", "flat_buried") == "v_shape":
        rotor_outer_radius = rotor.OD_mm / 2
        rotor_inner_radius = (rotor.ID_mm or 0.0) / 2
        outer_bridge = rotor.outer_bridge_thickness_mm
        if outer_bridge <= 0:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message="V-shape IPM requires positive outer bridge thickness",
                    field="rotor.outer_bridge_thickness_mm",
                    suggestion="Set outer_bridge_thickness_mm to a positive value (e.g., 1.5mm)",
                )
            )
        if rotor.v_depth_mm <= 0:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message="V-shape IPM requires positive V depth",
                    field="rotor.v_depth_mm",
                    suggestion="Increase v_depth_mm so the V apex is inside the rotor.",
                )
            )

        magnets = compute_v_shape_magnet_placements(config)
        max_pocket_r = max((mag.outer_radius_mm for mag in magnets), default=0.0)
        min_pocket_r = min((mag.inner_radius_mm for mag in magnets), default=rotor_outer_radius)
        max_length_clamp = max(
            (mag.length_clamped_mm or 0.0 for mag in magnets), default=0.0
        )
        if max_length_clamp > 1e-6 or max_pocket_r > rotor_outer_radius - outer_bridge:
            if max_length_clamp > 1e-6:
                message = (
                    "V-shape IPM magnet does not fit below the outer bridge: "
                    f"magnet_width_mm is {max_length_clamp:.2f}mm longer than "
                    "the longest leg the V pocket can hold"
                )
            else:
                message = (
                    "V-shape IPM magnet pocket violates the outer bridge: "
                    f"outer pocket radius {max_pocket_r:.2f}mm exceeds "
                    f"{rotor_outer_radius - outer_bridge:.2f}mm"
                )
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=message,
                    field="rotor.v_depth_mm",
                    suggestion="Increase v_depth_mm, reduce magnet_width_mm, or reduce v_angle_deg.",
                )
            )
        if min_pocket_r <= rotor_inner_radius + 0.5:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=(
                        "V-shape IPM pocket overlaps the shaft/inner-rotor margin: "
                        f"inner pocket radius {min_pocket_r:.2f}mm, "
                        f"shaft margin needs > {rotor_inner_radius + 0.5:.2f}mm"
                    ),
                    field="rotor.v_depth_mm",
                    suggestion="Reduce v_depth_mm, reduce rotor ID_mm, or shorten the magnet.",
                )
            )

        pole_pitch_rad = 2 * 3.14159 / rotor.pole_count
        for mag in magnets:
            pole_center = (
                mag.pole_index * pole_pitch_rad
                + math.radians(getattr(rotor, "magnet_angle_deg", 0.0) or 0.0)
            )
            delta = abs(_normalize_signed_angle(mag.center_angle_rad - pole_center))
            if delta + mag.half_width_rad >= pole_pitch_rad / 2:
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message="V-shape IPM magnet pocket crosses into the adjacent pole pitch",
                        field="rotor.v_angle_deg",
                        suggestion="Reduce v_angle_deg or magnet_width_mm.",
                    )
                )
                break
        paired_overlap_reported = False
        for pole_idx in range(rotor.pole_count):
            pole_magnets = [mag for mag in magnets if mag.pole_index == pole_idx]
            for idx, mag_a in enumerate(pole_magnets):
                poly_a = mag_a.pocket_corners_mm or mag_a.corners_mm
                if poly_a is None:
                    continue
                for mag_b in pole_magnets[idx + 1:]:
                    poly_b = mag_b.pocket_corners_mm or mag_b.corners_mm
                    if poly_b is None:
                        continue
                    if _polygons_overlap(poly_a, poly_b):
                        errors.append(
                            ErrorResponse(
                                error_code="INVALID_GEOMETRY",
                                message=(
                                    "V-shape IPM paired magnet pockets overlap near the inner web"
                                ),
                                field="rotor.inner_web_thickness_mm",
                                suggestion=(
                                    "Increase inner_web_thickness_mm, reduce magnet_thickness_mm, "
                                    "or reduce pocket_clearance_mm."
                                ),
                            )
                        )
                        paired_overlap_reported = True
                        break
                if paired_overlap_reported:
                    break
            if paired_overlap_reported:
                break

    elif config.topology == "IPM":
        rotor_inner_radius = (rotor.ID_mm or 0.0) / 2
        # Same helper the builder places the pocket with.
        magnet_center_radius = magnet_radial_center_mm(config)
        pocket_inner_radius = (
            magnet_center_radius
            - rotor.magnet_thickness_mm / 2
            - rotor.pocket_clearance_mm
        )
        if pocket_inner_radius <= rotor_inner_radius + 0.5:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=(
                        "IPM magnet pocket overlaps the shaft/inner-rotor margin: "
                        f"inner pocket radius {pocket_inner_radius:.2f}mm, "
                        f"shaft margin needs > {rotor_inner_radius + 0.5:.2f}mm"
                    ),
                    field="rotor.magnet_thickness_mm",
                    suggestion="Reduce magnet thickness/clearance or reduce rotor ID_mm",
                )
            )

        flat_shape = getattr(rotor, "flat_buried_magnet_shape", "straight")
        if flat_shape != "legacy_arc":
            placements = compute_flat_buried_magnet_placements(config)
            maximum_pocket_radius = rotor.OD_mm / 2 - rotor.bridge_thickness_mm
            containment_reported = False
            for placement in placements:
                pocket = placement.pocket_corners_mm or placement.corners_mm
                if pocket is None:
                    continue
                actual_outer_radius = max(math.hypot(x, y) for x, y in pocket)
                if actual_outer_radius > maximum_pocket_radius + GEOMETRY_FIT_TOLERANCE_MM:
                    errors.append(
                        ErrorResponse(
                            error_code="INVALID_GEOMETRY",
                            message=(
                                "Flat-IPM pocket cannot preserve the requested outer bridge: "
                                f"a pocket corner reaches {actual_outer_radius:.2f}mm radius, "
                                f"beyond the {maximum_pocket_radius:.2f}mm bridge boundary"
                            ),
                            field="rotor.bridge_thickness_mm",
                            suggestion=(
                                "Reduce magnet_width_mm, pocket_clearance_mm, or bridge_thickness_mm, "
                                "or increase rotor OD_mm."
                            ),
                        )
                    )
                    containment_reported = True
                    break

            if not containment_reported and len(placements) > 1:
                for index, placement in enumerate(placements):
                    adjacent = placements[(index + 1) % len(placements)]
                    pocket = placement.pocket_corners_mm or placement.corners_mm
                    adjacent_pocket = (
                        adjacent.pocket_corners_mm or adjacent.corners_mm
                    )
                    if pocket is None or adjacent_pocket is None:
                        continue
                    if _polygons_overlap(pocket, adjacent_pocket):
                        errors.append(
                            ErrorResponse(
                                error_code="INVALID_GEOMETRY",
                                message=(
                                    "Adjacent straight flat-IPM magnet pockets overlap "
                                    f"between poles {placement.pole_index + 1} and "
                                    f"{adjacent.pole_index + 1}"
                                ),
                                field="rotor.magnet_width_mm",
                                suggestion=(
                                    "Reduce magnet_width_mm or pocket_clearance_mm, "
                                    "or use fewer poles."
                                ),
                            )
                        )
                        break
                    actual_side_web_mm = _polygons_minimum_distance_mm(
                        pocket,
                        adjacent_pocket,
                    )
                    if (
                        actual_side_web_mm + GEOMETRY_FIT_TOLERANCE_MM
                        < rotor.side_bridge_thickness_mm
                    ):
                        errors.append(
                            ErrorResponse(
                                error_code="INVALID_GEOMETRY",
                                message=(
                                    "Adjacent straight flat-IPM pockets leave only "
                                    f"{actual_side_web_mm:.2f}mm of tangential steel, "
                                    "below the requested side bridge "
                                    f"{rotor.side_bridge_thickness_mm:.2f}mm"
                                ),
                                field="rotor.side_bridge_thickness_mm",
                                suggestion=(
                                    "Reduce magnet_width_mm, pocket_clearance_mm, or "
                                    "side_bridge_thickness_mm, or use fewer poles."
                                ),
                            )
                        )
                        break
        else:
            # Curved compatibility projects retain the historical centerline-arc
            # budget. Straight bars use their actual rectangular pocket distance
            # above; applying this arc approximation to them over-rejects small
            # rotors whose corner-to-corner steel web is still sufficient.
            pole_pitch_at_magnet_mm = (
                2 * math.pi * max(magnet_center_radius, 1.0) / rotor.pole_count
            )
            if (
                rotor.magnet_width_mm
                + 2 * (rotor.side_bridge_thickness_mm + rotor.pocket_clearance_mm)
                > pole_pitch_at_magnet_mm
            ):
                errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=(
                            "IPM magnet width plus side bridges exceeds pole pitch at "
                            f"the magnet centerline ({pole_pitch_at_magnet_mm:.2f}mm)"
                        ),
                        field="rotor.side_bridge_thickness_mm",
                        suggestion="Reduce magnet_width_mm or side_bridge_thickness_mm",
                    )
                )

    # SPM-specific validation: airgap after magnets must be > 0.3mm
    if config.topology == "SPM":
        # For SPM, magnets are on the rotor surface
        # magnet_outer_radius = rotor_OD/2 + magnet_thickness
        # stator_inner_radius = stator_ID/2
        # airgap after magnets = stator_inner_radius - (rotor_OD/2 + magnet_thickness)
        magnet_outer_radius = (rotor.OD_mm + 2 * rotor.magnet_thickness_mm) / 2
        stator_inner_radius = stator.ID_mm / 2
        min_airgap_required = 0.3

        remaining_airgap = stator_inner_radius - magnet_outer_radius

        if remaining_airgap < min_airgap_required:
            errors.append(
                ErrorResponse(
                    error_code="INVALID_GEOMETRY",
                    message=f"SPM magnet extends too close to stator bore: "
                    f"remaining airgap {remaining_airgap:.2f}mm < {min_airgap_required}mm minimum",
                    field="rotor.magnet_thickness_mm",
                    suggestion=f"Reduce magnet_thickness_mm by at least {min_airgap_required - remaining_airgap:.2f}mm "
                    f"or increase stator ID_mm",
                )
            )

    return errors


def winding_feasibility_warnings(config: MotorConfig) -> list[str]:
    """Return non-blocking feasibility warnings for the winding layout.

    These accompany validate_geometry(): a config can be solvable but still
    have a layout worth flagging (unusual q, phase-belt approximation).
    Benchmark fixtures used for FEMM validation are expected to produce zero
    warnings.
    """
    winding = config.winding
    warnings: list[str] = []
    if winding.type != "distributed":
        return warnings

    pole_count = config.rotor.pole_count
    pole_pairs = pole_count // 2
    slot_count = config.stator.slot_count
    q_value = distributed_slots_per_pole_per_phase_value(slot_count, pole_count)
    if pole_pairs <= 0 or q_value < 1.0:
        return warnings  # infeasible layouts are validate_geometry() errors
    if not distributed_winding_is_balanced(
        slot_count,
        pole_count,
        winding.layers,
        getattr(winding, "coil_span", None),
    ):
        return warnings

    q = q_value
    if q > 4:
        warnings.append(
            f"Distributed winding has q={q:g} slots per pole per phase. Values above 4 give "
            "diminishing winding-factor benefit and increase manufacturing complexity."
        )
    return warnings


def _normalize_signed_angle(theta: float) -> float:
    while theta > 3.14159:
        theta -= 2 * 3.14159
    while theta <= -3.14159:
        theta += 2 * 3.14159
    return theta


def _polygons_overlap(
    poly_a: tuple[tuple[float, float], ...],
    poly_b: tuple[tuple[float, float], ...],
) -> bool:
    """Return true when two polygon windows overlap or cross."""
    for idx, point_a in enumerate(poly_a):
        next_a = poly_a[(idx + 1) % len(poly_a)]
        for jdx, point_b in enumerate(poly_b):
            next_b = poly_b[(jdx + 1) % len(poly_b)]
            if _segments_intersect(point_a, next_a, point_b, next_b):
                return True
    return any(point_in_polygon(x, y, poly_b) for x, y in poly_a) or any(
        point_in_polygon(x, y, poly_a) for x, y in poly_b
    )


def _polygons_minimum_distance_mm(
    poly_a: tuple[tuple[float, float], ...],
    poly_b: tuple[tuple[float, float], ...],
) -> float:
    """Return the shortest Euclidean edge distance between two polygons."""

    if _polygons_overlap(poly_a, poly_b):
        return 0.0

    minimum = math.inf
    for polygon, other in ((poly_a, poly_b), (poly_b, poly_a)):
        for point in polygon:
            for index, edge_start in enumerate(other):
                edge_end = other[(index + 1) % len(other)]
                minimum = min(
                    minimum,
                    _point_segment_distance_mm(point, edge_start, edge_end),
                )
    return minimum


def _point_segment_distance_mm(
    point: tuple[float, float],
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
) -> float:
    """Return the Euclidean distance from a point to a finite segment."""

    dx = segment_end[0] - segment_start[0]
    dy = segment_end[1] - segment_start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return math.dist(point, segment_start)
    projection = (
        (point[0] - segment_start[0]) * dx
        + (point[1] - segment_start[1]) * dy
    ) / length_squared
    projection = max(0.0, min(1.0, projection))
    closest = (
        segment_start[0] + projection * dx,
        segment_start[1] + projection * dy,
    )
    return math.dist(point, closest)


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """Return true for a strict crossing between two line segments."""
    o1 = _orientation(p1, p2, q1)
    o2 = _orientation(p1, p2, q2)
    o3 = _orientation(q1, q2, p1)
    o4 = _orientation(q1, q2, p2)
    return o1 * o2 < -1e-9 and o3 * o4 < -1e-9


def _orientation(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def create_machine(config: MotorConfig) -> Optional["Machine"]:
    """Create a Pyleecan Machine object from motor configuration.

    This function maps coilEM configuration parameters to Pyleecan's Machine model,
    supporting both IPM and SPM topologies. It handles:
    - Stator geometry and slotting (SlotW11 for distributed windings)
    - Rotor geometry and magnet placement (HoleM50 for IPM, SlotM13 for SPM)
    - Winding configuration (WindingDW2L or WindingCW2LT)
    - Material assignments

    Args:
        config: Motor configuration

    Returns:
        Pyleecan Machine object, or None if Pyleecan is not available

    Raises:
        ValueError: If configuration is geometrically invalid or topology is unknown
    """
    # Validate geometry before attempting machine creation
    # This check is done regardless of Pyleecan availability
    validation_errors = validate_geometry(config)
    if validation_errors:
        error_messages = "\n".join([e.message for e in validation_errors])
        raise ValueError(f"Geometry validation failed:\n{error_messages}")

    # Check topology validity before Pyleecan check
    if config.topology not in ("IPM", "SPM"):
        raise ValueError(f"Unknown topology: {config.topology}")

    if not PYLEECAN_AVAILABLE:
        return None

    # Create the appropriate machine type
    if config.topology == "IPM":
        machine = _create_ipm_machine(config)
    else:  # SPM (already validated above)
        machine = _create_spm_machine(config)

    return machine


def _create_ipm_machine(config: MotorConfig) -> "MachineIPMSM":
    """Create an Interior Permanent Magnet Synchronous Machine (IPM).

    IPM machines have magnets embedded in the rotor core, typically in flux-barrier
    arrangements. This function configures the HoleM50 slot type for magnet placement.

    Args:
        config: Motor configuration

    Returns:
        Configured MachineIPMSM object
    """
    # Convert dimensions from mm to meters (Pyleecan uses SI units)
    stator_od_m = config.stator.OD_mm / 1000
    stator_id_m = config.stator.ID_mm / 1000
    rotor_od_m = config.rotor.OD_mm / 1000
    stack_length_m = config.stator.stack_length_mm / 1000

    # Create stator with SlotW11 (rectangular slots)
    stator = Stator()
    stator.mat_type.name = config.materials.stator_steel
    stator.Rext = stator_od_m / 2  # Outer radius
    stator.Rint = stator_id_m / 2  # Inner radius (bore)
    stator.L1 = stack_length_m

    # Configure stator slot geometry
    slot = SlotW11()
    slot.Zs = config.stator.slot_count
    slot.W0 = config.stator.slot_opening_mm / 1000  # Slot opening width
    slot.W3 = config.stator.tooth_width_mm / 1000   # Tooth width
    # H0 (slot opening height) and H1, H2 (slot body heights) require winding geometry
    # These are left as defaults here; full optimization would require detailed winding design
    stator.slot = slot

    # Configure stator winding
    _configure_stator_winding(stator, config)

    # Create rotor with HoleM50 (magnet holes for IPM)
    rotor = Rotor()
    rotor.mat_type.name = config.materials.rotor_steel
    rotor.Rext = rotor_od_m / 2  # Outer radius
    rotor.L1 = stack_length_m

    # Configure rotor magnet holes (HoleM50 represents magnet placement in IPM)
    hole = HoleM50()
    hole.Zs = config.rotor.pole_count  # Number of poles (= number of magnet holes)
    hole.W0 = config.rotor.magnet_width_mm / 1000  # Magnet width at pole face
    hole.W3 = config.rotor.magnet_thickness_mm / 1000  # Magnet radial thickness
    hole.magnet_0.mat_type.name = config.materials.magnet_grade
    hole.magnet_0.Wmag = config.rotor.magnet_width_mm / 1000
    hole.magnet_0.Hmag = config.rotor.magnet_thickness_mm / 1000

    # IPM-specific parameters
    hole.W4 = config.rotor.bridge_thickness_mm / 1000  # Bridge thickness
    hole.magnet_0.alpha = config.rotor.magnet_embrace  # Magnet coverage fraction

    rotor.hole = [hole]

    # Create machine
    machine = MachineIPMSM()
    machine.stator = stator
    machine.rotor = rotor
    machine.name = "IPM Motor (coilEM)"

    return machine


def _create_spm_machine(config: MotorConfig) -> "MachineSIPMSM":
    """Create a Surface Interior Permanent Magnet Synchronous Machine (SPM).

    SPM machines have magnets mounted on the rotor surface. This function uses
    SlotM13 for surface magnet slots.

    Args:
        config: Motor configuration

    Returns:
        Configured MachineSIPMSM object
    """
    # Convert dimensions from mm to meters
    stator_od_m = config.stator.OD_mm / 1000
    stator_id_m = config.stator.ID_mm / 1000
    rotor_od_m = config.rotor.OD_mm / 1000
    stack_length_m = config.stator.stack_length_mm / 1000

    # Create stator with SlotW11
    stator = Stator()
    stator.mat_type.name = config.materials.stator_steel
    stator.Rext = stator_od_m / 2
    stator.Rint = stator_id_m / 2
    stator.L1 = stack_length_m

    # Configure stator slot geometry
    slot = SlotW11()
    slot.Zs = config.stator.slot_count
    slot.W0 = config.stator.slot_opening_mm / 1000
    slot.W3 = config.stator.tooth_width_mm / 1000
    stator.slot = slot

    # Configure stator winding
    _configure_stator_winding(stator, config)

    # Create rotor with SlotM13 (surface magnets for SPM)
    rotor = Rotor()
    rotor.mat_type.name = config.materials.rotor_steel
    rotor.Rext = rotor_od_m / 2
    rotor.L1 = stack_length_m

    # Configure rotor surface magnet slots (SlotM13)
    slot = SlotM13()
    slot.Zs = config.rotor.pole_count
    slot.W0 = config.rotor.magnet_width_mm / 1000
    slot.H0 = config.rotor.magnet_thickness_mm / 1000
    slot.magnet_0.mat_type.name = config.materials.magnet_grade
    slot.magnet_0.Wmag = config.rotor.magnet_width_mm / 1000
    slot.magnet_0.Hmag = config.rotor.magnet_thickness_mm / 1000

    rotor.slot = slot

    # Create machine
    machine = MachineSIPMSM()
    machine.stator = stator
    machine.rotor = rotor
    machine.name = "SPM Motor (coilEM)"

    return machine


def _configure_stator_winding(stator: "Stator", config: MotorConfig) -> None:
    """Configure stator winding based on winding configuration.

    This helper function sets up the winding pattern, either distributed (DW2L)
    or concentrated (CW2LT).

    Args:
        stator: Stator object to configure
        config: Motor configuration with winding details
    """
    # Determine winding type
    #
    # WindingDW2L is instantiated for EVERY distributed
    # config, including single-layer ones (e.g. the ORNL Prius fixture declares
    # layers: 1). This is inert in practice:
    #   1. pyleecan is not installed in the runtime venv and is not declared in
    #      requirements.txt/pyproject.toml, so PYLEECAN_AVAILABLE is False and
    #      create_machine() returns None before reaching this helper.
    #   2. create_machine() has no callers in backend/, scripts/, or tests/ —
    #      the FEMM and Magneto2D lanes build geometry via geometry_drawer /
    #      femm_geometry, never through pyleecan. This is legacy integration.
    #   3. This code targets the pre-1.1 pyleecan API where the per-layer-count
    #      classes (WindingDW1L/WindingDW2L) carried an Nlay attribute; setting
    #      Nlay=1 on WindingDW2L was the old-API idiom for a single-layer
    #      distributed winding. Modern pyleecan (>=1.1) removed these classes
    #      in favor of a unified Winding.Nlayer, so if pyleecan integration is
    #      ever revived this helper must be rewritten against the new API
    #      rather than patched per-layer here.
    if config.winding.type == "distributed":
        winding = WindingDW2L()
    else:  # concentrated
        winding = WindingCW2LT()

    # Set winding parameters
    winding.Ntcoil = config.winding.turns_per_coil
    winding.Nlay = config.winding.layers
    winding.Npcpp = config.winding.parallel_paths

    stator.winding = winding
