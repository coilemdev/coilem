"""Rotor-angle plans: Preview's Back-EMF grid and its PM-only frame solves (#58)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.gmsh_mesh_rotation import full_cycle_congruent_bases, slot_congruence_groups
from backend.models import MotorConfig
from backend.sweep_planning import (
    PREVIEW_BACK_EMF_STEP_DEG,
    full_cycle_back_emf_angle_grid,
    is_uniform_full_cycle_grid,
    loaded_angle_grid,
    no_load_field_frame_angles,
)

pytestmark = pytest.mark.pr

CALIBRATION = json.loads(Path("tests/fixtures/solve_time_calibration.json").read_text(encoding="utf-8"))
# The UI's plan buttons (frontend/src/public/solvePlan.ts and App.tsx asPublicConfig).
PLAN_SETTINGS = {"quick": ("coarse", False), "standard": ("normal", True), "fine": ("fine", True)}


def _planned(design: str, plan: str) -> MotorConfig:
    config = deepcopy(CALIBRATION["designs"][design])
    mesh_density, thd_analysis = PLAN_SETTINGS[plan]
    config["solve_params"].update(solve_quality=plan, mesh_density=mesh_density)
    config["solve_options"].update(back_emf=True, thd_analysis=thd_analysis, cogging_torque=False)
    return MotorConfig.model_validate(config)


@pytest.mark.parametrize("design", sorted(CALIBRATION["designs"]))
def test_preview_back_emf_grid_matches_standard(design: str) -> None:
    preview, standard = _planned(design, "quick"), _planned(design, "standard")
    grid = full_cycle_back_emf_angle_grid(preview, loaded_angle_grid(preview))
    assert len(grid) == 48, "Preview used the 3.75 deg loaded step: 96 points and 96 meshes"
    assert grid == full_cycle_back_emf_angle_grid(standard, loaded_angle_grid(standard))
    assert grid[1] - grid[0] == PREVIEW_BACK_EMF_STEP_DEG
    assert is_uniform_full_cycle_grid(grid), "the Back-EMF FFT needs a uniform half-open cycle"
    # Preview's loaded window keeps its 3.75 deg resolution.
    loaded = loaded_angle_grid(preview)
    assert loaded[1] - loaded[0] == 3.75


def test_high_accuracy_and_custom_grids_are_unchanged() -> None:
    fine = _planned("ipm_14p_flat", "fine")
    assert len(full_cycle_back_emf_angle_grid(fine, loaded_angle_grid(fine))) == 96

    raw = deepcopy(CALIBRATION["designs"]["ipm_14p_flat"])
    raw["solve_params"].update(solve_quality="custom", rotor_step_deg=3.75, rotor_sweep_range_deg=45)
    raw["solve_options"].update(back_emf=True, thd_analysis=False)
    custom = MotorConfig.model_validate(raw)
    assert len(full_cycle_back_emf_angle_grid(custom, loaded_angle_grid(custom))) == 96


@pytest.mark.parametrize(("design", "extra"), [
    ("ipm_14p_flat", [3.75, 11.25, 18.75, 26.25, 33.75, 41.25]),
    ("spm_8p12s", [3.75, 11.25, 18.75, 26.25, 33.75, 41.25, 48.75, 56.25]),
])
def test_preview_positions_off_the_grid_get_a_no_load_solve_for_pm_only_frames(design: str, extra: list[float]) -> None:
    preview = _planned(design, "quick")
    loaded = loaded_angle_grid(preview)
    grid = full_cycle_back_emf_angle_grid(preview, loaded)
    frame_only = no_load_field_frame_angles(loaded, grid)
    assert frame_only == extra
    # Every loaded position is solved no-load, so PM-only playback covers all of them.
    solved = {round(angle * 1e6) for angle in [*grid, *frame_only]}
    assert all(round(angle * 1e6) in solved for angle in loaded)
    # Those positions are meshed for the loaded solve anyway.
    assert set(frame_only) <= set(loaded)


def _mesh_bases(config: MotorConfig, angles: list[float]) -> dict[float, float]:
    """The angle meshed for each angle under slot-pitch reuse, in the public app's convention."""
    pole_pairs = config.rotor.pole_count // 2
    jobs = [{"angle": angle, "rotor_angle_mech_deg": -angle / pole_pairs} for angle in dict.fromkeys(angles)]
    return {
        member["angle"]: group["base"]["angle"]
        for group in slot_congruence_groups(jobs, config.stator.slot_count)
        for member in [group["base"], *(job for job, _ in group["derived"])]
    }


@pytest.mark.parametrize("design", sorted(CALIBRATION["designs"]))
def test_preview_loaded_positions_keep_their_meshes(design: str) -> None:
    # Before #58 the Back-EMF grid was the full cycle at the loaded step, and
    # slot-pitch reuse rotated each loaded position's mesh from its congruence
    # class's base. Mesh-only anchors at those bases keep that, so Preview's
    # loaded results do not move by mesh noise.
    preview = _planned(design, "quick")
    loaded = loaded_angle_grid(preview)
    step = loaded[1] - loaded[0]
    pole_pairs = preview.rotor.pole_count // 2
    old_grid = [index * step for index in range(round(360 / step))]
    anchors = full_cycle_congruent_bases(
        loaded,
        step_deg=step,
        slot_count=preview.stator.slot_count,
        pole_pairs=pole_pairs,
        rotor_angle_mech_deg=lambda angle: -angle / pole_pairs,
    )
    new_jobs = [*loaded, *full_cycle_back_emf_angle_grid(preview, loaded), *anchors]
    before, after = _mesh_bases(preview, [*loaded, *old_grid]), _mesh_bases(preview, new_jobs)
    assert {angle: after[angle] for angle in loaded} == {angle: before[angle] for angle in loaded}
    # Anchors only stand in for bases the 48-angle grid dropped; no extra base meshes.
    assert len(set(after.values())) == len(set(_mesh_bases(preview, new_jobs[: -len(anchors) or None]).values()))


@pytest.mark.parametrize("plan", ["standard", "fine"])
def test_full_cycle_plans_need_no_extra_no_load_solves(plan: str) -> None:
    config = _planned("ipm_14p_flat", plan)
    loaded = loaded_angle_grid(config)
    assert no_load_field_frame_angles(loaded, full_cycle_back_emf_angle_grid(config, loaded)) == []
