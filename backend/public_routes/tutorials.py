"""Launch-safe local tutorial routes for the ten public lessons.

Every route here is a thin wrapper over :mod:`backend.tutorial_fields` (the
teaching fixtures the lessons solve) plus the Lesson 1 2p/6s SPM sweep, which
runs through the same launch-surface Magneto2D solver the rest of the public API
uses. The query parameters and response bodies match the private app's
``/tutorials/*`` routes so the shared lesson components need no fork.

The SSE plumbing and the single-solve claim deliberately reuse
:mod:`backend.public_routes.solve` instead of the private app's copies, so the
public error shape and ``/solve/cancel`` semantics stay uniform across the
public surface.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.field_composition import solve_armature_field_sweep, solve_pm_field_sweep
from backend.gmsh_solver import GmshUnavailableError
from backend.magneto2d_adapter import (
    Magneto2DExecutionError,
    Magneto2DUnsupportedError,
    run_magneto2d_mesh_preview,
)
from backend.models import MotorConfig, SolveOptionsConfig
from backend.public_routes.solve import (
    _ACTIVE_SOLVE,
    _claim_solve,
    _public_field_frame_descriptors,
    _public_result_payload,
    _release_solve,
    _sse_event,
    _stream_error_payload,
)
from backend.solver import Magneto2DSolver
from backend.solver_contract import SolveCancelledError
from backend.tutorial_fields import (
    run_airgap_tax_fixture,
    run_current_field_fixture,
    run_field_force_fixture,
    run_field_force_motor_fixture,
    run_follow_flux_fixture,
    run_iron_saturation_fixture,
    run_iron_saturation_spm_tooth_fixture,
    run_iron_saturation_tooth_fixture,
    run_linear_motor_capstone_fixture,
    run_rotating_field_motor_fixture,
    run_rotating_field_motor_sweep,
    run_rotating_field_sweep,
    run_rotor_chase_fixture,
    run_three_phase_motor_fixture,
    run_three_phase_motor_sweep,
)

router = APIRouter()

LESSON_ONE_DEFAULT_AIRGAP_MM = 1.0
LESSON_ONE_DEFAULT_MAGNET_ARC_PCT = 74.0
LESSON_ONE_DEFAULT_MAGNET_THICKNESS_MM = 4.0
LESSON_ONE_SOLVE_POSITIONS = 48
LESSON_ONE_ROTOR_STEP_DEG = 360 / LESSON_ONE_SOLVE_POSITIONS


def _lesson_one_tutorial_config() -> MotorConfig:
    """Return the balanced three-phase Lesson 1 2p/6s SPM configuration."""

    # model_validate so the nested dicts type-check: mypy flags the kwargs
    # form as dict-vs-model mismatches even though pydantic coerces both.
    return MotorConfig.model_validate(dict(
        schema_version="1.0",
        topology="SPM",
        stator={
            "OD_mm": 120,
            "ID_mm": 74,
            "slot_count": 6,
            "stack_length_mm": 40,
            # Six equal slots support a balanced A/C/B, +/- phase-belt map.
            # The compact mouth and tooth widths keep each teaching slot
            # distinct at the 74 mm bore without crowding adjacent teeth.
            "slot_opening_mm": 12,
            "tooth_width_mm": 16,
            "yoke_thickness_mm": 12,
        },
        rotor={
            "OD_mm": 64,
            "ID_mm": 18,
            "magnet_thickness_mm": 4,
            "magnet_width_mm": 79,
            "pole_count": 2,
            "magnet_embrace": 0.74,
            "bridge_thickness_mm": 1.5,
        },
        winding={
            "type": "concentrated",
            "turns_per_coil": 36,
            "layers": 1,
            "parallel_paths": 1,
        },
        materials={
            "stator_steel": "M350-50A",
            "rotor_steel": "M350-50A",
            "magnet_grade": "N42",
            "conductor": "copper",
        },
        solve_params={
            "solve_quality": "custom",
            "rotor_sweep_range_deg": 360,
            "rotor_step_deg": LESSON_ONE_ROTOR_STEP_DEG,
            "mesh_density": "coarse",
            "mesh_source": "native",
            "mesher": "gmsh",
            # Native Gmsh SPM sweeps must regenerate and retag the mesh at
            # each rotor angle. Reusing the imported mesh would leave the
            # magnets at the as-meshed angle and is rejected by Magneto2D.
            "rotor_rotation_model": "remesh_per_step",
            "current_amplitude_A": 7,
            "current_amplitude_convention": "peak",
            "current_angle_deg": 0,
            "rated_speed_rpm": 1200,
        },
        solve_options={
            "torque_sweep": True,
            "back_emf": False,
            "flux_density": True,
            "cogging_torque": False,
            "thd_analysis": False,
        },
    ))


def _apply_lesson_one_geometry_settings(
    config: MotorConfig,
    airgap_mm: float,
    magnet_arc_pct: float,
    magnet_thickness_mm: float,
) -> None:
    stator_inner_radius_mm = config.stator.ID_mm / 2.0
    magnet_outer_radius_mm = stator_inner_radius_mm - airgap_mm
    magnet_inner_radius_mm = magnet_outer_radius_mm - magnet_thickness_mm
    if magnet_inner_radius_mm <= (config.rotor.ID_mm or 0.0) / 2.0:
        raise ValueError("Lesson geometry leaves no room for the rotor core.")

    pole_pitch_rad = (2.0 * math.pi) / max(1, config.rotor.pole_count)
    magnet_embrace = magnet_arc_pct / 100.0
    magnet_center_radius_mm = (magnet_inner_radius_mm + magnet_outer_radius_mm) / 2.0

    config.rotor.OD_mm = magnet_inner_radius_mm * 2.0
    config.rotor.magnet_thickness_mm = magnet_thickness_mm
    config.rotor.magnet_embrace = magnet_embrace
    config.rotor.magnet_width_mm = magnet_center_radius_mm * pole_pitch_rad * magnet_embrace


def _apply_lesson_one_solve_settings(
    config: MotorConfig,
    phase_current_a: float,
    current_angle_deg: float,
) -> None:
    if config.solve_params is None:
        return
    config.solve_params.current_amplitude_A = phase_current_a
    config.solve_params.current_angle_deg = current_angle_deg


def _lesson_one_field_composition_config(
    phase_current_a: float,
    current_angle_deg: float,
    airgap_mm: float,
    magnet_arc_pct: float,
    magnet_thickness_mm: float,
    mesh_density: Literal["coarse", "normal", "fine"],
) -> MotorConfig:
    """Build the same 2p/6s operating point for a source-separated sweep."""

    config = _lesson_one_tutorial_config()
    _apply_lesson_one_geometry_settings(config, airgap_mm, magnet_arc_pct, magnet_thickness_mm)
    _apply_lesson_one_solve_settings(config, phase_current_a, current_angle_deg)
    assert config.solve_params is not None
    config.solve_params.mesh_density = mesh_density
    config.solve_options = SolveOptionsConfig(
        torque_sweep=True,
        back_emf=False,
        flux_density=True,
        cogging_torque=False,
        thd_analysis=False,
    )
    return config


def _public_lesson_one_field_composition_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Expose renderable artifact ids and numeric facts without local paths."""

    frames = _public_field_frame_descriptors(response.get("frames"))
    # A 36-bin profile repeated across 48 frames is unnecessary here: Lesson 9
    # preserves the user's selected angle when switching sources and can use
    # the retained max/mean summary for its initial best-frame fallback.
    for frame in frames:
        frame.pop("airgap_brbt", None)
    return {
        "schema_version": response.get("schema_version"),
        "cache_hit": bool(response.get("cache_hit")),
        "source": response.get("source"),
        "magnet_remanence_scale": response.get("magnet_remanence_scale"),
        "current_amplitude_A": response.get("current_amplitude_A"),
        "current_angle_deg": response.get("current_angle_deg"),
        "frame_count": len(frames),
        "elapsed_s": response.get("elapsed_s"),
        "frames": frames,
    }


