"""The declared private benchmark evidence: what it covers, and that the A-F record stays public."""

from __future__ import annotations

import json
from pathlib import Path

from backend import resources
from tools import verify_snapshot
from tools.release import private_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_file_under_an_evidence_root_is_classified() -> None:
    present = [path.relative_to(REPO_ROOT).as_posix() for root in private_evidence.EVIDENCE_ROOTS
               for path in (REPO_ROOT / root).rglob("*") if path.is_file() and path.name != ".DS_Store"]
    assert present
    assert private_evidence.unclassified(present) == []


def test_generated_records_are_private_and_their_definitions_public() -> None:
    for path in (
        "benchmarks/g-v2.0/RESULTS.md",
        "benchmarks/g-v2.0/results/coilem.json",
        "benchmarks/g-v2.0/references/femm-rotor/inner_spm_loaded.json",
        "benchmarks/g-v2.0/references/femm-stator-copper-20261117/manifest.json",
        "benchmarks/h-v1.0/RESULTS.md",
        "benchmarks/h-v1.0/references/femm5/outrunner_14p12s__still_air__in_plane.json",
        "benchmarks/thermal-v0.6/analytical-results.json",
        "benchmarks/thermal-v0.6/analytical-metrics.csv",
        "benchmarks/thermal-v0.6/spm_8p12s_concentrated-native.json",
        "benchmarks/thermal-v0.6/ipm_flat_8p12s_fsae-native.json",
        "benchmarks/thermal-v0.6/rotor-heat-recomputed.json",
        "benchmarks/thermal-v0.6/femm/spm_concentrated_iron.json",
        "benchmarks/thermal-v0.6/screenshots/thermal-results.png",
        "benchmarks/thermal-v0.6/PUBLISHED_PRIUS_RESULTS.md",
        "benchmarks/thermal-v0.6/THERMAL_PATH_AUDIT.md",
        "benchmarks/g-v2.0/MEASURED_CLAIMS.md",
        "benchmarks/h-v1.0/MEASURED_CLAIMS.md",
        "benchmarks/thermal-v0.6/MEASURED_CLAIMS.md",
        "tests/private_records/test_phase_g_records.py",
        "tests/private_records/known_disclosures.txt",
    ):
        assert private_evidence.is_private(path), path
        assert not private_evidence.is_public_definition(path), path
    for path in (
        "benchmarks/g-v2.0/README.md",
        "benchmarks/g-v2.0/benchmark_spec.json",
        "benchmarks/g-v2.0/fixtures/loss_inner_spm_loaded_1500rpm.json",
        "benchmarks/g-v2.0/femm-requests/inner_spm_loaded.json",
        "benchmarks/h-v1.0/fixtures/outrunner_14p12s.json",
        "benchmarks/thermal-v0.6/map-interpolation-gates.json",
        "benchmarks/thermal-v0.6/bench-gate.json",
        "benchmarks/thermal-v0.6/analytical-fixtures.json",
        "benchmarks/thermal-v0.6/ANALYTICAL_PROTOCOL.md",
        "benchmarks/thermal-v0.6/published/ornl-tm-2005-33.json",
    ):
        assert private_evidence.is_public_definition(path), path
        assert not private_evidence.is_private(path), path
    # One segment per star: a deeper file is not silently covered by a top-level pattern.
    assert private_evidence.unclassified(["benchmarks/thermal-v0.6/extra/a-results.json"]) == ["benchmarks/thermal-v0.6/extra/a-results.json"]
    assert private_evidence.is_private("benchmarks\\h-v1.0\\results\\coilem.json")


def test_only_the_new_benchmarks_and_the_private_record_tests_can_hold_private_files() -> None:
    # Widening this is a deliberate decision: nothing else in the public tree may ever be filtered.
    assert private_evidence.EVIDENCE_ROOTS == (
        "benchmarks/g-v2.0", "benchmarks/h-v1.0", "benchmarks/thermal-v0.6", "tests/private_records")
    for path in ("tests/test_loss_phase_g.py", "tests/_private_evidence.py", "tests/private_records_other/test_a.py",
                 "tests/fixtures/private_records/a.json", "tools/release/disclosure_fingerprints.json",
                 "tools/release/disclosures.py", "docs/RELEASING.md", "MATERIALS.md"):
        assert not private_evidence.is_private(path), path
        assert not private_evidence.in_evidence_root(path), path
    # Every file a private record test needs to run beside it is private with it.
    assert private_evidence.unclassified(["tests/private_records/data/case.json", "tests/private_records/conftest.py"]) == []


def test_the_public_a_to_f_record_and_its_qualification_evidence_are_never_private() -> None:
    manifest = json.loads((REPO_ROOT / "snapshot-manifest.json").read_text(encoding="utf-8"))
    outside = [entry["path"] for entry in manifest["files"] if not private_evidence.in_evidence_root(entry["path"])]
    assert outside and private_evidence.private_paths(outside) == []
    frozen = resources.benchmark_data_files(REPO_ROOT)
    assert any(path.startswith("benchmarks/records/") for path in frozen)
    assert private_evidence.private_paths(frozen) == []
    for path in ("benchmarks/qualification-5e6fab283d16/macos-arm64/report/benchmark_results.csv",
                 "benchmarks/records/macos-arm64.json", "benchmarks/README.md"):
        assert not private_evidence.is_private(path)


def test_the_public_tree_snapshot_check_refuses_private_evidence() -> None:
    manifest = {"public_patches": [{"path": "benchmarks/g-v2.0/RESULTS.md"}, {"path": "docs/VALIDATION.md"}]}
    paths = {"benchmarks/h-v1.0/results/coilem.json", "benchmarks/h-v1.0/README.md", "README.md"}
    assert verify_snapshot.public_tree_failures(paths, manifest) == [
        "private benchmark evidence in a public tree: benchmarks/h-v1.0/results/coilem.json",
        "private benchmark evidence named in public_patches: benchmarks/g-v2.0/RESULTS.md",
    ]
    assert verify_snapshot.public_tree_failures({"benchmarks/h-v1.0/README.md"}, {"public_patches": []}) == []


def test_the_phase_runners_say_the_stored_records_are_private_when_absent(tmp_path, monkeypatch, capsys) -> None:
    from tools import run_phase_g, run_phase_h

    monkeypatch.setattr(run_phase_g, "ROOT", tmp_path)
    assert run_phase_g.main(["--check"]) == 0
    assert "kept in the private repository" in capsys.readouterr().out
    assert run_phase_g.main(["--regrade"]) == 1
    assert "nothing to regrade" in capsys.readouterr().out
    assert not any(tmp_path.iterdir())

    monkeypatch.setattr(run_phase_h, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["run_phase_h", "--check"])
    assert run_phase_h.main() == 0
    assert "kept in the private repository" in capsys.readouterr().out
    assert not any(tmp_path.iterdir())
