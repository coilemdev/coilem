"""Exercise complete candidate grading with synthetic, hash-bound field data."""
import copy
import json
import shutil

import pytest

from backend.benchmark_suite.contract import read, sha
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.cogging import cogging_record
from tools import cogging_qualification as qualification
from tools import publish_cogging_qualification as publication

CANDIDATE = "a" * 40


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def measured(tmp_path):
    spec = load_suite(qualification.ROOT / qualification.SUITE)
    _, refs, digest = load_bundle(qualification.ROOT / qualification.BUNDLE, spec)
    identity = {"commit": CANDIDATE, "dirty": False, "platform": "Windows-test", "machine": "AMD64",
                "source_files": {name: sha(qualification.ROOT / name) for name in physics_sources(qualification.ROOT)}}
    manifest = {"status": "COMPLETE", "smoke": False, "identity": identity, "reference_mode": "FROZEN_REFERENCE",
                "selection": {"spec_sha256": sha(qualification.ROOT / qualification.SUITE), "bundle_sha256": digest},
                "started_at": "2026-11-10T00:00:00+00:00", "completed_at": "2026-11-10T00:01:00+00:00", "jobs": []}
    for case in spec["cases"]:
        cid = case["id"]
        config = read(qualification.ROOT / case["jobs"][0]["fixture"])
        request_path = f"jobs/{cid}/request.json"
        result_path = f"jobs/{cid}/result.json"
        write(tmp_path / request_path, {"identity": identity, "config": config})
        result = copy.deepcopy(refs[cid])
        wave = result["cogging_torque_waveform"]
        result["summary"]["cogging"] = cogging_record(wave["electrical_angle_deg"], wave["torque_Nm"],
            slot_count=config["stator"]["slot_count"], pole_count=config["rotor"]["pole_count"],
            method="weighted_stress").model_dump(mode="json")
        result["solve_metadata"].update(mesh_density="very_fine", mesh_source="native", torque_method="weighted_stress",
                                       solver_name="magneto2d-rust-0.5.0")
        request_sha = sha(tmp_path / request_path)
        write(tmp_path / result_path, {"status": "COMPLETE", "request_sha256": request_sha, "runtime_s": 10,
            "identity_before": identity, "identity_after": identity, "result": result})
        manifest["jobs"].append({"case_id": cid, "status": "COMPLETE", "request": request_path, "result": result_path,
                                  "request_sha256": request_sha, "result_sha256": sha(tmp_path / result_path)})
    write(tmp_path / "run_manifest.json", manifest)
    return tmp_path


def test_candidate_qualification_regrades_all_three_complete_grids(measured):
    result = qualification.assess(measured, CANDIDATE)
    assert result["status"] == "PASS" and result["platform"] == "windows-x86_64"
    assert len(result["rows"]) == 3
    assert sum(len(row["gates"]) for row in result["rows"]) == 18
    assert all(status == "PASS" for row in result["rows"] for status in row["gates"].values())


def test_candidate_qualification_refuses_other_candidate(measured):
    with pytest.raises(ValueError, match="complete clean candidate"):
        qualification.assess(measured, "b" * 40)


def test_candidate_qualification_checks_actual_field_mesh(measured):
    manifest = read(measured / "run_manifest.json")
    job = manifest["jobs"][0]
    path = measured / job["result"]
    result = read(path)
    result["result"]["solve_metadata"]["mesh_density"] = "normal"
    write(path, result)
    job["result_sha256"] = sha(path)
    write(measured / "run_manifest.json", manifest)
    with pytest.raises(ValueError, match="very-fine native mesh"):
        qualification.assess(measured, CANDIDATE)


def test_publication_independently_checks_reported_values(measured):
    result = qualification.assess(measured, CANDIDATE)
    artifact = measured.with_name(measured.name + "-artifact")
    artifact.mkdir()
    shutil.copytree(measured, artifact / "out")
    write(artifact / "qualification.json", result)
    assert publication.verify_platform(artifact, CANDIDATE)["status"] == "PASS"
    result["rows"][0]["cogging"]["peak_to_peak_error_pct"] = 9.0
    write(artifact / "qualification.json", result)
    with pytest.raises(ValueError, match="numerical values differ"):
        publication.verify_platform(artifact, CANDIDATE)


def test_publication_rejects_timing_that_differs_from_collection(measured):
    result = qualification.assess(measured, CANDIDATE)
    artifact = measured.with_name(measured.name + "-artifact")
    artifact.mkdir()
    shutil.copytree(measured, artifact / "out")
    result["collection_wall_s"] = 1
    write(artifact / "qualification.json", result)
    with pytest.raises(ValueError, match="independently verified candidate fields"):
        publication.verify_platform(artifact, CANDIDATE)
