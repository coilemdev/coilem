"""Derived machine constants (Kt, Ke, λ_pm) that fall out of a standard
loaded + no-load solve.

Why this lives on its own module:
  The three constants here are what a drive engineer actually writes on a
  datasheet — the quantities that parameterize the motor inside a system
  model, not inside a finite-element model. They're cheap derivations from
  numbers we already compute in `SolveSummary`, but they deserve their own
  docstring so the conventions are unambiguous.

Conventions (amplitude-invariant dq, single-turn per-phase):
  * `current_amplitude_A`       — peak phase current (not RMS).
  * `back_emf_fundamental_V`    — RMS line-to-neutral amplitude of the
                                  fundamental (order 1). This matches the
                                  convention used throughout the codebase
                                  (see `SolveSummary.back_emf_fundamental_V`
                                  and `fundamental_rms` in femm_postprocess /
                                  the Rust solver's `back_emf_fundamental_rms_v`).
  * `rated_speed_rpm`            — mechanical shaft speed in RPM.
  * `pole_pairs`                — P = pole_count / 2.

Definitions:
  ω_m      = 2π · rated_rpm / 60                  [rad/s mechanical]
  ω_e      = P · ω_m                              [rad/s electrical]
  E_peak_LN = √2 · back_emf_fundamental_V_rms_LN  [V, peak line-to-neutral]

  Kt   = avg_torque_Nm / current_amplitude_A      [Nm / A_peak]
  Ke   = E_peak_LN / ω_m                          [V·s / rad_mech]
  λ_pm = E_peak_LN / ω_e = Ke / P                 [Wb, peak flux linkage amplitude]

Sanity identity (non-salient PM at i_d = 0, amplitude-invariant Park):
  Kt  ≈  (3/2) · Ke         and         Kt / Ke → 1.5

If the ratio drifts far from 1.5 the solve point is saturated, salient, or
not at the aligned-q operating point. We don't enforce the identity here —
just compute the three numbers and let the UI surface them so the engineer
can eyeball the ratio.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

# Below this we consider the solve "no-load" and don't publish Kt — it would
# blow up numerically and doesn't mean anything without current injection.
_KT_MIN_CURRENT_A = 0.1
# Back-EMF needs at least this fundamental to mean anything; microvolt-level
# no-op results should not drive lambda_pm divisions.
_EMF_MIN_V = 1e-3
# Speed floor — below this we're essentially DC and Ke is undefined.
_RPM_MIN = 1.0


def compute_machine_constants(
    *,
    avg_torque_Nm: Optional[float],
    current_amplitude_A: Optional[float],
    back_emf_fundamental_V_rms_LN: Optional[float],
    rated_speed_rpm: Optional[float],
    pole_count: Optional[int],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute (Kt, Ke, λ_pm) from the standard loaded + no-load quantities.

    Returns a tuple of (Kt_Nm_per_A, Ke_Vs_per_rad_mech, lambda_pm_Wb).
    Each element is None when the relevant input is missing or the solve
    regime makes the constant undefined (e.g. Kt at zero current).
    """

    # Kt — needs a loaded solve with meaningful phase current.
    kt: Optional[float] = None
    current_amplitude = current_amplitude_A
    average_torque = avg_torque_Nm
    if current_amplitude is not None and average_torque is not None:
        if (
            _is_finite_positive(current_amplitude)
            and current_amplitude >= _KT_MIN_CURRENT_A
            and math.isfinite(average_torque)
        ):
            kt = average_torque / current_amplitude

    # Ke and λ_pm — need the no-load fundamental, a speed, and pole count.
    ke: Optional[float] = None
    lambda_pm: Optional[float] = None
    emf_fundamental_v_rms_ln = back_emf_fundamental_V_rms_LN
    speed_rpm = rated_speed_rpm
    if (
        emf_fundamental_v_rms_ln is not None
        and speed_rpm is not None
        and pole_count is not None
        and pole_count >= 2
    ):
        if (
            _is_finite_positive(emf_fundamental_v_rms_ln)
            and emf_fundamental_v_rms_ln >= _EMF_MIN_V
            and _is_finite_positive(speed_rpm)
            and speed_rpm >= _RPM_MIN
        ):
            pole_pairs = pole_count // 2
            omega_mech = 2.0 * math.pi * speed_rpm / 60.0
            e_peak_ln = math.sqrt(2.0) * emf_fundamental_v_rms_ln
            ke = e_peak_ln / omega_mech
            lambda_pm = ke / pole_pairs

    return kt, ke, lambda_pm


def _is_finite_positive(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x) and x > 0.0
