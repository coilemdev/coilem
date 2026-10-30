"""Protocol 1.5.0: the 1.4 matrix plus the app's shoed example, a separate extension until the 0.5.0 freeze."""

from __future__ import annotations

from pathlib import Path

from backend.benchmark_suite import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.contract import SPEC, canonical, read, sha
from backend.benchmark_suite.references import load_suite
from backend.models import MotorConfig

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/abcd-v1.5/benchmark_spec.json"
PREVIOUS = ROOT / "benchmarks/abcd-v1.4/benchmark_spec.json"
CASE_ID = "spm_8p12s_example_shoed"


def _case():
    return next(case for case in load_suite(SUITE)["cases"] if case["id"] == CASE_ID)


def test_the_extension_adds_one_shoed_case_and_keeps_the_default():
    spec, previous = load_suite(SUITE), load_suite(PREVIOUS)
    assert spec["protocol_version"] == "1.5.0" and "1.5.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.4.0" and SPEC == PREVIOUS
    assert spec["cases"][:-1] == previous["cases"] and spec["cases"][-1]["id"] == CASE_ID
    assert spec["extension"]["archived_suite_sha256"] == sha(PREVIOUS)
    for key in ("material_contract", "convention", "golden", "golden_sha256"):
        assert spec[key] == previous[key]
    # No FEMM record exists for the new case, so no bridge to the 1.1 bundle is claimed.
    assert "reference_compatibility" not in spec


def test_the_case_is_the_apps_shoed_example_on_the_phase_a_grid():
    case = _case()
    assert case["phase"] == "A" and [job["stage"] for job in case["jobs"]] == ["native"]
    job = case["jobs"][0]
    fixture = read(ROOT / job["fixture"])
    assert job["fixture_sha256"] == sha(ROOT / job["fixture"]) and job["input_sha256"] == canonical(fixture)
    config = MotorConfig.model_validate(fixture)
    assert config.stator.tooth_shoe_enabled and config.stator.tooth_shoe_overhang_mm == 1.5
    assert (config.stator.OD_mm, config.rotor.pole_count, config.stator.slot_count) == (200.0, 8, 12)
    assert (config.winding.turns_per_coil, config.winding.parallel_paths) == (15, 2)
    assert (config.solve_params.current_amplitude_A, config.solve_params.current_amplitude_convention) == (30.0, "rms")
    # Sampling, mesh and solver settings are the registered Phase A grid.
    baseline = read(ROOT / "benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json")
    changed = {"current_amplitude_A", "current_amplitude_convention", "rated_speed_rpm"}
    assert {k: v for k, v in fixture["solve_params"].items() if k not in changed} == {
        k: v for k, v in baseline["solve_params"].items() if k not in changed
    }
    assert fixture["solve_options"] == baseline["solve_options"]
