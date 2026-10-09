"""Pure-math geometry generation for SVG preview rendering.

This module generates SVG-ready geometry from motor configuration parameters
using only trigonometry — no Pyleecan or external solvers. Target: <50ms.
"""

import math
import time
from typing import Literal

from backend.geometry import (
    geometry_warnings,
    tooth_width_advisory,
    validate_geometry,
    winding_layout_problem,
)
from backend.geometry_drawer import (
    _slot_body_width_mm,
    bore_tooth_width_mm,
    compute_geometry,
    narrowest_tooth_width_mm,
    slot_width_at_yoke_mm,
    tooth_width_at_yoke_mm,
)
from backend.geometry_ir import build_geometry_ir
from backend.models import (
    ErrorResponse,
    GeometryPreview,
    GeometryRegion,
    MotorConfig,
    WindingCoil,
    WindingSlot,
)
from backend.preview_from_ir import append_winding_symbols, preview_regions_from_geometry_ir
from backend.winding_utils import (
    distributed_full_pitch_slots,
    distributed_fundamental_winding_factor,
    distributed_pitch_factor,
    distributed_slot_layer_assignments,
)


def generate_preview(config: MotorConfig) -> GeometryPreview:
    """Generate SVG-ready geometry preview from motor config.

    Pure math, no Pyleecan. Returns geometry regions and winding layout
    in <200ms for typical configs.

    Args:
        config: Motor configuration

    Returns:
        GeometryPreview with regions, winding layout, metadata, and timing
    """
    start_time = time.perf_counter()

    # Validate geometry
    validation_errors = validate_geometry(config)
    geom = compute_geometry(config)
    try:
        geometry_ir = build_geometry_ir(config, geom=geom)
        geometry_ir_report = geometry_ir.validation_report()
    except Exception as exc:  # pragma: no cover - defensive guard for preview UX
        validation_errors.append(
            ErrorResponse(
                error_code="INVALID_GEOMETRY",
                message=f"Geometry IR construction failed: {exc}",
                field=None,
                suggestion="Check geometry dimensions and topology-specific rotor fields.",
            )
        )
        geometry_ir = None
        geometry_ir_report = None
    else:
        if geometry_ir_report:
            for issue in geometry_ir_report.issues:
                validation_errors.append(
                    ErrorResponse(
                        error_code="INVALID_GEOMETRY",
                        message=f"Geometry IR invariant failed: {issue}",
                        field=None,
                        suggestion="Check region dimensions before solving or meshing.",
                    )
                )

    # Extract convenience references
    stator = config.stator
    rotor = config.rotor
    topology = config.topology
    winding = config.winding
    slotless_diagnostic = False

    regions: list[GeometryRegion] = []
    origin_x, origin_y = 0.0, 0.0

    bore_r = stator.ID_mm / 2
    stator_od_r = stator.OD_mm / 2
    rotor_core_outer_r = rotor.OD_mm / 2
    rotor_outer_r = rotor_core_outer_r + (rotor.magnet_thickness_mm if topology == "SPM" else 0.0)
    airgap_mm = bore_r - rotor_outer_r
    slot_bottom_r = stator_od_r - stator.yoke_thickness_mm
    tooth_pitch_rad = (2 * math.pi) / stator.slot_count
    # Sizes the in/out winding symbols, so it has to be the same slot the drawer
    # drew — measured at the body radius, not the bore pitch.
    slot_body_width = _slot_body_width_mm(config)

    # ============================================================================
    # WINDING LAYOUT (compute early so we can color slots by phase)
    # ============================================================================
    if slotless_diagnostic:
        winding_layout: list[WindingSlot] = []
        winding_coils: list[WindingCoil] = []
        winding_metadata = {
            "winding_factor": 0.0,
            "fill_factor": 0.0,
            "turns_per_coil": winding.turns_per_coil,
            "parallel_paths": winding.parallel_paths,
            "slotless_stator": True,
        }
    else:
        winding_layout, winding_metadata = _generate_winding_layout(
            stator.slot_count, rotor.pole_count, winding.type, winding.turns_per_coil,
            stator.ID_mm, winding.layers, winding.parallel_paths, winding.coil_span
        )
        winding_coils = _derive_winding_coils(
            winding_layout,
            stator.slot_count,
            winding.type,
            float(winding_metadata.get("coil_span_slots", 1.0) or 1.0),
        )

    if geometry_ir is not None:
        regions.extend(
            preview_regions_from_geometry_ir(
                geometry_ir,
                slotless_diagnostic=slotless_diagnostic,
            )
        )

    if not slotless_diagnostic:
        append_winding_symbols(
            regions,
            winding_layout,
            bore_r=bore_r,
            slot_bottom_r=slot_bottom_r,
            slot_body_width=slot_body_width,
            slot_pitch_rad=tooth_pitch_rad,
            origin_x=origin_x,
            origin_y=origin_y,
        )

    # ============================================================================
    # METADATA (winding_layout already computed above for slot coloring)
    # ============================================================================
    metadata = {
        "stator_od_mm": stator.OD_mm,
        "stator_id_mm": stator.ID_mm,
        "rotor_od_mm": rotor.OD_mm,
        "rotor_id_mm": rotor.ID_mm,
        "airgap_mm": airgap_mm,
        "pole_count": rotor.pole_count,
        "slot_count": stator.slot_count,
        "topology": topology,
        "ipm_topology": getattr(rotor, "ipm_topology", None),
        "side_bridge_thickness_mm": getattr(rotor, "side_bridge_thickness_mm", None),
        "pocket_clearance_mm": getattr(rotor, "pocket_clearance_mm", None),
        "magnet_angle_deg": getattr(rotor, "magnet_angle_deg", None),
        "v_angle_deg": getattr(rotor, "v_angle_deg", None),
        "v_depth_mm": getattr(rotor, "v_depth_mm", None),
        "inner_web_thickness_mm": getattr(rotor, "inner_web_thickness_mm", None),
        "outer_bridge_thickness_mm": getattr(rotor, "outer_bridge_thickness_mm", None),
        "slotless_diagnostic": slotless_diagnostic,
        # Additive preview metadata only — these are derived views of the existing
        # stator fields, never new persisted project inputs.
        "bore_tooth_width_mm": bore_tooth_width_mm(config),
        "tooth_width_at_yoke_mm": tooth_width_at_yoke_mm(config),
        "slot_width_at_yoke_mm": slot_width_at_yoke_mm(config),
        "narrowest_tooth_width_mm": narrowest_tooth_width_mm(config),
        **winding_metadata,  # Add winding factor, fill_factor, etc.
    }

    # Non-blocking: geometry that draws and solves but no longer matches what the
    # fields say. Kept out of validation_errors on purpose so it cannot stop a solve.
    warnings = geometry_warnings(config)
    if warnings:
        metadata["geometry_warnings"] = warnings
    width_advisory = tooth_width_advisory(config)
    if width_advisory:
        metadata["tooth_width_advisory"] = {
            "severity": width_advisory.severity,
            "kind": width_advisory.kind,
            "narrowest_width_mm": width_advisory.narrowest_width_mm,
            "yoke_tooth_width_mm": width_advisory.yoke_tooth_width_mm,
            "relative_narrowing": width_advisory.relative_narrowing,
        }

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return GeometryPreview(
        regions=regions,
        winding_layout=winding_layout,
        winding_coils=winding_coils,
        metadata=metadata,
        validation_errors=validation_errors,
        generation_time_ms=elapsed_ms,
    )


