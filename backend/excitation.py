"""Solver-neutral stator excitation profiles.

The public product frame is clockwise-positive, while the geometry/solver
kernels are counterclockwise-positive. Production adapters mirror the public
config before invoking this module; the pure ``clockwise_positive`` helper is
provided for shared golden-vector tests and user-facing waveform generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from backend.models import MotorConfig
from backend.winding_utils import winding_phase_axis_offset_elec_deg

ExcitationMode = Literal["sinusoidal", "ideal_six_step_120"]

SINUSOIDAL: Literal["sinusoidal"] = "sinusoidal"
IDEAL_SIX_STEP_120: Literal["ideal_six_step_120"] = "ideal_six_step_120"
EXCITATION_CONVENTION_VERSION = "openem.excitation/v1"

# Native counterclockwise-positive solver-frame table. The public clockwise
# table is obtained by the same theta -> -theta, advance -> 180-advance mirror
# used by backend.solver._clockwise_excitation_config.
_NATIVE_SIX_STEP_TABLE: tuple[tuple[int, int, int], ...] = (
    (-1, 0, 1),
    (0, -1, 1),
    (1, -1, 0),
    (1, 0, -1),
    (0, 1, -1),
    (-1, 1, 0),
)
_PUBLIC_SIX_STEP_TABLE: tuple[tuple[int, int, int], ...] = (
    (1, -1, 0),
    (0, -1, 1),
    (-1, 0, 1),
    (-1, 1, 0),
    (0, 1, -1),
    (1, 0, -1),
)


def _scaled_phase_currents(
    current_a: float,
    row: tuple[int, int, int],
) -> tuple[float, float, float]:
    """Scale one frozen three-phase command without losing tuple arity."""
    return (
        float(current_a) * row[0],
        float(current_a) * row[1],
        float(current_a) * row[2],
    )


@dataclass(frozen=True)
class PhaseCurrentSample:
    """Resolved terminal phase currents for one rotor electrical angle."""

    excitation_mode: ExcitationMode
    phase_current_a: tuple[float, float, float]
    effective_electrical_angle_deg: float
    source_current_angle_deg: float | None
    sector_index: int | None
    convention_version: str = EXCITATION_CONVENTION_VERSION


def wrap_360(angle_deg: float) -> float:
    """Normalize a finite angle into [0, 360), keeping exact boundaries."""
    if not math.isfinite(angle_deg):
        raise ValueError("electrical angle must be finite")
    wrapped = angle_deg % 360.0
    return 0.0 if wrapped == 360.0 else wrapped


def _normalize_commutation_boundary(angle_deg: float) -> float:
    """Match Rust's sector-boundary handling after angle unit roundtrips."""
    wrapped = wrap_360(angle_deg)
    nearest_boundary = round(wrapped / 60.0) * 60.0
    # Snap representation noise only; +/-1e-9 degree probes remain on their
    # respective sides of the lower-inclusive commutation boundary.
    if abs(wrapped - nearest_boundary) <= 1.0e-12:
        return wrap_360(nearest_boundary)
    return wrapped


def excitation_mode(config: MotorConfig) -> ExcitationMode:
    if config.solve_params is None:
        return SINUSOIDAL
    return config.solve_params.excitation_mode


def _sine_peak_current_a(config: MotorConfig) -> float:
    sp = config.solve_params
    if sp is None:
        return 0.0
    if sp.current_amplitude_convention == "rms":
        return float(sp.current_amplitude_A) * math.sqrt(2.0)
    if sp.current_amplitude_convention == "peak":
        return float(sp.current_amplitude_A)
    raise ValueError("sinusoidal excitation does not accept plateau current")



def phase_axis_offset_deg(config: MotorConfig) -> float:
    """Phase A's axis angle for this winding (#91).

    The current-angle convention assumes phase A's axis at 0 degrees electrical.
    Phase belts wider than one slot put it at the belt centre and tooth coils on
    a tooth, so the excitation subtracts this angle to keep gamma measured from
    the q-axis and six-step commutation in step. Mirrors
    solvers/magneto2d/src/sources.rs winding_phase_axis_offset_elec_deg.
    """

    return winding_phase_axis_offset_elec_deg(
        config.winding.type,
        config.stator.slot_count,
        config.rotor.pole_count,
        config.winding.layers,
        getattr(config.winding, "coil_span", None),
    )
