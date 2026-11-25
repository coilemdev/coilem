"""Independent anchors, failure preservation, identities and analytical CLI."""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.benchmark_suite import thermal_analytical as suite
from backend.benchmark_suite import thermal_analytical_reference as reference
from backend.resources import data_file
from tests._private_evidence import skip_without_private_evidence


def case(identity):
    return next(c for c in suite.registration()["cases"] if c["id"] == identity)


def test_registration_is_frozen_and_references_do_not_import_production_code():
    assert hashlib.sha256(data_file(suite.REGISTRATION).read_bytes()).hexdigest() == suite.REGISTRATION_SHA256
    spec = suite.registration()
    assert spec["protocol"] == "thermal-analytical-0.6.0-1"
    assert len({row["id"] for row in spec["cases"]}) == len(spec["cases"]) == 23
    tree = ast.parse(inspect.getsource(reference))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"__future__", "math", "dataclasses"}


def test_layered_reference_matches_hand_integrated_interfaces_and_means():
    result = reference.reference_for(case("layered_winding_only"))
    # Resistances L/kA = 1, .1, .05 K/W; 10 W traverses the unheated steel.
    # Ambient25; outer film10 K; yoke drop.5 K; contact.5 K; tooth drop1 K;
    # liner/contact1 K; winding generated-heat mean rise10/3 K.
    assert result.values == pytest.approx(dict(T_winding=38 + 10 / 3, T_teeth=36.5, T_yoke=35.25, Q_ambient=10, Q_balance=0))
    assert result.details["interfaces"]["winding"] == pytest.approx(dict(left_C=43, right_C=38, incoming_W=0, outgoing_W=10))
    assert result.details["interfaces"]["teeth"] == pytest.approx(dict(left_C=37, right_C=36, incoming_W=10, outgoing_W=10))
    iron = reference.reference_for(case("layered_iron_only"))
    assert iron.values == pytest.approx(dict(T_winding=35.625, T_teeth=35.575, T_yoke=35 + 23 / 120, Q_ambient=10, Q_balance=0))


def test_unequal_slab_boundary_flux_has_an_independent_exact_anchor():
    result = reference.reference_for(case("split_slab_unequal_faces"))
    # Full slab R=1 K/W; imposed20 K gradient transports20 W in addition
    # to half of the12 W source flowing to each boundary. Mean =30+12/12.
    assert result.values == dict(T_mean=31, Q_left=26, Q_right=-14, Q_balance=0)


def test_copper_references_match_scalar_and_two_equation_hand_balances():
    single = reference.reference_for(case("copper_one_stable"))
    assert single.values["T_winding"] == pytest.approx(20 + 20 / (1 - .00393 * 20))
    dual = reference.reference_for(case("copper_two_separate_temperatures"))
    # .8*x-.04*y=68, -.08*x+.86*y=63 for rises relative to20 C.
    x = (68 * .86 + .04 * 63) / (.8 * .86 - .04 * .08)
    y = (.8 * 63 + .08 * 68) / (.8 * .86 - .04 * .08)
    assert dual.values["T_winding"] == pytest.approx(20 + x)
    assert dual.values["T_end_winding"] == pytest.approx(20 + y)
    unstable = reference.reference_for(case("copper_two_shared_path_instability"))
    assert unstable.rejection_contains == "No stable thermal equilibrium"
    assert unstable.details["loop_gain"] == pytest.approx(1.26)


def test_full_suite_retains_reduction_failures_separately_from_correct_solver_checks():
    result = suite.run_suite(candidate_model=suite.LEGACY_MODEL)
    assert result["status"] == "FAIL"
    assert result["scopes"]["solver"] == dict(status="PASS", counts={"PASS": 16})
    assert result["scopes"]["model_reduction"] == dict(status="FAIL", counts={"PASS": 3, "FAIL": 4})
    assert {c["id"] for c in result["cases"] if c["status"] == "FAIL"} == {
        "layered_winding_only", "layered_iron_only", "layered_combined", "split_slab_unequal_faces"}
    for row in result["cases"]:
        assert row["output_status"] == "experimental" and row["output_status_reason"]
        assert row["status_reason"]
    # A correct average and global heat balance must not hide wrong boundary flows.
    split = next(c for c in result["cases"] if c["id"] == "split_slab_unequal_faces")
    assert next(m for m in split["metrics"] if m["name"] == "T_mean")["status"] == "PASS"
    assert next(m for m in split["metrics"] if m["name"] == "Q_balance")["status"] == "PASS"
    assert next(m for m in split["metrics"] if m["name"] == "Q_left")["absolute_error"] == pytest.approx(40)


