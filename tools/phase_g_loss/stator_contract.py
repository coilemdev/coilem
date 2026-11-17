"""Independent stator/DC-copper scope; original rotor-history gates are unchanged."""
from __future__ import annotations

import numpy as np

from tools.phase_g_loss.contract import ROOT, case_by_id, config_for, read, sha

PROFILE = ROOT / "benchmarks/phase-g-v1/stator-copper-59.json"
SAMPLES = 96
SPEEDS = (1500, 3000)


def checkpoint(directory, index):
    from pathlib import Path
    directory = Path(directory)
    path = directory / f"position-{index:04d}" / "position.json"
    if not path.exists():
        return None
    record = read(path)
    protocol = read(directory / "protocol.json")
    pairs = protocol["requested_config"]["rotor"]["pole_count"] // 2
    if record["index"] != index or abs(record["electrical_angle_deg"] + 360 * index / SAMPLES) > 1e-9:
        raise ValueError("Stator checkpoint electrical angle changed")
    if abs(record["mechanical_angle_deg"] + 360 * index / (SAMPLES * pairs)) > 1e-9:
        raise ValueError("Stator checkpoint mechanical angle changed")
    if record["protocol_sha256"] != sha(directory / "protocol.json") or record["geometry_sha256"] != sha(directory / "material-geometry.npz"):
        raise ValueError("Stator checkpoint input or integration geometry changed")
    for name, digest in record["sha256"].items():
        if sha(path.parent / name) != digest:
            raise ValueError("Stator checkpoint raw data changed")
    if "source_checkpoint" in record and sha(record["source_checkpoint"]) != record["source_checkpoint_sha256"]:
        raise ValueError("Original source checkpoint changed")
    return record


def config(case_id, count=96, speed=3000):
    raw = config_for(case_by_id(case_id))
    raw["solve_options"].update(rotor_iron_loss=False, losses_efficiency=True, torque_sweep=True,
                                back_emf=False, flux_density=False, cogging_torque=False,
                                torque_speed_envelope=False, thd_analysis=False)
    raw["solve_params"].update(solve_quality="custom", rotor_sweep_range_deg=360,
                               rotor_step_deg=360 / count, rated_speed_rpm=speed, magneto2d_workers=4)
    return raw


def magnetic_geometry(raw):
    """Geometry/base-mesh reuse may change current and sampling, never materials."""
    from copy import deepcopy
    raw = deepcopy(raw)
    raw.pop("solve_options", None)
    for key in ("current_amplitude_A", "rotor_step_deg", "rotor_sweep_range_deg", "rated_speed_rpm", "magneto2d_workers"):
        raw["solve_params"].pop(key, None)
    return raw


def iron_values(record):
    return {"hysteresis_W": record["iron_hysteresis_loss_W"],
            "lamination_eddy_W": record["iron_eddy_loss_W"], "total_W": record["iron_loss_W"]}


def cycle_repeatability(values, endpoint, area, calculate):
    """Bound stator cycle discretization error without replacing the raw fields.

    Pointwise rotor-history closure is retained as a diagnostic. Stator gates
    use area-weighted field repeatability and a separate loss sensitivity
    budget. The linearly closed waveform is diagnostic only, never reported
    as the reference or used to repair the measured history.
    """
    difference = endpoint - values[0]
    weights = np.asarray(area) / np.sum(area)
    rms = float(np.sqrt(np.sum(weights[:, None] * difference**2) / 2))
    baseline = float(np.sqrt(np.sum(weights[:, None] * values[0]**2) / 2))
    relative = rms / max(baseline, 1e-12)
    closed = values - np.arange(len(values))[:, None, None] / len(values) * difference
    sensitivities = {}
    passed = relative <= read(PROFILE)["cycle_area_weighted_rms_relative"]
    for speed in SPEEDS:
        original, diagnostic = calculate(values, speed), calculate(closed, speed)
        gates = {key: abs(original[key] - diagnostic[key]) <= max(.001, .01 * abs(original[key])) for key in original}
        sensitivities[str(speed)] = {"unmodified_W": original, "diagnostic_only_W": diagnostic, "gates": gates}
        passed &= all(gates.values())
    maximum = float(np.max(np.abs(difference)))
    unweighted_rms = float(np.sqrt(np.mean(difference**2)))
    return {"pass": bool(passed), "area_weighted_rms_T": rms, "rms_relative": relative,
            "max_T": maximum, "unweighted_rms_T": unweighted_rms,
            "strict_rotor_style_closure_pass": maximum <= 1e-6 and unweighted_rms <= 1e-7,
            "loss_sensitivity": sensitivities, "raw_fields_corrected": False}
