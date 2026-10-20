"""Loaded d/q flux linkage at the solved operating point (#113).

The d-axis is the magnets' axis, measured from the no-load flux linkage
rather than taken from the excitation code's angle conventions: at each
no-load position the phase flux-linkage space vector points along d. A fit of
that angle against rotor position gives its offset and direction of
rotation, so the same fit places d at every loaded position.

The loaded phase flux linkages and the phase currents the solve actually
applied (the slot-excitation frames) then go through an amplitude-invariant
Park transform. The q-axis is 90 electrical degrees ahead of d in the
direction the rotor angle increases, so positive torque is
T = 1.5 · P · (λd · iq − λq · id), the convention of
backend.models.performance. The sweep turns the rotor in the direction the
reported torque counts positive (counter-clockwise natively, clockwise on the
launch surface), so the d/q torque compares with the reported torque as it
stands on both. Averaging over the loaded positions removes the ripple.

The torque implied by the loaded flux linkage includes reluctance torque and
saturation, so its agreement with the solver's torque is a check on the
solve itself, unlike the no-load Kt / 1.5·Ke ratio.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from backend.models import DqFluxLinkage

_MIN_POSITIONS = 3
_TINY_CURRENT_A = 1e-6
_TINY_TORQUE_NM = 1e-9


def _clarke(a: float, b: float, c: float) -> tuple[float, float]:
    """Amplitude-invariant Clarke transform: a balanced set of peak X maps to |(α, β)| = X."""

    return (2.0 / 3.0) * (a - 0.5 * (b + c)), (b - c) / math.sqrt(3.0)


def _fit_d_axis(angles_deg: Sequence[float], abc: Sequence[Sequence[float]]) -> tuple[int, float, float] | None:
    """Direction (+1 or −1), offset (rad) and mean amplitude of a space vector that turns with the rotor.

    For no-load flux linkage the vector is the d-axis and the amplitude is λpm.
    """

    vectors = [_clarke(a, b, c) for a, b, c in zip(*abc)]
    if len(vectors) < _MIN_POSITIONS or len(vectors) != len(angles_deg):
        return None
    magnitudes = [math.hypot(alpha, beta) for alpha, beta in vectors]
    if max(magnitudes) <= 0:
        return None
    phases = [math.atan2(beta, alpha) for alpha, beta in vectors]
    best: tuple[float, int, float] | None = None
    for direction in (1, -1):
        offsets = [phase - direction * math.radians(angle) for phase, angle in zip(phases, angles_deg)]
        sx = sum(math.cos(offset) for offset in offsets)
        sy = sum(math.sin(offset) for offset in offsets)
        concentration = math.hypot(sx, sy) / len(offsets)
        if best is None or concentration > best[0]:
            best = (concentration, direction, math.atan2(sy, sx))
    concentration, direction, offset = best
    # A clean fit leaves the offsets bunched; a scattered one means the no-load
    # samples do not follow the rotor, so no d-axis can be placed.
    if concentration < 0.9:
        return None
    return direction, offset, sum(magnitudes) / len(magnitudes)


def dq_flux_linkage(
    *,
    pole_pairs: int,
    loaded_angles_deg: Sequence[float],
    loaded_flux_linkage_abc: Sequence[Sequence[float]],
    phase_current_abc: Sequence[Sequence[float]],
    solved_torque_nm: float,
    no_load_angles_deg: Sequence[float] | None = None,
    no_load_flux_linkage_abc: Sequence[Sequence[float]] | None = None,
    commanded_current_angle_deg: float | None = None,
) -> DqFluxLinkage | None:
    """The averaged d/q record, or None when the inputs cannot place the d-axis.

    The d-axis comes from the no-load flux linkage when the run has it.
    Without it, a commanded current angle places the axis from the applied
    currents instead: their space vector sits at d + (90° + γ) in the
    direction of rotation. The measured current angle then equals the
    commanded one by construction, so only the no-load route checks it.
    """

    count = len(loaded_angles_deg)
    if count < 1 or any(len(series) != count for series in (*loaded_flux_linkage_abc, *phase_current_abc)):
        return None
    lambda_pm: float | None = None
    source = "no_load_flux_linkage"
    fit = None
    if no_load_angles_deg is not None and no_load_flux_linkage_abc is not None:
        fit = _fit_d_axis(no_load_angles_deg, no_load_flux_linkage_abc)
    if fit is not None:
        direction, offset, lambda_pm = fit
    elif commanded_current_angle_deg is not None and math.isfinite(commanded_current_angle_deg):
        current_fit = _fit_d_axis(loaded_angles_deg, phase_current_abc)
        if current_fit is None:
            return None
        direction, current_offset, _ = current_fit
        offset = current_offset - direction * math.radians(90.0 + commanded_current_angle_deg)
        source = "applied_current_angle"
    else:
        return None
    sums = [0.0, 0.0, 0.0, 0.0]
    for index, angle in enumerate(loaded_angles_deg):
        theta = direction * math.radians(angle) + offset
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        for slot, abc in ((0, loaded_flux_linkage_abc), (2, phase_current_abc)):
            alpha, beta = _clarke(abc[0][index], abc[1][index], abc[2][index])
            sums[slot] += alpha * cos_t + beta * sin_t
            # q is 90° ahead of d in the direction the rotor angle increases.
            sums[slot + 1] += direction * (-alpha * sin_t + beta * cos_t)
    lambda_d, lambda_q, i_d, i_q = (value / count for value in sums)
    torque_dq = 1.5 * pole_pairs * (lambda_d * i_q - lambda_q * i_d)
    agreement = (
        100.0 * solved_torque_nm / torque_dq
        if math.isfinite(solved_torque_nm) and abs(torque_dq) > _TINY_TORQUE_NM
        else None
    )
    current = math.hypot(i_d, i_q)
    return DqFluxLinkage(
        i_d_A=i_d,
        i_q_A=i_q,
        lambda_d_Wb=lambda_d,
        lambda_q_Wb=lambda_q,
        torque_dq_Nm=torque_dq,
        torque_agreement_pct=agreement,
        current_angle_deg=math.degrees(math.atan2(-i_d, i_q)) if current > _TINY_CURRENT_A else None,
        lambda_pm_Wb=lambda_pm,
        apparent_L_d_H=(
            (lambda_d - lambda_pm) / i_d if lambda_pm is not None and abs(i_d) > _TINY_CURRENT_A * max(1.0, current) * 1e3 else None
        ),
        apparent_L_q_H=lambda_q / i_q if abs(i_q) > _TINY_CURRENT_A * max(1.0, current) * 1e3 else None,
        positions=count,
        d_axis_source=source,
    )


def dq_flux_linkage_from_sweep(
    sweep: dict[str, Any],
    slot_excitation_frames: Sequence[Any] | None,
    *,
    pole_count: int,
    solved_torque_nm: float,
    commanded_current_angle_deg: float | None = None,
) -> DqFluxLinkage | None:
    """Read the sweep report and the applied phase currents; None for anything incomplete.

    commanded_current_angle_deg places the d-axis when the sweep has no
    no-load samples (a run without the back-EMF sweep); pass it only for
    sinusoidal current.
    """

    def numbers(key: str) -> list[float] | None:
        values = sweep.get(key)
        if not isinstance(values, list) or not values:
            return None
        try:
            out = [float(value) for value in values]
        except (TypeError, ValueError):
            return None
        return out if all(math.isfinite(value) for value in out) else None

    loaded_angles = numbers("rotor_positions_elec_deg")
    loaded = [numbers(f"loaded_flux_linkage_{phase}_wb") for phase in "abc"]
    if loaded_angles is None or any(v is None for v in loaded):
        return None
    no_load_angles = numbers("no_load_rotor_positions_elec_deg")
    no_load = [numbers(f"no_load_flux_linkage_{phase}_wb") for phase in "abc"]
    if no_load_angles is None or any(v is None for v in no_load):
        no_load_angles, no_load = None, None
    if not slot_excitation_frames or len(slot_excitation_frames) != len(loaded_angles):
        return None
    currents: list[list[float]] = [[], [], []]
    for frame, angle in zip(slot_excitation_frames, loaded_angles):
        frame_angle = getattr(frame, "angle_deg", None)
        sample = getattr(frame, "phase_current_a", None)
        if frame_angle is None or abs(float(frame_angle) - angle) > 1e-6 or not sample or len(sample) != 3:
            return None
        for phase in range(3):
            currents[phase].append(float(sample[phase]))
    return dq_flux_linkage(
        pole_pairs=max(1, pole_count // 2),
        loaded_angles_deg=loaded_angles,
        loaded_flux_linkage_abc=loaded,
        phase_current_abc=currents,
        solved_torque_nm=solved_torque_nm,
        no_load_angles_deg=no_load_angles,
        no_load_flux_linkage_abc=no_load,
        commanded_current_angle_deg=commanded_current_angle_deg,
    )
