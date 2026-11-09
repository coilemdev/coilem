"""Release publication stays blocked even when development CI correctly passes."""
import hashlib
import json
from pathlib import Path

from tools.release.qualification import PRIUS_EXTRA_PHYSICS, check


def _write(root, name, value):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _measured(root):
    digest = _write(root, "backend/motor.py", "value = 1\n")
    _write(root, "backend/qualification.py", 'QUALIFICATION_REPORT = "platform/windows-x86_64/benchmark_summary.json"\n'
           'QUALIFICATION_BASIS = "measured at aaaaaaa"\n')
    _write(root, "backend/resources.py", 'BENCHMARK_SUITE_FILE = "suite.json"\nBENCHMARK_REFERENCE_BUNDLE_DIR = "references"\n')
    _write(root, "backend/benchmark_suite/physics.py", 'def physics_sources(root):\n    return ("backend/motor.py",)\n')
    suite = _write(root, "suite.json", {"protocol_version": "1.9.0", "cases": [{"id": "motor"}]})
    record_sha = _write(root, "references/motor.json", {"result": {}})
    review_sha = _write(root, "references/review.json", {
        "schema": "coilem.protocol16_reference_review/v1", "decision": "ACCEPTED_FOR_REGISTERED_PARITY",
        "suite_sha256": suite, "reference_commit": "reference", "parent_manifest_sha256": "parent",
        "parent_bundle_sha256": "parent-bundle", "cases": {"motor": {}},
    })
    reference = {"records": {"motor": {"file": "motor.json", "sha256": record_sha}},
                 "validation_status": "REVIEWED_FOR_REGISTERED_PARITY", "reference_commit": "reference",
                 "parent_manifest_sha256": "parent", "parent_bundle_sha256": "parent-bundle",
                 "review": {"file": "review.json", "sha256": review_sha}}
    manifest_sha = _write(root, "references/manifest.json", reference)
    bundle = hashlib.sha256(json.dumps({
        "manifest": manifest_sha, "records": reference["records"],
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    _write(root, "platform/windows-x86_64/benchmark_summary.json", {
        "run": {"status": "COMPLETE", "reference_mode": "FROZEN_REFERENCE",
                "identity": {"dirty": False, "commit": "a" * 40, "protocol_version": "1.9.0", "source_files": {"backend/motor.py": digest}},
                "selection": {"spec_sha256": suite, "bundle_sha256": bundle}},
        "rows": [{"id": "motor", "status": "PASS"}],
    })
    for key in ["windows-x86_64", "macos-arm64"]:
        _write(root, f"benchmarks/records/{key}.json", {
            "physics_files": {"backend/motor.py": digest}, "suite_sha256": suite, "reference_bundle_sha256": bundle,
            "measured_commit": "a" * 40, "source": f"platform/{key}",
        })
        _write(root, f"platform/{key}/benchmark_summary.json", json.loads((root / "platform/windows-x86_64/benchmark_summary.json").read_text()))
    sources = {"backend/motor.py": digest}
    for name in PRIUS_EXTRA_PHYSICS:
        sources[name] = _write(root, name, "value = 1\n")
    analysis_sha = hashlib.sha256(b"frozen analysis code").hexdigest()
    sources["snapshot-manifest.json"] = _write(root, "docs/benchmarks/pyleecan-prius-v1/source-snapshot.json", {
        "files": [{"path": "tools/report_prius_benchmark.py", "sha256": analysis_sha}],
    })
    _write(root, "docs/benchmarks/pyleecan-prius-v1/app-results.json", {
        "source_sha256": sources, "field_source_commit": "a" * 40, "field_source_dirty": False,
        "all_software_checks_pass": True, "checks": {"software": True},
        "analysis_runner_sha256": analysis_sha,
        "grading_provenance": {"frozen_before_fields": True}, "jobs": [{}] * 17,
        "audits": {"collection": {"field_reports": [{}] * 568}},
    })


def test_release_gate_requires_current_sources_and_both_platform_records(tmp_path):
    _measured(tmp_path)
    assert check(tmp_path, candidate="a" * 40) == []
    _write(tmp_path, "backend/motor.py", "value = 2\n")
    errors = check(tmp_path)
    assert "qualification physics mismatch: backend/motor.py" in errors
    assert "windows-x86_64 platform record does not match current physics" in errors
    assert "macos-arm64 platform record does not match current physics" in errors
    assert "Prius measured-source mismatch: backend/motor.py" in errors


def test_release_gate_rejects_a_different_candidate_or_protocol(tmp_path):
    _measured(tmp_path)
    assert "qualification report did not measure the frozen candidate" in check(tmp_path, candidate="b" * 40)
    assert "registered suite and measured report must both use protocol 1.5.0" in check(tmp_path, protocol="1.5.0")


def _bridged(root):
    """The registered suite reuses a review of the suite it was measured for (protocol 1.9.0)."""
    _measured(root)
    measured = (root / "suite.json").read_bytes()
    (root / "measured-suite.json").write_bytes(measured)
    change = {"measured_suite": "measured-suite.json", "measured_suite_sha256": hashlib.sha256(measured).hexdigest()}
    suite = _write(root, "suite.json", {"protocol_version": "1.9.0", "cases": [{"id": "motor"}],
                                        "reference_compatibility": {"solve_option_change": change}})
    for name in ["platform/windows-x86_64/benchmark_summary.json", "platform/macos-arm64/benchmark_summary.json"]:
        report = json.loads((root / name).read_text())
        report["run"]["selection"]["spec_sha256"] = suite
        _write(root, name, report)
    for key in ["windows-x86_64", "macos-arm64"]:
        record = json.loads((root / f"benchmarks/records/{key}.json").read_text())
        record["suite_sha256"] = suite
        _write(root, f"benchmarks/records/{key}.json", record)
    return change


def test_release_gate_accepts_a_review_of_the_suite_a_solve_option_bridge_reuses(tmp_path):
    _bridged(tmp_path)
    assert check(tmp_path, candidate="a" * 40) == []


def test_release_gate_rejects_a_bridge_to_a_changed_or_different_suite(tmp_path):
    _bridged(tmp_path)
    (tmp_path / "measured-suite.json").write_text(json.dumps({"protocol_version": "1.6.0", "cases": [{"id": "motor"}]}) + " ")
    assert "solve-option bridge names a changed measured suite" in check(tmp_path, candidate="a" * 40)
    change = _bridged(tmp_path)
    other = _write(tmp_path, "measured-suite.json", {"protocol_version": "1.6.0", "cases": [{"id": "other"}]})
    spec = json.loads((tmp_path / "suite.json").read_text())
    spec["reference_compatibility"]["solve_option_change"] = {**change, "measured_suite_sha256": other}
    _write(tmp_path, "suite.json", spec)
    assert "solve-option bridge measured suite has different cases" in check(tmp_path, candidate="a" * 40)


def test_release_gate_requires_the_loader_bundle_digest_not_the_manifest_digest(tmp_path):
    _measured(tmp_path)
    report = json.loads((tmp_path / "platform/windows-x86_64/benchmark_summary.json").read_text())
    report["run"]["selection"]["bundle_sha256"] = hashlib.sha256(
        (tmp_path / "references/manifest.json").read_bytes()
    ).hexdigest()
    _write(tmp_path, "platform/windows-x86_64/benchmark_summary.json", report)
    assert "qualification report does not use the registered frozen reference bundle" in check(tmp_path)


def test_release_gate_does_not_waive_reference_review(tmp_path):
    _measured(tmp_path)
    _write(tmp_path, "references/manifest.json", {
        "records": {"motor": {}}, "validation_status": "REVIEW_REQUIRED",
    })
    assert "registered reference bundle still requires review" in check(tmp_path)


def test_release_gate_requires_hash_bound_review_and_reference_records(tmp_path):
    _measured(tmp_path)
    _write(tmp_path, "references/review.json", {"decision": "ACCEPTED_FOR_REGISTERED_PARITY"})
    _write(tmp_path, "references/motor.json", {"result": {"changed": True}})
    errors = check(tmp_path)
    assert "registered reference review artifact hash mismatch" in errors
    assert "registered reference record hash mismatch: motor" in errors


def test_platform_hash_repinning_does_not_substitute_for_measured_candidate(tmp_path):
    _measured(tmp_path)
    path = "platform/macos-arm64/benchmark_summary.json"
    report = json.loads((tmp_path / path).read_text())
    report["run"]["identity"]["commit"] = "b" * 40
    _write(tmp_path, path, report)
    assert "macos-arm64 platform record lacks matching complete measured candidate evidence" in check(tmp_path, candidate="a"*40)


def test_default_tag_gate_requires_the_primary_candidate_on_both_platforms(tmp_path):
    _measured(tmp_path)
    record_path = "benchmarks/records/macos-arm64.json"
    record = json.loads((tmp_path / record_path).read_text())
    record["measured_commit"] = "b" * 40
    _write(tmp_path, record_path, record)
    path = "platform/macos-arm64/benchmark_summary.json"
    report = json.loads((tmp_path / path).read_text())
    report["run"]["identity"]["commit"] = "b" * 40
    _write(tmp_path, path, report)
    assert "macos-arm64 platform record lacks matching complete measured candidate evidence" in check(tmp_path)


def test_prius_evidence_publication_can_change_metadata_but_not_field_physics(tmp_path):
    _measured(tmp_path)
    path = "docs/benchmarks/pyleecan-prius-v1/app-results.json"
    prius = json.loads((tmp_path/path).read_text())
    prius["source_sha256"]["backend/qualification.py"] = "original measured qualification metadata"
    _write(tmp_path, path, prius)
    assert check(tmp_path) == []
    _write(tmp_path, "backend/solver_environment.py", "value = 2\n")
    assert "Prius measured-source mismatch: backend/solver_environment.py" in check(tmp_path)


def test_prius_grader_must_match_the_before_field_snapshot(tmp_path):
    _measured(tmp_path)
    path = "docs/benchmarks/pyleecan-prius-v1/app-results.json"
    prius = json.loads((tmp_path / path).read_text())
    prius["analysis_runner_sha256"] = "post-collection grader"
    _write(tmp_path, path, prius)
    assert "Prius analysis code is not bound to its before-field source snapshot" in check(tmp_path)


def test_release_gate_finds_legacy_prius_report_without_importing_candidate_code(tmp_path):
    _measured(tmp_path)
    destination = tmp_path / "legacy/prius"
    destination.parent.mkdir(parents=True)
    (tmp_path / "docs/benchmarks/pyleecan-prius-v1").rename(destination)
    _write(tmp_path, "backend/qualification.py", (
        'LEGACY_PRIUS_QUALIFICATION_REPORT = "legacy/prius/app-results.json"\n'
        'PRIUS_QUALIFICATION_REPORT = record.get("prius_report", LEGACY_PRIUS_QUALIFICATION_REPORT)\n'
        'raise AssertionError("Candidate code must not execute")\n'))
    assert check(tmp_path) == []
    _write(tmp_path, "backend/solver_environment.py", "value = 2\n")
    assert "Prius measured-source mismatch: backend/solver_environment.py" in check(tmp_path)


def test_registered_prius_report_takes_precedence_over_legacy_default(tmp_path):
    _measured(tmp_path)
    record_path = "benchmarks/records/windows-x86_64.json"
    record = json.loads((tmp_path / record_path).read_text())
    record["prius_report"] = "published/prius/app-results.json"
    _write(tmp_path, record_path, record)
    destination = tmp_path / "published/prius"
    destination.parent.mkdir(parents=True)
    (tmp_path / "docs/benchmarks/pyleecan-prius-v1").rename(destination)
    _write(tmp_path, "backend/qualification.py", 'LEGACY_PRIUS_QUALIFICATION_REPORT = "absent/app-results.json"\n')
    assert check(tmp_path) == []


def test_missing_evidence_fails_closed(tmp_path):
    assert check(tmp_path)


def test_supported_failure_or_yellow_cannot_pass_the_release_gate(tmp_path):
    _measured(tmp_path)
    for status in ("FAIL", "YELLOW", "UNSUPPORTED"):
        report = json.loads((tmp_path / "platform/windows-x86_64/benchmark_summary.json").read_text())
        report["rows"][0]["status"] = status
        _write(tmp_path, "platform/windows-x86_64/benchmark_summary.json", report)
        assert "qualification report has a supported case without passing registered gates" in check(tmp_path)
        _write(tmp_path, "platform/macos-arm64/benchmark_summary.json", report)
        assert "macos-arm64 platform record lacks matching complete measured candidate evidence" in check(tmp_path)


def test_current_development_evidence_cannot_be_promoted_by_passing_unit_tests():
    from backend.qualification import evidence_matches_runtime
    if not evidence_matches_runtime():
        errors = check(Path(__file__).resolve().parents[1])
        assert errors, "An experimental development build must not pass the release publication gate"


def test_the_measured_mesher_must_be_the_one_the_release_pins(tmp_path):
    _measured(tmp_path)
    _write(tmp_path, "backend/benchmark_suite/physics.py", (
        'PHYSICS_DEPENDENCIES = ("gmsh",)\nDEPENDENCY_LOCK_FILE = "requirements.lock"\n'
        'def physics_sources(root):\n    return ("backend/motor.py",)\n'
        'def pinned_dependencies(text):\n    return {"gmsh": tuple(line[6:] for line in text.splitlines() if line.startswith("gmsh=="))}\n'))
    _write(tmp_path, "requirements.lock", "gmsh==4.15.2\n")
    assert "qualification dependency mismatch: gmsh" in check(tmp_path)
    for key in ["windows-x86_64", "macos-arm64"]:
        path = f"platform/{key}/benchmark_summary.json"
        report = json.loads((tmp_path / path).read_text())
        report["run"]["identity"]["dependencies"] = {"gmsh": "4.15.2"}
        _write(tmp_path, path, report)
    assert check(tmp_path) == []
    _write(tmp_path, "requirements.lock", "gmsh==4.16.0\n")
    assert "qualification dependency mismatch: gmsh" in check(tmp_path)
