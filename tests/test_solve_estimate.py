"""The run-time estimate covers measured runs and follows the planned work."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import solve_estimate
from backend.magneto2d_adapter import cache_magneto2d_solve_mesh
from backend.models import MotorConfig
from backend.public_main import app
from backend.solve_estimate import estimate_solve, planned_work, prepared_mesh_elements

CALIBRATION = json.loads(Path("tests/fixtures/solve_time_calibration.json").read_text(encoding="utf-8"))
# The UI's plan buttons (frontend/src/public/solvePlan.ts and App.tsx asPublicConfig).
PLAN_SETTINGS = {
    "quick": ("coarse", False),
    "standard": ("normal", True),
    "fine": ("fine", True),
}


def _planned(design: str, plan: str) -> MotorConfig:
    config = deepcopy(CALIBRATION["designs"][design])
    mesh_density, thd_analysis = PLAN_SETTINGS[plan]
    config["solve_params"].update(solve_quality=plan, mesh_density=mesh_density)
    config["solve_options"].update(thd_analysis=thd_analysis, cogging_torque=False)
    return MotorConfig.model_validate(config)


@pytest.fixture(autouse=True)
def _reference_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Calibrated with eight Gmsh producers; keep the test independent of this host.
    monkeypatch.setattr(solve_estimate, "mesh_workers", lambda jobs: min(8, jobs))


@pytest.mark.parametrize("run", CALIBRATION["runs"], ids=lambda run: f"{run['design']}-{run['plan']}")
def test_measured_runs_fall_inside_the_estimated_range(run: dict) -> None:
    estimate = estimate_solve(_planned(run["design"], run["plan"]), mesh_elements=run["mesh_elements"])
    assert estimate.low_s <= run["measured_s"] <= estimate.high_s, (estimate, run["measured_s"])


def test_planned_work_counts_meshes_after_slot_pitch_reuse() -> None:
    # Preview meshes the 96-angle Back-EMF grid; 12 slots let angles a slot
    # pitch apart share a mesh, but 27 slots with 24 poles share none.
    assert planned_work(_planned("spm_8p12s", "quick")) == {"loaded": 17, "no_load": 96, "mesh_jobs": 96, "base_meshes": 32}
    assert planned_work(_planned("spm_24p", "quick"))["base_meshes"] == 96
    assert planned_work(_planned("spm_8p12s", "standard")) == {"loaded": 48, "no_load": 48, "mesh_jobs": 48, "base_meshes": 16}


def test_fewer_mesh_workers_lengthen_the_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _planned("spm_8p12s", "standard")
    eight = estimate_solve(config, mesh_elements=30000)
    monkeypatch.setattr(solve_estimate, "mesh_workers", lambda jobs: min(2, jobs))
    two = estimate_solve(config, mesh_elements=30000)
    assert two.seconds > eight.seconds * 1.2


def test_prepared_mesh_supplies_the_element_count() -> None:
    config = _planned("spm_8p12s", "quick")
    assert prepared_mesh_elements(None, config) is None
    assert prepared_mesh_elements("unknown", config) is None
    key = cache_magneto2d_solve_mesh(config, {"mesh": {"nodes": [[0, 0], [1, 0], [0, 1]], "triangles": [[0, 1, 2]] * 1234}})
    assert prepared_mesh_elements(key, config) == 1234
    assert estimate_solve(config, mesh_elements=1234).mesh_elements_source == "prepared_mesh"
    assert estimate_solve(config).mesh_elements_source == "estimate"


def test_validate_returns_a_range() -> None:
    config = _planned("spm_8p12s", "standard").model_dump(mode="json")
    response = TestClient(app, base_url="http://127.0.0.1").post("/solve/validate", json=config)
    assert response.status_code == 200, response.text
    body = response.json()
    low, high = body["estimated_solve_time_range_s"]
    assert low < body["estimated_solve_time_s"] < high
    assert body["estimated_mesh_elements_source"] == "estimate"