def _resolve_native_six_step(
    current_a: float,
    rotor_electrical_angle_deg: float,
    commutation_advance_deg: float,
) -> PhaseCurrentSample:
    effective = _normalize_commutation_boundary(
        rotor_electrical_angle_deg + commutation_advance_deg
    )
    sector = int(math.floor(effective / 60.0))
    row = _NATIVE_SIX_STEP_TABLE[sector]
    return PhaseCurrentSample(
        excitation_mode=IDEAL_SIX_STEP_120,
        phase_current_a=_scaled_phase_currents(current_a, row),
        effective_electrical_angle_deg=effective,
        source_current_angle_deg=None,
        sector_index=sector,
    )


def _resolve_public_six_step(
    current_a: float,
    rotor_electrical_angle_deg: float,
    commutation_advance_deg: float,
) -> PhaseCurrentSample:
    effective = _normalize_commutation_boundary(
        rotor_electrical_angle_deg + commutation_advance_deg
    )
    sector = int(math.floor(effective / 60.0))
    row = _PUBLIC_SIX_STEP_TABLE[sector]
    return PhaseCurrentSample(
        excitation_mode=IDEAL_SIX_STEP_120,
        phase_current_a=_scaled_phase_currents(current_a, row),
        effective_electrical_angle_deg=effective,
        source_current_angle_deg=None,
        sector_index=sector,
    )


def resolve_phase_current_sample(
    config: MotorConfig,
    rotor_electrical_angle_deg: float,
    *,
    clockwise_positive: bool = False,
) -> PhaseCurrentSample:
    """Resolve the exact terminal A/B/C currents for one rotor angle.

    Normal solver callers pass the internal counterclockwise-positive angle
    and an already-mirrored config. Golden-vector/UI callers may pass the
    public clockwise-positive angle with ``clockwise_positive=True``.
    """
    sp = config.solve_params
    if sp is None:
        return PhaseCurrentSample(
            excitation_mode=SINUSOIDAL,
            phase_current_a=(0.0, 0.0, 0.0),
            effective_electrical_angle_deg=wrap_360(rotor_electrical_angle_deg),
            source_current_angle_deg=None,
            sector_index=None,
        )

    if sp.excitation_mode == IDEAL_SIX_STEP_120:
        if sp.current_amplitude_convention != "plateau":
            raise ValueError(
                "ideal_six_step_120 requires current_amplitude_convention='plateau'"
            )
        rotor_angle = float(rotor_electrical_angle_deg)
        advance = float(sp.commutation_advance_deg)
        axis_offset = phase_axis_offset_deg(config)
        if clockwise_positive or sp.excitation_rotation_convention == "clockwise_positive_ui":
            public_rotor_angle = rotor_angle if clockwise_positive else -rotor_angle
            return _resolve_public_six_step(
                float(sp.current_amplitude_A),
                public_rotor_angle + axis_offset,
                advance,
            )
        return _resolve_native_six_step(
            float(sp.current_amplitude_A),
            rotor_angle - axis_offset,
            advance,
        )

    source_angle = (
        float(rotor_electrical_angle_deg)
        - 90.0
        + float(sp.current_angle_deg)
        - phase_axis_offset_deg(config)
    )
    peak = _sine_peak_current_a(config)
    theta = math.radians(source_angle)
    currents = (
        peak * math.sin(theta),
        peak * math.sin(theta - 2.0 * math.pi / 3.0),
        peak * math.sin(theta - 4.0 * math.pi / 3.0),
    )
    return PhaseCurrentSample(
        excitation_mode=SINUSOIDAL,
        phase_current_a=currents,
        effective_electrical_angle_deg=wrap_360(rotor_electrical_angle_deg),
        source_current_angle_deg=source_angle,
        sector_index=None,
    )


def phase_current_sample_dict(sample: PhaseCurrentSample) -> dict[str, float]:
    """Return a phase-name mapping for winding/current-density consumers."""
    return dict(zip(("A", "B", "C"), sample.phase_current_a, strict=True))


def terminal_to_slot_current_scale(config: MotorConfig) -> float:
    """Map public terminal phase current to the homogenized slot-side source.

    Every excitation mode drives each slot side with the terminal current: the
    flux-linkage extractors credit the same turns_per_coil per slot side
    (winding_utils.flux_linkage_slot_side_turn_factor), so source and linkage
    stay reciprocal. Six-step concentrated single-layer windings used to halve
    this source to match a halved flux-linkage credit (#80).
    """
    return 1.0