# ============================================================================
# HELPER FUNCTIONS FOR GEOMETRY GENERATION
# ============================================================================


def _create_annular_region(
    region_type: str,
    center_x: float,
    center_y: float,
    inner_radius: float,
    outer_radius: float,
    num_points: int = 64,
    fill: str = "#000000",
    label: str = "Region",
) -> GeometryRegion:
    """Create an annular (ring) region with inner and outer arcs.

    Args:
        region_type: Type label for the region
        center_x, center_y: Center point in mm
        inner_radius: Inner arc radius in mm
        outer_radius: Outer arc radius in mm
        num_points: Number of points per arc for smoothness
        fill: SVG fill color
        label: Human-readable label

    Returns:
        GeometryRegion with polygon points
    """
    points = []

    # Outer arc (counterclockwise)
    for i in range(num_points):
        angle = (i / num_points) * 2 * math.pi
        x = center_x + outer_radius * math.cos(angle)
        y = center_y + outer_radius * math.sin(angle)
        points.append([x, y])

    # Inner arc (clockwise, so reverse order)
    for i in range(num_points):
        angle = (1 - i / num_points) * 2 * math.pi
        x = center_x + inner_radius * math.cos(angle)
        y = center_y + inner_radius * math.sin(angle)
        points.append([x, y])

    # Close the polygon
    points.append(points[0])

    return GeometryRegion(region_type=region_type, points=points, fill=fill, label=label)


def _append_tessellated_arc(
    points: list[list[float]],
    center_x: float,
    center_y: float,
    radius: float,
    start_rad: float,
    end_rad: float,
    *,
    include_start: bool = True,
) -> None:
    """Append points along a circular arc (for SVG polygon tessellation)."""
    span = end_rad - start_rad
    n_segments = max(4, int(math.ceil(math.degrees(abs(span)))))
    start_index = 0 if include_start else 1
    for i in range(start_index, n_segments + 1):
        angle = start_rad + span * i / n_segments
        points.append([
            center_x + radius * math.cos(angle),
            center_y + radius * math.sin(angle),
        ])


