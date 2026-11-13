"""An unfinished motor's stator, using the shared production tooth geometry.

Hidden rotor-pocket defaults must not prevent an outer-to-inner construction
preview. This response deliberately contains no rotor, copper or qualification;
the complete preview/mesh/solve paths still validate the complete motor.
"""

from time import perf_counter

from backend.geometry import geometry_warnings, tooth_width_advisory
from backend.geometry_drawer import (
    MotorGeometry,
    _compute_slot_placements,
    bore_tooth_width_mm,
    narrowest_tooth_width_mm,
    slot_width_at_yoke_mm,
    tooth_width_at_yoke_mm,
)
from backend.geometry_ir import GEOMETRY_IR_VERSION, GeometryIR, _add_stator_regions
from backend.models import GeometryPreview, MotorConfig
from backend.preview_from_ir import preview_regions_from_geometry_ir


def generate_stator_construction_preview(config: MotorConfig) -> GeometryPreview:
    """Build only inner-layout stator iron, without evaluating unused magnets."""
    started = perf_counter()
    if config.rotor_layout == "outer":
        raise ValueError("Stator-only construction currently requires an inner rotor.")
    geom = MotorGeometry(
        stator_OD_r=config.stator.OD_mm / 2,
        stator_ID_r=config.stator.ID_mm / 2,
        rotor_OD_r=config.rotor.OD_mm / 2,
        shaft_r=(config.rotor.ID_mm or 0) / 2,
        airgap_mm=0,
        slots=_compute_slot_placements(config),
        pole_count=config.rotor.pole_count,
        slot_count=config.stator.slot_count,
        topology=config.topology,
    )
    regions = []
    _add_stator_regions(regions, config, geom, False)
    ir = GeometryIR(
        version=GEOMETRY_IR_VERSION,
        topology=config.topology,
        ipm_topology=config.rotor.ipm_topology,
        pole_count=config.rotor.pole_count,
        slot_count=config.stator.slot_count,
        regions=tuple(region for region in regions if region.kind in {"StatorYoke", "StatorTooth"}),
    )
    metadata = {
        "construction_only": True,
        "construction_parts": "stator",
        "topology": config.topology,
        "ipm_topology": config.rotor.ipm_topology,
        "rotor_layout": "inner",
        "stator_od_mm": config.stator.OD_mm,
        "stator_id_mm": config.stator.ID_mm,
        "slot_count": config.stator.slot_count,
        "pole_count": config.rotor.pole_count,
        "stack_length_mm": config.stator.stack_length_mm,
        "bore_tooth_width_mm": bore_tooth_width_mm(config),
        "tooth_width_at_yoke_mm": tooth_width_at_yoke_mm(config),
        "slot_width_at_yoke_mm": slot_width_at_yoke_mm(config),
        "narrowest_tooth_width_mm": narrowest_tooth_width_mm(config),
    }
    warnings = geometry_warnings(config)
    if warnings:
        metadata["geometry_warnings"] = warnings
    advisory = tooth_width_advisory(config)
    if advisory:
        metadata["tooth_width_advisory"] = {
            key: getattr(advisory, key) for key in (
                "severity", "kind", "narrowest_width_mm", "yoke_tooth_width_mm", "relative_narrowing"
            )
        }
    return GeometryPreview(
        regions=preview_regions_from_geometry_ir(ir),
        winding_layout=[],
        metadata=metadata,
        generation_time_ms=(perf_counter() - started) * 1000,
    )
