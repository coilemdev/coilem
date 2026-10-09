"""Topology-aware geometry and mesh-policy provenance helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.models import MotorConfig

# v3: config.materials joined the payload. The solve-mesh artifact's physics
# contract embeds material KEYS per region (e.g. "magnet:N42",
# "steel:stator:M19", backend/geometry_ir.py) and the Rust solver resolves
# imported-mesh materials FROM those keys (materials.rs
# material_from_contract_key) — so a frozen Mesh-tab artifact is only valid
# for the materials it was built with. Before v3, changing magnet grade or
# steel after freezing a mesh silently solved with the stale grade.
MAGNETO2D_MESH_SIGNATURE_VERSION = "magneto2d_mesh_signature/v3"
TOPOLOGY_PROVENANCE_SCHEMA_VERSION = "openem.topology_provenance.v1"


def _section(config: MotorConfig | Mapping[str, Any], name: str) -> Any:
    if isinstance(config, Mapping):
        return config.get(name) or {}
    return getattr(config, name, None)


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _effective_solve_value(solve_params: Any, method_name: str) -> float | None:
    method = getattr(solve_params, method_name, None)
    if callable(method):
        return _float_or_none(method())
    return None


def build_topology_geometry_provenance(
    config: MotorConfig | Mapping[str, Any],
) -> dict[str, Any]:
    """Return topology and geometry fields that make mesh artifacts distinct."""
    stator = _section(config, "stator")
    rotor = _section(config, "rotor")
    winding = _section(config, "winding")

    stator_id_mm = _float_or_none(_value(stator, "ID_mm"))
    rotor_od_mm = _float_or_none(_value(rotor, "OD_mm"))
    magnet_thickness_mm = _float_or_none(_value(rotor, "magnet_thickness_mm"))

    stator_inner_radius_mm = stator_id_mm / 2.0 if stator_id_mm is not None else None
    rotor_outer_radius_mm = rotor_od_mm / 2.0 if rotor_od_mm is not None else None
    magnet_outer_radius_mm = (
        rotor_outer_radius_mm + magnet_thickness_mm
        if rotor_outer_radius_mm is not None and magnet_thickness_mm is not None
        else None
    )
    winding_payload = {
        "type": _value(winding, "type"),
        "turns_per_coil": _value(winding, "turns_per_coil"),
        "layers": _value(winding, "layers"),
        "parallel_paths": _value(winding, "parallel_paths"),
    }
    coil_span = _value(winding, "coil_span")
    if coil_span is not None:
        winding_payload["coil_span"] = coil_span

    return {
        "schema_version": TOPOLOGY_PROVENANCE_SCHEMA_VERSION,
        "topology": _value(config, "topology"),
        "stator": {
            "OD_mm": _value(stator, "OD_mm"),
            "ID_mm": _value(stator, "ID_mm"),
            "slot_count": _value(stator, "slot_count"),
            "stack_length_mm": _value(stator, "stack_length_mm"),
            "slot_opening_mm": _value(stator, "slot_opening_mm"),
            "tooth_width_mm": _value(stator, "tooth_width_mm"),
            "yoke_thickness_mm": _value(stator, "yoke_thickness_mm"),
        },
        "rotor": {
            "OD_mm": _value(rotor, "OD_mm"),
            "ID_mm": _value(rotor, "ID_mm"),
            "pole_count": _value(rotor, "pole_count"),
            "magnet_thickness_mm": _value(rotor, "magnet_thickness_mm"),
            "magnet_width_mm": _value(rotor, "magnet_width_mm"),
            "magnet_embrace": _value(rotor, "magnet_embrace"),
            "bridge_thickness_mm": _value(rotor, "bridge_thickness_mm"),
            "ipm_topology": _value(rotor, "ipm_topology"),
            "flat_buried_magnet_shape": _value(
                rotor,
                "flat_buried_magnet_shape",
            ),
            "side_bridge_thickness_mm": _value(rotor, "side_bridge_thickness_mm"),
            "pocket_clearance_mm": _value(rotor, "pocket_clearance_mm"),
            "magnet_angle_deg": _value(rotor, "magnet_angle_deg"),
            "v_angle_deg": _value(rotor, "v_angle_deg"),
            "v_depth_mm": _value(rotor, "v_depth_mm"),
            "inner_web_thickness_mm": _value(rotor, "inner_web_thickness_mm"),
            "outer_bridge_thickness_mm": _value(rotor, "outer_bridge_thickness_mm"),
            "flux_barrier_count": _value(rotor, "flux_barrier_count"),
            "barrier_widths_mm": _value(rotor, "barrier_widths_mm"),
        },
        "winding": winding_payload,
        "derived": {
            "rotor_outer_radius_mm": rotor_outer_radius_mm,
            "stator_inner_radius_mm": stator_inner_radius_mm,
            "rotor_to_stator_radial_gap_mm": (
                stator_inner_radius_mm - rotor_outer_radius_mm
                if stator_inner_radius_mm is not None and rotor_outer_radius_mm is not None
                else None
            ),
            "spm_magnet_outer_radius_mm": magnet_outer_radius_mm,
            "spm_airgap_mm": (
                stator_inner_radius_mm - magnet_outer_radius_mm
                if stator_inner_radius_mm is not None and magnet_outer_radius_mm is not None
                else None
            ),
        },
    }


def build_mesh_policy_provenance(
    config: MotorConfig | Mapping[str, Any],
) -> dict[str, Any]:
    """Return mesh-policy fields that affect generated or imported mesh use."""
    solve_params = _section(config, "solve_params")
    return {
        "mesh_source": _value(solve_params, "mesh_source", "native"),
        "mesh_density": _value(solve_params, "mesh_density", "normal"),
        "mesher": _value(solve_params, "mesher", "gmsh"),
        "corner_refinement": bool(_value(solve_params, "corner_refinement", False)),
        "slot_sidewall_refinement": bool(
            _value(solve_params, "slot_sidewall_refinement", False)
        ),
        "rotor_rotation_model": _value(solve_params, "rotor_rotation_model", "fixed_mesh"),
    }


def build_topology_provenance(
    config: MotorConfig | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the topology provenance block stored on payloads and artifacts."""
    return {
        "schema_version": TOPOLOGY_PROVENANCE_SCHEMA_VERSION,
        "mesh_signature_version": MAGNETO2D_MESH_SIGNATURE_VERSION,
        "geometry": build_topology_geometry_provenance(config),
        "mesh_policy": build_mesh_policy_provenance(config),
    }