def _create_tapered_annular_region(
    region_type: str,
    center_x: float,
    center_y: float,
    inner_radius: float,
    outer_radius: float,
    inner_start_rad: float,
    inner_end_rad: float,
    outer_start_rad: float,
    outer_end_rad: float,
    fill: str = "#000000",
    label: str = "Region",
) -> GeometryRegion:
    """Tapered annular sector with curved inner/outer edges (matches mesh geometry)."""
    points: list[list[float]] = []
    _append_tessellated_arc(
        points, center_x, center_y, inner_radius, inner_start_rad, inner_end_rad,
    )
    points.append([
        center_x + outer_radius * math.cos(outer_end_rad),
        center_y + outer_radius * math.sin(outer_end_rad),
    ])
    _append_tessellated_arc(
        points, center_x, center_y, outer_radius, outer_end_rad, outer_start_rad,
        include_start=False,
    )
    points.append([
        center_x + inner_radius * math.cos(inner_start_rad),
        center_y + inner_radius * math.sin(inner_start_rad),
    ])
    points.append(points[0])

    return GeometryRegion(region_type=region_type, points=points, fill=fill, label=label)


def _create_stator_tooth_region(
    center_x: float,
    center_y: float,
    angle_rad: float,
    inner_radius: float,
    outer_radius: float,
    slot_pitch_rad: float,
    slot_opening_width_mm: float,
    slot_body_width_mm: float,
    fill: str = "#000000",
    label: str = "Tooth",
) -> GeometryRegion:
    """Create a stator tooth region that shares boundaries with tapered slots."""
    max_half_angle = 0.499 * slot_pitch_rad
    inner_slot_half = min(
        max_half_angle,
        (slot_opening_width_mm / 2) / inner_radius if inner_radius > 0 else 0,
    )
    outer_slot_half = min(
        max_half_angle,
        (slot_body_width_mm / 2) / outer_radius if outer_radius > 0 else 0,
    )
    inner_tooth_half = max(0.001, slot_pitch_rad / 2 - inner_slot_half)
    outer_tooth_half = max(0.001, slot_pitch_rad / 2 - outer_slot_half)

    return _create_tapered_annular_region(
        region_type=label.lower().replace(" ", "_"),
        center_x=center_x,
        center_y=center_y,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        inner_start_rad=angle_rad - inner_tooth_half,
        inner_end_rad=angle_rad + inner_tooth_half,
        outer_start_rad=angle_rad - outer_tooth_half,
        outer_end_rad=angle_rad + outer_tooth_half,
        fill=fill,
        label=label,
    )


def _create_slot_region(
    center_x: float,
    center_y: float,
    angle_rad: float,
    inner_radius: float,
    outer_radius: float,
    slot_pitch_rad: float,
    inner_width_mm: float,
    outer_width_mm: float,
    fill: str = "#000000",
    label: str = "Slot",
) -> GeometryRegion:
    """Create a tapered stator slot region.

    The airgap-side mouth uses ``slot_opening_mm`` while the outer body uses
    the tooth-pitch minus tooth-width body span.
    """
    max_half_angle = 0.499 * slot_pitch_rad
    inner_half_angle = min(max_half_angle, (inner_width_mm / 2) / inner_radius) if inner_radius > 0 else 0
    outer_half_angle = min(max_half_angle, (outer_width_mm / 2) / outer_radius) if outer_radius > 0 else 0

    return _create_tapered_annular_region(
        region_type=label.lower().replace(" ", "_"),
        center_x=center_x,
        center_y=center_y,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        inner_start_rad=angle_rad - inner_half_angle,
        inner_end_rad=angle_rad + inner_half_angle,
        outer_start_rad=angle_rad - outer_half_angle,
        outer_end_rad=angle_rad + outer_half_angle,
        fill=fill,
        label=label,
    )


def _create_circle_region(
    region_type: str,
    center_x: float,
    center_y: float,
    radius: float,
    num_points: int = 64,
    fill: str = "#000000",
    label: str = "Circle",
) -> GeometryRegion:
    """Create a circular region.

    Args:
        region_type: Type label for the region
        center_x, center_y: Center point in mm
        radius: Radius in mm
        num_points: Number of points for smoothness
        fill: SVG fill color
        label: Human-readable label

    Returns:
        GeometryRegion with polygon points
    """
    points = []
    for i in range(num_points):
        angle = (i / num_points) * 2 * math.pi
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        points.append([x, y])
    points.append(points[0])  # Close polygon

    return GeometryRegion(region_type=region_type, points=points, fill=fill, label=label)