def test_surface_mean_model_passes_the_unchanged_registered_cases():
    result = suite.run_suite()
    assert result["candidate_model"] == suite.DEFAULT_MODEL
    assert result["status"] == "PASS" and len(result["cases"]) == 23
    assert result["scopes"]["model_reduction"] == dict(status="PASS", counts={"PASS": 7})
    old = suite.run_suite(candidate_model=suite.LEGACY_MODEL)
    assert result["tolerances"] == old["tolerances"]
    for current, previous in zip(result["cases"], old["cases"]):
        assert current["reference"] == previous["reference"]
        assert current["parameters"] == previous["parameters"]
        assert current["output_status"] == "experimental"
    with pytest.raises(ValueError, match="Unknown analytical candidate"):
        suite.run_suite(candidate_model="misspelled")


@pytest.mark.parametrize("family_id", ["series_heated", "slab_one_face", "layered_combined"])
def test_fixed_heat_scaling_and_ambient_translation(family_id):
    original = case(family_id)
    changed = copy.deepcopy(original)
    p = changed["parameters"]
    ambient_key = "boundary_C" if "boundary_C" in p else "ambient_C"
    p[ambient_key] += 35
    if "layers" in p:
        for layer in p["layers"]:
            layer["heat_W"] *= 2
    else:
        p["heat_W"] *= 2
    for compute in (suite.prediction_for, lambda c: reference.reference_for(c).values):
        first, second = compute(original), compute(changed)
        datum = original["parameters"][ambient_key]
        for key, value in first.items():
            expected = datum + 35 + 2 * (value - datum) if key.startswith("T_") else 2 * value
            assert second[key] == pytest.approx(expected, abs=1e-10)


def test_fault_in_candidate_is_detected_without_changing_the_reference(monkeypatch):
    normal = suite.cylindrical_resistance
    monkeypatch.setattr(suite, "cylindrical_resistance", lambda *args: normal(*args) * 2)
    result = suite.run_suite(["cylindrical_housing"])
    assert result["status"] == "FAIL" and result["selection"] == "subset"
    assert result["cases"][0]["reference"] == reference.reference_for(case("cylindrical_housing")).values


def test_unexpected_exceptions_and_missing_metrics_cannot_pass(monkeypatch):
    def wrong_error(_, **kwargs):
        raise ValueError("Unrelated error")
    monkeypatch.setattr(suite, "prediction_for", wrong_error)
    result = suite.run_suite(["copper_one_critical"])
    assert result["status"] == "FAIL"
    assert result["cases"][0]["observed_rejection"]["message"] == "Unrelated error"
    monkeypatch.setattr(suite, "prediction_for", lambda _, **kwargs: {})
    assert suite.run_suite(["series_heated"])["status"] == "FAIL"
    assert suite.run_suite(["copper_one_critical"])["status"] == "FAIL"
    monkeypatch.setattr(suite, "prediction_for", lambda _, **kwargs: {"wrong_metric": float("inf")})
    result = suite.run_suite(["series_heated", "copper_one_critical"])
    assert result["status"] == "FAIL"
    json.dumps(result, allow_nan=False)


def test_nonfinite_prediction_is_a_serializable_failure(monkeypatch):
    normal = suite.prediction_for
    def invalid(c, **kwargs):
        return {**normal(c, **kwargs), "T_winding": float("nan")}
    monkeypatch.setattr(suite, "prediction_for", invalid)
    result = suite.run_suite(["series_heated"])
    assert result["status"] == "FAIL"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("selection", [[], ["missing"], ["series_heated", "series_heated"]])
def test_invalid_selection_is_never_a_vacuous_pass(selection):
    with pytest.raises(ValueError, match="distinct registered"):
        suite.run_suite(selection)


