"""Phase E, the cogging benchmark (protocol 1.7.0, #185): its registered requests and its gates."""

from __future__ import annotations

import json
import math
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from backend.benchmark_suite import PHASE_LABELS, PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.cogging_metrics import COGGING_METHOD, evaluate_cogging
from backend.benchmark_suite.contract import canonical, sha, write
from backend.benchmark_suite.references import load_suite
from backend.cogging import cogging_period, cogging_record

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json"
BASE_SPEC = ROOT / "benchmarks/abcd-v1.9/benchmark_spec.json"  # the default suite: Newton requests since v0.5.6


def test_phase_e_is_its_own_suite_derived_from_protocol_1_9() -> None:
    spec = load_suite(SPEC)
    assert PHASE_LABELS["E"] == "Cogging"
    assert spec["protocol_version"] == "1.7.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.10.0"  # the default keeps protocol 1.9.0's requests
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


@pytest.mark.parametrize("missing", ["candidate", "reference", "both"])
def test_a_missing_closing_endpoint_cannot_pass_the_benchmark(missing) -> None:
    candidate_wave, reference_wave = _waveform(), _waveform(end_shift=0.1)
    # Complete reference evidence fails closure; truncation must not hide that failure.
    complete = evaluate_cogging(_candidate(candidate_wave), _reference(reference_wave), CONFIG, FLOOR)
    assert complete["gates"]["reference_cogging_period"] == "FAIL"
    if missing in ("candidate", "both"):
        candidate_wave = {key: values[:-1] for key, values in candidate_wave.items()}
    if missing in ("reference", "both"):
        reference_wave = {key: values[:-1] for key, values in reference_wave.items()}
    evaluation = evaluate_cogging(_candidate(candidate_wave), _reference(reference_wave), CONFIG, FLOOR)
    assert evaluation["status"] == "INCOMPLETE"
    assert "MISSING" in evaluation["gates"].values()


@pytest.mark.parametrize("field", [
    "positions_per_period", "period_elec_deg", "period_mech_deg", "fundamental_order",
    "peak_to_peak_Nm", "peak_Nm", "first_harmonic_Nm", "mean_Nm", "endpoint_mismatch_Nm",
])
@pytest.mark.parametrize("with_reference", [False, True])
def test_stored_summary_cannot_override_its_waveform(field, with_reference):
    candidate = _candidate()
    candidate["summary"]["cogging"][field] += 1
    before = deepcopy(candidate)
    evaluation = evaluate_cogging(candidate, _reference(_waveform()) if with_reference else None, CONFIG, FLOOR)
    assert evaluation["status"] == "INCOMPLETE"
    assert evaluation["gates"]["candidate_cogging_summary"] == "FAIL"
    assert field in evaluation["reason"]
    assert "cogging_peak_to_peak" not in evaluation["gates"], "inconsistent evidence must never reach the numerical gates"
    assert candidate == before


@pytest.mark.parametrize("field", ["order", "multiple", "amplitude_Nm"])
def test_the_retained_harmonic_spectrum_must_also_match_the_waveform(field):
    candidate = _candidate()
    candidate["summary"]["cogging"]["harmonics"][1][field] += 1
    evaluation = evaluate_cogging(candidate, _reference(_waveform()), CONFIG, FLOOR)
    assert evaluation["status"] == "INCOMPLETE"
    assert "harmonics[1]" in evaluation["reason"]


@pytest.mark.parametrize("field,value", [
    ("peak_to_peak_Nm", float("nan")), ("first_harmonic_Nm", float("inf")),
    ("peak_to_peak_Nm", None), ("peak_Nm", "0.6"), ("peak_Nm", 10**1000), ("positions_per_period", True),
    ("harmonics", None), ("harmonics", []), ("harmonics", ["invalid"]),
])
def test_malformed_or_missing_summary_values_are_incomplete(field, value):
    candidate = _candidate()
    candidate["summary"]["cogging"][field] = value
    evaluation = evaluate_cogging(candidate, _reference(_waveform()), CONFIG, FLOOR)
    assert evaluation["status"] == "INCOMPLETE"
    assert field in evaluation["reason"]


def test_a_changed_waveform_cannot_reuse_its_earlier_summary():
    candidate = _candidate()
    candidate["cogging_torque_waveform"] = _waveform(1.15)
    assert evaluate_cogging(candidate, _reference(_waveform()), CONFIG, FLOOR)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("value", [float("inf"), 10**1000])
def test_unrepresentable_waveform_values_are_incomplete(value):
    candidate = _candidate()
    candidate["cogging_torque_waveform"]["torque_Nm"][0] = value
    assert evaluate_cogging(candidate, _reference(_waveform()), CONFIG, FLOOR)["status"] == "INCOMPLETE"


def test_nonuniform_candidate_positions_are_not_a_complete_sweep():
    candidate = _candidate()
    candidate["cogging_torque_waveform"]["electrical_angle_deg"][5] += 0.5
    evaluation = evaluate_cogging(candidate, _reference(_waveform()), CONFIG, FLOOR)
    assert evaluation["status"] == "INCOMPLETE" and "uniform" in evaluation["reason"]


