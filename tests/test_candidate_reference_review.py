"""Review receipts and candidate joins cannot substitute labels for measured fields."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from backend.benchmark_suite.contract import read, sha
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.references import load_suite, require_reviewed_bundle
from backend.winding_utils import flux_linkage_slot_side_turn_factor
from tools import qualify_benchmark_candidate as candidate_join
from tools.qualify_benchmark_candidate import derive
from tools.review_protocol16_references import audit_material_model, audit_sources

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"
BUNDLE = ROOT / "benchmarks/reference-baselines/protocol16-reviewed-20261103"
NATIVE = ROOT / "benchmarks/windows-v050-20261102-88aae101/native"


@pytest.fixture
def measured_source_hashes(monkeypatch):
    """Replay the historical harness's source registry; keep evidence hashes real.

    This fixture models the recorded 0.5.0 context, never today's expanded
    qualification registry. New sources cannot be retroactively measured.
    """
    recorded = read(NATIVE / "run_manifest.json")["identity"]["source_files"]
    historical = read(ROOT / "benchmarks/records-historical/v050/windows-x86_64.json")["physics_files"]
    assert all(recorded[name] == digest for name, digest in historical.items())
    sources = {ROOT / name: recorded[name] for name in historical}
    monkeypatch.setattr(candidate_join, "physics_sources", lambda root: tuple(historical))

    def source_sha(path):
        return sources[path] if path in sources else sha(path)

    monkeypatch.setattr(candidate_join, "sha", source_sha)
    return sources


def test_current_registry_rejects_a_historical_collection_without_the_new_cogging_source(tmp_path, monkeypatch):
    original = sha(NATIVE / "run_manifest.json")
    recorded = read(NATIVE / "run_manifest.json")["identity"]["source_files"]
    assert "backend/cogging.py" in physics_sources(ROOT) and "backend/cogging.py" not in recorded

    def measured_or_actual(path):
        name = path.relative_to(ROOT).as_posix()
        return recorded.get(name, sha(path))

    # Isolate the newly missing source: all other guarded files appear to be
    # the measured versions, but the registry remains the real current one.
    monkeypatch.setattr(candidate_join, "sha", measured_or_actual)
    output = tmp_path / "derived"
    with pytest.raises(ValueError, match="Candidate physics differ from the measured collection"):
        derive(NATIVE, suite=SUITE, bundle=BUNDLE, output=output, source="published/report")
    assert not output.exists()
    assert sha(NATIVE / "run_manifest.json") == original


def circuit_data():
    return {"reference_config": {"winding": {"type": "concentrated", "layers": 1, "parallel_paths": 2,
                                            "turns_per_coil": 10}, "stator": {"stack_length_mm": 20}},
            "source_extraction_evidence": [{"rows": [{"slot_area_m2": .002, "integrated_amp_turns_a": 20.,
                "turns_per_coil": 10, "turn_fraction": 1., "phase_current_a": 4., "effective_current_density_a_per_m2": 10000.}]}],
            "flux_extraction_evidence": [{"circuit_properties": [[2., 0., .04], [-1., 0., -.02], [-1., 0., -.02]],
                                          "terminal_flux_Wb": [.02, -.01, -.01]}]}


def test_circuit_review_checks_branch_current_and_terminal_flux():
    data = circuit_data()
    assert audit_sources(data, True)["max_ideal_NI_deviation_pct"] == 0
    wrong = copy.deepcopy(data)
    wrong["source_extraction_evidence"][0]["rows"][0].update(integrated_amp_turns_a=40., effective_current_density_a_per_m2=20000.)
    with pytest.raises(ValueError, match="circuit ampere-turns"):
        audit_sources(wrong, True)
    wrong = copy.deepcopy(data)
    wrong["flux_extraction_evidence"][0]["terminal_flux_Wb"] = [.04, -.02, -.02]
    with pytest.raises(ValueError, match="circuit flux normalization"):
        audit_sources(wrong, True)


def test_slot_review_rejects_unbalanced_gauge_reduction():
    data = circuit_data()
    factor = flux_linkage_slot_side_turn_factor("concentrated", 1, 2)
    contribution = factor*10*.020*.1
    rows = [{"phase": "A", "direction": direction, "turn_fraction": 1., "az_effective_wb_per_m": .1,
             "flux_linkage_contribution_wb": contribution*sign} for direction, sign in [("in", 1), ("out", -1)]]
    data["flux_extraction_evidence"] = [{"rows": rows}]
    audit_sources(data, False)
    rows[-1].update(direction="in", flux_linkage_contribution_wb=contribution)
    with pytest.raises(ValueError, match="unbalanced phase turn credit"):
        audit_sources(data, False)


def test_saved_model_material_audit_checks_actual_depth_and_remanence():
    import math

    text = ("[LengthUnits] = millimeters\n[ProblemType] = planar\n[Depth] = 50\n[Frequency] = 0\n"
            "[Precision] = 1e-8\n[MinAngle] = 30\n<BeginBlock>\n<BlockName> = coilEM_M350_50A_test\n"
            "<H_c> = 0\n<BHPoints> = 2\n0 0\n1 100\n<EndBlock>\n<BeginBlock>\n<BlockName> = Magnet\n"
            f"<H_c> = {1.315/(4e-7*math.pi*1.05)}\n<Mu_x> = 1.05\n<Mu_y> = 1.05\n<EndBlock>\n")
    options = {"depth_mm": 50., "remanence_T": 1.315, "permeability": 1.05, "steel_points": [(0., 0.), (1., 100.)]}
    assert audit_material_model(text, **options)["steel_points"] == 2
    with pytest.raises(ValueError, match="depth/frequency"):
        audit_material_model(text.replace("[Depth] = 50", "[Depth] = 1"), **options)
    with pytest.raises(ValueError, match="magnet Br"):
        audit_material_model(text, **{**options, "remanence_T": 1.25188})
    with pytest.raises(ValueError, match="steel curve length"):
        audit_material_model(text.replace("1 100\n", "1\n"), **options)


def test_reviewed_status_requires_unchanged_scope_receipt(tmp_path):
    manifest = read(BUNDLE/"manifest.json")
    shutil.copyfile(BUNDLE/"review.json", tmp_path/"review.json")
    require_reviewed_bundle(tmp_path, manifest, load_suite(SUITE))
    changed_suite = load_suite(SUITE)
    changed_suite["cases"][0]["phase"] = "B"
    with pytest.raises(ValueError, match="does not cover"):
        require_reviewed_bundle(tmp_path, manifest, changed_suite)
    receipt = read(tmp_path/"review.json")
    receipt["cases"].pop(next(iter(receipt["cases"])))
    (tmp_path/"review.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        require_reviewed_bundle(tmp_path, manifest, load_suite(SUITE))
    manifest["review"]["sha256"] = sha(tmp_path/"review.json")
    with pytest.raises(ValueError, match="does not cover"):
        require_reviewed_bundle(tmp_path, manifest, load_suite(SUITE))


def test_reviewed_candidate_join_reproduces_complete_evidence_without_fields(tmp_path, monkeypatch, measured_source_hashes):
    from backend import magneto2d_adapter

    def no_solver(*args, **kwargs):
        raise AssertionError("candidate evidence joins must execute zero field solves")

    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", no_solver)
    original = sha(NATIVE/"run_manifest.json")
    output = tmp_path/"derived"
    assert derive(NATIVE, suite=SUITE, bundle=BUNDLE, output=output, source="published/report") == "PASS_WITH_UNSUPPORTED"
    report = read(output/"report/benchmark_summary.json")
    assert report["counts"] == {"PASS": 46, "UNSUPPORTED": 1}
    assert report["run"]["comparison"]["field_solves_executed"] == 0
    assert report["run"]["comparison"]["native_manifest_sha256"] == original == sha(NATIVE/"run_manifest.json")
    assert read(NATIVE/"run_manifest.json")["selection"]["no_reference"] is True
    assert read(output/"platform-record.json")["physics_files"] == {
        path.relative_to(ROOT).as_posix(): digest for path, digest in measured_source_hashes.items()
    }


@pytest.mark.parametrize("source", [
    "backend/public_policy.py", "backend/solver/__init__.py", "backend/solver/_helpers.py",
    "backend/sweep_planning.py", "materials/electrical-steel/M350-50A.csv",
    "solvers/magneto2d/Cargo.lock",
])
def test_candidate_join_rejects_changed_physics_before_writing_output(tmp_path, measured_source_hashes, source):
    measured_source_hashes[ROOT / source] = "0" * 64
    original = sha(NATIVE / "run_manifest.json")
    output = tmp_path / "derived"
    with pytest.raises(ValueError, match="Candidate physics differ from the measured collection"):
        derive(NATIVE, suite=SUITE, bundle=BUNDLE, output=output, source="published/report")
    assert not output.exists()
    assert sha(NATIVE / "run_manifest.json") == original


def test_candidate_join_rejects_dirty_collection_before_writing_output(tmp_path):
    manifest = read(NATIVE/"run_manifest.json")
    manifest["identity"]["dirty"] = True
    native = tmp_path/"native"
    native.mkdir()
    (native/"run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="clean, full-grid"):
        derive(native, suite=SUITE, bundle=BUNDLE, output=tmp_path/"out", source="published/report")
    assert not (tmp_path/"out").exists()
