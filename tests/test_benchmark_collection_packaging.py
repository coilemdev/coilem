"""Installed benchmark data retains all three independent reference datasets."""

import shutil

import pytest

from backend import resources
from backend.benchmark_suite import collection, references
from backend.benchmark_suite.contract import ROOT


def test_installed_data_loads_all_six_phases_without_the_checkout(tmp_path, monkeypatch):
    files = resources.benchmark_data_files(ROOT)
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    monkeypatch.setattr(collection, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    _, full, _ = collection.load_collection()
    _, quick, _ = collection.load_collection(quick=True)
    assert sum(len(child["cases"]) for child in full) == 69
    assert [child["spec"]["protocol_version"] for child in full] == ["1.6.0", "1.7.0", "1.8.0"]
    assert [case["phase"] for child in quick for case in child["cases"]] == list("ABCDEF")
    assert full[1]["record"] is None
    assert full[1]["component"]["experimental"] is True
    assert all(child["suite_path"].is_relative_to(tmp_path) for child in full)
    # The experimental bundle binds the original public waveform evidence too.
    retained = tmp_path / "benchmarks/windows-v051-20261105-a4f9f4d/waveforms.json"
    assert retained.is_file()
    retained.unlink()
    with pytest.raises(FileNotFoundError):
        collection.load_collection()


def test_packaging_refuses_changed_declared_evidence(tmp_path):
    for relative in resources.collection_data_files(ROOT):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    retained = tmp_path / "benchmarks/windows-v051-20261105-a4f9f4d/waveforms.json"
    retained.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="packaged evidence changed"):
        resources.collection_data_files(tmp_path)