def test_changed_registration_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "registration.json"
    path.write_bytes(data_file(suite.REGISTRATION).read_bytes() + b" ")
    monkeypatch.setattr(suite, "data_file", lambda _: path)
    with pytest.raises(ValueError, match="frozen registration"):
        suite.registration()


def test_reports_preserve_failures_and_numerical_values_and_do_not_overwrite(tmp_path):
    report = suite.run_suite(candidate_model=suite.LEGACY_MODEL)
    destination = tmp_path / "evidence"
    suite.write_reports(report, destination)
    assert json.loads((destination / "results.json").read_text()) == report
    markdown = (destination / "summary.md").read_text()
    assert "Overall: **FAIL**" in markdown and "solver: **PASS** (16 PASS)" in markdown
    assert b"\r\n" not in (destination / "metrics.csv").read_bytes()
    with (destination / "metrics.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    qleft = next(row for row in rows if row["case"] == "split_slab_unequal_faces" and row["metric"] == "Q_left")
    assert qleft["status"] == "FAIL" and float(qleft["absolute_error"]) == pytest.approx(40)
    assert float(qleft["reference"]) == 26
    assert all(row["output_status"] == "experimental" and row["evidence_kind"] == "analytical_verification" for row in rows)
    assert all(row["registration_sha256"] == suite.REGISTRATION_SHA256 and row["output_status_reason"] for row in rows)
    assert any(row["case"] == "unheated_disconnected_node" and row["metric"] == "outcome" for row in rows)
    with pytest.raises(FileExistsError):
        suite.write_reports(report, destination)


def test_module_cli_works_outside_the_checkout_and_exits_nonzero_for_failures(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    args = [sys.executable, "-m", "backend.benchmark_suite.thermal_analytical"]
    failed = subprocess.run([*args, "--candidate-model", suite.LEGACY_MODEL, "--out-dir", str(tmp_path / "report")],
                            env=env, cwd=tmp_path, capture_output=True, text=True)
    assert failed.returncode == 1, failed.stderr
    assert "Overall: **FAIL**" in failed.stdout
    fixed = subprocess.run(args, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert fixed.returncode == 0 and "Overall: **PASS**" in fixed.stdout
    assert suite.DEFAULT_MODEL in fixed.stdout
    passed = subprocess.run([*args, "--case", "copper_one_stable"], env=env, cwd=tmp_path, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stderr
    assert "Selection: subset" in passed.stdout


@pytest.mark.parametrize("filename,candidate_model", [
    ("analytical-results.json", suite.LEGACY_MODEL),
    ("analytical-surface-mean-results.json", suite.DEFAULT_MODEL),
])
def test_published_bundle_reproduces_the_registered_comparisons(filename, candidate_model):
    skip_without_private_evidence("benchmarks/thermal-v0.6/" + filename)
    saved = json.loads(data_file("benchmarks/thermal-v0.6/" + filename).read_text())
    assert saved["output_status"] == "experimental"
    if candidate_model == suite.DEFAULT_MODEL:
        assert saved["candidate_model"] == candidate_model
    current = suite.run_suite(candidate_model=candidate_model)
    assert saved["registration_sha256"] == current["registration_sha256"]
    assert saved["status"] == current["status"] and saved["scopes"] == current["scopes"]
    assert len(saved["cases"]) == len(current["cases"])
    for recorded, fresh in zip(saved["cases"], current["cases"]):
        assert (recorded["id"], recorded["parameters"], recorded["status"]) == (fresh["id"], fresh["parameters"], fresh["status"])
        assert recorded["reference"] == pytest.approx(fresh["reference"], abs=1e-10, rel=1e-10)
        assert recorded["prediction"] == pytest.approx(fresh["prediction"], abs=1e-10, rel=1e-10)
        assert len(recorded["metrics"]) == len(fresh["metrics"])
        for old, new in zip(recorded["metrics"], fresh["metrics"]):
            assert (old["name"], old["status"]) == (new["name"], new["status"])
            assert old["absolute_error"] == pytest.approx(new["absolute_error"], abs=1e-10)