def _lesson_one_solve_payload(result: Any) -> dict[str, Any]:
    """Scrub a Lesson 1 solve result and tag it with the sweep's teaching facts.

    The private app builds this from its own ``_solve_result_complete_payload``;
    the public app routes it through the shared public sanitizer instead so the
    lesson stream cannot ship a field the rest of the public surface withholds.
    """

    payload = _public_result_payload(result)
    torque_waveform = getattr(result, "torque_waveform", None)
    angles = getattr(torque_waveform, "electrical_angle_deg", None) if torque_waveform else None
    field_frames = getattr(result, "field_line_frames", None) or []
    payload["tutorial_solve"] = {
        "mode": "balanced",
        "sweep_range_deg": 360,
        "rotor_step_deg": LESSON_ONE_ROTOR_STEP_DEG,
        "positions": len(angles or []),
        "field_frame_count": len(field_frames),
    }
    return payload


@router.get("/tutorials/follow-the-flux/solve", tags=["tutorials"])
async def follow_flux_solve(
    steel_return: bool = Query(False),
    steel_shape: Literal["bar", "plate", "puck"] = Query("bar"),
    steel_center_x_mm: float = Query(28.0, ge=-44.0, le=44.0),
    steel_center_y_mm: float = Query(0.0, ge=-28.0, le=28.0),
    magnet_center_x_mm: float = Query(0.0, ge=-30.0, le=30.0),
    magnet_center_y_mm: float = Query(0.0, ge=-26.0, le=26.0),
    magnet_angle_deg: float = Query(0.0, ge=-180.0, le=180.0),
    magnet2_enabled: bool = Query(False),
    magnet2_center_x_mm: float = Query(44.0, ge=-44.0, le=44.0),
    magnet2_center_y_mm: float = Query(0.0, ge=-26.0, le=26.0),
    magnet2_angle_deg: float = Query(0.0, ge=-180.0, le=180.0),
    steel_angle_deg: float = Query(0.0, ge=-180.0, le=180.0),
    mesh_density: Literal["coarse", "normal", "fine"] = Query("normal"),
) -> dict[str, Any]:
    """Solve the Lesson 1 field fixture with or without its steel return path."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_follow_flux_fixture,
                steel_return=steel_return,
                steel_shape=steel_shape,
                steel_center_x_mm=steel_center_x_mm,
                steel_center_y_mm=steel_center_y_mm,
                magnet_center_x_mm=magnet_center_x_mm,
                magnet_center_y_mm=magnet_center_y_mm,
                magnet_angle_deg=magnet_angle_deg,
                magnet2_enabled=magnet2_enabled,
                magnet2_center_x_mm=magnet2_center_x_mm,
                magnet2_center_y_mm=magnet2_center_y_mm,
                magnet2_angle_deg=magnet2_angle_deg,
                steel_angle_deg=steel_angle_deg,
                mesh_density=mesh_density,
                solve=True,
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Follow-the-flux solve timed out after 120s")
    except Magneto2DExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/airgap-tax/solve", tags=["tutorials"])
async def airgap_tax_solve(
    airgap_mm: float = Query(4.0, ge=0.5, le=8.0),
) -> dict[str, Any]:
    """Solve the Lesson 2 magnet and U-core fixture at the requested airgap."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_airgap_tax_fixture,
                airgap_mm=airgap_mm,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Airgap-tax solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/current-field/solve", tags=["tutorials"])
