"""Wall-clock estimate for a local Magneto2D solve.

The estimate follows the work the solver plans instead of a flat cost per
rotor position. Gmsh meshes every distinct angle of the loaded grid and the
full-cycle Back-EMF grid, except that angles a whole slot pitch apart share
one mesh; the field solves overlap that meshing; and packaging builds field
playback for every loaded position. Each term scales with the mesh size.

The coefficients come from timed runs of the bundled examples (Preview,
Standard and High accuracy) on a 10-core Apple-silicon laptop with coilEM
0.2.0 and Magneto2D 0.3.2. Machines differ, so callers show the range.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.gmsh_mesh_rotation import full_cycle_congruent_bases, gmsh_mesh_reuse_enabled, slot_congruence_groups
from backend.magneto2d_adapter import get_cached_solve_mesh_artifact
from backend.models import MotorConfig
from backend.solver import _gmsh_pipeline_worker_count
from backend.sweep_planning import full_cycle_back_emf_angle_grid, loaded_angle_grid, no_load_field_frame_angles

_FIXED_S = 8.4
# Seconds per base mesh per 1000 elements, with the reference producer pool.
_MESH_S_PER_KELEMENT = 0.0394
_REFERENCE_MESH_WORKERS = 8
# Seconds per loaded position per 1000 elements: field playback and saving.
_FINALIZE_S_PER_KELEMENT = 0.0605
# The ten calibration runs took 0.82x to 1.32x the central estimate
# (tests/fixtures/solve_time_calibration.json).
_RANGE = (0.75, 1.4)
# Elements per mesh-density step relative to coarse, for when no prepared mesh exists.
# Measured: normal about 2x coarse, fine about 3% above normal; very fine is a guess.
_DENSITY_ELEMENT_FACTOR = {"coarse": 1.0, "normal": 2.0, "fine": 2.1, "very_fine": 4.0}
# The Elmer lane remeshes and solves every position externally.
_ELMER_FACTOR = 3.0


@dataclass(frozen=True)
class SolveEstimate:
    seconds: float
    low_s: float
    high_s: float
    mesh_elements: int
    mesh_elements_source: Literal["prepared_mesh", "estimate"]
    base_meshes: int
    field_solves: int


def heuristic_mesh_elements(config: MotorConfig) -> int:
    """Approximate elements for the config's mesh density without meshing."""

    coarse = config.stator.slot_count * 500 + config.rotor.pole_count * 200 + 5000
    density = config.solve_params.mesh_density if config.solve_params else "normal"
    return int(round(coarse * _DENSITY_ELEMENT_FACTOR.get(density, 2.0)))


def prepared_mesh_elements(solve_mesh_key: str | None, config: MotorConfig) -> int | None:
    """Element count of the mesh the UI prepared for ``config``, while cached."""

    artifact = get_cached_solve_mesh_artifact(solve_mesh_key, config)
    mesh = artifact.get("mesh") if isinstance(artifact, dict) else None
    triangles = mesh.get("triangles") if isinstance(mesh, dict) else None
    return len(triangles) if isinstance(triangles, list) and triangles else None


def planned_work(config: MotorConfig) -> dict[str, int]:
    """Meshes and field solves the Magneto2D pipeline plans for ``config``."""

    loaded = loaded_angle_grid(config)
    options = config.solve_options
    no_load = full_cycle_back_emf_angle_grid(config, loaded) if options and (options.back_emf or options.thd_analysis) else []
    # Loaded positions off the Back-EMF grid also get a no-load solve, for their
    # PM-only frames; they are meshed for the loaded solve anyway (#58).
    frame_only = (
        no_load_field_frame_angles(loaded, no_load)
        if no_load and config.solve_params is not None and config.solve_params.stream_noload_field_lines
        else []
    )
    pole_pairs = max(1, config.rotor.pole_count // 2)

    def rotor_angle_mech_deg(angle: float) -> float:
        # The public solver's clockwise-positive convention, which picks each
        # congruence class's meshed base.
        return -float(angle) / pole_pairs

    anchors = (
        full_cycle_congruent_bases(
            loaded,
            step_deg=loaded[1] - loaded[0],
            slot_count=config.stator.slot_count,
            pole_pairs=pole_pairs,
            rotor_angle_mech_deg=rotor_angle_mech_deg,
        )
        if gmsh_mesh_reuse_enabled() and no_load and len(loaded) > 1 and no_load_field_frame_angles(loaded, no_load)
        else []
    )
    jobs: dict[int, dict[str, Any]] = {}
    for angle in (*loaded, *no_load, *anchors):
        key = int(round(float(angle) * 1_000_000.0))
        jobs.setdefault(key, {"angle_key": key, "rotor_angle_mech_deg": rotor_angle_mech_deg(angle)})
    mesh_jobs = list(jobs.values())
    base_meshes = len(mesh_jobs)
    if gmsh_mesh_reuse_enabled() and len(mesh_jobs) > 1:
        base_meshes = len(slot_congruence_groups(mesh_jobs, config.stator.slot_count))
    return {
        "loaded": len(loaded),
        "no_load": len(no_load) + len(frame_only),
        "mesh_jobs": len(mesh_jobs),
        "base_meshes": base_meshes,
    }


def mesh_workers(mesh_jobs: int) -> int:
    """Gmsh producer processes the solver will use: up to eight, one per CPU."""

    return _gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", mesh_jobs, uses_process_pool=True)


def estimate_solve(config: MotorConfig, *, mesh_elements: int | None = None, solver_id: str = "magneto2d") -> SolveEstimate:
    work = planned_work(config)
    source: Literal["prepared_mesh", "estimate"] = "prepared_mesh" if mesh_elements else "estimate"
    elements = mesh_elements or heuristic_mesh_elements(config)
    kelements = elements / 1000.0
    workers = mesh_workers(work["mesh_jobs"])
    mesh_s = _MESH_S_PER_KELEMENT * work["base_meshes"] * kelements * min(_REFERENCE_MESH_WORKERS, work["mesh_jobs"]) / workers
    seconds = _FIXED_S + mesh_s + _FINALIZE_S_PER_KELEMENT * work["loaded"] * kelements
    if solver_id == "elmer":
        seconds *= _ELMER_FACTOR
    return SolveEstimate(
        seconds=seconds,
        low_s=seconds * _RANGE[0],
        high_s=seconds * _RANGE[1],
        mesh_elements=elements,
        mesh_elements_source=source,
        base_meshes=work["base_meshes"],
        field_solves=work["loaded"] + work["no_load"],
    )
