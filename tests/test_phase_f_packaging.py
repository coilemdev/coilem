"""Installed builds retain the independently reviewed Windows F basis."""

import shutil
from pathlib import Path

from backend import resources
from backend.benchmark_suite.contract import ROOT
from backend.benchmark_suite.record import load_records


def test_phase_f_runtime_data_is_packaged_without_changing_default_suite():
    files = set(resources.benchmark_data_files(ROOT))
    separate = set(resources.phase_f_data_files(ROOT))
    assert resources.BENCHMARK_SUITE_FILE == "benchmarks/abcd-v1.6/benchmark_spec.json"
    assert resources.BENCHMARK_REFERENCE_BUNDLE_DIR == "benchmarks/reference-baselines/protocol16-reviewed-20261103"
    assert resources.PHASE_F_RECORD_FILE in separate
    assert resources.PHASE_F_SUITE_FILE in separate
    assert separate <= files
    assert len([name for name in separate if name.startswith("benchmarks/abcd-v1.8/fixtures/")]) == 10
    assert resources.PHASE_F_REFERENCE_BUNDLE_DIR + "/manifest.json" in separate
    assert any(Path(name).name == "review.json" for name in separate)
    bundle = ROOT / resources.PHASE_F_REFERENCE_BUNDLE_DIR
    assert {path.relative_to(ROOT).as_posix() for path in bundle.rglob("*.json")} <= separate
    assert len([name for name in separate if "/mesh-controls/" in name]) == 2
    assert all((ROOT / name).is_file() for name in files)


def test_phase_f_record_does_not_replace_default_platform_records():
    records = load_records(ROOT / resources.BENCHMARK_RECORDS_DIR)
    assert "windows-x86_64" in records
    assert records["windows-x86_64"]["suite_sha256"] != resources.read_data_json(resources.PHASE_F_RECORD_FILE)["suite_sha256"]
    assert len(records["windows-x86_64"]["cases"]) > 10


def test_absent_phase_f_record_does_not_add_a_qualification_basis(tmp_path):
    assert resources.phase_f_data_files(tmp_path) == ()


def test_relocated_packaged_data_retains_reviewed_qualification(tmp_path, monkeypatch):
    from backend import phase_f_qualification
    from backend.benchmark_suite import contract, references

    for relative in resources.phase_f_data_files(ROOT):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    monkeypatch.setattr(resources, "data_file", lambda relative: tmp_path / relative)
    monkeypatch.setattr(contract, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    assert phase_f_qualification._verified_evidence() is not None
    control = next((tmp_path / resources.PHASE_F_REFERENCE_BUNDLE_DIR / "mesh-controls").glob("*.json"))
    control.unlink()
    assert phase_f_qualification._verified_evidence() is None