async def current_field_solve(
    current_a: float = Query(8.0, ge=-20.0, le=20.0),
) -> dict[str, Any]:
    """Solve the Lesson 3 straight-conductor fixture at the requested current."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_current_field_fixture,
                current_a=current_a,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Current-field solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/iron-saturation/solve", tags=["tutorials"])
async def iron_saturation_solve(
    current_a: float = Query(100.0, ge=0.0, le=1200.0),
) -> dict[str, Any]:
    """Solve the Lesson 4 nonlinear M350-50A ring at the requested current."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_iron_saturation_fixture,
                current_a=current_a,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Iron-saturation solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/iron-saturation/tooth/solve", tags=["tutorials"])
async def iron_saturation_tooth_solve(
    current_a: float = Query(8.0, ge=0.0, le=20.0),
) -> dict[str, Any]:
    """Solve the Lesson 4 concentrated winding and nonlinear motor tooth."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_iron_saturation_tooth_fixture,
                current_a=current_a,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Iron-tooth solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/iron-saturation/spm-tooth/solve", tags=["tutorials"])
async def iron_saturation_spm_tooth_solve(
    current_a: float = Query(0.0, ge=0.0, le=20.0),
) -> dict[str, Any]:
    """Solve the Lesson 4 wound tooth facing an N42 surface magnet."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_iron_saturation_spm_tooth_fixture,
                current_a=current_a,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="SPM-tooth solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/field-force/solve", tags=["tutorials"])
