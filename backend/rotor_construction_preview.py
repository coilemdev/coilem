"""Display requested IPM parts even when they cannot form a solvable rotor.

This explicit construction response is never used by meshing or solving. In
particular V magnets retain their requested length instead of the production
drawer's protective outer-bridge clamp, so the interference is visible.
"""

import math
from time import perf_counter

from backend.geometry import validate_geometry
from backend.geometry_drawer import _oriented_rectangle_corners, compute_flat_buried_magnet_placements
from backend.models import GeometryPreview, GeometryRegion, MotorConfig
from backend.stator_construction_preview import generate_stator_construction_preview


def requested_ipm_slabs(config: MotorConfig):
    """Yield pole, magnet corners and pocket corners in requested model mm."""
    rotor = config.rotor
    if rotor.ipm_topology == "flat_buried":
        for magnet in compute_flat_buried_magnet_placements(config):
            yield magnet.pole_index, magnet.corners_mm, magnet.pocket_corners_mm
        return
    half_angle = math.radians(rotor.v_angle_deg / 2)
    apex_radius = rotor.OD_mm / 2 - rotor.v_depth_mm
    for pole in range(rotor.pole_count):
        angle = 2 * math.pi * pole / rotor.pole_count + math.radians(rotor.magnet_angle_deg)
        radial, tangent = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
        for sign in (1, -1):
            axis = tuple(math.cos(half_angle) * radial[i] + sign * math.sin(half_angle) * tangent[i] for i in (0, 1))
            normal = tuple(math.sin(half_angle) * radial[i] - sign * math.cos(half_angle) * tangent[i] for i in (0, 1))
            centre = tuple(apex_radius * radial[i] + sign * rotor.inner_web_thickness_mm / 2 * tangent[i]
                           + rotor.magnet_width_mm / 2 * axis[i] for i in (0, 1))
            yield pole, _oriented_rectangle_corners(centre, axis, normal, rotor.magnet_width_mm, rotor.magnet_thickness_mm), \
                _oriented_rectangle_corners(centre, axis, normal, rotor.magnet_width_mm + 2 * rotor.pocket_clearance_mm,
                                           rotor.magnet_thickness_mm + 2 * rotor.pocket_clearance_mm)


def generate_rotor_construction_preview(config: MotorConfig) -> GeometryPreview:
    started = perf_counter()
    if (config.topology != "IPM" or config.rotor_layout != "inner"
            or config.rotor.ipm_topology not in {"flat_buried", "v_shape"} or config.geometry_reference):
        raise ValueError("Diagnostic rotor construction supports generic inner-rotor flat or V-shaped IPM designs.")
    if config.rotor.ipm_topology == "flat_buried" and config.rotor.flat_buried_magnet_shape != "straight":
        raise ValueError("Diagnostic flat-IPM construction requires straight magnet bars.")
    preview = generate_stator_construction_preview(config)
    errors = [error for error in validate_geometry(config) if (error.field or "").startswith("rotor.")]
    if errors and config.rotor.ipm_topology == "v_shape":
        # A small pure-math search offers a concrete correction only after the
        # same production validator accepts it. No solve or parameter mutation.
        limit = min(200, config.rotor.OD_mm / 2 - (config.rotor.ID_mm or 0) / 2 - 0.5)
        feasible = []
        for index in range(1, 81):
            depth = round(max(0.1, limit * index / 81), 1)
            candidate = config.model_copy(update={"rotor": config.rotor.model_copy(update={"v_depth_mm": depth})})
            if not any((error.field or "").startswith("rotor.") for error in validate_geometry(candidate)):
                feasible.append(depth)
        if feasible:
            correction = f"For these dimensions, try V Depth {feasible[len(feasible) // 2]:g} mm."
            errors = [error.model_copy(update={"suggestion": f"{error.suggestion or ''} {correction}".strip()})
                      if error.field == "rotor.v_depth_mm" else error for error in errors]
    def circle(radius):
        return [[radius * math.cos(i * math.pi / 90), radius * math.sin(i * math.pi / 90)] for i in range(181)]
    rotor = config.rotor
    outer, inner = circle(rotor.OD_mm / 2), circle((rotor.ID_mm or 0) / 2)
    regions = list(preview.regions)
    regions.append(GeometryRegion(region_type="rotor_core", points=outer, loops=[outer, inner], fill="#536174", label="Rotor core"))
    if rotor.ID_mm:
        regions.append(GeometryRegion(region_type="shaft", points=inner, fill="#303846", label="Shaft"))
    for index, (pole, corners, pocket) in enumerate(requested_ipm_slabs(config)):
        if pocket and rotor.pocket_clearance_mm > 0:
            regions.append(GeometryRegion(
                region_type="rotor_air_pocket", points=pocket, loops=[pocket], fill="#18212C", label=f"Requested pocket {index + 1}",
            ))
        polarity = "N" if pole % 2 == 0 else "S"
        centre = [sum(point[i] for point in corners) / len(corners) for i in (0, 1)]
        regions.append(GeometryRegion(region_type=f"magnet_{polarity.lower()}", points=corners, loops=[corners],
                                      fill="#EF4444" if polarity == "N" else "#3B82F6",
                                      label=f"Requested magnet {index + 1}", text_label=polarity, text_position=centre))
    metadata = {**preview.metadata, "construction_parts": "rotor", "diagnostic_rotor": True,
                "diagnostic_only": bool(errors), "rotor_od_mm": rotor.OD_mm, "rotor_id_mm": rotor.ID_mm,
                "airgap_mm": (config.stator.ID_mm - rotor.OD_mm) / 2}
    return preview.model_copy(update={"regions": regions, "metadata": metadata, "validation_errors": errors,
                                     "generation_time_ms": (perf_counter() - started) * 1000})