def test_serialization_rounding_is_allowed_but_gates_use_recomputed_numbers():
    candidate, reference = _candidate(), _reference(_waveform())
    candidate["summary"]["cogging"]["peak_to_peak_Nm"] *= 1 + 1e-11
    candidate["summary"]["cogging"]["first_harmonic_Nm"] *= 1 + 1e-11
    # A closing waveform does not establish independent native endpoints.
    candidate["summary"]["cogging"]["endpoint_mismatch_Nm"] = None
    before = deepcopy((candidate, reference))
    evaluation = evaluate_cogging(candidate, reference, CONFIG, FLOOR)
    assert evaluation["status"] == "PASS"
    assert evaluation["cogging"]["peak_to_peak_error_Nm"] == 0
    assert evaluation["cogging"]["first_harmonic_error_Nm"] == 0
    assert evaluation["cogging"]["candidate"]["endpoint_mismatch_Nm"] is None
    assert (candidate, reference) == before


@pytest.mark.parametrize("stale", [False, True])
def test_report_pipeline_rejects_inconsistent_candidates_even_with_valid_artifact_hashes(tmp_path, stale):
    from backend.benchmark_suite.cli import evaluate

    case = next(case for case in load_suite(SPEC)["cases"] if "example_shoed" in case["id"])
    config = json.loads((ROOT / case["jobs"][0]["fixture"]).read_text())
    identity = {"commit": "synthetic-test-candidate"}
    candidate = _candidate()
    if stale:
        candidate["summary"]["cogging"]["peak_to_peak_Nm"] += 0.1
    write(tmp_path / "request.json", {"identity": identity, "config": config})
    write(tmp_path / "result.json", {
        "status": "COMPLETE", "request_sha256": sha(tmp_path / "request.json"),
        "identity_before": identity, "identity_after": identity, "result": candidate,
    })
    job = {"case_id": case["id"], "stage": "native", "status": "COMPLETE", "request": "request.json", "result": "result.json",
           "request_sha256": sha(tmp_path / "request.json"), "result_sha256": sha(tmp_path / "result.json")}
    original = (tmp_path / "result.json").read_bytes()
    rows = evaluate(tmp_path, {"identity": identity, "jobs": [job], "smoke": False}, [case],
                    {(case["id"], "native"): config}, {}, {}, {case["id"]: _reference(_waveform())})
    assert rows[0]["status"] == ("INCOMPLETE" if stale else "PASS")
    if stale:
        assert "peak_to_peak_Nm" in rows[0]["evaluation"]["reason"]
    assert (tmp_path / "result.json").read_bytes() == original


def test_retained_windows_waveforms_reproduce_the_original_outcomes_without_rewriting_evidence():
    folder = ROOT / "docs/benchmarks/cogging-windows-20261103"
    report_path, waves_path = folder / "results.json", folder / "waveforms.json"
    original = (report_path.read_bytes(), waves_path.read_bytes())
    report, waves = json.loads(original[0]), json.loads(original[1])
    measured = {case["case_id"]: case for case in report["cases"]}
    cases = {case["id"]: case for case in load_suite(SPEC)["cases"]}
    outcomes = Counter()
    for case in waves["cases"]:
        saved = measured[case["case_id"]]
        config = json.loads((ROOT / cases[case["case_id"]]["jobs"][0]["fixture"]).read_text())
        angles, torque = case["electrical_angle_deg"], case["magneto2d_normal_torque_Nm"]
        # Re-evaluation from retained fields is a diagnostic, not a new measured
        # candidate. Keep its original stored metrics and provenance unchanged.
        record = cogging_record(angles, torque, slot_count=saved["slots"], pole_count=saved["poles"], method=COGGING_METHOD)
        stored = record.model_dump(mode="json")
        for field in ("peak_Nm", "peak_to_peak_Nm", "first_harmonic_Nm", "mean_Nm", "endpoint_mismatch_Nm", "method"):
            stored[field] = saved["normal_native"][field]
        candidate = {"summary": {"cogging": stored}, "solve_metadata": {"solver_name": "magneto2d-0.4.0", "mesh_source": "native"},
                     "cogging_torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": torque}}
        reference = {"cogging_torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": case[
            "femm_refined_torque_Nm" if saved["selected_reference_mesh"] != "baseline" else "femm_baseline_torque_Nm"
        ]}}
        evaluation = evaluate_cogging(candidate, reference, config, saved["cogging_floor_Nm"])
        assert evaluation["status"] == saved["normal_vs_selected_reference"]["status"]
        assert evaluation["gates"] == saved["normal_vs_selected_reference"]["gates"]
        outcomes[evaluation["status"]] += 1
    assert outcomes == report["normal_selected_reference_counts"] == {"PASS": 10, "YELLOW": 2}
    assert (report_path.read_bytes(), waves_path.read_bytes()) == original


def test_phase_e_and_f_requests_use_newton_like_the_default_suite() -> None:
    # v0.5.6 made Newton the default; E and F derive from protocol 1.9.0, so no request keeps Picard.
    for suite in (SPEC, ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json"):
        for case in load_suite(suite)["cases"]:
            fixture = json.loads((ROOT / case["jobs"][0]["fixture"]).read_text(encoding="utf-8"))
            assert fixture["solve_params"]["nonlinear_solver"] == "newton", case["id"]
