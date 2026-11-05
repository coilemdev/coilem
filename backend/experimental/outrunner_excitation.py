"""Audited source winding → the common public clockwise current profiles."""
from backend.excitation import resolve_public_current_profile
from backend.experimental.outrunner_project import OutrunnerAnalysis
from backend.experimental.outrunner_sweep import PERIOD_DEG, POLE_PAIRS, SweepCase

# From the exact source: slots at 15+30*k degrees, signed 15-turn sides;
# their p=7 winding phasors are A=-90°, B=150°, C=30°. The gap-facing
# rotor north axis is at 0°. Relative to the common public profile this
# requires a 90° electrical offset and interchange of channels B/C.
# These are geometry conventions, not a fit to measured torque or EMF.
PHASE_AXIS_OFFSET_ELEC_DEG = 90.0
SOURCE_PHASE_ORDER = (0, 2, 1)


def running(settings: OutrunnerAnalysis) -> bool:
    return settings.excitation_mode != "fixed_phase_currents"


def currents_at(settings: OutrunnerAnalysis, angle_ccw_deg: float, *, noload: bool = False) -> tuple[float, float, float]:
    if noload:
        return (0., 0., 0.)
    if not running(settings):
        return tuple(settings.loaded_currents_A)
    sample = resolve_public_current_profile(
        settings.excitation_mode, settings.current_amplitude_A, settings.current_amplitude_convention,
        -POLE_PAIRS*angle_ccw_deg, axis_offset_deg=PHASE_AXIS_OFFSET_ELEC_DEG,
        current_angle_deg=settings.current_angle_deg, advance_deg=settings.commutation_advance_deg,
    )
    return tuple(sample.phase_current_a[index] for index in SOURCE_PHASE_ORDER)


def sweep_cases(settings: OutrunnerAnalysis, analysis: str) -> list[SweepCase]:
    if analysis == "source_point":
        return [SweepCase("source_point", 0, currents_at(settings, 0), "source_point", "full")]
    sign = -1 if running(settings) else 1
    cases = []
    for family in ("loaded", "noload"):
        if analysis not in ("both", "loaded_torque" if family == "loaded" else "noload_bemf"):
            continue
        for index in range(settings.unique_samples+1):
            angle = sign*PERIOD_DEG*index/settings.unique_samples
            cases.append(SweepCase(f"{family}_{index:04d}", angle, currents_at(settings, angle, noload=family == "noload"), family))
    return cases
