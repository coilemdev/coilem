"""Release publication stays blocked even when development CI correctly passes."""
import hashlib
import json
from pathlib import Path

from tools.release.qualification import check


def _write(root, name, value):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _measured(root):
    digest = _write(root, "backend/motor.py", "value = 1\n")
    _write(root, "backend/qualification.py", 'QUALIFICATION_REPORT = "report.json"\nQUALIFICATION_BASIS = "measured at aaaaaaa"\n')
    _write(root, "backend/resources.py", 'BENCHMARK_SUITE_FILE = "suite.json"\nBENCHMARK_REFERENCE_BUNDLE_DIR = "references"\n')
    _write(root, "backend/benchmark_suite/physics.py", 'def physics_sources(root):\n    return ("backend/motor.py",)\n')
    suite = _write(root, "suite.json", {"protocol_version": "1.6.0", "cases": [{"id": "motor"}]})
    bundle = _write(root, "references/manifest.json", {"records": {"motor": {}}})
    _write(root, "report.json", {
        "run": {"status": "COMPLETE", "reference_mode": "FROZEN_REFERENCE",
                "identity": {"dirty": False, "commit": "a" * 40, "protocol_version": "1.6.0", "source_files": {"backend/motor.py": digest}},
                "selection": {"spec_sha256": suite, "bundle_sha256": bundle}},
        "rows": [{"id": "motor", "status": "PASS"}],
    })
    for key in ["windows-x86_64", "macos-arm64"]:
        _write(root, f"benchmarks/records/{key}.json", {
            "physics_files": {"backend/motor.py": digest}, "suite_sha256": suite, "reference_bundle_sha256": bundle,
        })
    _write(root, "docs/benchmarks/pyleecan-prius-v1/app-results.json", {"source_sha256": {"backend/motor.py": digest}})


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


def test_missing_evidence_fails_closed(tmp_path):
    assert check(tmp_path)


def test_current_development_evidence_cannot_be_promoted_by_passing_unit_tests():
    from backend.qualification import evidence_matches_runtime
    if not evidence_matches_runtime():
        errors = check(Path(__file__).resolve().parents[1])
        assert errors, "An experimental development build must not pass the release publication gate"
