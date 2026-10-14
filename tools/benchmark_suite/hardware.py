"""Exploratory hardware correlation: native no-load Back-EMF against measured values.

There is no pass/fail: ORNL Prius Phase B (#69) sets no threshold in advance, and
the row's verdict comes from its FEMM parity gates alone. The conversion chain
is explicit: the native phase waveforms are line-to-neutral volts at the solved
speed; line-to-line is phase A minus phase B; no-load Back-EMF scales linearly
with speed.
"""

from __future__ import annotations

import math

LABEL = "Exploratory hardware correlation; no pass/fail"


def _stats(values):
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return None
    return {"mean": sum(finite) / len(finite), "min": min(finite), "max": max(finite)}


def no_load_back_emf_line_to_line(result, config, targets):
    """Predicted line-to-line RMS and peak at each measured speed, with signed error %."""

    wave = result["back_emf_waveform"]
    phase_a, phase_b = wave["phase_a_V"], wave["phase_b_V"]
    if len(phase_a) != len(phase_b) or len(phase_a) < 2:
        raise ValueError("Back-EMF waveform is incomplete")
    if not (config.get("solve_options") or {}).get("back_emf"):
        raise ValueError("The registered request has no no-load Back-EMF solve")
    solved_rpm = float(config["solve_params"]["rated_speed_rpm"])
    line = [a - b for a, b in zip(phase_a, phase_b)]
    rms = math.sqrt(sum(v * v for v in line) / len(line))
    peak = max(abs(v) for v in line)
    rows = []
    for target in targets["rows"]:
        scale = float(target["motor_shaft_rpm"]) / solved_rpm
        predicted_rms, predicted_peak = rms * scale, peak * scale
        rows.append(
            {
                "motor_shaft_rpm": target["motor_shaft_rpm"],
                "measured_ll_rms_V": target["back_emf_ll_rms_V"],
                "predicted_ll_rms_V": predicted_rms,
                "rms_error_pct": (predicted_rms - target["back_emf_ll_rms_V"]) / target["back_emf_ll_rms_V"] * 100,
                "measured_ll_peak_V": target["back_emf_ll_peak_V"],
                "predicted_ll_peak_V": predicted_peak,
                "peak_error_pct": (predicted_peak - target["back_emf_ll_peak_V"]) / target["back_emf_ll_peak_V"] * 100,
            }
        )
    return {
        "kind": "no_load_back_emf_line_to_line",
        "label": LABEL,
        "status": "NO_VERDICT",
        "solved_speed_rpm": solved_rpm,
        "samples_per_electrical_period": len(line),
        "conversion": [
            "Native phase waveforms are line-to-neutral volts at the solved speed.",
            "Line-to-line = phase A - phase B, sampled on the registered electrical-angle grid.",
            "RMS over one electrical period; peak = largest sampled absolute value.",
            "No-load Back-EMF scales linearly with speed from the solved speed.",
        ],
        "allowances": [
            "2D model at the registered stack length: no end effects and no skew.",
            "Magnet properties at their catalog values; the measured test had oil at a nominal 25 degC.",
            "The sampled peak can miss narrow harmonic peaks between grid points.",
        ],
        "rows": rows,
        "rms_error_pct": _stats([r["rms_error_pct"] for r in rows]),
        "peak_error_pct": _stats([r["peak_error_pct"] for r in rows]),
    }
