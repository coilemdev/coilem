"""Calibration/held-out DC bench gate. No rotating or hotspot qualification."""

from __future__ import annotations

import hashlib
import json
import math
import re

from backend.resources import data_file

REGISTRATION = "benchmarks/thermal-v0.6/bench-gate.json"


def registration():
    return json.loads(data_file(REGISTRATION).read_text())


def winding_temperature(cold_C, cold_ohm, hot_ohm, alpha20):
    """Resistance rise with copper's coefficient referred to 20 C, not cold C."""
    if not all(math.isfinite(v) for v in (cold_C, cold_ohm, hot_ohm, alpha20)) or min(cold_ohm, hot_ohm, alpha20) <= 0:
        raise ValueError("Resistance temperatures need finite inputs and positive corrected resistances/alpha")
    if cold_C <= -273.15 or 1 + alpha20 * (cold_C - 20) <= 0:
        raise ValueError("Invalid cold temperature")
    return 20 + ((hot_ohm / cold_ohm) * (1 + alpha20 * (cold_C - 20)) - 1) / alpha20


def _measurement(point, spec):
    for key in ("ambient_C", "predicted_active_C", "predicted_end_C", "active_fraction", "winding_uncertainty_K", "steady_drift_K_per_min",
                "measured_copper_W", "model_copper_W"):
        if not math.isfinite(point[key]):
            raise ValueError("Bench readings and uncertainties must be finite")
    resistance = point["resistance"]
    if any(not math.isfinite(value) for value in resistance.values()):
        raise ValueError("Resistance measurements must be finite")
    if min(resistance["cold_lead_ohm"], resistance["hot_lead_ohm"]) < 0:
        raise ValueError("Lead corrections must be nonnegative")
    # Equivalent same terminals/connection at both temperatures; subtract lead
    # and contact resistance measured independently at each temperature.
    cold = resistance["cold_ohm"] - resistance["cold_lead_ohm"]
    hot = resistance["hot_ohm"] - resistance["hot_lead_ohm"]
    temperature = winding_temperature(resistance["cold_C"], cold, hot, spec["alpha20_per_K"])
    ambient = point["ambient_C"]
    fraction = point["active_fraction"]
    if not 0 < fraction < 1:
        raise ValueError("Resistance average needs active fraction strictly between zero and one")
    # Uniform conductor/cross-section: R20 fraction equals conductor length
    # fraction. Terminal resistance observes active AND end winding copper.
    predicted_temperature = fraction * point["predicted_active_C"] + (1 - fraction) * point["predicted_end_C"]
    predicted = predicted_temperature - ambient
    rise = temperature - ambient
    if min(predicted, rise) <= 0 or not all(math.isfinite(v) for v in (ambient, predicted, rise)):
        raise ValueError("DC gate needs positive finite measured and predicted rises")
    if point["winding_uncertainty_K"] <= 0 or point["winding_uncertainty_K"] > spec["max_uncertainty_K"]:
        raise ValueError("Temperature uncertainty is missing or above the frozen gate limit")
    if point["steady_drift_K_per_min"] < 0 or point["steady_drift_K_per_min"] > spec["steady_drift_K_per_min"]:
        raise ValueError("Operating point did not meet the registered steady-state criterion")
    heat = point["measured_copper_W"]
    if not math.isfinite(heat) or heat <= 0:
        raise ValueError("Measured DC heat must be positive")
    if abs(point["model_copper_W"] - heat) > spec["heat_relative_band"] * heat:
        raise ValueError("Model source heat does not match measured DC heat")
    return dict(id=point["id"], predicted_rise_K=predicted, measured_rise_K=rise, measured_temperature_C=temperature,
                ambient_C=ambient, heat_W=heat, uncertainty_K=point["winding_uncertainty_K"])