def _create_rectangular_magnet(
    center_x: float,
    center_y: float,
    angle_rad: float,
    radial_center: float,
    magnet_width_mm: float,
    magnet_thickness_mm: float,
    fill: str = "#FF0000",
    label: str = "Magnet",
) -> GeometryRegion:
    """Create a rectangular magnet region in polar coordinates.

    The magnet is positioned at angle_rad, centered radially at radial_center,
    with dimensions magnet_width_mm (tangential) x magnet_thickness_mm (radial).

    Args:
        center_x, center_y: Motor center in mm
        angle_rad: Center angle in radians
        radial_center: Radial center position in mm
        magnet_width_mm: Tangential width in mm
        magnet_thickness_mm: Radial thickness in mm
        fill: SVG fill color
        label: Human-readable label

    Returns:
        GeometryRegion with polygon points
    """
    # Angular half-width
    half_angular_width = (magnet_width_mm / 2) / radial_center if radial_center > 0 else 0
    half_radial_thickness = magnet_thickness_mm / 2

    inner_r = radial_center - half_radial_thickness
    outer_r = radial_center + half_radial_thickness

    angle1 = angle_rad - half_angular_width
    angle2 = angle_rad + half_angular_width

    # Four corners
    p1 = [center_x + inner_r * math.cos(angle1),
          center_y + inner_r * math.sin(angle1)]
    p2 = [center_x + inner_r * math.cos(angle2),
          center_y + inner_r * math.sin(angle2)]
    p3 = [center_x + outer_r * math.cos(angle2),
          center_y + outer_r * math.sin(angle2)]
    p4 = [center_x + outer_r * math.cos(angle1),
          center_y + outer_r * math.sin(angle1)]

    points = [p1, p2, p3, p4, p1]  # Close polygon

    return GeometryRegion(
        region_type=label.lower().replace(" ", "_"),
        points=points,
        fill=fill,
        label=label,
    )


def _create_arc_magnet(
    center_x: float,
    center_y: float,
    angle_rad: float,
    inner_radius: float,
    outer_radius: float,
    magnet_width_mm: float,
    fill: str = "#FF0000",
    label: str = "Magnet",
) -> GeometryRegion:
    """Create a surface magnet region (arc shape for SPM).

    Args:
        center_x, center_y: Motor center in mm
        angle_rad: Center angle in radians
        inner_radius: Inner arc radius in mm
        outer_radius: Outer arc radius in mm
        magnet_width_mm: Tangential width in mm
        fill: SVG fill color
        label: Human-readable label

    Returns:
        GeometryRegion with polygon points
    """
    mean_radius = (inner_radius + outer_radius) / 2
    half_angular_width = (magnet_width_mm / 2) / mean_radius if mean_radius > 0 else 0

    angle1 = angle_rad - half_angular_width
    angle2 = angle_rad + half_angular_width

    # Tessellate the inner and outer arcs so the magnet renders as a true
    # curved segment rather than a straight-edged trapezoid. Aim for ~1 degree
    # of arc per segment, with a sensible floor.
    arc_span = angle2 - angle1
    n_segments = max(8, int(math.ceil(math.degrees(arc_span))))

    points: list[list[float]] = []
    # Outer arc: angle1 -> angle2
    for i in range(n_segments + 1):
        a = angle1 + (arc_span * i / n_segments)
        points.append([center_x + outer_radius * math.cos(a),
                       center_y + outer_radius * math.sin(a)])
    # Inner arc: angle2 -> angle1 (reverse direction to close polygon)
    for i in range(n_segments + 1):
        a = angle2 - (arc_span * i / n_segments)
        points.append([center_x + inner_radius * math.cos(a),
                       center_y + inner_radius * math.sin(a)])
    points.append(points[0])  # Close polygon

    return GeometryRegion(
        region_type=label.lower().replace(" ", "_"),
        points=points,
        fill=fill,
        label=label,
    )


