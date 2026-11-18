"""Phase G: full-motor stator iron and specified-wire DC copper only."""
from __future__ import annotations

import math

LOSS_KEYS = ("iron_hysteresis_loss_W", "iron_eddy_loss_W", "iron_loss_W", "copper_loss_W", "phase_resistance_ohm")


def values(result):
    summary = result["summary"]
    iron = summary["iron_loss"]
    if iron["status"] == "unavailable":
        raise ValueError("Stator iron loss is unavailable")
    output = {key: iron[key] for key in LOSS_KEYS[:3]}
    output.update(copper_loss_W=summary["loss_breakdown"]["copper_loss_W"],
                  phase_resistance_ohm=summary["winding_resistance"]["phase_resistance_ohm"])
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in output.values()):
        raise ValueError("Missing, negative or nonfinite loss measurement")
    if output["phase_resistance_ohm"] <= 0 or output["iron_loss_W"] <= 0:
        raise ValueError("Loss fixture needs positive resistance and stator loss")
    return output


def validate_reference(reference, config):
    if (reference.get("schema") != "coilem.stator_dc_reference/v1"
            or reference.get("rotor_loss_included") is not False
            or reference.get("full_motor_efficiency_qualified") is not False
            or reference.get("reference_loss_history_pass") is not True
            or reference.get("speed_rpm") != config["solve_params"]["rated_speed_rpm"]
            or reference.get("electrical_samples") != 96):
        raise ValueError("Loss reference does not cover the registered full-motor point")
    result = reference.get("values") or {}
    if set(result) != set(LOSS_KEYS) or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                                         or not math.isfinite(v) or v < 0 for v in result.values()):
        raise ValueError("Loss reference has missing or nonfinite components")
    if result["phase_resistance_ohm"] <= 0 or result["iron_loss_W"] <= 0:
        raise ValueError("Loss reference needs positive resistance and stator loss")
    return result


def evaluate_loss(candidate, reference, config):
    measured = values(candidate)
    metadata = candidate["solve_metadata"]
    angles = candidate["torque_waveform"]["electrical_angle_deg"]
    params, options = config["solve_params"], config["solve_options"]
    gates = []
    def gate(name, passed, value=None, maximum=None):
        gates.append({"id": name, "status": "PASS" if passed else "FAIL", "value": value, "maximum": maximum})
    gate("full_motor", params.get("symmetry", "full") == "full" and not metadata.get("sector_repeats"))
    gate("rotor_loss_excluded", options.get("rotor_iron_loss") is False and candidate["summary"].get("rotor_iron_loss") is None)
    gate("loss_requested", options.get("losses_efficiency") is True)
    grid = len(angles) == metadata.get("rotor_positions") == 96 and all(
        abs(angle - i * 3.75) <= 1e-7 for i, angle in enumerate(angles))
    gate("complete_electrical_grid", grid, len(angles), 96)
    ratio = metadata.get("nonlinear_worst_tolerance_ratio")
    gate("field_convergence", isinstance(ratio, (int, float)) and not isinstance(ratio, bool)
         and math.isfinite(ratio) and 0 <= ratio <= 1, ratio, 1)
    gate("native_mesh", metadata.get("mesh_source") == "native")
    gate("iron_component_balance", abs(measured["iron_loss_W"] - measured["iron_hysteresis_loss_W"]
         - measured["iron_eddy_loss_W"]) <= max(1e-9, 1e-9 * measured["iron_loss_W"]))
    expected_copper = 1.5 * params["current_amplitude_A"]**2 * measured["phase_resistance_ohm"]
    gate("dc_copper_balance", abs(measured["copper_loss_W"] - expected_copper) <= max(1e-9, 1e-9 * expected_copper))
    comparisons = {}
    if reference is not None:
        baseline = validate_reference(reference, config)
        for key, value in measured.items():
            copper = key in LOSS_KEYS[3:]
            limit = max(1e-12 if copper else .001, (.01 if copper else .10) * abs(baseline[key]))
            difference = abs(value - baseline[key])
            comparisons[key] = {"candidate": value, "reference": baseline[key], "absolute_difference": difference,
                                "difference_pct": 100 * (value - baseline[key]) / baseline[key] if baseline[key] else None}
            gate(key, difference <= limit, difference, limit)
    passed = all(g["status"] == "PASS" for g in gates)
    return {"status": ("PASS" if reference is not None else "NATIVE_ONLY") if passed else "FAIL", "gates": gates,
            "loss_values": measured, "loss_comparison": comparisons, "model_status": "experimental",
            "rotor_loss_status": "experimental", "rotor_loss_included": False, "full_motor_efficiency_qualified": False,
            "scope": "Numerical stator hysteresis/lamination eddy and specified-wire DC copper; material accuracy is unqualified."}