async def field_force_solve(
    current_a: float = Query(8.0, ge=-20.0, le=20.0),
    pole_gap_mm: float = Query(8.0, ge=0.5, le=16.0),
) -> dict[str, Any]:
    """Solve the Lesson 5 current-carrying conductor between magnet poles."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_field_force_fixture,
                current_a=current_a,
                pole_gap_mm=pole_gap_mm,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Field-force solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/field-force/motor/solve", tags=["tutorials"])
async def field_force_motor_solve(
    current_a: float = Query(8.0, ge=-20.0, le=20.0),
    loop_angle_deg: float = Query(90.0, ge=0.0, le=360.0),
    pole_gap_mm: float = Query(8.0, ge=0.5, le=16.0),
) -> dict[str, Any]:
    """Run a fresh Lesson 5 FEM side-force solve and return loop torque."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_field_force_motor_fixture,
                current_a=current_a,
                loop_angle_deg=loop_angle_deg,
                pole_gap_mm=pole_gap_mm,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Motor-effect solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/field-force/wire-only/solve", tags=["tutorials"])
async def field_force_wire_only_solve(
    current_a: float = Query(8.0, ge=-20.0, le=20.0),
    pole_gap_mm: float = Query(8.0, ge=0.5, le=16.0),
) -> dict[str, Any]:
    """Solve only the conductor-current contribution on the Lesson 5 mesh."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_field_force_fixture,
                current_a=current_a,
                pole_gap_mm=pole_gap_mm,
                wire_only=True,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Wire-only field solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/field-force/magnet-only/solve", tags=["tutorials"])
async def field_force_magnet_only_solve(
    pole_gap_mm: float = Query(8.0, ge=0.5, le=16.0),
) -> dict[str, Any]:
    """Solve only the permanent-magnet contribution on the Lesson 5 mesh."""

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(
                run_field_force_fixture,
                current_a=0.0,
                pole_gap_mm=pole_gap_mm,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
        payload["magnet_only"] = True
        return payload
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Magnet-only field solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/chapter-1-capstone/solve", tags=["tutorials"])
async def chapter_one_capstone_solve(
    current_a: float = Query(0.0, ge=-20.0, le=20.0),
    airgap_mm: float = Query(8.0, ge=2.0, le=10.0),
    winding_spacing_mm: float = Query(18.0, ge=12.0, le=22.0),
    magnet_1: int = Query(1, ge=-1, le=1),
    magnet_2: int = Query(1, ge=-1, le=1),
    magnet_3: int = Query(1, ge=-1, le=1),
    magnet_4: int = Query(1, ge=-1, le=1),
) -> dict[str, Any]:
    """Solve the Chapter 1 linear actuator's PM and moving-winding field."""

    orientations = (magnet_1, magnet_2, magnet_3, magnet_4)
    if any(orientation == 0 for orientation in orientations):
        raise HTTPException(status_code=422, detail="Each magnet orientation must be -1 or 1")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_linear_motor_capstone_fixture,
                current_a=current_a,
                airgap_mm=airgap_mm,
                magnet_orientations=orientations,
                winding_spacing_mm=winding_spacing_mm,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Linear-capstone solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/rotating-field/sweep", tags=["tutorials"])
