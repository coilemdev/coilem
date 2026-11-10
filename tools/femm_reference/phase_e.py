"""Preserved Phase E v3 lowering with repository-local requests."""

from __future__ import annotations

import cmath
import math

from tools.femm_reference import runtime
from tools.femm_reference.runtime import canonical, read, sha

PUBLIC = runtime.DATA
SPEC = PUBLIC / "spec_e.json"


def inputs():
    spec = read(SPEC)
    assert spec["protocol_version"] == "1.7.0" and spec["convention"] == "public-clockwise-v2"
    cases = {case["id"]: case for case in spec["cases"]}
    assert len(cases) == 12 and all(case["phase"] == "E" for case in cases.values())
    for case in cases.values():
        job = case["jobs"][0]
        path = PUBLIC / job["fixture"]
        assert sha(path) == job["fixture_sha256"], case["id"] + ": fixture bytes"
        config = read(path)
        assert canonical(config) == job["input_sha256"], case["id"] + ": canonical input"
        assert config["solve_options"]["cogging_torque"] and config["solve_params"]["corner_refinement"]
    return spec, cases


def identity():
    return runtime.identity("e")


def load_adapter():
    runtime.activate("e")
    import v3_adapter

    v3_adapter.install()
    from backend.femm_solver import FEMMSolver
    from backend.geometry_drawer import compute_geometry
    from backend.material_catalog import MAGNET_PROPERTIES
    from backend.material_contract import load_electrical_steel_curve
    from backend.models import MotorConfig
    from tools.femm_reference import automation

    femm = automation.femm_module()
    return FEMMSolver, MotorConfig, compute_geometry, load_electrical_steel_curve, MAGNET_PROPERTIES, femm, automation, v3_adapter


def summary(values):
    period = values[:-1]
    count = len(period)
    return {
        "peak_to_peak_Nm": max(values) - min(values),
        "peak_Nm": max(map(abs, values)),
        "first_harmonic_Nm": 2 * abs(sum(value * cmath.exp(-2j * math.pi * i / count) for i, value in enumerate(period))) / count,
        "mean_Nm": sum(period) / count,
        "endpoint_mismatch_Nm": abs(values[-1] - values[0]),
    }
