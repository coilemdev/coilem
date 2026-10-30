"""Protocol 1.6.0: the 0.5.0 reference gates (shoed slot, magnet temperature, λd/λq points) and the d/q gate."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from backend.benchmark_suite import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.contract import SPEC, canonical, read, sha
from backend.benchmark_suite.dq_metrics import DQ_FLUX_LINKAGE_PCT, dq_gates, reference_dq, with_dq_gates
from backend.benchmark_suite.references import load_suite
from backend.magnet_temperature import br_scale, grade_temperature_range_C
from backend.models import MotorConfig
from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"
PREVIOUS = ROOT / "benchmarks/abcd-v1.4/benchmark_spec.json"
SHOED_EXTENSION = ROOT / "benchmarks/abcd-v1.5/benchmark_spec.json"
BASES = {"spm_8p12s_concentrated": "spm_8p12s_concentrated__baseline", "ipm_flat_8p12s_fsae_contract": "ipm_flat_8p12s_fsae_contract"}


def _fixture(case):
    return read(ROOT / case["jobs"][0]["fixture"])


def _diff(a, b, path=()):
    """Every leaf that differs between two fixtures, as (path, a, b)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [item for key in sorted(set(a) | set(b)) for item in _diff(a.get(key), b.get(key), (*path, key))]
    return [] if a == b else [(path, a, b)]


def test_the_suite_is_the_14_matrix_plus_the_reference_gate_cases():
    spec, previous = load_suite(SUITE), load_suite(PREVIOUS)
    assert spec["protocol_version"] == "1.6.0" and "1.6.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.4.0" and SPEC == PREVIOUS  # the default moves at the freeze, with its bundle
    assert spec["cases"][: len(previous["cases"])] == previous["cases"]
    added = spec["cases"][len(previous["cases"]) :]
    assert [case["id"] for case in added] == spec["extension"]["added_cases"] and len(added) == 17
    assert spec["extension"]["archived_suite_sha256"] == sha(PREVIOUS)
    assert "reference_compatibility" not in spec
    for key in ("material_contract", "convention", "golden", "golden_sha256"):
        assert spec[key] == previous[key]
    for case in added:
        job = case["jobs"][0]
        assert job["fixture_sha256"] == sha(ROOT / job["fixture"]) and job["input_sha256"] == canonical(_fixture(case))
        MotorConfig.model_validate(_fixture(case))


def test_the_shoed_case_is_the_15_request():
    shoed = next(case for case in load_suite(SHOED_EXTENSION)["cases"] if case["id"] == "spm_8p12s_example_shoed")
    assert shoed in load_suite(SUITE)["cases"]


def test_temperature_cases_change_only_the_magnet_temperature():
    spec = load_suite(SUITE)
    by_id = {case["id"]: case for case in spec["cases"]}
    temperature_cases = [case for case in spec["cases"] if "magnet_temperature_C" in case]
    assert len(temperature_cases) == 4
    for case in temperature_cases:
        prefix = case["id"].split("__")[0]
        base = _fixture(by_id[BASES[prefix]])
        fixture = _fixture(case)
        grade = fixture["materials"]["magnet_grade"]
        assert _diff(base, fixture) == [(("solve_params", "magnet_temperature_C"), None, case["magnet_temperature_C"])]
        low, high = grade_temperature_range_C(grade)
        assert low <= case["magnet_temperature_C"] <= high
        assert case["magnet_remanence_T"] == pytest.approx(MAGNET_SOLVER_INPUTS[grade][1] * br_scale(grade, case["magnet_temperature_C"]))


def test_dq_points_change_only_the_current_and_its_angle():
    spec = load_suite(SUITE)
    by_id = {case["id"]: case for case in spec["cases"]}
    dq_cases = [case for case in spec["cases"] if case.get("dq_reference")]
    assert len(dq_cases) == 12
    for case in dq_cases:
        base = _fixture(by_id[BASES[case["id"].split("__")[0]]])
        changed = {path for path, _, _ in _diff(base, _fixture(case))}
        assert changed <= {("solve_params", "current_amplitude_A"), ("solve_params", "current_angle_deg")}
        # The d-axis comes from the no-load sweep, so every point keeps it.
        assert _fixture(case)["solve_options"]["back_emf"] is True
    angles = {_fixture(case)["solve_params"]["current_angle_deg"] for case in dq_cases}
    assert angles == {0.0, 30.0, 60.0}


# ── The d/q gate on an analytic reference ───────────────────────────────────

POLE_COUNT, LAMBDA_PM, L_D, L_Q = 8, 0.05, 0.0004, 0.0008
CONFIG = {"rotor": {"pole_count": POLE_COUNT}}


