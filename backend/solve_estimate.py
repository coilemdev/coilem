"""Wall-clock estimate for a local Magneto2D solve.

The estimate follows the work the solver plans instead of a flat cost per
rotor position. Gmsh meshes every distinct angle of the loaded grid, the
full-cycle Back-EMF grid and the cogging period, except that angles a whole
slot pitch apart share one mesh; the field solves overlap that meshing; and
packaging builds field playback for every loaded position. Each term scales
with the mesh size. A sector solve (``solve_params.symmetry = "auto"`` on a
motor that repeats) meshes and solves only one repeating sector, so the size
that counts is the sector's.

The coefficients come from timed runs of the bundled examples (Preview,
Standard and High accuracy) on a 10-core Apple-silicon laptop with coilEM
0.5.8 and Magneto2D 0.6.0 (tests/fixtures/solve_time_calibration.json).
Machines differ, so callers show the range.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from backend.geometry_drawer import compute_geometry
from backend.geometry_ir import build_geometry_ir
from backend.gmsh_mesh_rotation import full_cycle_congruent_bases, gmsh_mesh_reuse_enabled, slot_congruence_groups
from backend.magneto2d_adapter import get_cached_solve_mesh_artifact
from backend.models import MotorConfig
from backend.sector_geometry import detect_sector_symmetry
from backend.solver import _cogging_angle_grid, _gmsh_pipeline_worker_count
from backend.sweep_planning import full_cycle_back_emf_angle_grid, loaded_angle_grid, no_load_field_frame_angles

if TYPE_CHECKING:
    from backend.flux_linkage_map import MapStore
    from backend.models.config import TorqueSpeedAnalysisConfig

# Validation, run storage and the stream outside the solver: 1.9 to 2.5 s for Preview.
_FIXED_S = 2.0
# Seconds per base mesh per 1000 elements, with the reference producer pool.
_MESH_S_PER_KELEMENT = 0.0191
_REFERENCE_MESH_WORKERS = 8
# Fast mesh build (solve_params.mesh_build): the meshing stage took 0.47x
# (IPM 14p) and 0.71x (SPM 24p) of its Precise time in one timed pass.
_FAST_MESH_FACTOR = 0.6
# Seconds per loaded position per 1000 elements: its field solve, playback and saving.
_FINALIZE_S_PER_KELEMENT = 0.0098
# Registered full-motor SPM pilot: 925.75 summed pose seconds / 385 poses /
# 89.16k elements. The opt-in rotor stage runs up to four positions by default.
_ROTOR_S_PER_POSITION_KELEMENT = 0.027
# The ten calibration runs took 0.79x (surface-magnet) to 1.66x (interior-magnet
# rotors mesh slower) the central estimate on battery power; the low end leaves
# room for a faster run on mains power.
_RANGE = (0.7, 1.75)
# Elements per mesh-density step relative to coarse, for when no prepared mesh exists.
# Measured: normal about 2x coarse, fine about 3% above normal; very fine is a guess.
_DENSITY_ELEMENT_FACTOR = {"coarse": 1.0, "normal": 2.0, "fine": 2.1, "very_fine": 4.0}
# The Elmer lane remeshes and solves every position externally.
_ELMER_FACTOR = 3.0
# A torque-speed map solves its grid points one after another, each over half an
# electrical cycle (backend.flux_linkage_map), with its meshes from the solve cache
# after the first point. Each point costs a fixed part (setup, loss and d/q
# post-processing) and a part per rotor position; the three timed maps took 0.96x
# to 1.12x this estimate.
_MAP_POINT_S = 2.0
_MAP_S_PER_POSITION_KELEMENT = 0.006


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


def sector_repeats(config: MotorConfig, solver_id: str = "magneto2d") -> int:
    """How many copies of the solved region make up the motor: 1 for a full-motor solve.

    The mesher's own check (``gmsh_solver._sector_ir_for_solve``) without meshing:
    Magneto2D solves a sector of an SPM or IPM design with ``symmetry = "auto"``
    when its geometry and winding repeat. In the rare case that the mesher then
    cannot cut that sector cleanly, it solves the full motor, and the estimate
    reads low until a prepared mesh gives the real size.
    """

    if (
        solver_id != "magneto2d"
        or config.solve_params is None
        or config.solve_params.symmetry != "auto"
        or str(config.topology).upper() not in {"SPM", "IPM"}
    ):
        return 1
    try:
        symmetry = detect_sector_symmetry(build_geometry_ir(config, geom=compute_geometry(config), rotor_angle_deg=0.0))
    except Exception:  # noqa: BLE001 - an estimate never fails the request it accompanies
        return 1
    return symmetry.repeats if symmetry is not None else 1


def prepared_mesh_elements(solve_mesh_key: str | None, config: MotorConfig) -> int | None:
    """Element count of the mesh the UI prepared for ``config``, while cached.

    For a sector solve that is the solved sector, not the whole motor the Mesh
    tab draws.
    """

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
    # The cogging period (#185), less the angles the Back-EMF grid already solves.
    no_load_keys = {int(round(float(angle) * 1_000_000.0)) for angle in (*no_load, *frame_only)}
    cogging = [angle for angle in _cogging_angle_grid(config) if int(round(float(angle) * 1_000_000.0)) not in no_load_keys]
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
    for angle in (*loaded, *no_load, *cogging, *anchors):
        key = int(round(float(angle) * 1_000_000.0))
        jobs.setdefault(key, {"angle_key": key, "rotor_angle_mech_deg": rotor_angle_mech_deg(angle)})
    mesh_jobs = list(jobs.values())
    base_meshes = len(mesh_jobs)
    if gmsh_mesh_reuse_enabled() and len(mesh_jobs) > 1:
        base_meshes = len(slot_congruence_groups(mesh_jobs, config.stator.slot_count))
    return {
        "loaded": len(loaded),
        "no_load": len(no_load) + len(frame_only) + len(cogging),
        "mesh_jobs": len(mesh_jobs),
        "base_meshes": base_meshes,
        **({"rotor_iron_loss": _rotor_positions(config)} if options and options.rotor_iron_loss else {}),
    }


def _rotor_positions(config):
    from backend.rotor_loss_solver import planned_positions

    return planned_positions(config)


def mesh_workers(mesh_jobs: int) -> int:
    """Gmsh producer processes the solver will use: up to eight, one per CPU."""

    return _gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", mesh_jobs, uses_process_pool=True)


def estimate_solve(config: MotorConfig, *, mesh_elements: int | None = None, solver_id: str = "magneto2d") -> SolveEstimate:
    work = planned_work(config)
    source: Literal["prepared_mesh", "estimate"] = "prepared_mesh" if mesh_elements else "estimate"
    elements = mesh_elements or max(1, round(heuristic_mesh_elements(config) / sector_repeats(config, solver_id)))
    kelements = elements / 1000.0
    workers = mesh_workers(work["mesh_jobs"])
    mesh_s = _MESH_S_PER_KELEMENT * work["base_meshes"] * kelements * min(_REFERENCE_MESH_WORKERS, work["mesh_jobs"]) / workers
    if config.solve_params is not None and config.solve_params.mesh_build == "fast":
        mesh_s *= _FAST_MESH_FACTOR
    seconds = _FIXED_S + mesh_s + _FINALIZE_S_PER_KELEMENT * work["loaded"] * kelements
    rotor_positions = work.get("rotor_iron_loss", 0) if solver_id != "elmer" else 0
    if rotor_positions:
        rotor_workers = max(1, min(8, config.solve_params.magneto2d_workers or 4))
        seconds += _MESH_S_PER_KELEMENT*kelements + _ROTOR_S_PER_POSITION_KELEMENT*rotor_positions*kelements/rotor_workers
    if solver_id == "elmer":
        seconds *= _ELMER_FACTOR
    return SolveEstimate(
        seconds=seconds,
        low_s=seconds * _RANGE[0],
        high_s=seconds * _RANGE[1],
        mesh_elements=elements,
        mesh_elements_source=source,
        base_meshes=work["base_meshes"] + bool(rotor_positions),
        field_solves=work["loaded"] + work["no_load"] + rotor_positions,
    )



@dataclass(frozen=True)
class MapEstimate:
    seconds: float
    low_s: float
    high_s: float
    solves: int
    solves_remaining: int
    positions_per_point: int


def stored_map_points(store: MapStore, currents: Sequence[float], gammas: Sequence[float], *, require_rotor_loss: bool = False) -> int:
    """Grid points a map store already holds; a map run solves only the others."""

    finished = sum(1 for current in currents for gamma in gammas
                   if current > 0 and store.load(current, gamma, require_rotor_loss=require_rotor_loss) is not None)
    zero = any(current == 0 for current in currents) and store.load(0.0, gammas[0], require_rotor_loss=require_rotor_loss) is not None
    return finished + (1 if zero else 0)


def estimate_map(
    settings: TorqueSpeedAnalysisConfig, *, mesh_elements: int, store: MapStore | None = None,
    rotor_positions: int = 0, rotor_workers: int = 4,
) -> MapEstimate:
    """Wall-clock estimate for a torque-speed map, counting only the points ``store`` lacks.

    A stored map that covers the peak current is reused whole, so it costs nothing.
    """

    from backend.flux_linkage_map import map_grid, map_positions_per_point, map_solve_count

    currents, gammas = map_grid(settings.limits.peak_current_A, settings.preset)
    solves = map_solve_count(currents, gammas)
    remaining = solves
    if store is not None:
        remaining = 0 if store.covering_map(settings.limits.peak_current_A) is not None else (
            solves - stored_map_points(store, currents, gammas, require_rotor_loss=rotor_positions > 0)
        )
    positions = map_positions_per_point(settings.preset)
    seconds = remaining * (_MAP_POINT_S + _MAP_S_PER_POSITION_KELEMENT * positions * mesh_elements / 1000.0)
    if rotor_positions:
        seconds += remaining * mesh_elements / 1000.0 * (
            _MESH_S_PER_KELEMENT + _ROTOR_S_PER_POSITION_KELEMENT * rotor_positions / max(1, min(8, rotor_workers)))
    return MapEstimate(
        seconds=seconds,
        low_s=seconds * _RANGE[0],
        high_s=seconds * _RANGE[1],
        solves=solves,
        solves_remaining=remaining,
        positions_per_point=positions + rotor_positions,
    )