async def rotating_field_sweep(
    peak_current_a: float = Query(8.0, gt=0.0, le=20.0),
) -> dict[str, Any]:
    """Solve one electrical revolution of the Lesson 6 two-phase field."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_rotating_field_sweep,
                peak_current_a=peak_current_a,
                mesh_density="normal",
            ),
            timeout=180.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Rotating-field sweep timed out after 180s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/rotating-field/motor-sweep", tags=["tutorials"])
async def rotating_field_motor_sweep(
    peak_current_a: float = Query(8.0, gt=0.0, le=20.0),
    field_component: Literal["combined", "stator", "rotor"] = Query("combined"),
) -> dict[str, Any]:
    """Solve one Lesson 7 four-pole source view over an electrical cycle."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_rotating_field_motor_sweep,
                peak_current_a=peak_current_a,
                field_component=field_component,
                mesh_density="normal",
            ),
            timeout=180.0,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Rotating-field motor sweep timed out after 180s",
        )
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/rotating-field/motor-geometry", tags=["tutorials"])
async def rotating_field_motor_geometry() -> dict[str, Any]:
    """Return the real Lesson 7 Gmsh motor geometry without waiting for its field sweep."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_rotating_field_motor_fixture,
                electrical_angle_deg=0.0,
                rotor_angle_deg=-15.0,
                peak_current_a=8.0,
                mesh_density="normal",
                solve=False,
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Rotating-field motor geometry timed out after 120s",
        )
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/three-phase-motor/sweep", tags=["tutorials"])
async def three_phase_motor_sweep(
    peak_current_a: float = Query(8.0, gt=0.0, le=20.0),
    field_component: Literal[
        "combined",
        "stator",
        "rotor",
        "phase_a",
        "phase_b",
        "phase_c",
        "open_c",
    ] = Query("combined"),
) -> dict[str, Any]:
    """Solve one Lesson 8 three-phase source view over an electrical cycle."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_three_phase_motor_sweep,
                peak_current_a=peak_current_a,
                field_component=field_component,
                mesh_density="normal",
            ),
            timeout=180.0,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Three-phase motor sweep timed out after 180s",
        )
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/three-phase-motor/geometry", tags=["tutorials"])
async def three_phase_motor_geometry() -> dict[str, Any]:
    """Return the exact Lesson 8 Gmsh geometry without waiting for field solves."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_three_phase_motor_fixture,
                electrical_angle_deg=0.0,
                rotor_angle_deg=-15.0,
                peak_current_a=8.0,
                mesh_density="normal",
                solve=False,
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Three-phase motor geometry timed out after 120s",
        )
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/rotor-chase/solve", tags=["tutorials"])
async def rotor_chase_solve(
    field_source: Literal["stator", "rotor", "combined"] = Query("combined"),
    rotor_angle_deg: float = Query(90.0, ge=-180.0, le=360.0),
    pole_gap_mm: float = Query(8.0, ge=2.0, le=16.0),
    source_kind: Literal["pm", "electromagnet"] = Query("pm"),
    source_current_a: float = Query(0.0, ge=-20.0, le=20.0),
) -> dict[str, Any]:
    """Solve the Lesson 6 PM or wound-pole source with the PM rotor."""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_rotor_chase_fixture,
                field_source=field_source,
                rotor_angle_deg=rotor_angle_deg,
                pole_gap_mm=pole_gap_mm,
                source_kind=source_kind,
                source_current_a=source_current_a,
                mesh_density="normal",
            ),
            timeout=120.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Rotor-chase solve timed out after 120s")
    except (Magneto2DExecutionError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tutorials/lesson-1/mesh-preview", tags=["tutorials"])
async def lesson_one_mesh_preview(
    airgap_mm: float = Query(LESSON_ONE_DEFAULT_AIRGAP_MM, ge=0.5, le=2.5),
    magnet_arc_pct: float = Query(LESSON_ONE_DEFAULT_MAGNET_ARC_PCT, ge=55.0, le=90.0),
    magnet_thickness_mm: float = Query(LESSON_ONE_DEFAULT_MAGNET_THICKNESS_MM, ge=2.5, le=6.0),
    mesh_density: Literal["coarse", "normal", "fine"] = Query("coarse"),
) -> dict[str, Any]:
    """Generate the Lesson 1 2p/6s SPM Gmsh mesh preview."""

    config = _lesson_one_tutorial_config()
    _apply_lesson_one_geometry_settings(config, airgap_mm, magnet_arc_pct, magnet_thickness_mm)
    if config.solve_params is not None:
        config.solve_params.mesh_density = mesh_density
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(run_magneto2d_mesh_preview, config),
            timeout=300.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Lesson 1 mesh preview timed out after 300s")
    except Magneto2DUnsupportedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GmshUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Magneto2DExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _run_lesson_one_field_composition(
    *,
    source: Literal["pm", "armature"],
    phase_current_a: float,
    current_angle_deg: float,
    airgap_mm: float,
    magnet_arc_pct: float,
    magnet_thickness_mm: float,
    mesh_density: Literal["coarse", "normal", "fine"],
) -> dict[str, Any]:
    config = _lesson_one_field_composition_config(
        phase_current_a,
        current_angle_deg,
        airgap_mm,
        magnet_arc_pct,
        magnet_thickness_mm,
        mesh_density,
    )
    solver = Magneto2DSolver(launch_surface=True)
    _claim_solve(solver)
    solve_function = solve_pm_field_sweep if source == "pm" else solve_armature_field_sweep
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                solve_function,
                config,
                solver_factory=lambda: solver,
            ),
            timeout=300.0,
        )
        return _public_lesson_one_field_composition_payload(response)
    except TimeoutError as exc:
        solver.cancel_active_solve()
        label = "rotor-only" if source == "pm" else "stator-only"
        raise HTTPException(
            status_code=504,
            detail=f"Lesson 9 {label} field solve timed out after 300s",
        ) from exc
    except Magneto2DUnsupportedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GmshUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Magneto2DExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _release_solve(solver)


@router.get("/tutorials/lesson-1/field-composition/pm", tags=["tutorials"])
async def lesson_one_field_composition_pm(
    phase_current_a: float = Query(7.0, ge=0.0, le=20.0),
    current_angle_deg: float = Query(0.0, ge=0.0, le=360.0),
    airgap_mm: float = Query(LESSON_ONE_DEFAULT_AIRGAP_MM, ge=0.5, le=2.5),
    magnet_arc_pct: float = Query(LESSON_ONE_DEFAULT_MAGNET_ARC_PCT, ge=55.0, le=90.0),
    magnet_thickness_mm: float = Query(LESSON_ONE_DEFAULT_MAGNET_THICKNESS_MM, ge=2.5, le=6.0),
    mesh_density: Literal["coarse", "normal", "fine"] = Query("coarse"),
) -> dict[str, Any]:
    """Run the exact zero-current, permanent-magnet-only Lesson 9 sweep."""

    return await _run_lesson_one_field_composition(
        source="pm",
        phase_current_a=phase_current_a,
        current_angle_deg=current_angle_deg,
        airgap_mm=airgap_mm,
        magnet_arc_pct=magnet_arc_pct,
        magnet_thickness_mm=magnet_thickness_mm,
        mesh_density=mesh_density,
    )


@router.get("/tutorials/lesson-1/field-composition/armature", tags=["tutorials"])
async def lesson_one_field_composition_armature(
    phase_current_a: float = Query(7.0, gt=0.0, le=20.0),
    current_angle_deg: float = Query(0.0, ge=0.0, le=360.0),
    airgap_mm: float = Query(LESSON_ONE_DEFAULT_AIRGAP_MM, ge=0.5, le=2.5),
    magnet_arc_pct: float = Query(LESSON_ONE_DEFAULT_MAGNET_ARC_PCT, ge=55.0, le=90.0),
    magnet_thickness_mm: float = Query(LESSON_ONE_DEFAULT_MAGNET_THICKNESS_MM, ge=2.5, le=6.0),
    mesh_density: Literal["coarse", "normal", "fine"] = Query("coarse"),
) -> dict[str, Any]:
    """Run the exact Br=0, stator-current-only Lesson 9 sweep."""

    return await _run_lesson_one_field_composition(
        source="armature",
        phase_current_a=phase_current_a,
        current_angle_deg=current_angle_deg,
        airgap_mm=airgap_mm,
        magnet_arc_pct=magnet_arc_pct,
        magnet_thickness_mm=magnet_thickness_mm,
        mesh_density=mesh_density,
    )


@router.get("/tutorials/lesson-1/solve/stream", tags=["tutorials"])
async def lesson_one_solve_stream(
    phase_current_a: float = Query(7.0, ge=0.0, le=20.0),
    current_angle_deg: float = Query(0.0, ge=0.0, le=360.0),
    airgap_mm: float = Query(LESSON_ONE_DEFAULT_AIRGAP_MM, ge=0.5, le=2.5),
    magnet_arc_pct: float = Query(LESSON_ONE_DEFAULT_MAGNET_ARC_PCT, ge=55.0, le=90.0),
    magnet_thickness_mm: float = Query(LESSON_ONE_DEFAULT_MAGNET_THICKNESS_MM, ge=2.5, le=6.0),
    mesh_density: Literal["coarse", "normal", "fine"] = Query("coarse"),
) -> StreamingResponse:
    """Stream Lesson 1's balanced 0-360 loaded torque sweep."""

    config = _lesson_one_tutorial_config()
    _apply_lesson_one_geometry_settings(config, airgap_mm, magnet_arc_pct, magnet_thickness_mm)
    _apply_lesson_one_solve_settings(config, phase_current_a, current_angle_deg)
    if config.solve_params is not None:
        config.solve_params.mesh_density = mesh_density
    config.solve_options = SolveOptionsConfig(
        torque_sweep=True,
        back_emf=False,
        flux_density=True,
        cogging_torque=False,
        thd_analysis=False,
    )

    solver = Magneto2DSolver(launch_surface=True)
    _claim_solve(solver)

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        future: asyncio.Task[Any] | None = None

        def on_progress(
            position: int,
            total: int,
            torque_Nm: float | None,
            stage: str = "torque_sweep",
            elec_deg: float | None = None,
            phase_a_V: float | None = None,
            phase_b_V: float | None = None,
            phase_c_V: float | None = None,
            field_line_frame: dict[str, Any] | None = None,
            solver_detail: dict[str, Any] | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "position": position,
                "total": total,
                "elapsed_s": round(time.perf_counter() - started, 1),
                "stage": stage,
            }
            # The lesson chart reads torque and angle only; the live field
            # frames stay off the wire and are fetched per position from
            # /solve/field-frame/{artifact_id} after the complete event.
            optional_values = {
                "torque_Nm": torque_Nm,
                "angle_deg": elec_deg,
                "phase_a_V": phase_a_V,
                "phase_b_V": phase_b_V,
                "phase_c_V": phase_c_V,
                "solver_detail": solver_detail,
            }
            payload.update(
                {
                    key: value
                    for key, value in optional_values.items()
                    if value is not None
                }
            )
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        try:
            yield _sse_event(
                "progress",
                {
                    "position": 0,
                    "total": 0,
                    "stage": "starting",
                    "elapsed_s": 0,
                },
            )
            future = asyncio.create_task(
                asyncio.to_thread(solver.solve, config, on_progress=on_progress)
            )
            while not future.done():
                try:
                    progress = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield _sse_event("progress", progress)
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                yield _sse_event("progress", queue.get_nowait())

            result = await future
            if _ACTIVE_SOLVE["cancelled"]:
                raise SolveCancelledError("Solve cancelled by user.")
            public_result = await asyncio.to_thread(_lesson_one_solve_payload, result)
            # The solve and response packaging are both complete. Release the
            # single-solver lane before the browser receives the terminal
            # event so an immediate Stator-only / Rotor-only selection cannot
            # race the generator's final cleanup and receive a false 409.
            _release_solve(solver)
            yield _sse_event("complete", public_result)
        except asyncio.CancelledError:
            solver.cancel_active_solve()
            raise
        except Exception as exc:
            yield _sse_event("error", _stream_error_payload(exc))
        finally:
            if future is not None and not future.done():
                solver.cancel_active_solve()
            _release_solve(solver)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