def _abc(alpha, beta):
    return alpha, -alpha / 2 + math.sqrt(3) / 2 * beta, -alpha / 2 - math.sqrt(3) / 2 * beta


def _reference(current=40.0, gamma_deg=30.0, torque_scale=1.0):
    """Waveforms of a linear motor whose d-axis turns with the electrical angle."""
    angles = [index * 7.5 for index in range(13)]
    i_d, i_q = -current * math.sin(math.radians(gamma_deg)), current * math.cos(math.radians(gamma_deg))
    lambda_d, lambda_q = LAMBDA_PM + L_D * i_d, L_Q * i_q
    loaded, currents, no_load = ([[], [], []] for _ in range(3))
    for angle in angles:
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        for target, (d, q) in ((loaded, (lambda_d, lambda_q)), (currents, (i_d, i_q)), (no_load, (LAMBDA_PM, 0.0))):
            for series, value in zip(target, _abc(d * c - q * s, d * s + q * c)):
                series.append(value)
    torque = 1.5 * POLE_COUNT / 2 * (lambda_d * i_q - lambda_q * i_d) * torque_scale
    phases = "abc"
    return {
        "summary": {"avg_torque_Nm": torque},
        "loaded_flux_linkage_waveform": {"electrical_angle_deg": angles, **{f"phase_{p}_Wb": v for p, v in zip(phases, loaded)}},
        "phase_current_waveform": {"electrical_angle_deg": angles, **{f"phase_{p}_A": v for p, v in zip(phases, currents)}},
        "no_load_flux_linkage_waveform": {"electrical_angle_deg": angles, **{f"phase_{p}_Wb": v for p, v in zip(phases, no_load)}},
    }, lambda_d, lambda_q


def _candidate(lambda_d, lambda_q):
    return {"summary": {"dq_flux_linkage": {"lambda_d_Wb": lambda_d, "lambda_q_Wb": lambda_q}}}


def test_the_reference_is_transformed_with_coilems_own_convention():
    reference, lambda_d, lambda_q = _reference()
    record = reference_dq(reference, CONFIG)
    assert record["lambda_d_Wb"] == pytest.approx(lambda_d) and record["lambda_q_Wb"] == pytest.approx(lambda_q)
    assert record["current_angle_deg"] == pytest.approx(30.0) and record["torque_agreement_pct"] == pytest.approx(100.0)


@pytest.mark.parametrize(("shift_pct", "expected"), [(0.0, "PASS"), (2.9, "PASS"), (4.5, "YELLOW"), (7.0, "FAIL")])
def test_lambda_gates_measure_the_error_against_the_reference_flux(shift_pct, expected):
    reference, lambda_d, lambda_q = _reference()
    scale = math.hypot(lambda_d, lambda_q)
    gates, details = dq_gates(_candidate(lambda_d + shift_pct / 100 * scale, lambda_q - shift_pct / 100 * scale), reference, CONFIG)
    assert gates["lambda_d"] == gates["lambda_q"] == expected
    assert details["lambda_d_error_pct"] == pytest.approx(shift_pct, abs=1e-6)
    assert DQ_FLUX_LINKAGE_PCT == (3.0, 6.0)


def test_a_reference_whose_dq_torque_disagrees_is_flagged():
    reference, lambda_d, lambda_q = _reference(torque_scale=1.035)
    gates, _ = dq_gates(_candidate(lambda_d, lambda_q), reference, CONFIG)
    assert gates["reference_dq_torque"] == "YELLOW"
    reference, _, _ = _reference(torque_scale=1.08)
    assert dq_gates(_candidate(lambda_d, lambda_q), reference, CONFIG)[0]["reference_dq_torque"] == "FAIL"


def test_gates_join_the_amplitude_evaluation_and_missing_data_is_incomplete():
    reference, lambda_d, lambda_q = _reference()
    base = {"status": "PASS", "gates": {"mean_torque": "PASS", "bemf_fundamental": "PASS"}}
    merged = with_dq_gates(base, _candidate(lambda_d * 1.05, lambda_q), reference, CONFIG)
    assert merged["status"] == "YELLOW" and merged["gates"]["mean_torque"] == "PASS" and merged["gates"]["lambda_d"] == "YELLOW"
    incomplete = copy.deepcopy(reference)
    del incomplete["no_load_flux_linkage_waveform"]
    assert with_dq_gates(base, _candidate(lambda_d, lambda_q), incomplete, CONFIG)["status"] == "INCOMPLETE"
    assert with_dq_gates(base, {"summary": {}}, reference, CONFIG)["status"] == "INCOMPLETE"