def _add_ipm_magnets(
    regions: list, config: MotorConfig, center_x: float, center_y: float
) -> None:
    """Add IPM (interior permanent magnet) regions.

    Magnets are embedded inside the rotor at:
    radial_center = rotor_OD/2 - bridge_thickness - magnet_thickness/2

    Args:
        regions: List to append magnet regions to
        config: MotorConfig object
        center_x, center_y: Motor center in mm
    """
    rotor_config = config.rotor
    if getattr(rotor_config, "ipm_topology", "flat_buried") == "v_shape":
        geom = compute_geometry(config)
        v_shape_label_positions: dict[int, list[float]] = {}
        for pole_idx in range(rotor_config.pole_count):
            pole_magnets = [mag for mag in geom.magnets if mag.pole_index == pole_idx]
            if not pole_magnets:
                continue
            label_x = sum(
                mag.radial_center_mm * math.cos(mag.center_angle_rad)
                for mag in pole_magnets
            ) / len(pole_magnets)
            label_y = sum(
                mag.radial_center_mm * math.sin(mag.center_angle_rad)
                for mag in pole_magnets
            ) / len(pole_magnets)
            v_shape_label_positions[pole_idx] = [center_x + label_x, center_y + label_y]

        labeled_poles: set[int] = set()
        for mag in geom.magnets:
            side = f" {mag.side}" if mag.side else ""
            if mag.pocket_corners_mm is not None:
                pocket = _create_polygon_region(
                    mag.pocket_corners_mm,
                    center_x,
                    center_y,
                    fill="#111827",
                    label=f"Pocket {mag.pole_index}{side}",
                )
                pocket.region_type = f"ipm_pocket_{mag.pole_index}_{mag.side or 'v'}"
                regions.append(pocket)

            fill = "#E53E3E" if mag.polarity == "N" else "#3182CE"
            magnet = _create_polygon_region(
                mag.corners_mm or (),
                center_x,
                center_y,
                fill=fill,
                label=f"Magnet {mag.polarity} {mag.pole_index}{side}",
            )
            if mag.pole_index not in labeled_poles:
                magnet.text_label = mag.polarity
                magnet.text_position = v_shape_label_positions.get(mag.pole_index)
                labeled_poles.add(mag.pole_index)
            regions.append(magnet)
        return

    rotor_od = rotor_config.OD_mm
    pole_count = rotor_config.pole_count
    magnet_thickness = rotor_config.magnet_thickness_mm
    magnet_width = rotor_config.magnet_width_mm
    bridge_thickness = rotor_config.bridge_thickness_mm
    pocket_clearance = getattr(rotor_config, "pocket_clearance_mm", 0.0) or 0.0
    magnet_angle_offset = math.radians(getattr(rotor_config, "magnet_angle_deg", 0.0) or 0.0)

    # Radial center of magnet
    magnet_radial_center = (
        rotor_od / 2 - bridge_thickness - pocket_clearance - magnet_thickness / 2
    )

    # Angular pitch per pole
    pole_pitch_rad = 2 * math.pi / pole_count

    for pole_idx in range(pole_count):
        angle_rad = (pole_idx * pole_pitch_rad) + magnet_angle_offset

        # Alternate N/S polarity
        if pole_idx % 2 == 0:
            fill = "#E53E3E"  # Red for N
            polarity = "N"
        else:
            fill = "#3182CE"  # Blue for S
            polarity = "S"

        if pocket_clearance > 0:
            pocket = _create_rectangular_magnet(
                center_x,
                center_y,
                angle_rad,
                magnet_radial_center,
                magnet_width + 2 * pocket_clearance,
                magnet_thickness + 2 * pocket_clearance,
                fill="#111827",
                label=f"Pocket {pole_idx}",
            )
            pocket.region_type = f"ipm_pocket_{pole_idx}"
            regions.append(pocket)

        magnet = _create_rectangular_magnet(
            center_x,
            center_y,
            angle_rad,
            magnet_radial_center,
            magnet_width,
            magnet_thickness,
            fill=fill,
            label=f"Magnet {polarity} {pole_idx}",
        )
        # Add N/S text label at magnet center
        magnet.text_label = polarity
        magnet.text_position = [
            center_x + magnet_radial_center * math.cos(angle_rad),
            center_y + magnet_radial_center * math.sin(angle_rad),
        ]
        regions.append(magnet)


def _create_polygon_region(
    points: tuple[tuple[float, float], ...],
    center_x: float,
    center_y: float,
    fill: str,
    label: str,
) -> GeometryRegion:
    translated = [[center_x + x, center_y + y] for x, y in points]
    if translated:
        translated.append(translated[0])
    return GeometryRegion(
        region_type=label.lower().replace(" ", "_"),
        points=translated,
        fill=fill,
        label=label,
    )


def _add_spm_magnets(
    regions: list, rotor_config, center_x: float, center_y: float
) -> None:
    """Add SPM (surface permanent magnet) regions.

    Magnets are arcs on rotor surface:
    inner_radius = rotor_OD/2
    outer_radius = rotor_OD/2 + magnet_thickness

    Args:
        regions: List to append magnet regions to
        rotor_config: RotorConfig object
        center_x, center_y: Motor center in mm
    """
    rotor_od = rotor_config.OD_mm
    pole_count = rotor_config.pole_count
    magnet_thickness = rotor_config.magnet_thickness_mm
    magnet_width = rotor_config.magnet_width_mm

    inner_radius = rotor_od / 2
    outer_radius = rotor_od / 2 + magnet_thickness

    pole_pitch_rad = 2 * math.pi / pole_count

    for pole_idx in range(pole_count):
        angle_rad = pole_idx * pole_pitch_rad

        if pole_idx % 2 == 0:
            fill = "#E53E3E"  # Red for N
            polarity = "N"
        else:
            fill = "#3182CE"  # Blue for S
            polarity = "S"

        magnet = _create_arc_magnet(
            center_x,
            center_y,
            angle_rad,
            inner_radius,
            outer_radius,
            magnet_width,
            fill=fill,
            label=f"Magnet {polarity} {pole_idx}",
        )
        mean_r = (inner_radius + outer_radius) / 2
        magnet.text_label = polarity
        magnet.text_position = [
            center_x + mean_r * math.cos(angle_rad),
            center_y + mean_r * math.sin(angle_rad),
        ]
        regions.append(magnet)


