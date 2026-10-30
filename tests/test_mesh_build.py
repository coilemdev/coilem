"""Mesh build: Precise keeps the benchmark's Gmsh node placement, Fast trades it for speed."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import gmsh_solver
from backend.magneto2d_adapter import build_magneto2d_mesh_signature
from backend.models import MotorConfig
from backend.public_report import _design_setting_groups
from backend.qualification import classify_qualification
from backend.solve_estimate import estimate_solve
from backend.topology_provenance import build_topology_provenance

QUALIFIED = Path("benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json")


def _config(mesh_build: str | None = None) -> MotorConfig:
    config = MotorConfig.model_validate_json(QUALIFIED.read_text(encoding="utf-8"))
    if mesh_build is not None:
        config = config.model_copy(
            update={"solve_params": config.solve_params.model_copy(update={"mesh_build": mesh_build})}
        )
    return config


def test_precise_is_the_default_and_other_values_are_rejected() -> None:
    assert _config().solve_params.mesh_build == "precise"
    payload = _config().model_dump(mode="json")
    payload["solve_params"]["mesh_build"] = "medium"
    with pytest.raises(ValidationError):
        MotorConfig.model_validate(payload)


@pytest.mark.parametrize(("mesh_build", "precision"), [("precise", 1e-9), ("fast", 1e-6)])
def test_gmsh_integrates_mesh_sizes_to_the_chosen_precision(monkeypatch, mesh_build, precision) -> None:
    calls: list[float] = []
    set_number = gmsh_solver.gmsh.option.setNumber

    def record(name, value):
        if name == "Mesh.LcIntegrationPrecision":
            calls.append(value)
        return set_number(name, value)

    monkeypatch.setattr(gmsh_solver.gmsh.option, "setNumber", record)
    config = _config(mesh_build)
    config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"mesh_density": "coarse"})})
    preview = gmsh_solver.run_gmsh_mesh_preview(config)
    assert calls == [precision]
    assert preview["mesh_info"]["num_triangles"] > 0


def test_mesh_build_is_part_of_the_mesh_signature_and_provenance() -> None:
    default, precise, fast = _config(), _config("precise"), _config("fast")
    # Precise records nothing, so meshes built before the setting existed keep
    # their signatures and mesh-evidence hashes.
    assert "mesh_build" not in build_topology_provenance(precise)["mesh_policy"]
    assert build_topology_provenance(precise) == build_topology_provenance(default)
    assert build_topology_provenance(fast)["mesh_policy"]["mesh_build"] == "fast"
    # Cached meshes of one build are never reused for the other.
    assert build_magneto2d_mesh_signature(precise) != build_magneto2d_mesh_signature(fast)


def test_fast_meshes_are_experimental(monkeypatch) -> None:
    monkeypatch.setattr("backend.qualification.evidence_matches_runtime", lambda: True)
    assert classify_qualification(_config("precise"))["status"] == "qualified"
    fast = classify_qualification(_config("fast"))
    assert fast["status"] == "experimental"
    assert fast["reason"] == "Fast mesh build: the benchmark measured meshes built with Precise node placement."


def test_fast_shortens_only_the_meshing_part_of_the_estimate() -> None:
    precise = estimate_solve(_config("precise"), mesh_elements=30_000)
    fast = estimate_solve(_config("fast"), mesh_elements=30_000)
    assert fast.seconds < precise.seconds
    assert (fast.base_meshes, fast.field_solves) == (precise.base_meshes, precise.field_solves)


def test_run_settings_name_the_mesh_build() -> None:
    settings = dict(
        entry
        for _title, entries in _design_setting_groups(_config("fast").model_dump(mode="json"))
        for entry in entries
    )
    assert settings["Mesh build"] == "fast"
