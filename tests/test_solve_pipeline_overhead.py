"""Per-position solve bookkeeping got cheaper without changing its outputs."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from backend import magneto2d_adapter as adapter
from backend import mesh_evidence
from backend.gmsh_mesh_rotation import copy_json_like
from backend.models import MotorConfig
from backend.solver import _zero_current_solve_mesh_artifact

ROOT = Path(__file__).resolve().parents[1]


def _config() -> MotorConfig:
    return MotorConfig.model_validate(json.loads((ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text()))


def _artifact() -> dict:
    return {
        "mesh": {"nodes": [[0.0, 1.0], [-0.0, 2.5], [1.5, -3.0]], "triangles": [[0, 1, 2]]},
        "element_region_ids": ["slot_1"],
        "element_current_density_a_per_m2": [-4.0e6],
        "element_magnetization": [[0.0, 0.0]],
        "rotor_angle_mech_deg": -0.0,
        "physics_contract": {
            "version": 2,
            "regions": [
                {
                    "id": "slot_1",
                    "kind": "SlotWinding",
                    "current_density_a_per_m2": -4.0e6,
                    "winding": {"phase": "A", "current_density_a_per_m2": -4.0e6},
                },
                {"id": "rotor_core", "kind": "RotorCore", "material": "M350-50A"},
            ],
        },
    }


def _original_hash(payload) -> str:
    text = json.dumps(
        mesh_evidence._normalize_canonical_json(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_persisted_report_appends_the_environment_to_the_solver_text(monkeypatch, tmp_path):
    solver_report = {"solve_info": {"total_time_ms": 805, "x": 1.0e-5}, "results": {"torque": [-52.25, 0.1]}}

    def runner(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(json.dumps(solver_report, indent=1) + "\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(adapter, "ensure_magneto2d_binary", lambda: Path("unused"))
    report = adapter.run_magneto2d_report(
        _config(), sweep=False, solve_mesh_artifact=_artifact(), runner=runner, persist_artifacts_dir=tmp_path,
    )

    persisted = json.loads(next(tmp_path.glob("*_report.json")).read_text())
    assert persisted == report
    assert list(persisted) == ["solve_info", "results", "solver_environment"]
    assert json.loads(next(tmp_path.glob("*_mesh.json")).read_text()) == _artifact()


def test_zero_current_copy_shares_the_mesh_and_leaves_its_input_alone() -> None:
    artifact = _artifact()
    before = copy.deepcopy(artifact)

    zeroed = _zero_current_solve_mesh_artifact(artifact)

    assert artifact == before
    assert zeroed["mesh"] is artifact["mesh"]
    assert zeroed["element_current_density_a_per_m2"] == [0.0]
    slot, rotor = zeroed["physics_contract"]["regions"]
    assert slot["current_density_a_per_m2"] == 0.0
    assert slot["winding"] == {"phase": "A", "current_density_a_per_m2": 0.0}
    assert rotor is artifact["physics_contract"]["regions"][1]
    assert zeroed["physics_contract"]["version"] == 2


def test_json_like_copies_are_equal_and_independent() -> None:
    artifact = _artifact()

    copied = copy_json_like(artifact)

    assert copied == artifact
    copied["mesh"]["nodes"][0][0] = 99.0
    assert artifact["mesh"]["nodes"][0][0] == 0.0


def test_evidence_hashes_match_the_original_normalizing_hash() -> None:
    artifact = _artifact()
    zeroed = _zero_current_solve_mesh_artifact(artifact)
    cache: mesh_evidence.CanonicalTextCache = {}

    loaded = mesh_evidence.build_solve_mesh_evidence(artifact, canonical_cache=cache)
    noload = mesh_evidence.build_solve_mesh_evidence(
        zeroed, geometry_sha256=loaded["geometry_sha256"], canonical_cache=cache,
    )

    geometry = {
        "mesh": artifact["mesh"],
        "element_region_ids": artifact["element_region_ids"],
        "rotor_angle_mech_deg": artifact["rotor_angle_mech_deg"],
    }
    assert loaded["artifact_sha256"] == _original_hash(artifact)
    assert loaded["geometry_sha256"] == _original_hash(geometry)
    assert noload["artifact_sha256"] == _original_hash(zeroed)
    assert noload == mesh_evidence.build_solve_mesh_evidence(zeroed)
    for payload in (-0.0, [-0.0], {"label": "a:-0.0,b", "v": -0.012}, {"é": [0.0, -0.0]}):
        assert mesh_evidence._sha256_json(payload) == _original_hash(payload)


def test_binary_freshness_is_reused_until_the_binary_changes(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "magneto2d"
    binary.write_bytes(b"bin")
    scans = []
    monkeypatch.setattr(adapter, "MAGNETO2D_BINARY", binary)
    monkeypatch.setattr(adapter, "_magneto2d_fresh_verdict", None)
    monkeypatch.setattr(adapter, "_latest_magneto2d_source_mtime", lambda: scans.append(1) or 0.0)

    assert adapter._magneto2d_binary_is_fresh()
    assert adapter._magneto2d_binary_is_fresh()
    assert len(scans) == 1

    stat = binary.stat()
    os.utime(binary, (stat.st_atime, stat.st_mtime + 5))
    assert adapter._magneto2d_binary_is_fresh()
    assert len(scans) == 2
