"""Phase E cogging gates (protocol 1.7.0, public issue 185).

coilEM's cogging sweep is compared with a FEMM 4.2 no-load torque waveform
over the same cogging period at the same rotor positions. Both sides are
summarised by `backend.cogging.cogging_record`, so the peak-to-peak and the
first cogging harmonic have one definition. Neither waveform is aligned,
fitted or filtered.

A relative error means nothing for a low-cogging design, so each gate also
passes within an absolute floor registered with the case: 0.5% of the FEMM
mean loaded torque of the case's registered base request
(docs/COGGING_BENCHMARK_PROPOSAL.md). Two self-checks test the reference on
its own, as `reference_dq_torque` does for the d/q points: an exact solve
repeats at the end of the period and averages to zero over it.
"""

from __future__ import annotations

from backend.benchmark_suite.abc_metrics import waveform_metrics
from backend.cogging import cogging_record

# Percent of the reference value: pass, then yellow. The floor widens both.
COGGING_RELATIVE_PCT = (10.0, 20.0)
# The method the registered cases are measured with (docs/COGGING_CONVERGENCE.md).
COGGING_METHOD = "weighted_stress"
_ANGLE_TOLERANCE_DEG = 1e-6
_STATUS_ORDER = ("MISSING", "FAIL", "YELLOW", "PASS")


def _relative_band(candidate: float, reference: float, floor: float) -> tuple[str, float, float | None]:
    error = abs(candidate - reference)
    scale = abs(reference)
    green, yellow = COGGING_RELATIVE_PCT
    status = (
        "PASS" if error <= max(green / 100 * scale, floor)
        else "YELLOW" if error <= max(yellow / 100 * scale, 2 * floor)
        else "FAIL"
    )
    return status, error, (error / scale * 100 if scale > 0 else None)


def _waveform(record: dict, key: str = "cogging_torque_waveform") -> tuple[list[float], list[float]] | None:
    wave = record.get(key) or {}
    angles, torque = wave.get("electrical_angle_deg"), wave.get("torque_Nm")
    if not isinstance(angles, list) or not isinstance(torque, list) or len(angles) != len(torque) or len(angles) < 3:
        return None
    try:
        return [float(value) for value in angles], [float(value) for value in torque]
    except (TypeError, ValueError):
        return None


def evaluate_cogging(result: dict, reference: dict | None, config: dict, floor_nm: float) -> dict:
    """Gates and the numbers behind them for one Phase E case."""

    slots, poles = int(config["stator"]["slot_count"]), int(config["rotor"]["pole_count"])
    metadata = result.get("solve_metadata") or {}
    if not str(metadata.get("solver_name", "")).startswith("magneto2d-") or metadata.get("mesh_source") != "native":
        raise ValueError("Candidate did not use the public native solver")
    candidate = (result.get("summary") or {}).get("cogging")
    candidate_wave = _waveform(result)
    if not candidate or candidate_wave is None:
        return {"status": "INCOMPLETE", "gates": {"cogging_sweep": "MISSING"}, "reason": "The candidate has no cogging sweep"}
    method_gate = "PASS" if candidate.get("method") == COGGING_METHOD else "FAIL"
    if reference is None:
        return {
            "status": "NOT_COMPARED",
            "gates": {"cogging_method": method_gate, "reference_comparison": "NOT_EVALUATED"},
            "cogging": {"candidate": candidate, "floor_Nm": floor_nm},
        }
    reference_wave = _waveform(reference)
    expected = (
        cogging_record(*reference_wave, slot_count=slots, pole_count=poles, method="reference")
        if reference_wave is not None
        else None
    )
    details = {"candidate": candidate, "reference": None if expected is None else expected.model_dump(mode="json"), "floor_Nm": floor_nm}
    if expected is None:
        return {
            "status": "INCOMPLETE",
            "gates": {"cogging_method": method_gate, "reference_cogging_waveform": "MISSING"},
            "cogging": details,
        }
    angles_match = len(candidate_wave[0]) == len(reference_wave[0]) and all(
        abs(a - b) <= _ANGLE_TOLERANCE_DEG for a, b in zip(candidate_wave[0], reference_wave[0])
    )
    peak_status, peak_error, peak_pct = _relative_band(candidate["peak_to_peak_Nm"], expected.peak_to_peak_Nm, floor_nm)
    first_status, first_error, first_pct = _relative_band(candidate["first_harmonic_Nm"], expected.first_harmonic_Nm, floor_nm)
    gates = {
        "cogging_method": method_gate,
        "cogging_angle_grid": "PASS" if angles_match else "FAIL",
        "cogging_peak_to_peak": peak_status,
        "cogging_first_harmonic": first_status,
        "reference_cogging_period": "PASS" if expected.endpoint_mismatch_Nm <= floor_nm else "FAIL",
        "reference_cogging_mean": "PASS" if abs(expected.mean_Nm) <= floor_nm else "FAIL",
    }
    details.update(
        peak_to_peak_error_Nm=peak_error,
        peak_to_peak_error_pct=peak_pct,
        first_harmonic_error_Nm=first_error,
        first_harmonic_error_pct=first_pct,
        # Diagnostic only: the waveforms' shape agreement, never a gate.
        waveform=waveform_metrics(result["cogging_torque_waveform"], reference["cogging_torque_waveform"], "torque_Nm"),
    )
    worst = next((status for status in _STATUS_ORDER if status in gates.values()), "PASS")
    return {"status": "INCOMPLETE" if worst == "MISSING" else worst, "gates": gates, "cogging": details}
