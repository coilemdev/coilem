"""Composed reports preserve grades, experimental scope and reference identity."""

import copy
import json

import pytest

from backend.benchmark_suite.collection_report import build_collection_report
from backend.benchmark_suite.contract import read, sha
from backend.benchmark_suite.record import build_record


def child(identifier, phase, status="PASS", experimental=False):
    result = {"summary": {"avg_torque_Nm": 1, "back_emf_fundamental_V": 1,
                          "cogging": {"peak_to_peak_Nm": 1.2, "first_harmonic_Nm": 0.1}},
              "torque_waveform": {"electrical_angle_deg": [0, 180], "torque_Nm": [1, 1]},
              "back_emf_waveform": {"electrical_angle_deg": [0, 180], "phase_a_V": [1, -1]}}
    row = {"id": identifier + "-case", "phase": phase, "status": status,
           "evaluation": {"status": status, "gates": {"test_gate": status}},
           "configurations": {"native": {}}, "measurements": {"native": result}}
    return {"component": {"id": identifier, "phases": [phase], "experimental": experimental},
            "summary": {"status": status, "rows": [row], "run": {
                "identity": {"commit": "a" * 40, "protocol_version": {"A": "1.6.0", "E": "1.7.0", "F": "1.8.0"}[phase],
                             "harness_version": "1.10.0", "local_path": "C:" + "/" + "/".join(("Users", "private", "operator"))},
                "reference_id": "sha256:" + identifier, "reference_review_scope": "EXPERIMENTAL" if experimental else "REVIEWED"}},
            "comparison": {"status": "NO_RECORD" if experimental else "MATCH", "matched": 0 if experimental else 1,
                           "compared": 0 if experimental else 1, "cases": {}},
            "relative_directory": "suites/" + identifier}


def manifest(children, status="COMPLETE", quick=False):
    return {"status": status, "selection": {"options": {"quick": quick}},
            "components": [{"id": part["component"]["id"]} for part in children]}


def test_experimental_yellow_remains_visible_outside_record_match(tmp_path):
    children = [child("abcd", "A"), child("cogging", "E", "YELLOW", True), child("outrunner", "F")]
    original = copy.deepcopy(children)
    summary, comparison = build_collection_report(tmp_path, manifest(children, quick=True), children)
    assert children == original
    assert summary["schema"] == "coilem.benchmark_collection_summary/v1"
    assert summary["status"] == "YELLOW"
    assert summary["counts"] == {"PASS": 2, "YELLOW": 1}
    assert summary["collection"]["experimental_counts"] == {"YELLOW": 1}
    assert comparison["status"] == "MATCH"
    assert (comparison["matched"], comparison["compared"]) == (2, 2)
    assert comparison["experimental_phases"] == ["E"]
    assert [part["protocol_version"] for part in summary["collection"]["components"]] == ["1.6.0", "1.7.0", "1.8.0"]
    e = next(row for row in summary["rows"] if row["phase"] == "E")
    assert e["status"] == e["evaluation"]["gates"]["test_gate"] == "YELLOW"
    assert e["experimental"] is True
    markdown = (tmp_path / "report/benchmark_report.md").read_text(encoding="utf-8")
    assert "YELLOW (experimental)" in markdown
    assert "no single reference commit" in markdown
    share = (tmp_path / "share/coilem-benchmark.md").read_text(encoding="utf-8")
    assert "--quick" in share
    assert "Experimental" in share and "YELLOW" in share
    public = json.dumps(read(tmp_path / "share/coilem-benchmark.json"))
    assert "C:/Users" not in public and "private/operator" not in public
    for relative, digest in read(tmp_path / "report/artifact_manifest.json").items():
        assert sha(tmp_path / "report" / relative) == digest
    with pytest.raises(ValueError, match="separate per-suite"):
        build_record(summary, source="unused", physics_files={})


def test_experimental_numeric_failure_does_not_hide_record_mismatch(tmp_path):
    children = [child("abcd", "A"), child("cogging", "E", "FAIL", True)]
    children[0]["comparison"].update(status="DIFFERS", matched=0)
    summary, comparison = build_collection_report(tmp_path, manifest(children), children)
    assert summary["status"] == "FAIL"
    assert summary["counts"]["FAIL"] == 1
    assert comparison["status"] == "DIFFERS"
    assert comparison["compared"] == 1


def test_unfinished_empty_collection_never_reports_pass(tmp_path):
    summary, comparison = build_collection_report(tmp_path, {"status": "RUNNING", "components": [{"id": "pending"}]}, [])
    assert summary["status"] == "INCOMPLETE"
    assert comparison["status"] == "NO_RECORD"
    html = (tmp_path / "report/coilem_benchmark_report.html").read_text(encoding="utf-8")
    assert "Outcome: INCOMPLETE" in html and "Outcome: PASS" not in html


def test_phase_e_cannot_be_reported_as_registered_coverage(tmp_path):
    children = [child("cogging", "E", experimental=False)]
    with pytest.raises(ValueError, match="explicitly experimental"):
        build_collection_report(tmp_path, manifest(children), children)


def test_duplicate_cases_are_rejected(tmp_path):
    children = [child("one", "A"), child("two", "F")]
    children[1]["summary"]["rows"][0]["id"] = children[0]["summary"]["rows"][0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        build_collection_report(tmp_path, manifest(children), children)
