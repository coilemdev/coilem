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


# Runs of a plan that has since changed measured different work (#58).
CURRENT_RUNS = [run for run in CALIBRATION["runs"] if "superseded_by" not in run]


@pytest.mark.parametrize("run", CURRENT_RUNS, ids=lambda run: f"{run['design']}-{run['plan']}")
def test_measured_runs_fall_inside_the_estimated_range(run: dict) -> None:
    estimate = estimate_solve(_planned(run["design"], run["plan"]), mesh_elements=run["mesh_elements"])
    assert estimate.low_s <= run["measured_s"] <= estimate.high_s, (estimate, run["measured_s"])


def test_planned_work_counts_meshes_after_slot_pitch_reuse() -> None:
    # Preview's Back-EMF grid has Standard's 48 angles (#58). Its 8 loaded
    # positions between them get mesh-only jobs at the congruent angles a full
    # cycle at their step meshes for them, so they keep those meshes. 12 slots
    # let angles a slot pitch apart share a mesh; 27 slots with 24 poles share none.
    preview = _planned("spm_8p12s", "quick")
    assert planned_work(preview) == {"loaded": 17, "no_load": 48, "mesh_jobs": 64, "base_meshes": 24}
    # The public solve route streams PM-only frames, so those 8 are solved no-load too.
    streamed = preview.model_copy(
        update={"solve_params": preview.solve_params.model_copy(update={"stream_noload_field_lines": True})}
    )
    assert planned_work(streamed)["no_load"] == 56
    assert planned_work(_planned("spm_24p", "quick"))["base_meshes"] == 52
    assert planned_work(_planned("spm_8p12s", "standard")) == {"loaded": 48, "no_load": 48, "mesh_jobs": 48, "base_meshes": 16}


@pytest.mark.parametrize("design", sorted(CALIBRATION["designs"]))
def test_preview_is_estimated_faster_than_standard(design: str) -> None:
    preview = estimate_solve(_planned(design, "quick"))
    standard = estimate_solve(_planned(design, "standard"))
    # Even its pessimistic end stays below Standard's estimate, as measured (#58).
    assert preview.high_s < standard.seconds


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
