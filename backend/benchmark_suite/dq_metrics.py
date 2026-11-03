"""Registered λd/λq gates (protocol 1.6.0): loaded d/q flux linkage against the reference.

The reference records raw per-position phase flux linkages and phase
currents, loaded and at no load. The harness applies coilEM's own transform
(backend/dq_flux_linkage.py: amplitude-invariant Park, d-axis fitted from the
no-load flux linkage, positions averaged) to them, so candidate and
reference cannot differ by convention. Errors are shares of the reference's
loaded flux-linkage magnitude, which keeps λq meaningful where it is small.

A reference whose own d/q torque, 1.5·P·(λd·iq − λq·id), does not reproduce
its solved torque points to a convention or bookkeeping mistake in the
reference, so that check is a gate of its own.
"""

import math

from backend.benchmark_suite.abc_metrics import band

# Percent of the reference's |λdq|: pass, then yellow.
DQ_FLUX_LINKAGE_PCT = (3.0, 6.0)
# Percent between the reference's d/q torque and its solved torque: pass, then yellow.
DQ_REFERENCE_TORQUE_PCT = (2.0, 5.0)

_STATUS_ORDER = ("MISSING", "FAIL", "YELLOW", "PASS")


def _series(waveform, key):
    values = (waveform or {}).get(key)
    if not isinstance(values, list) or not values:
        return None
    try:
        out = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(value) for value in out) else None


def reference_dq(reference, config):
    """The reference's d/q record from its raw waveforms, or None when they are incomplete."""

    from backend.dq_flux_linkage import dq_flux_linkage

    loaded = reference.get("loaded_flux_linkage_waveform")
    current = reference.get("phase_current_waveform")
    no_load = reference.get("no_load_flux_linkage_waveform")
    angles = _series(loaded, "electrical_angle_deg")
    flux = [_series(loaded, f"phase_{phase}_Wb") for phase in "abc"]
    currents = [_series(current, f"phase_{phase}_A") for phase in "abc"]
    no_load_angles = _series(no_load, "electrical_angle_deg")
    no_load_flux = [_series(no_load, f"phase_{phase}_Wb") for phase in "abc"]
    torque = (reference.get("summary") or {}).get("avg_torque_Nm")
    if angles is None or None in flux or None in currents or no_load_angles is None or None in no_load_flux or torque is None:
        return None
    if _series(current, "electrical_angle_deg") != angles:
        return None
    record = dq_flux_linkage(
        pole_pairs=max(1, int(config["rotor"]["pole_count"]) // 2),
        loaded_angles_deg=angles,
        loaded_flux_linkage_abc=flux,
        phase_current_abc=currents,
        solved_torque_nm=float(torque),
        no_load_angles_deg=no_load_angles,
        no_load_flux_linkage_abc=no_load_flux,
    )
    return None if record is None else record.model_dump(mode="json")


def dq_gates(candidate, reference, config):
    """λd, λq and reference-consistency gates with the numbers behind them."""

    measured = (candidate.get("summary") or {}).get("dq_flux_linkage") or {}
    expected = reference_dq(reference, config)
    details = {"candidate": measured or None, "reference": expected}
    if not measured or expected is None:
        return {"lambda_d": "MISSING", "lambda_q": "MISSING", "reference_dq_torque": "MISSING"}, details
    scale = math.hypot(expected["lambda_d_Wb"], expected["lambda_q_Wb"])
    if not scale > 0:
        return {"lambda_d": "MISSING", "lambda_q": "MISSING", "reference_dq_torque": "MISSING"}, details
    error_d = abs(measured["lambda_d_Wb"] - expected["lambda_d_Wb"]) / scale * 100
    error_q = abs(measured["lambda_q_Wb"] - expected["lambda_q_Wb"]) / scale * 100
    agreement = expected.get("torque_agreement_pct")
    consistency = abs(agreement - 100.0) if agreement is not None else None
    details.update(lambda_d_error_pct=error_d, lambda_q_error_pct=error_q, reference_dq_torque_error_pct=consistency)
    return {
        "lambda_d": band(error_d, *DQ_FLUX_LINKAGE_PCT),
        "lambda_q": band(error_q, *DQ_FLUX_LINKAGE_PCT),
        "reference_dq_torque": band(consistency, *DQ_REFERENCE_TORQUE_PCT),
    }, details


def with_dq_gates(evaluation, candidate, reference, config):
    """The A/B/C evaluation with the d/q gates added and the status recomputed over all gates."""

    gates, details = dq_gates(candidate, reference, config)
    merged = {**evaluation.get("gates", {}), **gates}
    values = set(merged.values())
    worst = next((status for status in _STATUS_ORDER if status in values), "PASS")
    status = "INCOMPLETE" if worst == "MISSING" else worst
    return {**evaluation, "gates": merged, "status": status, "dq": details}
