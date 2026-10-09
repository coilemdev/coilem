"""Adapter between motor configurations and native Magneto2D reports.

Owns support checks, request translation and Rust process execution.
Streaming parsers and shared process state live in adjacent modules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from math import ceil, gcd, isfinite
from pathlib import Path
from typing import Any

from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.logging_utils import log_event
from backend.material_contract import electrical_steel_preflight_records
from backend.models import MotorConfig, SolveOptionsConfig
from backend.solver_environment import solver_environment_provenance, solver_process_environment, solver_setting
from backend.sweep_planning import loaded_angle_grid, loaded_sweep_plan
from backend.topology_provenance import (
    build_mesh_signature_payload,
    build_topology_provenance,
)
from backend.winding_utils import (
    distributed_full_pitch_slots,
    distributed_slots_per_pole_per_phase_value,
    distributed_winding_is_balanced,
)

# Module-level state and exception classes are now in ._state for re-use by
# streaming.py without circular imports. Re-export them here so call sites
# `from backend.magneto2d_adapter import MAGNETO2D_BINARY` etc. keep working.
from ._state import (  # noqa: F401  (re-exports for backward-compat call sites)
    _ACTIVE_MAGNETO2D_PROCESS_LOCK,
    _ACTIVE_MAGNETO2D_PROCESSES,
    _MAGNETO2D_BUILD_LOCK,
    _MAX_SOLVE_MESH_CACHE_SIZE,
    _SOLVE_MESH_CACHE,
    LIVE_FIELD_CONTOUR_BANDS_PER_SIDE,
    LIVE_FIELD_FRAME_PREFIX,
    LIVE_FIELD_MESH_PREFIX,
    MAGNETO2D_BINARY,
    MAGNETO2D_FINE_NONLINEAR_TOL,
    MAGNETO2D_INTERACTIVE_NONLINEAR_TOL,
    MAGNETO2D_MANIFEST,
    REPO_ROOT,
    SOLVE_CONTEXT_PREFIX,
    SOLVE_ITERATION_PROGRESS_PREFIX,
    SWEEP_PROGRESS_RE,
    Magneto2DExecutionError,
    Magneto2DUnsupportedError,
)

# Streaming parsers were lifted into a sibling module.
from .streaming import (  # noqa: F401  (re-exports for backward-compat call sites)
    _build_live_field_plot_payload,
    _format_field_preview_log,
    _format_magneto2d_context,
    _format_magneto2d_solver_line,
    _is_magneto2d_step_diagnostic,
    _magneto2d_step_label,
    _pack_live_contours,
    _pack_live_float,
    _pack_live_float_list,
    _pack_live_segment,
    _parse_live_field_frame,
    _parse_live_field_mesh,
    _parse_solve_context,
    _parse_solve_iteration_progress,
    _parse_sweep_progress,
)

IMPORTED_PHYSICS_CONTRACT_VERSION = "magneto2d_imported_physics/v0"
_WINDING_SOURCE_GROUP_RE = re.compile(
    r"^winding:(?P<phase>[A-Za-z0-9]+):(?P<direction>in|out):"
    r"slot(?P<index>\d+)(?::layer(?P<layer>\d+))?$"
)


def _topology_label(config: MotorConfig) -> str:
    return str(getattr(config, "topology", "") or "").upper()


def _solve_param_value(config: MotorConfig, name: str, default: Any) -> Any:
    solve_params = getattr(config, "solve_params", None)
    if solve_params is None:
        return default
    return getattr(solve_params, name, default)


def _non_spm_import_lane_error(config: MotorConfig) -> str | None:
    """Return the support error for non-SPM Magneto2D solve lanes."""
    topology = _topology_label(config)
    if topology == "SPM":
        return None
    rotor_rotation_model = str(
        _solve_param_value(config, "rotor_rotation_model", "fixed_mesh") or "fixed_mesh"
    )
    if rotor_rotation_model == "remesh_per_step":
        return None
    return (
        f"Magneto2D {topology or 'non-SPM'} Gmsh solves require "
        "solve_params.rotor_rotation_model='remesh_per_step'."
    )



def _validate_non_spm_imported_physics_artifact(
    config: MotorConfig,
    solve_mesh_artifact: dict[str, Any] | None,
) -> None:
    """Fail before Rust when a non-SPM run lacks imported physics metadata."""
    topology = _topology_label(config)
    if topology == "SPM":
        return

    if not isinstance(solve_mesh_artifact, dict):
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} solves require a Gmsh "
            "SolveMeshArtifact with an imported physics contract."
        )

    mesh = solve_mesh_artifact.get("mesh")
    mesh_info = (mesh.get("info") if isinstance(mesh, dict) else None) or {}
    mesh_source = str(mesh_info.get("mesh_source") or "").lower()
    if mesh_source != "gmsh":
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} solves require a Gmsh "
            f"mesh artifact; got mesh_source={mesh_source or 'missing'}."
        )

    contract = solve_mesh_artifact.get("physics_contract") or {}
    version = contract.get("version") if isinstance(contract, dict) else None
    if version != IMPORTED_PHYSICS_CONTRACT_VERSION:
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} solves require imported physics "
            f"contract {IMPORTED_PHYSICS_CONTRACT_VERSION}; got {version or 'missing'}."
        )

    triangles = mesh.get("triangles") if isinstance(mesh, dict) else None
    mesh_regions = mesh.get("regions") if isinstance(mesh, dict) else None
    if not isinstance(triangles, list) or not isinstance(mesh_regions, list):
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract is missing "
            "mesh triangles or element region kinds."
        )
    element_count = len(triangles)
    if len(mesh_regions) != element_count:
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract has "
            f"{len(mesh_regions)} element region kinds for {element_count} triangles."
        )

    element_region_ids = solve_mesh_artifact.get("element_region_ids")
    if not isinstance(element_region_ids, list) or len(element_region_ids) != element_count:
        actual = len(element_region_ids) if isinstance(element_region_ids, list) else "missing"
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
            f"element_region_ids metadata: got {actual}, expected {element_count}."
        )

    contract_regions = contract.get("regions")
    if not isinstance(contract_regions, list) or not contract_regions:
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
            "region material metadata."
        )
    contract_region_by_id: dict[str, dict[str, Any]] = {}
    for entry in contract_regions:
        if not isinstance(entry, dict):
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} imported physics contract has "
                "invalid region material metadata."
            )
        region_id = str(entry.get("id") or "")
        region_kind = str(entry.get("kind") or "")
        material = str(entry.get("material") or "")
        if not region_id or not region_kind or not material:
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
                "region id, kind, or material metadata."
            )
        contract_region_by_id[region_id] = entry

    for idx, (region_id, mesh_region) in enumerate(
        zip(element_region_ids, mesh_regions, strict=False)
    ):
        region_id_str = str(region_id or "")
        entry = contract_region_by_id.get(region_id_str)
        if entry is None:
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
                f"region material metadata for element {idx} region {region_id_str or 'missing'}."
            )
        if str(entry.get("kind")) != str(mesh_region):
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} imported physics contract region "
                f"kind mismatch for element {idx}: contract={entry.get('kind')!r}, "
                f"mesh={mesh_region!r}."
            )

    motion = contract.get("motion")
    motion_angle = motion.get("rotor_angle_mech_deg") if isinstance(motion, dict) else None
    if not isinstance(motion_angle, (int, float)) or not isfinite(float(motion_angle)):
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
            "baked rotor motion metadata."
        )

    element_magnetization = solve_mesh_artifact.get("element_magnetization")
    if not isinstance(element_magnetization, list) or len(element_magnetization) != element_count:
        actual = len(element_magnetization) if isinstance(element_magnetization, list) else "missing"
        raise Magneto2DUnsupportedError(
            f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
            f"element_magnetization metadata: got {actual}, expected {element_count}."
        )
    for idx, region_kind in enumerate(mesh_regions):
        if str(region_kind) != "Magnet":
            continue
        value = element_magnetization[idx]
        if not isinstance(value, (int, float)) or not isfinite(float(value)):
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} imported physics contract missing "
                f"magnetization metadata for magnet element {idx}."
            )

    current_a = _solve_param_value(config, "current_amplitude_A", 0.0)
    try:
        is_loaded = abs(float(current_a)) > 1.0e-12
    except (TypeError, ValueError):
        is_loaded = False
    slot_indices = [
        idx for idx, region_kind in enumerate(mesh_regions) if str(region_kind) == "SlotWinding"
    ]
    if is_loaded:
        if not slot_indices:
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} loaded imported physics contract "
                "missing SlotWinding elements for current-density metadata."
            )
        element_current_density = solve_mesh_artifact.get("element_current_density_a_per_m2")
        if (
            not isinstance(element_current_density, list)
            or len(element_current_density) != element_count
        ):
            actual = (
                len(element_current_density)
                if isinstance(element_current_density, list)
                else "missing"
            )
            raise Magneto2DUnsupportedError(
                f"Magneto2D {topology or 'non-SPM'} loaded imported physics contract "
                f"missing element_current_density_a_per_m2 metadata: got {actual}, "
                f"expected {element_count}."
            )
        for idx in slot_indices:
            value = element_current_density[idx]
            if not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise Magneto2DUnsupportedError(
                    f"Magneto2D {topology or 'non-SPM'} loaded imported physics contract "
                    f"missing current density metadata for SlotWinding element {idx}."
                )


def build_magneto2d_mesh_signature(config: MotorConfig) -> str:
    """Return a stable signature for mesh-affecting native FEM inputs."""
    signature_payload = build_mesh_signature_payload(config)
    return hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


























def write_provenance_sidecar(
    persist_artifacts_dir: Path,
    prefix: str,
    solve_mesh_artifact: dict[str, Any],
) -> None:
    """Persist the few provenance strings report-building needs.

    The solve-mesh artifact JSON carries full node/triangle/metadata arrays
    and reaches tens of megabytes on fine meshes; report-building only needs
    the contract version and four provenance labels, so they get their own
    tiny sidecar file.
    """
    contract = solve_mesh_artifact.get("physics_contract")
    if not isinstance(contract, dict):
        return
    provenance = contract.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    payload = {
        "physics_contract_version": contract.get("version"),
        "region_source": provenance.get("region_source"),
        "current_density_source": (
            provenance.get("current_density_source") or provenance.get("current_source")
        ),
        "magnetization_source": provenance.get("magnetization_source"),
        "material_assignment_source": provenance.get("material_assignment_source"),
    }
    try:
        (persist_artifacts_dir / f"{prefix}_provenance.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass






def hash_solve_mesh_artifact(solve_mesh_artifact: dict[str, Any]) -> str:
    """Stable SHA-256 of a solve-mesh artifact (sorted JSON)."""
    return hashlib.sha256(
        json.dumps(solve_mesh_artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def cache_magneto2d_solve_mesh(
    config: MotorConfig,
    solve_mesh_artifact: dict[str, Any],
) -> str:
    """Store a reusable native solve mesh and return its opaque key."""
    mesh_signature = build_magneto2d_mesh_signature(config)
    artifact_hash = hash_solve_mesh_artifact(solve_mesh_artifact)
    cache_key = hashlib.sha256(
        f"{mesh_signature}:{artifact_hash}".encode("utf-8")
    ).hexdigest()[:24]

    _SOLVE_MESH_CACHE[cache_key] = {
        "artifact": solve_mesh_artifact,
        "mesh_signature": mesh_signature,
        "stored_at": time.time(),
    }
    _SOLVE_MESH_CACHE.move_to_end(cache_key)
    while len(_SOLVE_MESH_CACHE) > _MAX_SOLVE_MESH_CACHE_SIZE:
        _SOLVE_MESH_CACHE.popitem(last=False)
    return cache_key


def get_cached_solve_mesh_artifact(
    cache_key: str | None,
    config: MotorConfig | None = None,
) -> dict[str, Any] | None:
    """Return a cached native solve mesh when the key and config still match."""
    if not cache_key:
        return None
    entry = _SOLVE_MESH_CACHE.get(cache_key)
    if entry is None:
        return None
    if config is not None and entry["mesh_signature"] != build_magneto2d_mesh_signature(config):
        return None
    _SOLVE_MESH_CACHE.move_to_end(cache_key)
    return entry["artifact"]


def iter_cached_solve_mesh_artifacts(
    config: MotorConfig | None = None,
) -> list[dict[str, Any]]:
    """Return cached solve-mesh artifacts, newest first.

    When ``config`` is given, only artifacts whose mesh signature still matches
    are returned. Used to attach a thermal loss map onto SolveResult
    without requiring the caller to remember the cache key.
    """
    out: list[dict[str, Any]] = []
    expected = build_magneto2d_mesh_signature(config) if config is not None else None
    for entry in reversed(list(_SOLVE_MESH_CACHE.values())):
        if expected is not None and entry.get("mesh_signature") != expected:
            continue
        art = entry.get("artifact")
        if isinstance(art, dict):
            out.append(art)
    return out


NATIVE_DISTRIBUTED_OPT_IN_ENV = "COILEM_MAGNETO2D_NATIVE_DISTRIBUTED"


def _native_distributed_opt_in_enabled() -> bool:
    """Legacy compatibility for scripts that still report the old opt-in flag."""
    return solver_setting(NATIVE_DISTRIBUTED_OPT_IN_ENV, "").strip() == "1"


def _native_distributed_winding_error(config: MotorConfig) -> str | None:
    """Gate the native distributed subset, naming the failed condition.

    Permitted (returns None): one- or two-layer balanced star-of-slots
    distributed windings with q >= 1. Full-pitch fractional layouts omit
    coil_span; validated integer-q short-pitch spans stay in [2q, 3q] slots
    with layers=2. coil_span is validated here (mirroring
    backend.geometry.validate_geometry) so the gate stays self-consistent on
    call paths that consult it without first running geometry validation
    (e.g. the plain POST /solve route).
    """
    winding = config.winding
    slot_count = config.stator.slot_count
    pole_count = config.rotor.pole_count
    pole_pairs = pole_count // 2

    if winding.layers not in (1, 2):
        return (
            f"Distributed windings with layers={winding.layers} are not supported "
            "by native Magneto2D yet; supported distributed layouts are one- or "
            "two-layer balanced star-of-slots windings."
        )
    q_value = distributed_slots_per_pole_per_phase_value(slot_count, pole_count)
    is_integer_q = abs(q_value - round(q_value)) < 1e-12
    if pole_pairs < 1 or q_value < 1.0:
        return (
            f"Distributed windings with q={q_value:g} are not supported by native "
            "Magneto2D; distributed layouts require q >= 1. Use a concentrated "
            "winding for sub-unity fractional-slot combinations."
        )
    if not distributed_winding_is_balanced(slot_count, pole_count, winding.layers, winding.coil_span):
        return (
            f"Distributed windings with slot_count={slot_count}, pole_count={pole_count}, "
            f"q={q_value:g} do not produce a balanced star-of-slots table for native "
            "Magneto2D."
        )
    # coil_span (chording) is forwarded to the Rust lane and actively re-pitches
    # the phase belts, so an out-of-range span silently produces a wrong torque/
    # BEMF. Reject the same shapes backend.geometry.validate_geometry() does, in
    # case the gate is consulted without geometry validation (e.g. POST /solve).
    coil_span = winding.coil_span
    if coil_span is not None:
        if not is_integer_q:
            return (
                f"Explicit coil_span={coil_span} is not supported for fractional-q "
                f"distributed layouts (q={q_value:g}) in native Magneto2D yet; omit "
                "coil_span or use an integer-q slot/pole combination."
            )
        q = int(round(q_value))
        full_pitch = distributed_full_pitch_slots(slot_count, pole_count)
        min_span = 2 * q
        max_span = 3 * q
        if coil_span < min_span or coil_span > max_span:
            return (
                f"Distributed winding coil_span={coil_span} is outside the supported "
                f"short-pitch range [{min_span}, {max_span}] slots for this layout "
                f"(q={q}, full pitch={full_pitch:g}); native Magneto2D cannot model "
                "that chord."
            )
        if winding.layers < 2 and coil_span != full_pitch:
            return (
                f"Short-pitch coil_span={coil_span} requires layers=2; a single-layer "
                "distributed winding has no upper-layer return side to shift for "
                "native Magneto2D."
            )
    return None


def get_magneto2d_winding_support_error(config: MotorConfig) -> str | None:
    """Return the winding-boundary support error, or None.

    Scoped to the winding model only: this is the boundary that lane routing
    acts on. Other unsupported-config reasons (missing
    solve_params, non-SPM import-lane conditions) are handled by the solver's
    own lanes and must NOT trigger a FEMM reroute — e.g. the experimental
    native IPM gmsh lane accepts configs this full gate would reject.

    The native distributed subset accepts: one- or
    two-layer balanced star-of-slots layouts with q >= 1. Fractional-q layouts
    are accepted when full-pitch; explicit coil_span remains limited to
    integer-q short-pitch spans. Other distributed shapes (q < 1, unbalanced
    slot counts, out-of-range coil_span, schema-invalid layer counts) keep a
    specific rejection naming the failed condition.
    """
    if config.winding.type == "distributed":
        return _native_distributed_winding_error(config)
    if config.winding.type != "concentrated":
        return (
            f"Winding type '{config.winding.type}' is not supported by native "
            "Magneto2D."
        )
    if config.winding.layers != 1:
        return (
            "Magneto2D supports only single-layer concentrated windings."
        )
    return None


def get_magneto2d_support_error(config: MotorConfig) -> str | None:
    """Return a human-readable support error, or None if supported."""
    if config.solve_params is None:
        return "magneto2d requires solve_params"
    winding_error = get_magneto2d_winding_support_error(config)
    if winding_error is not None:
        return winding_error
    non_spm_error = _non_spm_import_lane_error(config)
    if non_spm_error is not None:
        return non_spm_error

    return None


def is_magneto2d_supported(config: MotorConfig) -> bool:
    """Return True when Python can pass the config to Magneto2D."""
    return get_magneto2d_support_error(config) is None


def require_magneto2d_supported(config: MotorConfig) -> None:
    """Raise if Python cannot pass the config to Magneto2D."""
    support_error = get_magneto2d_support_error(config)
    if support_error is not None:
        raise Magneto2DUnsupportedError(support_error)


def build_magneto2d_payload(config: MotorConfig) -> dict[str, Any]:
    """Translate the supported backend MotorConfig subset into CLI JSON."""
    require_magneto2d_supported(config)
    material_preflight = electrical_steel_preflight_records(
        {
            "stator_steel": config.materials.stator_steel,
            "rotor_steel": config.materials.rotor_steel,
        },
        consumer="magneto2d",
    )
    for material_id, material in config.materials.custom_steels.items():
        roles = [role for role in ("stator_steel", "rotor_steel") if getattr(config.materials, role) == material_id]
        if roles:
            material_preflight.append(material.preflight_record(roles))
    solve_params = config.solve_params
    assert solve_params is not None
    mesh_source = getattr(solve_params, "mesh_source", "native")
    rotor_rotation_model = solve_params.rotor_rotation_model
    winding_payload: dict[str, Any] = {
        "type": config.winding.type,
        "turns_per_coil": config.winding.turns_per_coil,
        "layers": config.winding.layers,
        "parallel_paths": config.winding.parallel_paths,
    }
    if config.winding.coil_span is not None:
        winding_payload["coil_span"] = config.winding.coil_span

    payload: dict[str, Any] = {
        "schema_version": config.schema_version,
        "topology": config.topology,
        "stator": {
            "OD_mm": config.stator.OD_mm,
            "ID_mm": config.stator.ID_mm,
            "slot_count": config.stator.slot_count,
            "stack_length_mm": config.stator.stack_length_mm,
            "slot_opening_mm": config.stator.slot_opening_mm,
            "tooth_width_mm": config.stator.tooth_width_mm,
            "yoke_thickness_mm": config.stator.yoke_thickness_mm,
        },
        "rotor": {
            "OD_mm": config.rotor.OD_mm,
            "ID_mm": config.rotor.ID_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "magnet_width_mm": config.rotor.magnet_width_mm,
            "pole_count": config.rotor.pole_count,
            "magnet_embrace": config.rotor.magnet_embrace,
            "bridge_thickness_mm": config.rotor.bridge_thickness_mm,
        },
        "winding": winding_payload,
        "materials": {
            "stator_steel": config.materials.stator_steel,
            "rotor_steel": config.materials.rotor_steel,
            "magnet_grade": config.materials.magnet_grade,
            "conductor": config.materials.conductor,
            "custom_steels": {key: material.model_dump() for key, material in config.materials.custom_steels.items()},
        },
        "solve_params": {
            "solve_quality": solve_params.solve_quality,
            "rotor_sweep_range_deg": solve_params.rotor_sweep_range_deg,
            "rotor_step_deg": solve_params.rotor_step_deg,
            # Mesh density is passed through as-is from user config.
            # Mesh density controls spatial resolution; accuracy needs convergence checks.
            # Default 'normal' is a good balance for interactive use.
            "mesh_source": mesh_source,
            "mesh_density": solve_params.mesh_density,
            "mesher": solve_params.mesher,
            "current_amplitude_A": solve_params.current_amplitude_A,
            "current_amplitude_convention": solve_params.current_amplitude_convention,
            "current_angle_deg": solve_params.current_angle_deg,
            "rated_speed_rpm": solve_params.rated_speed_rpm,
            "max_nonlinear_iterations": solve_params.max_nonlinear_iterations,
            "nonlinear_solver": solve_params.nonlinear_solver,
            "linear_solver_preconditioner": solve_params.linear_solver_preconditioner,
            "linear_steel_mu_rel": solve_params.linear_steel_mu_rel,
            "stream_noload_field_lines": bool(getattr(solve_params, "stream_noload_field_lines", False)),
            "rotor_rotation_model": rotor_rotation_model,
            "torque_method": solve_params.torque_method,
            "corner_refinement": bool(getattr(solve_params, "corner_refinement", False)),
            "slot_sidewall_refinement": bool(getattr(solve_params, "slot_sidewall_refinement", False)),
        },
        "openem_provenance": {
            "solver_environment": solver_environment_provenance(_magneto2d_env_overrides(config)),
            **build_topology_provenance(config),
            "electrical_steel_materials": material_preflight,
        },
        "solve_options": {
            "torque_sweep": (config.solve_options.torque_sweep if config.solve_options is not None else True),
            "back_emf": (config.solve_options.back_emf if config.solve_options is not None else True),
            "flux_density": (config.solve_options.flux_density if config.solve_options is not None else True),
            "cogging_torque": (config.solve_options.cogging_torque if config.solve_options is not None else False),
            "torque_speed_envelope": (config.solve_options.torque_speed_envelope if config.solve_options is not None else False),
            "thd_analysis": (config.solve_options.thd_analysis if config.solve_options is not None else False),
        },
    }
    if solve_params.excitation_mode == "ideal_six_step_120":
        payload["solve_params"].update(
            {
                "excitation_mode": solve_params.excitation_mode,
                "commutation_advance_deg": solve_params.commutation_advance_deg,
                "phase_connection": solve_params.phase_connection,
                "excitation_rotation_convention": (
                    solve_params.excitation_rotation_convention
                ),
            }
        )
    return payload


def _magneto2d_env_overrides(config: MotorConfig) -> dict[str, str]:
    """Return per-run Rust feature flags for native postprocess extractors."""
    solve_params = config.solve_params
    solve_quality = (
        getattr(solve_params, "solve_quality", None)
        if solve_params is not None
        else None
    )
    torque_method = (
        getattr(solve_params, "torque_method", "contour")
        if solve_params is not None
        else "contour"
    )
    overrides: dict[str, str] = {}

    armature_only_field = (
        getattr(solve_params, "field_composition_source", "resultant") == "armature"
        if solve_params is not None
        else False
    )
    if armature_only_field:
        # Per-process, not process-global: run_magneto2d_report copies this
        # override into only the spawned Rust solver's environment. Magnet
        # permeability and geometry remain intact while Br is exactly zero.
        overrides["COILEM_MAGNET_BR_SCALE"] = "0"

    if solve_quality in {"quick", "standard"}:
        overrides["MAGNETO2D_NONLINEAR_TOL"] = MAGNETO2D_INTERACTIVE_NONLINEAR_TOL
    elif solve_quality == "fine":
        overrides["MAGNETO2D_NONLINEAR_TOL"] = MAGNETO2D_FINE_NONLINEAR_TOL

    linear_steel_mu_rel = (
        getattr(solve_params, "linear_steel_mu_rel", None)
        if solve_params is not None
        else None
    )
    if linear_steel_mu_rel is not None:
        overrides["COILEM_MAGNETO2D_LINEAR_STEEL_MU_REL"] = f"{linear_steel_mu_rel:g}"

    linear_solver_preconditioner = (
        getattr(solve_params, "linear_solver_preconditioner", "direct")
        if solve_params is not None
        else "direct"
    )
    if linear_solver_preconditioner == "direct":
        # faer sparse direct Cholesky (the Rust-side default). Pin the PCG
        # fallback to IC(0) so a failed factorization still gets the fast
        # iterative path.
        overrides["MAGNETO2D_LINEAR_SOLVER"] = "direct"
        overrides["MAGNETO2D_PCG_PRECONDITIONER"] = "ic0"
    elif linear_solver_preconditioner in {"ic0", "jacobi"}:
        overrides["MAGNETO2D_LINEAR_SOLVER"] = "pcg"
        overrides["MAGNETO2D_PCG_PRECONDITIONER"] = str(linear_solver_preconditioner)

    # Rayon worker count for the rotor sweep. The Rust side
    # reads COILEM_MAGNETO2D_WORKERS in main.rs and drives
    # solve::run_rotor_sweep_with_mesh_and_workers — None lets rayon use
    # all host cores (back-compat default), Some(N) pins the per-position
    # parallel iterator to exactly N threads. We only emit the env var
    # when the operator asked for an override; absent var lets the Rust
    # default fire (which respects rayon's RAYON_NUM_THREADS if set).
    magneto2d_workers = (
        getattr(solve_params, "magneto2d_workers", None)
        if solve_params is not None
        else None
    )
    if magneto2d_workers is not None and int(magneto2d_workers) >= 1:
        overrides["COILEM_MAGNETO2D_WORKERS"] = str(int(magneto2d_workers))

    stream_noload_field_lines = (
        getattr(solve_params, "stream_noload_field_lines", None)
        if solve_params is not None
        else None
    )
    fields_set: set[str] = (
        getattr(solve_params, "model_fields_set", set())
        if solve_params is not None
        else set()
    )
    if stream_noload_field_lines is True:
        overrides["COILEM_MAGNETO2D_STREAM_NOLOAD_FIELD"] = "1"
    elif "stream_noload_field_lines" in fields_set:
        overrides["COILEM_MAGNETO2D_STREAM_NOLOAD_FIELD"] = "0"


    # Always populate WST series in the cached report. Results postprocess can
    # then switch Contour/Arkkio/MST/WST without rerunning the field solve.
    overrides.update(
        {
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_TORQUE": "1",
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_AIRGAP_ONLY": "1",
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_ELEMENT_B": "1",
        }
    )

    cogging_method_env = {
        "arkkio": "arkkio",
        "contour": "contour",
        "mst": "mst",
        "weighted_stress": "weighted_stress",
        "weighted_stress_centered": "weighted_stress_centered",
    }.get(str(torque_method), "contour")
    overrides["MAGNETO2D_COGGING_TORQUE_METHOD"] = cogging_method_env

    return overrides


def _valid_magneto2d_nonlinear_tol(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if 0.0 < parsed < 1.0 else None


def estimate_magneto2d_nonlinear_tolerance(config: MotorConfig) -> float:
    """Return the nonlinear convergence tolerance a backend Magneto2D run uses."""
    env_overrides = _magneto2d_env_overrides(config)
    configured_tol = _valid_magneto2d_nonlinear_tol(
        env_overrides.get("MAGNETO2D_NONLINEAR_TOL")
    )
    if configured_tol is not None:
        return configured_tol

    env_tol = _valid_magneto2d_nonlinear_tol(solver_setting("MAGNETO2D_NONLINEAR_TOL"))
    if env_tol is not None:
        return env_tol

    # Rust's direct-CLI fallback keeps custom/unknown quality at the fine
    # signoff tolerance when no environment override is present.
    return float(MAGNETO2D_FINE_NONLINEAR_TOL)


def _resolve_magneto2d_sweep_plan(
    config: MotorConfig,
) -> tuple[int, float]:
    """Return (n_positions, sweep_span_deg) for a magneto2d rotor sweep.

    Honors the Native-FEM app presets (quick=60°, standard=180°,
    fine=360°). Standard promotes to 360° when Back-EMF is requested so the
    reported waveform covers a full electrical cycle. THD always forces a
    full 360° pass because its FFT bins require periodic support.
    """
    require_magneto2d_supported(config)
    return loaded_sweep_plan(config)


def _magneto2d_cli_sweep_span_deg(sweep_positions: int, requested_span_deg: float) -> float:
    """Return the Rust CLI span that realizes the requested angle grid.

    The app/backend define partial sweeps as inclusive grids, e.g.
    ``[0, 7.5, ..., 60]``. The Rust solver distributes ``N`` samples over the
    half-open interval ``[0, cli_span)``, so partial sweeps need one extra step
    of span to make the final emitted field land on the requested endpoint.
    Full-cycle sweeps intentionally stay half-open ``[0, 360)`` to avoid a
    duplicate 360° sample in FFT/report calculations.
    """
    if requested_span_deg >= 360.0 - 1e-6 or sweep_positions <= 1:
        return requested_span_deg
    return requested_span_deg * sweep_positions / max(1, sweep_positions - 1)


def estimate_magneto2d_sweep_positions(config: MotorConfig) -> int:
    """Position count for a magneto2d rotor sweep (preset- and THD-aware)."""
    positions, _ = _resolve_magneto2d_sweep_plan(config)
    return positions


def estimate_magneto2d_cogging_positions(config: MotorConfig) -> int:
    """Position count for the native zero-current cogging sub-sweep.

    Mirrors ``solve.rs``: one electrical cogging period sampled at the native
    diagnostic step plus the terminal endpoint. Returns 0 when the cogging
    option is disabled.
    """
    require_magneto2d_supported(config)
    opts = config.solve_options or SolveOptionsConfig()
    if not opts.cogging_torque:
        return 0

    slot_count = config.stator.slot_count
    pole_count = config.rotor.pole_count
    if slot_count <= 0 or pole_count <= 0:
        return 0

    cogging_period_elec_deg = 180.0 * gcd(slot_count, pole_count) / slot_count
    step_deg = _magneto2d_cogging_step_deg()
    return max(2, ceil(cogging_period_elec_deg / step_deg) + 1)


def _magneto2d_cogging_step_deg() -> float:
    """Diagnostic cogging step override shared with the Rust solver."""
    raw_step_deg = solver_setting("MAGNETO2D_COGGING_STEP_DEG")
    if raw_step_deg is None:
        return 1.0
    try:
        step_deg = float(raw_step_deg)
    except ValueError:
        return 1.0
    if not isfinite(step_deg) or step_deg <= 0.0:
        return 1.0
    return step_deg


def estimate_magneto2d_sweep_span_deg(config: MotorConfig) -> float:
    """Electrical-degree span for a magneto2d rotor sweep (preset-aware)."""
    _, span = _resolve_magneto2d_sweep_plan(config)
    return span


def estimate_magneto2d_sweep_angle_grid(config: MotorConfig) -> list[float]:
    """Return the backend-defined electrical angle grid for a magneto2d sweep."""
    require_magneto2d_supported(config)
    return loaded_angle_grid(config)


def _latest_magneto2d_source_mtime() -> float:
    candidates = [
        MAGNETO2D_MANIFEST,
        MAGNETO2D_MANIFEST.with_name("Cargo.lock"),
        *(MAGNETO2D_MANIFEST.parent / "src").rglob("*.rs"),
    ]
    existing = [path for path in candidates if path.exists()]
    return max((path.stat().st_mtime for path in existing), default=0.0)


def _magneto2d_binary_is_fresh() -> bool:
    if not MAGNETO2D_BINARY.exists():
        return False
    return MAGNETO2D_BINARY.stat().st_mtime >= _latest_magneto2d_source_mtime()


def _summarize_process_failure(stderr: str | None, stdout: str | None, returncode: int) -> str:
    text = (stderr or stdout or "").strip()
    if returncode < 0:
        signal_number = abs(returncode)
        tail = ""
        if text:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                tail = "; stderr tail: " + " | ".join(lines[-4:])
        return f"terminated by signal {signal_number}{tail}"

    if not text:
        return f"exit code {returncode}"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return f"exit code {returncode}"

    priority_lines = [
        line
        for line in lines
        if (
            "error:" in line.lower()
            or "panicked at" in line.lower()
            or line.lower().startswith("thread '")
            or "stack backtrace" in line.lower()
        )
    ]
    chosen = priority_lines[-8:] if priority_lines else lines[-8:]
    return f"exit code {returncode}: " + " | ".join(chosen)


def _resolve_cargo_executable() -> str:
    """Return a Cargo executable path even when GUI-launched PATH is sparse."""
    env_cargo = os.environ.get("CARGO")
    cargo_names = ("cargo", "cargo.exe") if os.name == "nt" else ("cargo",)
    home_candidates: list[Path] = []
    for env_name in ("HOME", "USERPROFILE"):
        env_home = os.environ.get(env_name)
        if env_home:
            home_candidates.append(Path(env_home))
    path_home = Path.home()
    if path_home not in home_candidates:
        home_candidates.append(path_home)

    candidates = [Path(env_cargo) if env_cargo else None]
    candidates.extend(
        home / ".cargo" / "bin" / cargo_name
        for home in home_candidates
        for cargo_name in cargo_names
    )
    candidates.append(Path(shutil.which("cargo") or "") if shutil.which("cargo") else None)
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return str(candidate)
    return "cargo"


def _magneto2d_build_env() -> dict[str, str] | None:
    """Return explicit local Cargo build overrides, when configured."""
    explicit_rustflags = os.environ.get("COILEM_MAGNETO2D_BUILD_RUSTFLAGS")
    if explicit_rustflags is None:
        return None
    build_env = os.environ.copy()
    build_env["CARGO_BUILD_RUSTFLAGS"] = explicit_rustflags
    return build_env



def ensure_magneto2d_binary(runner: Any = subprocess.run) -> Path:
    """Build the release binary when needed and return its executable path."""
    if _magneto2d_binary_is_fresh():
        return MAGNETO2D_BINARY

    with _MAGNETO2D_BUILD_LOCK:
        if _magneto2d_binary_is_fresh():
            return MAGNETO2D_BINARY

        build_command = [
            _resolve_cargo_executable(),
            "build",
            "--release",
            "--manifest-path",
            str(MAGNETO2D_MANIFEST),
        ]
        try:
            completed = runner(
                build_command,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
                env=_magneto2d_build_env(),
            )
        except FileNotFoundError as exc:
            raise Magneto2DExecutionError(
                "magneto2d build could not start because Cargo was not found. "
                "Install Rust/Cargo or add it to PATH, then run "
                "`cargo build --release --manifest-path solvers/magneto2d/Cargo.toml`."
            ) from exc
        if completed.returncode != 0:
            raise Magneto2DExecutionError(
                "magneto2d build failed: "
                + _summarize_process_failure(
                    getattr(completed, "stderr", None),
                    getattr(completed, "stdout", None),
                    completed.returncode,
                )
            )
        if not MAGNETO2D_BINARY.exists():
            raise Magneto2DExecutionError("magneto2d build finished but the release binary was not found")
        return MAGNETO2D_BINARY


def build_magneto2d_command(
    input_path: Path,
    output_path: Path,
    sweep_positions: int | None = None,
    sweep_span_deg: float | None = None,
    rotor_angle_deg: float | None = None,
    solve_mesh_path: Path | None = None,
    batch_input_path: Path | None = None,
    executable: Path | str | None = None,
    mesher: str | None = None,
) -> list[str]:
    """Build the command used to execute the magneto2d CLI binary."""
    # `mesher` remains a backend schema concept ("gmsh") but the Rust CLI no
    # longer selects or owns mesh generation. Meshes are supplied via
    # --mesh-input/--batch-input.
    _ = mesher
    command = [
        str(executable or MAGNETO2D_BINARY),
        _path_arg(input_path),
    ]
    if sweep_positions is not None:
        command.extend(["--sweep", str(sweep_positions)])
    # Only pass --sweep-span-deg on partial sweeps. The binary default is
    # 360° so leaving the flag off keeps standard/fine runs bit-identical
    # to the pre-2×-nesting behaviour (useful for golden-fixture diffs).
    if (
        sweep_positions is not None
        and sweep_span_deg is not None
        and sweep_span_deg < 360.0 - 1e-6
    ):
        command.extend(["--sweep-span-deg", f"{sweep_span_deg:.6f}"])
    if rotor_angle_deg is not None:
        # Decimal truncation can cross a six-step boundary after multiplication
        # by a non-power-of-two pole-pair count. Preserve the original float.
        command.extend(["--rotor-angle-deg", repr(float(rotor_angle_deg))])
    if solve_mesh_path is not None:
        command.extend(["--mesh-input", _path_arg(solve_mesh_path)])
    if batch_input_path is not None:
        command.extend(["--batch-input", _path_arg(batch_input_path)])
    command.extend(["-o", _path_arg(output_path)])
    return command


def _path_arg(path: Path) -> str:
    return path.as_posix()


def build_magneto2d_mesh_command(
    input_path: Path,
    output_path: Path,
    executable: Path | str | None = None,
    mesher: str | None = None,
    rotor_angle_deg: float | None = None,
) -> list[str]:
    """Build the command for mesh-only preview (no field solve)."""
    _ = mesher
    command = [
        str(executable or MAGNETO2D_BINARY),
        _path_arg(input_path),
        "--mesh-only",
        "-o",
        _path_arg(output_path),
    ]
    if rotor_angle_deg is not None:
        command.extend(["--rotor-angle-deg", repr(float(rotor_angle_deg))])
    return command


def run_magneto2d_report(
    config: MotorConfig,
    *,
    sweep: bool = True,
    rotor_angle_deg: float | None = None,
    solve_mesh_artifact: dict[str, Any] | None = None,
    progress_callback: Any | None = None,
    persist_artifacts_dir: Path | None = None,
    artifact_prefix: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Run magneto2d and return its raw JSON report."""
    require_magneto2d_supported(config)
    mesher_choice = getattr(config.solve_params, "mesher", None)
    mesh_source = str(_solve_param_value(config, "mesh_source", "native") or "native")
    if (
        sweep
        and mesher_choice == "gmsh"
        and _topology_label(config) == "SPM"
        and mesh_source == "native"
    ):
        # 2026-06-12 root cause: Gmsh meshes enter the Rust solver as
        # imported artifacts, so rotor sweeps silently demote
        # rotor_rotation_model='remesh_per_step' to fixed-mesh, and
        # fixed-mesh magnet re-tagging is invalid on unstructured meshes
        # away from the as-meshed angle (cogging k_phys read ~4.4x high on
        # spm_8p12s_concentrated). The non-SPM lanes already reject this;
        # SPM must too.
        raise Magneto2DUnsupportedError(
            "Magneto2D SPM Gmsh rotor sweeps cannot rotate inside a single "
            "solve: the Gmsh mesh is imported, which silently demotes "
            "rotor_rotation_model='remesh_per_step' to fixed-mesh, and "
            "fixed-mesh magnet re-tagging is invalid on unstructured meshes "
            "away from the as-meshed angle. Drive the sweep per angle "
            "instead (backend.solver per-angle Gmsh lane with "
            "solve_params.rotor_rotation_model='remesh_per_step')."
        )
    if (
        mesh_source == "native"
        and mesher_choice in {None, "gmsh"}
        and solve_mesh_artifact is None
    ):
        gmsh_preview = run_gmsh_mesh_preview(
            config,
            rotor_angle_deg=rotor_angle_deg if not sweep else 0.0,
        )
        solve_mesh_artifact = gmsh_preview.get("solve_mesh_artifact")
        if not isinstance(solve_mesh_artifact, dict):
            raise Magneto2DExecutionError("Gmsh mesh preview did not include a solve mesh artifact")
    _validate_non_spm_imported_physics_artifact(config, solve_mesh_artifact)
    if solve_mesh_artifact is None:
        raise Magneto2DUnsupportedError(
            "Magneto2D requires a Gmsh or FEMM solve mesh artifact; "
            "legacy Rust native meshing has been removed."
        )
    payload = build_magneto2d_payload(config)
    env_overrides = _magneto2d_env_overrides(config)
    run_env = solver_process_environment(env_overrides)
    if sweep and progress_callback is not None and persist_artifacts_dir is not None:
        run_env.setdefault("COILEM_MAGNETO2D_FIELD_FRAME_STRIDE", "1")
    if sweep:
        sweep_positions, sweep_span_deg = _resolve_magneto2d_sweep_plan(config)
        cli_sweep_span_deg = _magneto2d_cli_sweep_span_deg(sweep_positions, sweep_span_deg)
    else:
        sweep_positions = None
        sweep_span_deg = None
        cli_sweep_span_deg = None
    mesh_density_log = (
        config.solve_params.mesh_density if config.solve_params is not None else "normal"
    )
    sweep_span_log = (
        f" · sweep_span_deg={sweep_span_deg:.2f}"
        if sweep_span_deg is not None and sweep_span_deg < 360.0 - 1e-6
        else ""
    )
    cli_sweep_span_log = (
        f" · cli_sweep_span_deg={cli_sweep_span_deg:.2f}"
        if (
            cli_sweep_span_deg is not None
            and sweep_span_deg is not None
            and abs(cli_sweep_span_deg - sweep_span_deg) > 1e-9
        )
        else ""
    )
    log_event(
        "MAGNETO2D",
        f"solve start mode={'sweep' if sweep else 'single'} "
        f"mesher={mesher_choice or 'gmsh'} mesh_density={mesh_density_log} "
        f"topology={config.topology}"
        + (f" · sweep_positions={sweep_positions}" if sweep_positions is not None else "")
        + sweep_span_log
        + cli_sweep_span_log,
    )

    # `dir=None` → uses tempfile.gettempdir() (portable across Windows / macOS / Linux).
    # Previous code hardcoded `dir="/tmp"` which is a Linux/macOS path and breaks on
    # Windows unless `C:\tmp` happens to exist.
    with tempfile.TemporaryDirectory(prefix="openem_magneto2d_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "input.json"
        output_path = tmp_path / "report.json"
        solve_mesh_path = tmp_path / "solve_mesh.json"
        prefix = artifact_prefix or ("sweep" if sweep else "single")
        if persist_artifacts_dir is not None:
            persist_artifacts_dir.mkdir(parents=True, exist_ok=True)
            run_env["MAGNETO2D_NONLINEAR_DIAGNOSTICS_PATH"] = str(
                persist_artifacts_dir / f"{prefix}_nonlinear_diagnostics.json"
            )
        input_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if solve_mesh_artifact is not None:
            solve_mesh_path.write_text(
                json.dumps(solve_mesh_artifact, indent=2),
                encoding="utf-8",
            )

        executable = ensure_magneto2d_binary() if runner is subprocess.run else MAGNETO2D_BINARY
        command = build_magneto2d_command(
            input_path,
            output_path,
            sweep_positions=sweep_positions,
            sweep_span_deg=cli_sweep_span_deg,
            rotor_angle_deg=None if sweep else rotor_angle_deg,
            solve_mesh_path=solve_mesh_path if solve_mesh_artifact is not None else None,
            executable=executable,
            mesher=mesher_choice,
        )
        if progress_callback is not None and runner is subprocess.run:
            completed = _run_with_progress(command, progress_callback, env=run_env)
        else:
            runner_kwargs = {
                "cwd": str(REPO_ROOT),
                "capture_output": True,
                "text": True,
                "check": False,
            }
            if runner is subprocess.run:
                runner_kwargs["env"] = run_env
            completed = runner(command, **runner_kwargs)
        if completed.returncode != 0:
            raise Magneto2DExecutionError(
                "magneto2d CLI failed: "
                + _summarize_process_failure(
                    getattr(completed, "stderr", None),
                    getattr(completed, "stdout", None),
                    completed.returncode,
                )
            )
        if not output_path.exists():
            raise Magneto2DExecutionError("magneto2d CLI did not produce a report JSON")

        try:
            report = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("magneto2d returned invalid JSON") from exc

        report["solver_environment"] = solver_environment_provenance(env_overrides)
        output_path.write_text(json.dumps(report), encoding="utf-8")
        if persist_artifacts_dir is not None:
            shutil.copy2(input_path, persist_artifacts_dir / f"{prefix}_input.json")
            shutil.copy2(output_path, persist_artifacts_dir / f"{prefix}_report.json")
            if solve_mesh_artifact is not None:
                shutil.copy2(solve_mesh_path, persist_artifacts_dir / f"{prefix}_mesh.json")
                write_provenance_sidecar(persist_artifacts_dir, prefix, solve_mesh_artifact)

        return report


def run_magneto2d_batch_reports(
    config: MotorConfig,
    jobs: list[dict[str, Any]],
    *,
    keep_first_field_plot: bool = False,
    progress_callback: Any | None = None,
    persist_artifacts_dir: Path | None = None,
    artifact_prefix: str | None = None,
    runner: Any = subprocess.run,
) -> list[dict[str, Any]]:
    """Run imported-mesh single-angle jobs in one magneto2d batch process."""
    if not jobs:
        return []
    require_magneto2d_supported(config)
    mesher_choice = getattr(config.solve_params, "mesher", None)
    for job in jobs:
        artifact = job.get("solve_mesh_artifact")
        if not isinstance(artifact, dict):
            raise Magneto2DExecutionError("Magneto2D batch job is missing a solve mesh artifact")
        _validate_non_spm_imported_physics_artifact(config, artifact)

    payload = build_magneto2d_payload(config)
    env_overrides = _magneto2d_env_overrides(config)
    run_env = solver_process_environment(env_overrides)
    prefix = artifact_prefix or "batch"

    mesh_density_log = (
        config.solve_params.mesh_density if config.solve_params is not None else "normal"
    )
    log_event(
        "MAGNETO2D",
        f"solve start mode=batch-imported jobs={len(jobs)} "
        f"mesher={mesher_choice or 'gmsh'} mesh_density={mesh_density_log} "
        f"topology={config.topology}",
    )

    with tempfile.TemporaryDirectory(prefix="openem_magneto2d_batch_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "input.json"
        batch_path = tmp_path / "batch_input.json"
        output_path = tmp_path / "report.json"
        if persist_artifacts_dir is not None:
            persist_artifacts_dir.mkdir(parents=True, exist_ok=True)
            run_env["MAGNETO2D_NONLINEAR_DIAGNOSTICS_PATH"] = str(
                persist_artifacts_dir / f"{prefix}_nonlinear_diagnostics.json"
            )
        input_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        batch_payload = {
            "keep_first_field_plot": bool(keep_first_field_plot),
            "jobs": [
                {
                    "rotor_angle_deg": float(job["rotor_angle_deg"]),
                    "solve_mesh_artifact": job["solve_mesh_artifact"],
                }
                for job in jobs
            ],
        }
        batch_path.write_text(json.dumps(batch_payload, indent=2), encoding="utf-8")

        executable = ensure_magneto2d_binary() if runner is subprocess.run else MAGNETO2D_BINARY
        command = build_magneto2d_command(
            input_path,
            output_path,
            batch_input_path=batch_path,
            executable=executable,
            mesher=mesher_choice,
        )
        if progress_callback is not None and runner is subprocess.run:
            completed = _run_with_progress(command, progress_callback, env=run_env)
        else:
            runner_kwargs = {
                "cwd": str(REPO_ROOT),
                "capture_output": True,
                "text": True,
                "check": False,
            }
            if runner is subprocess.run:
                runner_kwargs["env"] = run_env
            completed = runner(command, **runner_kwargs)
        if completed.returncode != 0:
            raise Magneto2DExecutionError(
                "magneto2d CLI failed: "
                + _summarize_process_failure(
                    getattr(completed, "stderr", None),
                    getattr(completed, "stdout", None),
                    completed.returncode,
                )
            )
        if not output_path.exists():
            raise Magneto2DExecutionError("magneto2d CLI did not produce a batch report JSON")

        try:
            report = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("magneto2d returned invalid batch JSON") from exc

        reports = report.get("reports")
        if not isinstance(reports, list):
            raise Magneto2DExecutionError("magneto2d batch report did not include a reports list")
        if len(reports) != len(jobs):
            raise Magneto2DExecutionError(
                f"magneto2d batch returned {len(reports)} reports for {len(jobs)} jobs"
            )
        if any(not isinstance(item, dict) for item in reports):
            raise Magneto2DExecutionError("magneto2d batch report included a non-object report")
        for item in reports:
            item["solver_environment"] = solver_environment_provenance(env_overrides)
        output_path.write_text(json.dumps(report), encoding="utf-8")
        if persist_artifacts_dir is not None:
            shutil.copy2(input_path, persist_artifacts_dir / f"{prefix}_input.json")
            shutil.copy2(output_path, persist_artifacts_dir / f"{prefix}_report.json")
            shutil.copy2(batch_path, persist_artifacts_dir / f"{prefix}_batch_input.json")
        return [dict(item) for item in reports]


def cancel_active_magneto2d_processes() -> None:
    """Best-effort cancellation for active Rust magneto2d subprocesses."""
    with _ACTIVE_MAGNETO2D_PROCESS_LOCK:
        processes = list(_ACTIVE_MAGNETO2D_PROCESSES)

    for process in processes:
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()


def _run_with_progress(command: list[str], progress_callback: Any, *, env: dict[str, str] | None = None):
    """Run the CLI and forward sweep progress lines to the callback."""
    # encoding="utf-8" is REQUIRED on Windows: without it, Popen(text=True) uses
    # locale.getpreferredencoding() which is cp1252 on a default Western-Windows
    # install. The Rust binary emits UTF-8 progress lines that include Ψ (U+03A8)
    # and ° (U+00B0); cp1252 can't decode Ψ and a UnicodeDecodeError silently kills
    # the stderr pump, so the progress_callback never fires and the frontend's
    # torque waveform stays at "0 solved positions".
    # errors="replace" keeps the pump alive even if an unexpected byte sneaks in.
    # bufsize=1 forces line-buffering on the Python side so we see progress lines
    # as Rust flushes them, not after the whole process exits.
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env if env is not None else solver_process_environment(),
    )
    with _ACTIVE_MAGNETO2D_PROCESS_LOCK:
        _ACTIVE_MAGNETO2D_PROCESSES.add(process)

    stderr_lines: list[str] = []
    # Throttle pass-through of non-progress Rust stderr.
    # The Rust side emits per-quadrant MST/Arkkio diagnostics multiple times
    # per rotor position — forwarding every line floods the backend terminal.
    # We always pass through a small allowlist of high-signal lines (mesher
    # banner, mesh-size summary, errors) and sample everything else at most
    # once every _RUST_STDERR_THROTTLE_SEC seconds.
    _RUST_STDERR_THROTTLE_SEC = 3.0
    _ALWAYS_PRINT_SUBSTRINGS = (
        "mesher=",       # `magneto2d: mesher=gmsh` banner
        "rayon pool",    # worker-count banner; confirms native sweep parallelism
        "parallel sweep completed",
        "nodes",         # mesh summary (e.g. "mesh: 4821 nodes, 9632 triangles")
        "triangles",
        "ERROR",
        "error:",
        "panicked",
        "warning:",
        "arkkio_diag",   # Environment-gated torque-method diagnostics
    )
    last_forwarded_monotonic = 0.0
    live_field_mesh: dict[str, Any] | None = None
    live_field_mesh_sent = False
    solve_log_context: dict[str, Any] | None = None
    try:
        if process.stderr is not None:
            for line in process.stderr:
                solve_context = _parse_solve_context(line)
                if solve_context is not None:
                    solve_log_context = solve_context
                    continue

                iteration_progress = _parse_solve_iteration_progress(line)
                if iteration_progress is not None:
                    solve_log_context = iteration_progress
                    elec_deg = iteration_progress.get("elec_deg")
                    progress_callback(
                        iteration_progress["completed_positions"],
                        iteration_progress["total_positions"],
                        None,
                        float(elec_deg) if isinstance(elec_deg, (int, float)) else None,
                        None,
                        None,
                        None,
                        None,
                        "magneto2d_iteration",
                        iteration_progress,
                    )
                    continue

                parsed_live_field_mesh = _parse_live_field_mesh(line)
                if parsed_live_field_mesh is not None:
                    live_field_mesh = parsed_live_field_mesh
                    live_field_mesh_sent = False
                    continue

                include_static_mesh = live_field_mesh is None or not live_field_mesh_sent
                live_field_frame = _parse_live_field_frame(
                    line,
                    live_field_mesh,
                    include_static_mesh=include_static_mesh,
                )
                if live_field_frame is not None:
                    frame_position, frame_total, frame_elec_deg, field_line_frame = live_field_frame
                    if live_field_mesh is not None:
                        live_field_mesh_sent = True
                    log_event(
                        "MAG2D_STEP",
                        _format_field_preview_log(frame_position, frame_total, frame_elec_deg),
                    )
                    progress_callback(
                        frame_position,
                        frame_total,
                        None,
                        frame_elec_deg,
                        None,
                        None,
                        None,
                        field_line_frame,
                    )
                    continue

                parsed = _parse_sweep_progress(line)
                if parsed is not None:
                    position, total, torque, elec_deg, psi_a, psi_b, psi_c = parsed
                    native_stage = (
                        "magneto2d_cogging"
                        if line.lstrip().startswith("cogging ")
                        else "magneto2d_sweep"
                    )
                    progress_callback(
                        position,
                        total,
                        torque,
                        elec_deg,
                        psi_a,
                        psi_b,
                        psi_c,
                        None,
                        native_stage,
                    )
                    continue

                stripped = line.rstrip()
                if not stripped:
                    continue
                stderr_lines.append(line)
                is_important = any(token in stripped for token in _ALWAYS_PRINT_SUBSTRINGS)
                now = time.monotonic()
                if is_important or (now - last_forwarded_monotonic) >= _RUST_STDERR_THROTTLE_SEC:
                    if _is_magneto2d_step_diagnostic(stripped):
                        log_event(
                            "MAG2D_STEP",
                            _format_magneto2d_solver_line(stripped, solve_log_context),
                        )
                    else:
                        log_event("MAG2D_RUST", stripped)
                    last_forwarded_monotonic = now

        stdout = process.stdout.read() if process.stdout is not None else ""
        returncode = process.wait()
    finally:
        with _ACTIVE_MAGNETO2D_PROCESS_LOCK:
            _ACTIVE_MAGNETO2D_PROCESSES.discard(process)

    class Completed:
        def __init__(self, returncode: int, stdout: str, stderr: str):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Completed(returncode, stdout, "".join(stderr_lines))


def _coerce_gmsh_mesh_preview_config(config: MotorConfig) -> MotorConfig:
    """Mesh preview is geometry-only — coerce IPM Gmsh policy fields full solves require."""
    if config.solve_params is None:
        return config
    mesher = str(getattr(config.solve_params, "mesher", "") or "")
    if mesher != "gmsh" or _topology_label(config) == "SPM":
        return config
    rotor_rotation_model = str(
        getattr(config.solve_params, "rotor_rotation_model", "fixed_mesh") or "fixed_mesh"
    )
    if rotor_rotation_model == "remesh_per_step":
        return config
    return config.model_copy(
        update={
            "solve_params": config.solve_params.model_copy(
                update={"rotor_rotation_model": "remesh_per_step"},
            ),
        },
    )


def run_magneto2d_mesh_preview(
    config: MotorConfig,
    *,
    rotor_angle_deg: float | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Run magneto2d in mesh-only mode and return the mesh preview JSON.

    This is fast (<1s) because it only generates the mesh geometry without
    running any field solve or matrix assembly.
    """
    config = _coerce_gmsh_mesh_preview_config(config)
    require_magneto2d_supported(config)
    mesher_choice = getattr(config.solve_params, "mesher", None)
    mesh_source = str(_solve_param_value(config, "mesh_source", "native") or "native")
    if mesh_source != "native":
        raise Magneto2DUnsupportedError(
            "Magneto2D mesh preview only generates native Gmsh meshes. "
            "Only solve_params.mesh_source='native' is supported."
        )
    if mesher_choice not in {None, "gmsh"}:
        raise Magneto2DUnsupportedError(
            "Magneto2D mesh preview only supports the backend Gmsh mesher; "
            "legacy Rust native mesh preview has been removed."
        )
    if _topology_label(config) != "SPM" and mesher_choice != "gmsh":
        raise Magneto2DUnsupportedError(
            "Magneto2D generated mesh preview requires the Gmsh mesher."
        )
    payload = build_magneto2d_payload(config)
    if mesher_choice == "gmsh":
        report = run_gmsh_mesh_preview(config, rotor_angle_deg=rotor_angle_deg)
        solve_mesh_artifact = report.pop("solve_mesh_artifact", None)
        if isinstance(solve_mesh_artifact, dict):
            report["solve_mesh_key"] = cache_magneto2d_solve_mesh(
                config,
                solve_mesh_artifact,
            )
        return report
    log_event(
        "MAGNETO2D",
        f"mesh-preview start mesher={mesher_choice or 'gmsh'} topology={config.topology}",
    )

    # `dir=None` -> portable tempdir (Windows %TEMP%, Linux/macOS /tmp or $TMPDIR).
    with tempfile.TemporaryDirectory(prefix="openem_magneto2d_mesh_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "input.json"
        output_path = tmp_path / "mesh_preview.json"
        input_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        executable = ensure_magneto2d_binary() if runner is subprocess.run else MAGNETO2D_BINARY
        command = build_magneto2d_mesh_command(
            input_path,
            output_path,
            executable=executable,
            mesher=mesher_choice,
            rotor_angle_deg=rotor_angle_deg,
        )
        # Plumb env overrides (corner refinement, torque method, etc.) into the
        # mesh-preview run so the user can see refined corners in the Mesh tab
        # before kicking off a full solve. Without this, mesh-preview would
        # always show the unrefined mesh even when corner_refinement=true,
        # making the toggle silently ineffective for the visual feedback loop.
        env_overrides = _magneto2d_env_overrides(config)
        run_env = solver_process_environment(env_overrides)
        completed = runner(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=run_env,
        )
        if completed.returncode != 0:
            raise Magneto2DExecutionError(
                "magneto2d mesh preview failed: "
                + _summarize_process_failure(
                    getattr(completed, "stderr", None),
                    getattr(completed, "stdout", None),
                    completed.returncode,
                )
            )
        if not output_path.exists():
            raise Magneto2DExecutionError("magneto2d mesh preview did not produce output")

        try:
            report = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("magneto2d mesh preview returned invalid JSON") from exc
        solve_mesh_artifact = report.pop("solve_mesh_artifact", None)
        if isinstance(solve_mesh_artifact, dict):
            report["solve_mesh_key"] = cache_magneto2d_solve_mesh(
                config,
                solve_mesh_artifact,
            )
        return report
