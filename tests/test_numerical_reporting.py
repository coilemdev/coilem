"""Numerical resolution is visible diagnostic context, never a changed verdict."""

import copy
import json

import pytest

from backend.benchmark_suite.contract import read
from backend.benchmark_suite.report import build, numerical_resolution_text
from backend.benchmark_suite.share import SHARE_DIR, SHARE_NAME, write_share_report


def resolution(**changes):
    return {
        "unit": "N m", "candidate": 0.0002, "reference": 0.0,
        "signed_delta": 0.0002, "abs_delta": 0.0002,
        "relative_delta_pct": None, "relative_meaningful": False,
        "reference_near_zero": True, "opposite_signs": False,
        "noise_sensitivity": "NO_CONTROL_EVIDENCE",
        "uncertainty_status": "INSUFFICIENT_EVIDENCE",
        "evidence_sides": [], "observed_variation_abs": None,
        **changes,
    }


def row(status="PASS", diagnostic=None):
    evaluation = {
        "status": status, "gates": {"mean_torque": status},
        "diagnostic_findings": [{"code": "EXISTING_DIAGNOSTIC", "status": "UNRESOLVED"}],
    }
    if diagnostic is not None:
        evaluation["numerical_resolution"] = diagnostic
    return {
        "id": "numerical_reporting_example", "phase": "A", "fixture": "unused.json",
        "status": status, "evaluation": evaluation,
        "configurations": {"native": {"name": "test input"}},
        "measurements": {"native": {
            "summary": {"avg_torque_Nm": 0.0002, "back_emf_fundamental_V": 1.0},
            "torque_waveform": {"electrical_angle_deg": [0, 180], "torque_Nm": [0.0002, 0.0002]},
            "back_emf_waveform": {"electrical_angle_deg": [0, 180], "phase_a_V": [1.0, -1.0]},
        }},
    }


def manifest():
    return {
        "status": "COMPLETE", "smoke": False, "reference_mode": "FROZEN_REFERENCE",
        "identity": {
            "harness_version": "test", "protocol_version": "test", "commit": "candidate",
            "dirty": False, "platform": "Windows-test", "machine": "AMD64", "python": "test",
            "dependencies": {}, "source_sha256": "source", "binary_sha256": "binary",
        },
        "selection": {"spec_sha256": "suite", "bundle_sha256": "bundle"},
    }


def test_near_zero_diagnostic_preserves_outcome_and_formats_absolute_units(tmp_path):
    case = row(diagnostic=resolution())
    original = copy.deepcopy(case["evaluation"])
    assert build(tmp_path, manifest(), [case]) == "PASS"
    saved = read(tmp_path / "report/benchmark_summary.json")
    assert saved["counts"] == {"PASS": 1}
    assert saved["rows"][0]["evaluation"] == original == case["evaluation"]
    for name in ("coilem_benchmark_report.html", "benchmark_report.md"):
        text = (tmp_path / "report" / name).read_text(encoding="utf-8")
        assert "absolute difference 0.2 mNm" in text
        assert "relative difference suppressed near zero" in text
        assert "no control evidence" in text
        assert "Uncertainty: insufficient evidence" in text
    assert numerical_resolution_text({}) == ""


def test_control_variation_does_not_waive_a_failed_gate(tmp_path):
    case = row("FAIL", resolution(
        reference=0.1, candidate=0.1002, reference_near_zero=False,
        relative_meaningful=True, relative_delta_pct=0.2,
        evidence_sides=["reference"], observed_variation_abs=0.0003,
        noise_sensitivity="DIFFERENCE_WITHIN_OBSERVED_VARIATION",
    ))
    original = copy.deepcopy(case["evaluation"])
    assert build(tmp_path, manifest(), [case]) == "FAIL"
    assert read(tmp_path / "report/benchmark_summary.json")["rows"][0]["evaluation"] == original
    text = (tmp_path / "report/benchmark_report.md").read_text(encoding="utf-8")
    assert "relative difference 0.2%" in text
    assert "Observed variation 0.3 mNm (reference controls)" in text
    assert "not an uncertainty bound or proof of noise" in text
    assert "Recorded verdict and gates unchanged" in text


def test_pdf_uses_the_same_numerical_resolution_note(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    build(tmp_path, manifest(), [row(diagnostic=resolution())], pdf=True)
    text = " ".join(page.extract_text() for page in pypdf.PdfReader(tmp_path / "report/coilem_benchmark_report.pdf").pages)
    assert "absolute difference 0.2 mNm" in text
    assert "Uncertainty: insufficient evidence" in text


def test_share_exports_only_scalar_context_and_no_control_provenance(tmp_path):
    private_path = "\\".join(("C:", "Users", "private", "evidence.json"))
    diagnostic = resolution(
        observed_studies=[{"study_id": "PRIVATE_STUDY", "source": private_path}],
        observed_variation_by_side={"reference": {"model_id": "PRIVATE_MODEL", "source": private_path}},
        study_id="PRIVATE_STUDY", case_id="PRIVATE_CASE", source_path=private_path,
    )
    case = row("FAIL", diagnostic)
    original = copy.deepcopy(case["evaluation"])
    output = tmp_path / "share-test"
    summary = {"run": manifest(), "status": "FAIL", "counts": {"FAIL": 1}, "rows": [case]}
    selection = {"phases": ["A"], "quick": False, "case_ids": [case["id"]]}
    comparison = {"status": "NO_RECORD", "platform": "windows-x86_64", "cases": {}}
    markdown = write_share_report(output, summary, comparison, selection=selection).read_text(encoding="utf-8")
    payload = read(output / SHARE_DIR / f"{SHARE_NAME}.json")
    portable = payload["cases"][0]
    assert portable["status"] == "FAIL" and portable["gates"] == original["gates"]
    assert case["evaluation"] == original
    assert portable["numerical_resolution"]["noise_sensitivity"] == "NO_CONTROL_EVIDENCE"
    assert portable["numerical_resolution"]["evidence_sides"] == []
    assert "Observed variation" not in markdown
    assert "absolute difference 0.2 mNm" in markdown
    serialized = json.dumps(payload) + markdown
    for secret in ("PRIVATE_STUDY", "PRIVATE_MODEL", "PRIVATE_CASE", "private", "observed_studies", "observed_variation_by_side"):
        assert secret not in serialized


def test_missing_resolution_stays_absent_from_rendering_and_share(tmp_path):
    case = row()
    build(tmp_path, manifest(), [case])
    assert "numerical resolution" not in (tmp_path / "report/benchmark_report.md").read_text(encoding="utf-8")
    from backend.benchmark_suite.share import _case

    assert "numerical_resolution" not in _case(case, {})