def build_mesh_signature_payload(
    config: MotorConfig,
) -> dict[str, Any]:
    """Return the stable payload hashed for mesh cache compatibility."""
    debug = _section(config, "debug")
    solve_params = _section(config, "solve_params")
    materials = _section(config, "materials")
    return {
        "version": MAGNETO2D_MESH_SIGNATURE_VERSION,
        "topology_provenance": build_topology_provenance(config),
        "materials": {
            "stator_steel": _value(materials, "stator_steel"),
            "rotor_steel": _value(materials, "rotor_steel"),
            "magnet_grade": _value(materials, "magnet_grade"),
            "conductor": _value(materials, "conductor"),
        },
        "mesh_policy_effective": {
            "effective_step_deg": _effective_solve_value(solve_params, "effective_step_deg"),
            "effective_native_loaded_sweep_range_deg": _effective_solve_value(
                solve_params,
                "effective_native_loaded_sweep_range_deg",
            ),
        },
        "debug": {
            "slotless_noload_diagnostic": bool(
                _value(debug, "slotless_noload_diagnostic", False)
            ),
            "slotted_noload_diagnostic": bool(
                _value(debug, "slotted_noload_diagnostic", False)
            ),
            "loaded_field_diagnostic": bool(_value(debug, "loaded_field_diagnostic", False)),
            "probe_angle_deg": _value(debug, "probe_angle_deg", None),
        },
    }
