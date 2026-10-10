"""Registered A/B/C amplitude gates and signed waveform diagnostics."""

import math


def band(value, green, yellow):
    if value is None or not math.isfinite(value):
        return "MISSING"
    return "PASS" if value <= green else "YELLOW" if value <= yellow else "FAIL"


def pct(candidate, reference):
    if candidate is None or reference is None or abs(reference) < 1e-15:
        return None
    return abs(candidate - reference) / abs(reference) * 100


def waveform_metrics(candidate, reference, key):
    ca = candidate.get("electrical_angle_deg", [])
    ra = reference.get("electrical_angle_deg", [])
    cv = candidate.get(key, [])
    rv = reference.get(key, [])
    match = len(ca) == len(ra) == len(cv) == len(rv) and len(cv) > 0 and all(abs(float(a) - float(b)) < 1e-7 for a, b in zip(ca, ra))
    output = {"grid_match": match, "candidate_positions": len(cv), "reference_positions": len(rv)}
    if not match:
        return output
    rms = math.sqrt(sum(float(x) ** 2 for x in rv) / len(rv))
    output["nrmse_pct"] = math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(cv, rv)) / len(rv)) / rms * 100 if rms > 1e-15 else None
    cm = sum(cv) / len(cv)
    rm = sum(rv) / len(rv)
    denominator = math.sqrt(sum((v - cm) ** 2 for v in cv) * sum((v - rm) ** 2 for v in rv))
    output["correlation"] = sum((x - cm) * (y - rm) for x, y in zip(cv, rv)) / denominator if denominator > 1e-15 else None
    return output


def compare(data, reference):
    result = data["result"]
    cs = result.get("summary", {})
    rs = reference.get("summary", {})
    ca = cs.get("avg_torque_Nm")
    ra = rs.get("avg_torque_Nm")
    mean_abs = abs(ca - ra) if ca is not None and ra is not None else None
    mean_pct = pct(ca, ra)
    nearzero = ra is not None and abs(ra) < 0.01
    cwave = result.get("back_emf_waveform", {})
    rwave = reference.get("back_emf_waveform", {})
    cpeak = max(map(abs, cwave.get("phase_a_V", [])), default=None)
    rpeak = max(map(abs, rwave.get("phase_a_V", [])), default=None)
    fdelta = pct(cs.get("back_emf_fundamental_V"), rs.get("back_emf_fundamental_V"))
    pdelta = pct(cpeak, rpeak)
    metadata = result.get("solve_metadata", {})
    method = metadata.get("torque_method")
    native = metadata.get("mesh_source") == "native"
    torque_wave = waveform_metrics(result.get("torque_waveform", {}), reference.get("torque_waveform", {}), "torque_Nm")
    emf_wave = waveform_metrics(cwave, rwave, "phase_a_V")
    findings = []
    if (
        emf_wave.get("correlation") is not None
        and emf_wave["correlation"] < -0.95
        and emf_wave.get("nrmse_pct") is not None
        and emf_wave["nrmse_pct"] > 150
    ):
        findings.append(
            {
                "code": "BACK_EMF_POLARITY_MISMATCH",
                "status": "UNRESOLVED",
                "message": (
                    "Signed Back-EMF waveforms have opposite polarity after the declared angle mapping. "
                    "Voltage/speed convention requires an audit. PASS gates measure amplitude; signed waveform agreement is diagnostic."
                ),
            }
        )
    gates = {
        "mean_torque": band(mean_abs, 0.01, 0.02) if nearzero else band(mean_pct, 8, 15),
        "bemf_fundamental": band(fdelta, 10, 15),
        "bemf_peak": band(pdelta, 10, 15),
        "torque_method": "PASS" if method == "weighted_stress" else "FAIL",
        "native_mesh": "PASS" if native else "FAIL",
        "angle_grids": "PASS" if torque_wave["grid_match"] and emf_wave["grid_match"] else "FAIL",
    }
    status = (
        "INCOMPLETE" if "MISSING" in gates.values() else "FAIL" if "FAIL" in gates.values() else "YELLOW" if "YELLOW" in gates.values() else "PASS"
    )
    return {
        "status": status,
        "gates": gates,
        "candidate_average_Nm": ca,
        "reference_average_Nm": ra,
        "average_delta_pct": mean_pct,
        "average_absolute_delta_Nm": mean_abs,
        "near_zero_reference": nearzero,
        "bemf_fundamental_delta_pct": fdelta,
        "bemf_peak_delta_pct": pdelta,
        "torque_waveform": torque_wave,
        "bemf_waveform": emf_wave,
        "diagnostic_findings": findings,
        "actual_torque_method": method,
        "actual_mesh_source": metadata.get("mesh_source"),
        "environment": metadata.get("solver_environment") or metadata.get("environment_policy"),
        "solve_metadata": metadata,
    }