def check_bench(bundle=None, *, spec=None):
    spec = registration() if spec is None else spec
    base = dict(claim="Average winding-to-ambient DC paths for the exact registered motor and cooling only",
                exclusions=["hotspots", "rotor", "magnets", "air-gap cooling", "rotating or speed-dependent ratings"])
    if bundle is None:
        return dict(**base, status="NOT_COMPARED", output_status="experimental",
                    status_reason="Owner motor/cooling registration and physical DC data are pending.", metrics=[])
    spec_hash = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bundle.get("registration_sha256") != spec_hash:
        raise ValueError("Bench data do not match the pre-registered protocol")
    if not spec.get("owner_registration"):
        return dict(**base, status="NOT_COMPARED", output_status="experimental",
                    status_reason="Protocol tolerances are frozen; owner motor/cooling registration is still pending.", metrics=[])
    owner = spec["owner_registration"]
    for key in ("motor_id", "geometry_sha256", "cooling_id", "thermal_inputs_sha256", "prediction_identity"):
        if not owner.get(key) or bundle.get(key) != owner[key]:
            raise ValueError(f"Bench evidence does not match registered {key}")
    if bundle.get("evidence_kind") not in ("physical_measurement", "synthetic") or not bundle.get("raw_data_sha256"):
        raise ValueError("Bench evidence needs its kind and raw measurement identity")
    for key in ("geometry_sha256", "thermal_inputs_sha256", "raw_data_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", bundle[key]):
            raise ValueError("Bench provenance needs SHA256 identities")
    points = bundle["points"]
    ids = [point["id"] for point in points]
    expected = {row["id"]: row for row in spec["points"]}
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise ValueError("Supply every pre-registered point exactly once")
    calibration, validation = [], []
    for point in points:
        registered = expected[point["id"]]
        if point["role"] != registered["role"]:
            raise ValueError("Calibration and held-out validation roles cannot change after collection")
        measured = _measurement(point, spec)
        if abs(measured["heat_W"] - registered["target_heat_W"]) > spec["heat_relative_band"] * registered["target_heat_W"]:
            raise ValueError("DC level differs from its pre-registered target")
        (calibration if point["role"] == "calibration" else validation).append(measured)
    if not calibration or len(validation) < 2:
        raise ValueError("Gate needs calibration and at least two held-out validation levels")
    # Through-origin least squares on calibration rises only. This is valid
    # because M1 scales every resistance by the one common multiplier.
    multiplier = sum(p["predicted_rise_K"] * p["measured_rise_K"] for p in calibration) / sum(p["predicted_rise_K"] ** 2 for p in calibration)
    metrics = []
    for point in validation:
        predicted = multiplier * point["predicted_rise_K"]
        error = abs(predicted - point["measured_rise_K"])
        pass_band = max(spec["relative_band"] * point["measured_rise_K"], spec["absolute_floor_K"])
        yellow_band = max(spec["yellow_relative_band"] * point["measured_rise_K"], spec["yellow_floor_K"])
        # Conservative uncertainty-aware gate: uncertainty does not enlarge bands.
        bound = error + point["uncertainty_K"]
        status = "PASS" if bound <= pass_band else "YELLOW" if bound <= yellow_band else "FAIL"
        metrics.append(dict(**point, calibrated_prediction_C=point["ambient_C"] + predicted,
                            absolute_error_K=error, error_plus_uncertainty_K=bound, pass_band_K=pass_band, yellow_band_K=yellow_band, status=status))
    status = "FAIL" if any(m["status"] == "FAIL" for m in metrics) else "YELLOW" if any(m["status"] == "YELLOW" for m in metrics) else "PASS"
    physical = bundle["evidence_kind"] == "physical_measurement"
    return dict(**base, status=status, output_status="qualified" if physical and status == "PASS" else "experimental",
                status_reason=(f"Fitted thermal-resistance multiplier: {multiplier:.6g}. "
                    "One multiplier cannot identify several uncertain heat paths. "
                    "Held-out DC validation only; synthetic data never qualify outputs. Exact motor/cooling identity must match on use."),
                calibration_multiplier=multiplier, calibration_ids=[p["id"] for p in calibration], metrics=metrics,
                qualification_identity=owner if physical and status == "PASS" else None)
