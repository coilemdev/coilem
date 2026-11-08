"""Saved-result sensitivity reviews preserve the numerical record."""

import copy
import hashlib
import json

import pytest

from backend.benchmark_suite.abc_metrics import compare
from tools.review_numerical_resolution import main, review, write_report


def request():
    return {"schema": "coilem.numerical_resolution_request/v1", "comparisons": [
        {"id": "small-torque", "original_gate_status": "FAIL", "candidate": 0.0000133,
         "reference": 0.0000649, "unit": "N m", "relative_floor_abs": 0.01,
         "original_gate_details": {"absolute_tolerance_Nm": 0.00005}}
    ]}


def test_review_preserves_failure_without_controls(tmp_path):
    payload = request()
    untouched = copy.deepcopy(payload)
    report = review(payload)
    assert payload == untouched
    assert report["original_gate_counts"] == {"FAIL": 1}
    assert report["new_gate_verdict_assigned"] is False
    assert report["rows"][0]["numerical_resolution"]["relative_meaningful"] is False
    write_report(report, tmp_path / "review")
    text = (tmp_path / "review/numerical-resolution.md").read_text(encoding="utf-8")
    assert "Original gate: FAIL" in text
    assert "uncertainty" in text
    assert "noise" in text
    with pytest.raises(ValueError, match="Preserve"):
        write_report(report, tmp_path / "review")


def test_cli_writes_new_hashed_report_and_preserves_input(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(request()), encoding="utf-8")
    before = path.read_bytes()
    assert main(["--input", str(path), "--out-dir", str(tmp_path / "out")]) == 0
    assert path.read_bytes() == before
    report = json.loads((tmp_path / "out/numerical-resolution.json").read_text())
    assert report["source_input_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["registration_or_qualification_changed"] is False
    hashes = json.loads((tmp_path / "out/artifact-manifest.json").read_text())
    assert len(hashes) == 3
    for name, expected in hashes.items():
        assert hashlib.sha256((tmp_path / "out" / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("mutation", ["duplicate", "missing_verdict", "nonfinite", "invalid_root", "invalid_item", "unknown_unit"])
def test_bad_review_cannot_create_a_reassuring_report(tmp_path, mutation):
    payload = request()
    if mutation == "duplicate":
        payload["comparisons"] *= 2
    elif mutation == "missing_verdict":
        del payload["comparisons"][0]["original_gate_status"]
    elif mutation == "nonfinite":
        payload["comparisons"][0]["candidate"] = float("nan")
    elif mutation == "invalid_root":
        payload = []
    elif mutation == "invalid_item":
        payload["comparisons"][0] = None
    else:
        payload["comparisons"][0]["unit"] = "unknown-unit"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SystemExit) as error:
        main(["--input", str(path), "--out-dir", str(tmp_path / "out")])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


def test_voltage_review_has_correct_quantity_label(tmp_path):
    payload = request()
    payload["comparisons"][0]["unit"] = "V"
    report = review(payload)
    write_report(report, tmp_path / "voltage")
    text = (tmp_path / "voltage/numerical-resolution.md").read_text(encoding="utf-8")
    assert "Voltage numerical resolution" in text
    assert "Mean torque numerical resolution" not in text


def test_near_zero_explanation_preserves_registered_gates_and_polarity_finding():
    angles = [0, 90, 180, 270]
    candidate = {"summary": {"avg_torque_Nm": 0.000001, "back_emf_fundamental_V": 1},
                 "torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": [0.000001] * 4},
                 "back_emf_waveform": {"electrical_angle_deg": angles, "phase_a_V": [0, -1, 0, 1]},
                 "solve_metadata": {"torque_method": "weighted_stress", "mesh_source": "native"}}
    reference = copy.deepcopy(candidate)
    reference["summary"]["avg_torque_Nm"] = -0.0001
    reference["back_emf_waveform"]["phase_a_V"] = [0, 1, 0, -1]
    evaluation = compare({"result": candidate}, reference)
    assert evaluation["status"] == "PASS"
    assert evaluation["gates"] == dict.fromkeys(
        ("mean_torque", "bemf_fundamental", "bemf_peak", "torque_method", "native_mesh", "angle_grids"), "PASS")
    assert evaluation["average_delta_pct"] == pytest.approx(101)
    diagnostic = evaluation["numerical_resolution"]
    assert diagnostic["abs_delta"] == pytest.approx(0.000101)
    assert diagnostic["relative_delta_pct"] is None
    assert diagnostic["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"
    assert evaluation["diagnostic_findings"][0]["code"] == "BACK_EMF_POLARITY_MISMATCH"
