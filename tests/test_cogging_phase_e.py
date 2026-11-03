"""Phase E, the cogging benchmark (protocol 1.7.0, #185): its registered requests and its gates."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from backend.benchmark_suite import PHASE_LABELS, PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.cogging_metrics import COGGING_METHOD, evaluate_cogging
from backend.benchmark_suite.contract import canonical, sha
from backend.benchmark_suite.references import load_suite
from backend.cogging import cogging_period, cogging_record

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json"
BASE_SPEC = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"


def test_phase_e_is_its_own_suite_and_1_6_stays_the_default() -> None:
    spec = load_suite(SPEC)
    assert PHASE_LABELS["E"] == "Cogging"
    assert spec["protocol_version"] == "1.7.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.6.0"
    assert {case["phase"] for case in spec["cases"]} == {"E"}
    assert len(spec["cases"]) == 12
    assert spec["phase_e"]["status"] == "PROPOSED_NOT_REGISTERED"
    assert spec["phase_e"]["base_suite_sha256"] == sha(BASE_SPEC)
    base = load_suite(BASE_SPEC)
    for key in ("convention", "material_contract", "golden", "golden_sha256"):
        assert spec[key] == base[key]


def test_each_request_is_its_base_request_with_cogging_and_corner_refinement() -> None:
    spec = load_suite(SPEC)
    base_cases = {case["id"]: case for case in load_suite(BASE_SPEC)["cases"]}
    geometries = set()
    for case in spec["cases"]:
        base = base_cases[case["base_case"]]
        assert case["id"] == f"{base['id']}__cogging"
        assert case["base_phase"] == base["phase"] and base["phase"] in "ABC"
        job, base_job = case["jobs"][0], base["jobs"][0]
        fixture = json.loads((ROOT / job["fixture"]).read_text(encoding="utf-8"))
        assert sha(ROOT / job["fixture"]) == job["fixture_sha256"]
        assert canonical(fixture) == job["input_sha256"]
        expected = json.loads((ROOT / base_job["fixture"]).read_text(encoding="utf-8"))
        assert canonical(expected) == base_job["input_sha256"]
        expected["solve_options"]["cogging_torque"] = True
        expected["solve_params"]["corner_refinement"] = True
        assert fixture == expected
        slots, poles = fixture["stator"]["slot_count"], fixture["rotor"]["pole_count"]
        assert case["cogging_cycles_per_revolution"] == math.lcm(slots, poles)
        # Cogging depends on the stator, rotor and magnets only: every case is a different motor.
        geometries.add(canonical({key: fixture[key] for key in ("topology", "stator", "rotor", "materials")}))
    assert len(geometries) == len(spec["cases"])


def test_each_floor_is_half_a_percent_of_its_base_reference_torque() -> None:
    for case in load_suite(SPEC)["cases"]:
        basis = case["cogging_floor_basis"]
        record = json.loads((ROOT / basis["reference_record"]).read_text(encoding="utf-8"))
        assert record["case_id"] == case["base_case"]
        assert basis["avg_torque_Nm"] == record["result"]["summary"]["avg_torque_Nm"]
        assert case["cogging_floor_Nm"] == round(0.005 * abs(basis["avg_torque_Nm"]), 6)


def test_a_cogging_case_needs_a_registered_floor(tmp_path) -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    del spec["cases"][0]["cogging_floor_Nm"]
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="registered floor"):
        load_suite(path)


CONFIG = json.loads((ROOT / "benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json").read_text(encoding="utf-8"))
FLOOR = 0.0557


def _waveform(scale: float = 1.0, *, offset: float = 0.0, end_shift: float = 0.0, positions: int = 24):
    period, _, _ = cogging_period(12, 8)
    angles = [period * index / positions for index in range(positions + 1)]
    torque = [scale * (0.6 * math.sin(2 * math.pi * a / period) + 0.2 * math.sin(6 * math.pi * a / period)) + offset for a in angles]
    torque[-1] += end_shift
    return {"electrical_angle_deg": angles, "torque_Nm": torque}


def _candidate(waveform=None, method=COGGING_METHOD):
    waveform = waveform or _waveform()
    record = cogging_record(waveform["electrical_angle_deg"], waveform["torque_Nm"], slot_count=12, pole_count=8, method=method)
    return {
        "summary": {"cogging": record.model_dump(mode="json")},
        "cogging_torque_waveform": waveform,
        "solve_metadata": {"solver_name": "magneto2d-0.4.0", "mesh_source": "native"},
    }


def _reference(waveform):
    return {"summary": {"cogging_torque_Nm": max(waveform["torque_Nm"]) - min(waveform["torque_Nm"])}, "cogging_torque_waveform": waveform}


@pytest.mark.parametrize(
    ("scale", "expected"),
    [(1.0, "PASS"), (1.05, "PASS"), (1.15, "YELLOW"), (1.5, "FAIL")],
)
def test_peak_to_peak_and_first_harmonic_are_banded_against_the_reference(scale, expected) -> None:
    evaluation = evaluate_cogging(_candidate(), _reference(_waveform(scale)), CONFIG, FLOOR)
    assert evaluation["gates"]["cogging_peak_to_peak"] == expected
    assert evaluation["gates"]["cogging_first_harmonic"] == expected
    assert evaluation["status"] == expected
    for gate in ("cogging_method", "cogging_angle_grid", "reference_cogging_period", "reference_cogging_mean"):
        assert evaluation["gates"][gate] == "PASS"


def test_the_floor_passes_a_low_cogging_design_that_a_relative_error_would_fail() -> None:
    # 0.03 N·m against 0.02 N·m p-p is 50% off, but under the 0.0557 N·m floor.
    evaluation = evaluate_cogging(_candidate(_waveform(0.03)), _reference(_waveform(0.02)), CONFIG, FLOOR)
    assert evaluation["gates"]["cogging_peak_to_peak"] == "PASS"
    assert evaluation["cogging"]["peak_to_peak_error_pct"] > 40
    assert evaluate_cogging(_candidate(_waveform(0.03)), _reference(_waveform(0.02)), CONFIG, 0.001)["status"] == "FAIL"


def test_a_reference_that_does_not_close_or_does_not_average_to_zero_fails_its_self_checks() -> None:
    open_period = evaluate_cogging(_candidate(), _reference(_waveform(end_shift=0.1)), CONFIG, FLOOR)
    assert open_period["gates"]["reference_cogging_period"] == "FAIL"
    biased = evaluate_cogging(_candidate(), _reference(_waveform(offset=0.1)), CONFIG, FLOOR)
    assert biased["gates"]["reference_cogging_mean"] == "FAIL"
    assert biased["status"] == "FAIL"


def test_grid_method_and_missing_data_are_explicit() -> None:
    shifted = _waveform()
    shifted["electrical_angle_deg"] = [angle + 0.5 for angle in shifted["electrical_angle_deg"]]
    assert evaluate_cogging(_candidate(), _reference(shifted), CONFIG, FLOOR)["gates"]["cogging_angle_grid"] == "FAIL"
    assert evaluate_cogging(_candidate(method="arkkio"), _reference(_waveform()), CONFIG, FLOOR)["gates"]["cogging_method"] == "FAIL"
    native_only = evaluate_cogging(_candidate(), None, CONFIG, FLOOR)
    assert native_only["status"] == "NOT_COMPARED"
    assert native_only["gates"] == {"cogging_method": "PASS", "reference_comparison": "NOT_EVALUATED"}
    missing = _candidate()
    missing["summary"]["cogging"] = None
    assert evaluate_cogging(missing, _reference(_waveform()), CONFIG, FLOOR)["status"] == "INCOMPLETE"
    foreign = deepcopy(_candidate())
    foreign["solve_metadata"]["solver_name"] = "elmer"
    with pytest.raises(ValueError, match="public native solver"):
        evaluate_cogging(foreign, _reference(_waveform()), CONFIG, FLOOR)