def _generate_winding_layout(
    slot_count: int,
    pole_count: int,
    winding_type: str = "distributed",
    turns_per_coil: int = 1,
    stator_id_mm: float = 72,
    layers: int = 2,
    parallel_paths: int = 1,
    coil_span: int | None = None,
) -> tuple[list[WindingSlot], dict]:
    """Generate 3-phase winding layout with winding factor computation.

    Supports both distributed and concentrated windings. Computes winding factor (kw),
    fill factor estimate, and handles edge cases for unusual slot/pole combinations.

    Args:
        slot_count: Number of stator slots
        pole_count: Number of rotor poles
        winding_type: "distributed" or "concentrated"
        turns_per_coil: Turns per coil
        stator_id_mm: Stator inner diameter in mm (for slot area calculation)
        layers: Number of winding layers (1 or 2)
        parallel_paths: Number of parallel paths
        coil_span: Optional distributed coil span in slots. None means full pitch.

    Returns:
        Tuple of (winding_layout list, metadata dict with winding_factor, fill_factor, warnings)
    """
    winding_layout: list[WindingSlot] = []
    phases: list[str] = ["A", "B", "C"]
    metadata: dict[str, object] = {}
    warnings: list[str] = []
    fundamental_winding_factor = 1.0

    # Number of pole pairs
    pole_pairs = max(1, pole_count // 2)

    # Whether the three phases come out equal is a property of the slot/pole pair,
    # not of the slot count alone. This used to warn on `slot_count % 3 != 0`, which
    # is wrong in both directions: 24 slots is divisible by 3 and still leaves phase
    # B empty at 12 poles, while plenty of counts that are not divisible by 3 balance
    # perfectly well. Ask the same helpers validate_geometry rejects on, so the
    # advisory in the preview payload and the blocking error can never disagree.
    # One decision, shared with validate_geometry. Asking a balance predicate directly
    # was still not enough for the distributed path: the validator also refuses q < 1,
    # which distributed_winding_is_balanced() happily calls balanced, so 12s/8p was
    # blocked with nothing in the payload to explain it (90 such combinations).
    layout_problem = winding_layout_problem(
        slot_count, pole_count, winding_type, layers=layers, coil_span=coil_span
    )
    if layout_problem is not None:
        kind = "concentrated" if winding_type == "concentrated" else "distributed"
        warnings.append(
            f"{slot_count} slots with {pole_count} poles is not a workable "
            f"three-phase {kind} winding: {layout_problem.detail}"
        )

    if winding_type == "concentrated":
        # Concentrated winding: each coil wraps around a single tooth.
        # Phase/sign distribution for concentrated windings. Keep this in sync
        # with geometry_drawer._compute_slot_placements; the preview payload is
        # the UI-facing representation of the same winding the solvers consume.
        slot_phase_map = _assign_concentrated_phases(slot_count, pole_count, phases)

        for slot_idx in range(slot_count):
            phase: Literal["A", "B", "C"] = slot_phase_map.get(slot_idx, "A")  # type: ignore[assignment]
            elec_angle_deg = (slot_idx * 360.0 * pole_pairs / slot_count) % 360.0
            sector = int(elec_angle_deg / 60) % 6
            direction_by_sector: tuple[Literal["in", "out"], ...] = (
                "in",
                "out",
                "in",
                "out",
                "in",
                "out",
            )
            direction = direction_by_sector[sector]
            layer = 1  # Concentrated windings typically use single layer

            winding_layout.append(
                WindingSlot(
                    slot_index=slot_idx,
                    phase=phase,
                    direction=direction,
                    layer=layer,
                )
            )

        coil_span_slots = 1.0

        # Winding factor for concentrated: kw = kd * kp
        # For concentrated: kd=1 (all turns in one slot), kp depends on coil span
        kd_concentrated = 1.0
        # Coil span for concentrated = 1 tooth
        pole_pitch = slot_count / pole_count
        kp_concentrated = math.sin((coil_span_slots / pole_pitch) * math.pi / 2)
        kw_concentrated = kd_concentrated * kp_concentrated
        metadata["winding_factor"] = kw_concentrated
        fundamental_winding_factor = kw_concentrated
        metadata["coil_span_slots"] = coil_span_slots
        metadata["coil_span_label"] = _format_coil_span_label(coil_span_slots)

    else:  # distributed winding
        # Integer-slot full-pitch 60-degree phase belts, from the shared map
        # in backend.winding_utils (same source geometry_drawer and the
        # Magneto2D excitation path consume; mirrored by
        # solvers/magneto2d/src/sources.rs). Full pitch: coil span = one pole
        # pitch = 3q slots.
        coil_span_slots = float(
            distributed_full_pitch_slots(slot_count, pole_count)
            if coil_span is None
            else int(coil_span)
        )

        for slot_idx in range(slot_count):
            for assignment in distributed_slot_layer_assignments(
                slot_idx,
                slot_count,
                pole_count,
                layers,
                coil_span=coil_span,
            ):
                phase_dist: Literal["A", "B", "C"] = assignment.phase  # type: ignore[assignment]
                direction_dist: Literal["in", "out"] = assignment.direction  # type: ignore[assignment]
                winding_layout.append(
                    WindingSlot(
                        slot_index=slot_idx,
                        phase=phase_dist,
                        direction=direction_dist,
                        layer=assignment.layer,
                    )
                )

        # The layout above is FULL-PITCH, so its true fundamental winding
        # factor is the distribution factor kd (kp = 1) of the map we
        # actually build — computed by the same shared module that produced
        # the slot assignment, so the preview UI, the analytical crosscheck
        # table, and the solvers can never disagree.
        kw = distributed_fundamental_winding_factor(slot_count, pole_count, coil_span)

        metadata["winding_factor"] = kw
        fundamental_winding_factor = kw
        metadata["coil_span_slots"] = coil_span_slots
        metadata["coil_span_label"] = _format_coil_span_label(coil_span_slots)
        if coil_span is not None:
            metadata["full_pitch_slots"] = distributed_full_pitch_slots(
                slot_count,
                pole_count,
            )
            metadata["pitch_factor"] = distributed_pitch_factor(
                slot_count,
                pole_count,
                1,
                coil_span,
            )

    # Compute fill factor estimate
    # Simplified: fill_factor = (turns_per_coil * wire_area * slot_count) / total_slot_area
    # Using default copper wire diameter = 1.0 mm
    DEFAULT_WIRE_DIAMETER_MM = 1.0
    wire_cross_section_mm2 = math.pi * (DEFAULT_WIRE_DIAMETER_MM / 2) ** 2

    # Estimate total slot area (approximate as rectangular)
    tooth_pitch_mm = math.pi * stator_id_mm / slot_count
    slot_width_mm = tooth_pitch_mm * 0.4  # Rough estimate: 40% of pitch
    slot_depth_mm = tooth_pitch_mm * 0.3  # Rough estimate: 30% of pitch
    slot_area_mm2 = slot_width_mm * slot_depth_mm
    total_slot_area_mm2 = slot_area_mm2 * slot_count

    # Conductors-per-slot convention: layers split a physical
    # slot's conductor bundle, they do not multiply it.
    conductor_area_mm2 = turns_per_coil * wire_cross_section_mm2 * slot_count
    fill_factor = conductor_area_mm2 / total_slot_area_mm2 if total_slot_area_mm2 > 0 else 0
    fill_factor = min(fill_factor, 1.0)  # Cap at 100%
    metadata["fill_factor"] = fill_factor
    metadata["mmf_harmonics"] = _build_mmf_harmonic_spectrum(
        slot_count,
        pole_count,
        winding_layout,
        fundamental_winding_factor,
    )

    # Add warnings to metadata if any
    if warnings:
        metadata["winding_warnings"] = warnings

    return winding_layout, metadata


def _format_coil_span_label(coil_span_slots: float) -> str:
    """Format coil span in slot pitches for preview metadata."""
    if abs(coil_span_slots - 1.0) < 1e-9:
        return "1 slot pitch"
    if abs(coil_span_slots - round(coil_span_slots)) < 1e-9:
        return f"{int(round(coil_span_slots))} slots"
    return f"{coil_span_slots:.2f} slots"


def _slot_harmonic_winding_factor(
    slot_count: int,
    pole_count: int,
    winding_layout: list[WindingSlot],
    harmonic: int,
) -> float:
    """Estimate phase-A winding factor for one space harmonic.

    This winding-function diagnostic uses the generated slot/sign table. It is
    not used to scale FEA currents; solvers consume that same source table
    directly.
    """
    phase_a_slots = [slot for slot in winding_layout if slot.phase == "A"]
    if not phase_a_slots or slot_count <= 0:
        return 0.0

    pole_pairs = max(1, pole_count // 2)
    phasor = 0j
    for slot in phase_a_slots:
        sign = 1.0 if slot.direction == "in" else -1.0
        angle_rad = harmonic * 2.0 * math.pi * pole_pairs * slot.slot_index / slot_count
        phasor += sign * complex(math.cos(angle_rad), math.sin(angle_rad))

    return abs(phasor) / len(phase_a_slots)


def _build_mmf_harmonic_spectrum(
    slot_count: int,
    pole_count: int,
    winding_layout: list[WindingSlot],
    fundamental_winding_factor: float,
) -> list[dict[str, float | int | str]]:
    """Build a compact relative MMF harmonic spectrum for the UI."""
    fundamental = max(abs(fundamental_winding_factor), 1e-9)
    spectrum: list[dict[str, float | int | str]] = []
    for harmonic in (1, 5, 7, 11):
        winding_factor = (
            fundamental
            if harmonic == 1
            else _slot_harmonic_winding_factor(
                slot_count,
                pole_count,
                winding_layout,
                harmonic,
            )
        )
        relative_mmf_pct = (
            100.0
            if harmonic == 1
            else (winding_factor / harmonic) / fundamental * 100.0
        )
        spectrum.append(
            {
                "harmonic": harmonic,
                "label": "Fundamental" if harmonic == 1 else f"{harmonic}th",
                "winding_factor": winding_factor,
                "relative_mmf_pct": relative_mmf_pct,
            }
        )
    return spectrum


def _derive_winding_coils(
    winding_layout: list[WindingSlot],
    slot_count: int,
    winding_type: str,
    coil_span_slots: float,
) -> list[WindingCoil]:
    """Derive coil-level connectivity from the per-slot winding layout.

    Concentrated windings are tooth-wound: coil k wraps the tooth between
    slot k and slot k+1, so its two sides occupy those two slots (each slot
    therefore holds sides of two adjacent coils). Distributed windings pair
    each 'in' conductor with a same-phase 'out' conductor one coil span away.

    The per-slot layout stays the authoritative phase map (slot k carries
    coil k's phase); this just adds the pairing renderers need to draw
    physical coils and end turns.
    """
    if slot_count <= 0 or not winding_layout:
        return []

    coils: list[WindingCoil] = []

    if winding_type == "concentrated":
        by_slot = {entry.slot_index: entry for entry in winding_layout}
        for slot_idx in range(slot_count):
            entry = by_slot.get(slot_idx)
            if entry is None:
                continue
            coils.append(
                WindingCoil(
                    coil_index=len(coils),
                    phase=entry.phase,
                    polarity=1 if entry.direction == "in" else -1,
                    slot_in=slot_idx,
                    slot_out=(slot_idx + 1) % slot_count,
                    tooth_wound=True,
                    layer=entry.layer,
                )
            )
        return coils

    # Distributed: greedy in/out pairing at ±coil_span within each phase.
    span = max(1, round(coil_span_slots))
    outs_by_phase: dict[str, list[WindingSlot]] = {}
    for entry in winding_layout:
        if entry.direction == "out":
            outs_by_phase.setdefault(entry.phase, []).append(entry)

    def circular_distance(a: int, b: int) -> int:
        diff = abs(a - b) % slot_count
        return min(diff, slot_count - diff)

    used: set[int] = set()
    for entry in winding_layout:
        if entry.direction != "in":
            continue
        candidates = [
            o for o in outs_by_phase.get(entry.phase, []) if id(o) not in used
        ]
        if not candidates:
            continue
        ahead = (entry.slot_index + span) % slot_count
        behind = (entry.slot_index - span) % slot_count
        match = next((o for o in candidates if o.slot_index == ahead), None) or next(
            (o for o in candidates if o.slot_index == behind), None
        )
        if match is None:
            match = min(
                candidates,
                key=lambda o: circular_distance(o.slot_index, entry.slot_index),
            )
        used.add(id(match))
        coils.append(
            WindingCoil(
                coil_index=len(coils),
                phase=entry.phase,
                polarity=1,
                slot_in=entry.slot_index,
                slot_out=match.slot_index,
                tooth_wound=circular_distance(entry.slot_index, match.slot_index) == 1,
                layer=entry.layer,
            )
        )

    return coils


def _assign_concentrated_phases(
    slot_count: int, pole_count: int, phases: list[str]
) -> dict[int, str]:
    """Assign phases to slots for concentrated winding using EMF phasor star.

    Each slot's electrical angle determines its phase assignment via
    60-degree sectors of the EMF phasor diagram. This is critical for
    fractional-slot concentrated windings (e.g. 12s/8p, q=0.5) where
    consecutive slots are NOT the same phase.

    Sectors: A(0-60°), C(60-120°), B(120-180°), A(180-240°), C(240-300°), B(300-360°)
    — the canonical positive-sequence phasor-star belt order (A, -C, B, -A,
    C, -B), matching geometry_drawer._compute_slot_placements. Directions
    alternate in/out per sector in both conventions, so only the phase
    letters differ from the old (mirrored) B/C-swapped order.

    Args:
        slot_count: Number of slots
        pole_count: Number of poles
        phases: Phase names ["A", "B", "C"]

    Returns:
        Dictionary mapping slot_index -> phase
    """
    slot_phase_map = {}
    pole_pairs = max(1, pole_count // 2)
    sector_phases = (phases[0], phases[2], phases[1])  # A, C, B

    for slot_idx in range(slot_count):
        elec_angle_deg = (slot_idx * 360.0 * pole_pairs / slot_count) % 360.0
        sector = int(elec_angle_deg / 60) % 6
        slot_phase_map[slot_idx] = sector_phases[sector % 3]

    return slot_phase_map
