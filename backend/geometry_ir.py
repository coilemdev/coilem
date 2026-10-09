"""Shared geometry IR for topology-scalable solver and mesher paths.

The IR is intentionally solver-neutral. It captures the physical regions and
their sources once, then lets preview, FEMM, Gmsh, and Magneto2D adapters lower
the same contract into renderer-specific primitives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from backend.geometry_drawer import MotorGeometry, compute_geometry
from backend.models import MotorConfig
from backend.solver_environment import solver_setting
from backend.winding_utils import distributed_slot_layer_assignments

GEOMETRY_IR_VERSION = "geometry_ir/v0"
SHAFT_MATERIAL_ENV = "COILEM_SHAFT_MATERIAL"

SegmentKind = Literal["line", "arc"]
LoopKind = Literal["circle", "annulus", "arc_band", "polygon"]
RegionKind = Literal[
    "ExteriorAir",
    "StatorYoke",
    "StatorTooth",
    "SlotWinding",
    "Airgap",
    "RotorCore",
    "Shaft",
    "Magnet",
    "FluxBarrier",
    "MagnetPocketAir",
]
MotionGroup = Literal["stationary", "rotor", "sliding_airgap", "none"]


def shaft_material_key(config: MotorConfig) -> str:
    """Return the solver-neutral shaft material key.

    The Prius/ORNL benchmark baseline keeps the shaft non-magnetic. Set
    COILEM_SHAFT_MATERIAL=rotor_steel for parity probes that model the shaft
    as the configured rotor steel.
    """

    raw = solver_setting(SHAFT_MATERIAL_ENV, "").strip().lower()
    if raw in {"rotor_steel", "rotor-steel", "rotor", "steel", "rotor_core"}:
        return f"steel:rotor:{config.materials.rotor_steel}"
    return "air"


@dataclass(frozen=True)
class GeometryIRPoint:
    """A point in millimeters in the motor cross-section frame."""

    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class GeometryIRSegment:
    """One directed boundary segment in a closed region loop."""

    kind: SegmentKind
    start: GeometryIRPoint
    end: GeometryIRPoint
    center: GeometryIRPoint | None = None
    radius_mm: float | None = None
    sweep_deg: float | None = None
    boundary_tag: str | None = None


@dataclass(frozen=True)
class GeometryIRLoop:
    """A closed loop made from line and/or arc segments."""

    loop_id: str
    kind: LoopKind
    segments: tuple[GeometryIRSegment, ...]
    points_mm: tuple[GeometryIRPoint, ...] = ()
    boundary_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeometryIRRegion:
    """One physical region to be meshed and assigned material/source metadata."""

    region_id: str
    kind: RegionKind
    material_key: str
    loops: tuple[GeometryIRLoop, ...]
    area_mm2: float
    motion_group: MotionGroup
    source_group: str | None = None
    magnetization_xy: tuple[float, float] | None = None
    boundary_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeometryIRValidationReport:
    """Geometry-derived facts and invariant failures for a built IR."""

    version: str
    topology: str
    ipm_topology: str | None
    region_count: int
    region_area_by_kind_mm2: dict[str, float]
    magnet_area_mm2: float
    pocket_air_area_mm2: float
    slot_winding_area_mm2: float
    airgap_area_mm2: float
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeometryIR:
    """Shared geometry IR v0."""

    version: str
    topology: str
    ipm_topology: str | None
    pole_count: int
    slot_count: int
    regions: tuple[GeometryIRRegion, ...]
    metadata: dict[str, float | int | str | None] = field(default_factory=dict)

    def validation_report(self) -> GeometryIRValidationReport:
        return validate_geometry_ir(self)


def build_geometry_ir(
    config: MotorConfig,
    *,
    geom: MotorGeometry | None = None,
) -> GeometryIR:
    """Build the shared geometry IR from a motor configuration."""

    geom = geom or compute_geometry(config)
    topology = str(config.topology).upper()
    ipm_topology = str(getattr(config.rotor, "ipm_topology", "") or "").lower()
    if topology == "SPM":
        return _build_spm_geometry_ir(config, geom)
    if topology == "IPM" and ipm_topology == "v_shape":
        return _build_v_shape_ipm_geometry_ir(config, geom)
    if topology == "IPM" and ipm_topology == "pyleecan_holem50":
        return _build_pyleecan_holem50_ipm_geometry_ir(config, geom)
    if topology == "IPM":
        return _build_flat_ipm_geometry_ir(config, geom)
    return _build_motor_geometry_ir(config, geom)


def _build_spm_geometry_ir(config: MotorConfig, geom: MotorGeometry) -> GeometryIR:
    return _build_motor_geometry_ir(config, geom)


def _build_flat_ipm_geometry_ir(config: MotorConfig, geom: MotorGeometry) -> GeometryIR:
    return _build_motor_geometry_ir(config, geom)


def _build_v_shape_ipm_geometry_ir(config: MotorConfig, geom: MotorGeometry) -> GeometryIR:
    return _build_motor_geometry_ir(config, geom)


def _build_pyleecan_holem50_ipm_geometry_ir(
    config: MotorConfig,
    geom: MotorGeometry,
) -> GeometryIR:
    return _build_motor_geometry_ir(config, geom)


def _build_motor_geometry_ir(config: MotorConfig, geom: MotorGeometry) -> GeometryIR:
    """Build the current shared IR region set for one motor topology family."""

    regions: list[GeometryIRRegion] = []
    slotless_stator = False

    bore_breakpoints = _add_stator_regions(regions, config, geom, slotless_stator)
    _add_airgap_region(regions, config, geom, bore_breakpoints=bore_breakpoints)
    _add_rotor_regions(regions, config, geom)
    _add_magnet_regions(regions, config, geom)

    metadata: dict[str, float | int | str | None] = {
        "stator_od_mm": float(config.stator.OD_mm),
        "stator_id_mm": float(config.stator.ID_mm),
        "rotor_od_mm": float(config.rotor.OD_mm),
        "rotor_id_mm": (
            float(config.rotor.ID_mm) if config.rotor.ID_mm is not None else None
        ),
        "airgap_mm": float(geom.airgap_mm),
        "stack_length_mm": float(config.stator.stack_length_mm),
        "pocket_clearance_mm": float(
            getattr(config.rotor, "pocket_clearance_mm", 0.0) or 0.0
        ),
    }
    split_distributed_layers = (
        config.winding.type == "distributed"
        and config.winding.layers >= 2
        and not bool(config.stator.tooth_shoe_enabled)
    )
    if split_distributed_layers:
        metadata["winding_type"] = str(config.winding.type)
        metadata["winding_layers"] = int(config.winding.layers)
        if config.winding.coil_span is not None:
            metadata["coil_span_slots"] = int(config.winding.coil_span)

    return GeometryIR(
        version=GEOMETRY_IR_VERSION,
        topology=str(config.topology),
        ipm_topology=getattr(config.rotor, "ipm_topology", None),
        pole_count=config.rotor.pole_count,
        slot_count=config.stator.slot_count,
        regions=tuple(regions),
        metadata=metadata,
    )


def validate_geometry_ir(ir: GeometryIR) -> GeometryIRValidationReport:
    """Validate topology-neutral region invariants from the IR."""

    by_kind: dict[str, float] = {}
    issues: list[str] = []

    for region in ir.regions:
        if not math.isfinite(region.area_mm2) or region.area_mm2 <= 0:
            issues.append(f"{region.region_id} has non-positive area")
        by_kind[region.kind] = by_kind.get(region.kind, 0.0) + region.area_mm2
        if region.kind == "Magnet" and region.magnetization_xy is None:
            issues.append(f"{region.region_id} missing magnetization vector")

    topology = ir.topology.upper()
    ipm_topology = (ir.ipm_topology or "").lower()
    paired_ipm = ipm_topology in {"v_shape", "pyleecan_holem50"}
    expected_magnets = ir.pole_count * 2 if paired_ipm else ir.pole_count
    actual_magnets = sum(1 for region in ir.regions if region.kind == "Magnet")
    if actual_magnets != expected_magnets:
        issues.append(
            f"expected {expected_magnets} Magnet regions, found {actual_magnets}"
        )

    slot_regions = [region for region in ir.regions if region.kind == "SlotWinding"]
    winding_type = str(ir.metadata.get("winding_type") or "")
    winding_layers = int(ir.metadata.get("winding_layers") or 1)
    expected_layers = max(1, winding_layers) if winding_type == "distributed" else 1
    expected_slot_regions = ir.slot_count * expected_layers
    if slot_regions and len(slot_regions) != expected_slot_regions:
        issues.append(
            f"expected {expected_slot_regions} SlotWinding regions, found {len(slot_regions)}"
        )

    if by_kind.get("Airgap", 0.0) <= 0:
        issues.append("missing positive Airgap region")

    pocket_clearance = float(ir.metadata.get("pocket_clearance_mm") or 0.0)
    if topology == "IPM" and ipm_topology == "v_shape" and pocket_clearance > 0:
        expected_pockets = expected_magnets
        actual_pockets = sum(
            1 for region in ir.regions if region.kind == "MagnetPocketAir"
        )
        if actual_pockets != expected_pockets:
            issues.append(
                f"expected {expected_pockets} MagnetPocketAir regions, "
                f"found {actual_pockets}"
            )
    elif topology == "IPM" and ipm_topology == "pyleecan_holem50":
        expected_pockets = ir.pole_count * 3
        actual_pockets = sum(
            1 for region in ir.regions if region.kind == "MagnetPocketAir"
        )
        if actual_pockets != expected_pockets:
            issues.append(
                f"expected {expected_pockets} MagnetPocketAir regions, "
                f"found {actual_pockets}"
            )

    return GeometryIRValidationReport(
        version=ir.version,
        topology=ir.topology,
        ipm_topology=ir.ipm_topology,
        region_count=len(ir.regions),
        region_area_by_kind_mm2=by_kind,
        magnet_area_mm2=by_kind.get("Magnet", 0.0),
        pocket_air_area_mm2=by_kind.get("MagnetPocketAir", 0.0),
        slot_winding_area_mm2=by_kind.get("SlotWinding", 0.0),
        airgap_area_mm2=by_kind.get("Airgap", 0.0),
        issues=tuple(issues),
    )


def _add_stator_regions(
    regions: list[GeometryIRRegion],
    config: MotorConfig,
    geom: MotorGeometry,
    slotless_stator: bool,
) -> list[float]:
    """Append stator yoke/tooth/winding regions and return bore breakpoints.

    The returned breakpoint angles are the bore-side transitions the airgap
    should mesh against (slot-mouth edges without the shoe, shoe-tip edges
    with the shoe). ``_add_airgap_region`` consumes them.
    """
    stator_material = f"steel:stator:{config.materials.stator_steel}"
    if slotless_stator or not geom.slots:
        regions.append(
            _annulus_region(
                "stator_yoke",
                "StatorYoke",
                stator_material,
                geom.stator_ID_r,
                geom.stator_OD_r,
                "stationary",
            )
        )
        return []

    slot_outer_r = geom.slots[0].outer_radius_mm
    stator_inner_breakpoints: list[float] = []
    stator_outer_breakpoints: list[float] = []
    for slot in geom.slots:
        stator_inner_breakpoints.extend(slot.edge_angles_at_radius(geom.stator_ID_r))
        stator_outer_breakpoints.extend(slot.edge_angles_at_radius(slot_outer_r))

    regions.append(
        GeometryIRRegion(
            region_id="stator_yoke",
            kind="StatorYoke",
            material_key=stator_material,
            loops=(
                _circle_loop("stator_yoke_outer", geom.stator_OD_r),
                _circle_loop_with_breakpoints(
                    "stator_yoke_inner",
                    slot_outer_r,
                    stator_outer_breakpoints,
                ),
            ),
            area_mm2=math.pi * max(0.0, geom.stator_OD_r**2 - slot_outer_r**2),
            motion_group="stationary",
        )
    )

    shoe_enabled = bool(config.stator.tooth_shoe_enabled)
    bore_r = geom.stator_ID_r
    if shoe_enabled:
        # Clamp the shoulder inside the slot band so the body band keeps a
        # positive height; a degenerate (zero-height) body band would emit
        # coincident loop points that confuse downstream tessellation.
        shoulder_r = min(bore_r + config.stator.tooth_shoe_height_mm, slot_outer_r - 1e-6)
        overhang_mm = config.stator.tooth_shoe_overhang_mm
        slot_pitch_rad = 2.0 * math.pi / config.stator.slot_count
        slot_opening_mm = config.stator.slot_opening_mm
    else:
        shoulder_r = bore_r
        overhang_mm = 0.0
        slot_pitch_rad = 0.0
        slot_opening_mm = 0.0

    bore_breakpoints: list[float] = []
    # Per-tooth shoe boundary angles. Tooth ``idx`` is between slot ``idx`` and
    # slot ``idx + 1``; the slot loop reuses these exact angles so tooth/slot
    # boundaries line up even after local shoulder fillets are applied.
    tooth_shoe_boundaries: list[tuple[float, float, float, float, float, float]] = []

    for idx, slot in enumerate(geom.slots):
        next_slot = geom.slots[(idx + 1) % len(geom.slots)]
        tooth_r = 0.5 * (geom.stator_ID_r + slot_outer_r)
        right_of_slot = slot.center_angle_rad + slot.half_width_at_radius(tooth_r)
        left_of_next = (
            next_slot.center_angle_rad - next_slot.half_width_at_radius(tooth_r)
        )
        if left_of_next < right_of_slot:
            left_of_next += 2 * math.pi
        tooth_center = 0.5 * (right_of_slot + left_of_next)
        inner_half = _angle_delta(
            slot.edge_angles_at_radius(geom.stator_ID_r)[1],
            next_slot.edge_angles_at_radius(geom.stator_ID_r)[0],
        ) / 2
        outer_half = _angle_delta(
            slot.edge_angles_at_radius(slot_outer_r)[1],
            next_slot.edge_angles_at_radius(slot_outer_r)[0],
        ) / 2
        outer_start = tooth_center - outer_half
        outer_end = tooth_center + outer_half
        if shoe_enabled:
            bore_tip_half, shoulder_half = _tooth_shoe_half_angles(
                inner_half,
                outer_half,
                bore_r,
                slot_outer_r,
                shoulder_r,
                overhang_mm,
                slot_pitch_rad,
                slot_opening_mm,
            )
            bore_start = tooth_center - bore_tip_half
            bore_end = tooth_center + bore_tip_half
            shoulder_start = tooth_center - shoulder_half
            shoulder_end = tooth_center + shoulder_half
            tooth_loop = _shoed_annular_loop(
                f"stator_tooth_{idx}_boundary",
                bore_r,
                shoulder_r,
                slot_outer_r,
                bore_start,
                bore_end,
                shoulder_start,
                shoulder_end,
                outer_start,
                outer_end,
            )
            tooth_area = _loop_area_mm2(tooth_loop)
            bore_breakpoints.extend((bore_start, bore_end))
            tooth_shoe_boundaries.append(
                (
                    bore_start,
                    bore_end,
                    shoulder_start,
                    shoulder_end,
                    outer_start,
                    outer_end,
                )
            )
        else:
            inner_start = tooth_center - inner_half
            inner_end = tooth_center + inner_half
            tooth_loop = _tapered_annular_loop(
                f"stator_tooth_{idx}_boundary",
                geom.stator_ID_r,
                slot_outer_r,
                inner_start,
                inner_end,
                outer_start,
                outer_end,
            )
            tooth_area = _tapered_annular_sector_area(
                geom.stator_ID_r,
                slot_outer_r,
                inner_start,
                inner_end,
                outer_start,
                outer_end,
            )
        regions.append(
            GeometryIRRegion(
                region_id=f"stator_tooth_{idx}",
                kind="StatorTooth",
                material_key=stator_material,
                loops=(tooth_loop,),
                # Use arc-bounded area (not chord polygon) to match Gmsh's
                # triangulation. Chord polygon under-/over-counts by the
                # circular segments at the inner/outer arcs, which is small
                # for narrow teeth (8p12s, 10p12s) but >5% for wide ones
                # (4p6s) — tripped the QA check at gmsh_solver.py:868.
                area_mm2=tooth_area,
                motion_group="stationary",
            )
        )

    conductor_material = f"conductor:{config.materials.conductor}"
    for slot_idx, slot in enumerate(geom.slots):
        inner_left, inner_right = slot.edge_angles_at_radius(slot.inner_radius_mm)
        outer_left, outer_right = slot.edge_angles_at_radius(slot.outer_radius_mm)
        if shoe_enabled:
            # The slot is the complement of its adjacent tooth shoes. Reuse the
            # exact adjacent tooth boundary angles so the winding region shares
            # the same line/fillet boundary instead of independently
            # reconstructing a near-match from slot-center half angles.
            left_tooth = tooth_shoe_boundaries[(slot_idx - 1) % len(tooth_shoe_boundaries)]
            right_tooth = tooth_shoe_boundaries[slot_idx % len(tooth_shoe_boundaries)]
            bore_left = left_tooth[1]
            bore_right = right_tooth[0]
            shoulder_left = left_tooth[3]
            shoulder_right = right_tooth[2]
            outer_left = left_tooth[5]
            outer_right = right_tooth[4]
            winding_loop = _shoed_annular_loop(
                f"slot_winding_{slot.slot_index}_boundary",
                bore_r,
                shoulder_r,
                slot.outer_radius_mm,
                bore_left,
                bore_right,
                shoulder_left,
                shoulder_right,
                outer_left,
                outer_right,
            )
            winding_area = _loop_area_mm2(winding_loop)
        else:
            winding_loop = _tapered_annular_loop(
                f"slot_winding_{slot.slot_index}_boundary",
                slot.inner_radius_mm,
                slot.outer_radius_mm,
                inner_left,
                inner_right,
                outer_left,
                outer_right,
            )
            winding_area = _tapered_annular_sector_area(
                slot.inner_radius_mm,
                slot.outer_radius_mm,
                inner_left,
                inner_right,
                outer_left,
                outer_right,
            )

        if config.winding.type == "distributed" and config.winding.layers >= 2 and not shoe_enabled:
            for assignment in distributed_slot_layer_assignments(
                slot.slot_index,
                config.stator.slot_count,
                config.rotor.pole_count,
                config.winding.layers,
                coil_span=config.winding.coil_span,
            ):
                layer_inner_r, layer_outer_r = _slot_layer_radial_bounds(
                    slot.inner_radius_mm,
                    slot.outer_radius_mm,
                    assignment.layer,
                    2,
                )
                layer_inner_left = _slot_wall_angle_at_radius(slot, "left", layer_inner_r)
                layer_inner_right = _slot_wall_angle_at_radius(slot, "right", layer_inner_r)
                layer_outer_left = _slot_wall_angle_at_radius(slot, "left", layer_outer_r)
                layer_outer_right = _slot_wall_angle_at_radius(slot, "right", layer_outer_r)
                layer_loop = _tapered_annular_loop(
                    f"slot_winding_{slot.slot_index}_layer{assignment.layer}_boundary",
                    layer_inner_r,
                    layer_outer_r,
                    layer_inner_left,
                    layer_inner_right,
                    layer_outer_left,
                    layer_outer_right,
                )
                layer_area = _tapered_annular_sector_area(
                    layer_inner_r,
                    layer_outer_r,
                    layer_inner_left,
                    layer_inner_right,
                    layer_outer_left,
                    layer_outer_right,
                )
                regions.append(
                    GeometryIRRegion(
                        region_id=f"slot_winding_{slot.slot_index}_layer{assignment.layer}",
                        kind="SlotWinding",
                        material_key=conductor_material,
                        loops=(layer_loop,),
                        area_mm2=layer_area,
                        motion_group="stationary",
                        source_group=(
                            f"winding:{assignment.phase}:{assignment.direction}:"
                            f"slot{slot.slot_index}:layer{assignment.layer}"
                        ),
                    )
                )
            continue

        source = f"winding:{slot.phase}:{slot.direction}:slot{slot.slot_index}"
        regions.append(
            GeometryIRRegion(
                region_id=f"slot_winding_{slot.slot_index}",
                kind="SlotWinding",
                material_key=conductor_material,
                loops=(winding_loop,),
                # Arc-bounded sector area (see stator_tooth comment above).
                area_mm2=winding_area,
                motion_group="stationary",
                source_group=source,
            )
        )

    return bore_breakpoints if shoe_enabled else stator_inner_breakpoints


def _slot_layer_radial_bounds(
    inner_radius_mm: float,
    outer_radius_mm: float,
    layer: int,
    layers: int,
) -> tuple[float, float]:
    radial_span = max(0.0, outer_radius_mm - inner_radius_mm)
    n_layers = max(1, layers)
    layer_idx = max(1, min(layer, n_layers)) - 1
    r0 = inner_radius_mm + radial_span * layer_idx / n_layers
    r1 = inner_radius_mm + radial_span * (layer_idx + 1) / n_layers
    return r0, r1


def _slot_wall_angle_at_radius(slot, side: str, radius_mm: float) -> float:
    """Return the polar angle where a straight slot wall crosses a radius."""

    inner_left, inner_right = slot.edge_angles_at_radius(slot.inner_radius_mm)
    outer_left, outer_right = slot.edge_angles_at_radius(slot.outer_radius_mm)
    if side == "left":
        a0, a1 = inner_left, outer_left
    else:
        a0, a1 = inner_right, outer_right

    p0 = (
        slot.inner_radius_mm * math.cos(a0),
        slot.inner_radius_mm * math.sin(a0),
    )
    p1 = (
        slot.outer_radius_mm * math.cos(a1),
        slot.outer_radius_mm * math.sin(a1),
    )
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    target2 = radius_mm * radius_mm
    qa = dx * dx + dy * dy
    qb = 2.0 * (p0[0] * dx + p0[1] * dy)
    qc = p0[0] * p0[0] + p0[1] * p0[1] - target2
    if qa <= 1.0e-18:
        return math.atan2(p0[1], p0[0])
    disc = max(0.0, qb * qb - 4.0 * qa * qc)
    roots = [
        (-qb - math.sqrt(disc)) / (2.0 * qa),
        (-qb + math.sqrt(disc)) / (2.0 * qa),
    ]
    nominal = (
        (radius_mm - slot.inner_radius_mm)
        / max(1.0e-12, slot.outer_radius_mm - slot.inner_radius_mm)
    )
    t = min(roots, key=lambda value: (0.0 if -1.0e-9 <= value <= 1.0 + 1.0e-9 else 1.0, abs(value - nominal)))
    t = max(0.0, min(1.0, t))
    x = p0[0] + t * dx
    y = p0[1] + t * dy
    return _angle_near(math.atan2(y, x), slot.center_angle_rad)


def _angle_near(angle_rad: float, reference_rad: float) -> float:
    while angle_rad - reference_rad > math.pi:
        angle_rad -= 2.0 * math.pi
    while angle_rad - reference_rad <= -math.pi:
        angle_rad += 2.0 * math.pi
    return angle_rad


def _add_airgap_region(
    regions: list[GeometryIRRegion],
    config: MotorConfig,
    geom: MotorGeometry,
    *,
    bore_breakpoints: list[float] | None = None,
) -> None:
    topology = str(config.topology).upper()
    airgap_inner_r = geom.rotor_OD_r
    airgap_inner_breakpoints: list[float] = []
    if topology == "SPM" and geom.magnets:
        airgap_inner_r = max(mag.outer_radius_mm for mag in geom.magnets)
        airgap_inner_breakpoints = _magnet_edge_angles(geom)

    if geom.slots:
        # Prefer shoe-aware bore breakpoints from the stator builder so the
        # airgap bore-circle nodes land on the actual shoe tips / slot mouths
        # rather than the un-flared slot-mouth config edges.
        stator_inner_breakpoints = list(bore_breakpoints) if bore_breakpoints is not None else []
        if bore_breakpoints is None:
            for slot in geom.slots:
                stator_inner_breakpoints.extend(
                    slot.edge_angles_at_radius(geom.stator_ID_r)
                )
        regions.append(
            GeometryIRRegion(
                region_id="airgap",
                kind="Airgap",
                material_key="air",
                loops=(
                    _circle_loop_with_breakpoints(
                        "airgap_outer",
                        geom.stator_ID_r,
                        stator_inner_breakpoints,
                        boundary_tag="airgap_outer",
                    ),
                    _circle_loop_with_breakpoints(
                        "airgap_inner",
                        airgap_inner_r,
                        airgap_inner_breakpoints,
                        boundary_tag="airgap_inner",
                    ),
                ),
                area_mm2=math.pi * max(0.0, geom.stator_ID_r**2 - airgap_inner_r**2),
                motion_group="sliding_airgap",
                boundary_tags=("airgap_inner", "airgap_outer"),
            )
        )
    else:
        regions.append(
            _annulus_region(
                "airgap",
                "Airgap",
                "air",
                airgap_inner_r,
                geom.stator_ID_r,
                "sliding_airgap",
                boundary_tags=("airgap_inner", "airgap_outer"),
            )
        )


def _add_rotor_regions(
    regions: list[GeometryIRRegion],
    config: MotorConfig,
    geom: MotorGeometry,
) -> None:
    rotor_material = f"steel:rotor:{config.materials.rotor_steel}"
    shaft_material = shaft_material_key(config)
    rotor_outer_breakpoints = (
        _magnet_edge_angles(geom) if str(config.topology).upper() == "SPM" else []
    )
    exclusion_loops: list[GeometryIRLoop] = [
        _circle_loop("shaft_boundary", geom.shaft_r, boundary_tag="shaft")
    ]
    exclusion_area = math.pi * geom.shaft_r**2
    pocket_magnet_ids: set[int] = set()

    for pocket in geom.rotor_air_pockets:
        exclusion_loops.append(
            _polygon_loop(
                f"rotor_pocket_cutout_{pocket.pocket_index}",
                pocket.corners_mm,
            )
        )
        exclusion_area += _polygon_area(pocket.corners_mm)
        pocket_magnet_ids.update(pocket.magnet_indices)

    for idx, mag in enumerate(geom.magnets):
        if idx in pocket_magnet_ids:
            continue
        if mag.pocket_corners_mm is not None:
            exclusion_loops.append(
                _polygon_loop(f"rotor_pocket_cutout_{idx}", mag.pocket_corners_mm)
            )
            exclusion_area += _polygon_area(mag.pocket_corners_mm)
        elif str(config.topology).upper() == "IPM" and mag.corners_mm is not None:
            exclusion_loops.append(
                _polygon_loop(f"rotor_magnet_cutout_{idx}", mag.corners_mm)
            )
            exclusion_area += _polygon_area(mag.corners_mm)
        elif str(config.topology).upper() == "IPM":
            exclusion_loops.append(_magnet_arc_band_loop(f"rotor_magnet_cutout_{idx}", mag))
            exclusion_area += _magnet_arc_band_area(mag)

    rotor_area = max(0.0, math.pi * geom.rotor_OD_r**2 - exclusion_area)
    regions.append(
        GeometryIRRegion(
            region_id="rotor_core",
            kind="RotorCore",
            material_key=rotor_material,
            loops=(
                _circle_loop_with_breakpoints(
                    "rotor_outer",
                    geom.rotor_OD_r,
                    rotor_outer_breakpoints,
                    boundary_tag="rotor_od",
                ),
                *exclusion_loops,
            ),
            area_mm2=rotor_area,
            motion_group="rotor",
            boundary_tags=("rotor_od",),
        )
    )
    regions.append(
        _circle_region(
            "shaft",
            "Shaft",
            shaft_material,
            geom.shaft_r,
            "rotor",
            boundary_tag="shaft",
        )
    )


def _add_magnet_regions(
    regions: list[GeometryIRRegion],
    config: MotorConfig,
    geom: MotorGeometry,
) -> None:
    magnet_material = f"magnet:{config.materials.magnet_grade}"
    topology = str(config.topology).upper()

    if topology == "SPM":
        _add_spm_inter_pole_air_regions(regions, geom)

    magnet_loops: list[GeometryIRLoop] = []
    magnet_areas: list[float] = []
    for idx, mag in enumerate(geom.magnets):
        if mag.corners_mm is not None:
            magnet_points = mag.corners_mm
            magnet_loop = _polygon_loop(f"magnet_{idx}_boundary", magnet_points)
            magnet_area = _polygon_area(magnet_points)
        elif topology == "SPM":
            a1 = mag.center_angle_rad - mag.half_width_rad
            a2 = mag.center_angle_rad + mag.half_width_rad
            magnet_loop = _arc_band_loop(
                f"magnet_{idx}_boundary",
                mag.inner_radius_mm,
                mag.outer_radius_mm,
                a1,
                a2,
            )
            magnet_area = 0.5 * (
                mag.outer_radius_mm**2 - mag.inner_radius_mm**2
            ) * (a2 - a1)
        else:
            magnet_loop = _magnet_arc_band_loop(f"magnet_{idx}_boundary", mag)
            magnet_area = _magnet_arc_band_area(mag)

        magnet_loops.append(magnet_loop)
        magnet_areas.append(magnet_area)

    for pocket in geom.rotor_air_pockets:
        pocket_loop = _polygon_loop(
            f"magnet_pocket_air_{pocket.pocket_index}_outer",
            pocket.corners_mm,
        )
        contained_magnet_loops = tuple(
            magnet_loops[idx]
            for idx in pocket.magnet_indices
            if 0 <= idx < len(magnet_loops)
        )
        contained_magnet_area = sum(
            magnet_areas[idx]
            for idx in pocket.magnet_indices
            if 0 <= idx < len(magnet_areas)
        )
        pocket_air_area = max(
            0.0,
            _polygon_area(pocket.corners_mm) - contained_magnet_area,
        )
        regions.append(
            GeometryIRRegion(
                region_id=f"magnet_pocket_air_{pocket.pocket_index}",
                kind="MagnetPocketAir",
                material_key="air",
                loops=(pocket_loop, *contained_magnet_loops),
                area_mm2=pocket_air_area,
                motion_group="rotor",
                boundary_tags=("magnet_pocket_air",),
            )
        )

    for idx, mag in enumerate(geom.magnets):
        magnet_loop = magnet_loops[idx]
        magnet_area = magnet_areas[idx]

        if mag.pocket_corners_mm is not None:
            pocket_area = _polygon_area(mag.pocket_corners_mm)
            pocket_air_area = max(0.0, pocket_area - magnet_area)
            regions.append(
                GeometryIRRegion(
                    region_id=f"magnet_pocket_air_{idx}",
                    kind="MagnetPocketAir",
                    material_key="air",
                    loops=(
                        _polygon_loop(
                            f"magnet_pocket_air_{idx}_outer",
                            mag.pocket_corners_mm,
                        ),
                        magnet_loop,
                    ),
                    area_mm2=pocket_air_area,
                    motion_group="rotor",
                    boundary_tags=("magnet_pocket_air",),
                )
            )

        regions.append(
            GeometryIRRegion(
                region_id=f"magnet_{idx}",
                kind="Magnet",
                material_key=magnet_material,
                loops=(magnet_loop,),
                area_mm2=magnet_area,
                motion_group="rotor",
                source_group=f"pm:{mag.polarity}:magnet{idx}",
                magnetization_xy=_unit_vector_deg(mag.magnetization_angle_deg),
                boundary_tags=("magnet",),
            )
        )


def _add_spm_inter_pole_air_regions(
    regions: list[GeometryIRRegion],
    geom: MotorGeometry,
) -> None:
    if len(geom.magnets) < 2:
        return

    magnets = sorted(geom.magnets, key=lambda mag: mag.center_angle_rad % (2 * math.pi))
    magnet_outer_r = max(mag.outer_radius_mm for mag in magnets)
    # An inter-pole gap can never be wider than one pole pitch. The wrap below
    # cannot tell "the seam between the last and first magnet" from "these two
    # magnets overlap", and both look like gap_end <= gap_start — so an overlap
    # used to come out as a near-complete turn and emit a bogus full-ring region
    # (a 1.6 deg overlap became a 358 deg sweep). Gmsh then meshed the real,
    # degenerate sliver and the mesh QA gate reported a ~99% area mismatch, miles
    # from the actual cause. Bounding the sweep keeps the overlap out of the IR;
    # validate_geometry is what tells the user their magnets are too wide.
    pole_pitch_rad = 2 * math.pi / len(magnets)
    for idx, mag in enumerate(magnets):
        next_mag = magnets[(idx + 1) % len(magnets)]
        gap_start = mag.center_angle_rad + mag.half_width_rad
        gap_end = next_mag.center_angle_rad - next_mag.half_width_rad
        while gap_end <= gap_start:
            gap_end += 2 * math.pi
        gap_sweep = gap_end - gap_start
        if gap_sweep <= 1.0e-9 or gap_sweep > pole_pitch_rad + 1.0e-9:
            continue
        regions.append(
            GeometryIRRegion(
                region_id=f"spm_inter_pole_air_{idx}",
                kind="MagnetPocketAir",
                material_key="air",
                loops=(
                    _arc_band_loop(
                        f"spm_inter_pole_air_{idx}_boundary",
                        geom.rotor_OD_r,
                        magnet_outer_r,
                        gap_start,
                        gap_end,
                    ),
                ),
                area_mm2=0.5
                * max(0.0, magnet_outer_r**2 - geom.rotor_OD_r**2)
                * gap_sweep,
                motion_group="rotor",
                boundary_tags=("spm_inter_pole_air",),
            )
        )


def _annulus_region(
    region_id: str,
    kind: RegionKind,
    material_key: str,
    inner_radius_mm: float,
    outer_radius_mm: float,
    motion_group: MotionGroup,
    *,
    boundary_tags: tuple[str, ...] = (),
) -> GeometryIRRegion:
    area = math.pi * max(0.0, outer_radius_mm**2 - inner_radius_mm**2)
    return GeometryIRRegion(
        region_id=region_id,
        kind=kind,
        material_key=material_key,
        loops=(
            _circle_loop(
                f"{region_id}_outer",
                outer_radius_mm,
                boundary_tag=boundary_tags[-1] if boundary_tags else None,
            ),
            _circle_loop(
                f"{region_id}_inner",
                inner_radius_mm,
                boundary_tag=boundary_tags[0] if boundary_tags else None,
            ),
        ),
        area_mm2=area,
        motion_group=motion_group,
        boundary_tags=boundary_tags,
    )


def _circle_region(
    region_id: str,
    kind: RegionKind,
    material_key: str,
    radius_mm: float,
    motion_group: MotionGroup,
    *,
    boundary_tag: str | None = None,
) -> GeometryIRRegion:
    return GeometryIRRegion(
        region_id=region_id,
        kind=kind,
        material_key=material_key,
        loops=(_circle_loop(f"{region_id}_boundary", radius_mm, boundary_tag),),
        area_mm2=math.pi * radius_mm**2,
        motion_group=motion_group,
        boundary_tags=(boundary_tag,) if boundary_tag else (),
    )


def _polygon_region(
    region_id: str,
    kind: RegionKind,
    material_key: str,
    points: tuple[tuple[float, float], ...],
    motion_group: MotionGroup,
    *,
    source_group: str | None = None,
) -> GeometryIRRegion:
    return GeometryIRRegion(
        region_id=region_id,
        kind=kind,
        material_key=material_key,
        loops=(_polygon_loop(f"{region_id}_boundary", points),),
        area_mm2=_polygon_area(points),
        motion_group=motion_group,
        source_group=source_group,
    )


def _circle_loop(
    loop_id: str,
    radius_mm: float,
    boundary_tag: str | None = None,
) -> GeometryIRLoop:
    points = (
        GeometryIRPoint(radius_mm, 0.0),
        GeometryIRPoint(0.0, radius_mm),
        GeometryIRPoint(-radius_mm, 0.0),
        GeometryIRPoint(0.0, -radius_mm),
    )
    center = GeometryIRPoint(0.0, 0.0)
    segments = tuple(
        GeometryIRSegment(
            kind="arc",
            start=points[idx],
            end=points[(idx + 1) % len(points)],
            center=center,
            radius_mm=radius_mm,
            sweep_deg=90.0,
            boundary_tag=boundary_tag,
        )
        for idx in range(len(points))
    )
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="circle",
        segments=segments,
        points_mm=points,
        boundary_tags=(boundary_tag,) if boundary_tag else (),
    )


def _circle_loop_with_breakpoints(
    loop_id: str,
    radius_mm: float,
    angles_rad: list[float] | tuple[float, ...],
    boundary_tag: str | None = None,
) -> GeometryIRLoop:
    angles = _normalized_unique_angles(angles_rad)
    if len(angles) < 2:
        return _circle_loop(loop_id, radius_mm, boundary_tag)

    points = tuple(_point(radius_mm, angle) for angle in angles)
    center = GeometryIRPoint(0.0, 0.0)
    segments: list[GeometryIRSegment] = []
    for idx, angle in enumerate(angles):
        next_idx = (idx + 1) % len(angles)
        next_angle = angles[next_idx]
        if next_idx == 0:
            next_angle += 2 * math.pi
        segments.append(
            GeometryIRSegment(
                kind="arc",
                start=points[idx],
                end=points[next_idx],
                center=center,
                radius_mm=radius_mm,
                sweep_deg=math.degrees(next_angle - angle),
                boundary_tag=boundary_tag,
            )
        )
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="circle",
        segments=tuple(segments),
        points_mm=points,
        boundary_tags=(boundary_tag,) if boundary_tag else (),
    )


def _tapered_annular_loop(
    loop_id: str,
    inner_radius_mm: float,
    outer_radius_mm: float,
    inner_start_rad: float,
    inner_end_rad: float,
    outer_start_rad: float,
    outer_end_rad: float,
) -> GeometryIRLoop:
    inner_start = _point(inner_radius_mm, inner_start_rad)
    inner_end = _point(inner_radius_mm, inner_end_rad)
    outer_start = _point(outer_radius_mm, outer_start_rad)
    outer_end = _point(outer_radius_mm, outer_end_rad)
    center = GeometryIRPoint(0.0, 0.0)
    inner_sweep = _positive_angle_delta(inner_start_rad, inner_end_rad)
    outer_sweep = _positive_angle_delta(outer_start_rad, outer_end_rad)
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="arc_band",
        segments=(
            GeometryIRSegment(
                "arc",
                inner_start,
                inner_end,
                center,
                inner_radius_mm,
                math.degrees(inner_sweep),
            ),
            GeometryIRSegment("line", inner_end, outer_end),
            GeometryIRSegment(
                "arc",
                outer_end,
                outer_start,
                center,
                outer_radius_mm,
                -math.degrees(outer_sweep),
            ),
            GeometryIRSegment("line", outer_start, inner_start),
        ),
        points_mm=(inner_start, inner_end, outer_end, outer_start),
    )


def _arc_band_loop(
    loop_id: str,
    inner_radius_mm: float,
    outer_radius_mm: float,
    start_angle_rad: float,
    end_angle_rad: float,
) -> GeometryIRLoop:
    p_inner_start = _point(inner_radius_mm, start_angle_rad)
    p_inner_end = _point(inner_radius_mm, end_angle_rad)
    p_outer_start = _point(outer_radius_mm, start_angle_rad)
    p_outer_end = _point(outer_radius_mm, end_angle_rad)
    center = GeometryIRPoint(0.0, 0.0)
    sweep_deg = math.degrees(end_angle_rad - start_angle_rad)
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="arc_band",
        segments=(
            GeometryIRSegment("arc", p_outer_start, p_outer_end, center, outer_radius_mm, sweep_deg),
            GeometryIRSegment("line", p_outer_end, p_inner_end),
            GeometryIRSegment("arc", p_inner_end, p_inner_start, center, inner_radius_mm, -sweep_deg),
            GeometryIRSegment("line", p_inner_start, p_outer_start),
        ),
        points_mm=(p_outer_start, p_outer_end, p_inner_end, p_inner_start),
    )


def _polygon_loop(
    loop_id: str,
    points: tuple[tuple[float, float], ...],
) -> GeometryIRLoop:
    ir_points = tuple(GeometryIRPoint(float(x), float(y)) for x, y in points)
    segments = tuple(
        GeometryIRSegment("line", ir_points[idx], ir_points[(idx + 1) % len(ir_points)])
        for idx in range(len(ir_points))
    )
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="polygon",
        segments=segments,
        points_mm=ir_points,
    )


def _magnet_rect_points(mag) -> tuple[tuple[float, float], ...]:
    a1 = mag.center_angle_rad - mag.half_width_rad
    a2 = mag.center_angle_rad + mag.half_width_rad
    return (
        _polar_point(mag.inner_radius_mm, a1),
        _polar_point(mag.inner_radius_mm, a2),
        _polar_point(mag.outer_radius_mm, a2),
        _polar_point(mag.outer_radius_mm, a1),
    )


def _magnet_arc_band_loop(loop_id: str, mag) -> GeometryIRLoop:
    return _arc_band_loop(
        loop_id,
        mag.inner_radius_mm,
        mag.outer_radius_mm,
        mag.center_angle_rad - mag.half_width_rad,
        mag.center_angle_rad + mag.half_width_rad,
    )


def _magnet_arc_band_area(mag) -> float:
    sweep_rad = 2.0 * mag.half_width_rad
    return 0.5 * max(0.0, mag.outer_radius_mm**2 - mag.inner_radius_mm**2) * sweep_rad


def _tapered_annular_sector_area(
    inner_radius_mm: float,
    outer_radius_mm: float,
    inner_start_rad: float,
    inner_end_rad: float,
    outer_start_rad: float,
    outer_end_rad: float,
) -> float:
    """Exact area of a region bounded by two arcs (inner + outer) and two
    straight radial-ish lines connecting their endpoints.

    The IR was previously computing this as a flat chord-polygon, which
    matches Gmsh's arc-bounded triangulation only for narrow sectors. Wide
    sectors (4p6s SPM teeth ~30° tooth pitch) had a >5% area mismatch that
    tripped the post-mesh QA check at backend/gmsh_solver.py:868.

    Formula: polygon_area + outer_circular_segment - inner_circular_segment
    where each segment is the area between an arc and its chord. For a region
    that lives BETWEEN the two arcs (e.g. stator tooth, slot winding), the
    polygon over-counts by the inner segment (chord is closer to origin than
    inner arc) and under-counts by the outer segment (outer arc is farther
    from origin than its chord).
    """
    polygon_pts = (
        _polar_point(inner_radius_mm, inner_start_rad),
        _polar_point(inner_radius_mm, inner_end_rad),
        _polar_point(outer_radius_mm, outer_end_rad),
        _polar_point(outer_radius_mm, outer_start_rad),
    )
    polygon = _polygon_area(polygon_pts)
    inner_sweep = abs(inner_end_rad - inner_start_rad)
    outer_sweep = abs(outer_end_rad - outer_start_rad)
    inner_segment = 0.5 * inner_radius_mm**2 * (inner_sweep - math.sin(inner_sweep))
    outer_segment = 0.5 * outer_radius_mm**2 * (outer_sweep - math.sin(outer_sweep))
    return polygon - inner_segment + outer_segment


def _tooth_shoe_half_angles(
    body_inner_half_rad: float,
    body_outer_half_rad: float,
    bore_r: float,
    slot_outer_r: float,
    shoulder_r: float,
    overhang_mm: float,
    slot_pitch_rad: float,
    slot_opening_mm: float,
) -> tuple[float, float]:
    """Compute (bore_tip_half, shoulder_half) for a shoed stator tooth.

    The tooth body (without shoe) tapers from ``body_inner_half_rad`` at the
    bore to ``body_outer_half_rad`` at the slot-outer radius. The shoulder is
    sampled from that existing body taper. The bore tip then extends beyond the
    original bore-side body by ``overhang_mm / bore_r`` radians per side.

    The widened bore half-angle is clamped below ``slot_pitch_rad / 2`` so
    adjacent shoe tips never overlap (the post-shoe slot mouth stays
    non-negative). This mirrors the config-level validator in
    ``StatorConfig`` (``2 * overhang < slot_opening_mm``) but operates on
    the actual interpolated shoulder half-angle, which gives the shoe
    the exact bore-side mouth that the validator describes:
    ``slot_opening_mm - 2 * overhang_mm``.
    """
    radial_span = max(1e-9, slot_outer_r - bore_r)
    t = max(0.0, min(1.0, (shoulder_r - bore_r) / radial_span))
    shoulder_half = body_inner_half_rad + t * (
        body_outer_half_rad - body_inner_half_rad
    )
    bore_tip_half = body_inner_half_rad + overhang_mm / max(1e-9, bore_r)
    # Hard limit: adjacent shoe tips must not overlap.
    max_bore_half = max(shoulder_half, 0.5 * slot_pitch_rad - 1e-9)
    bore_tip_half = min(bore_tip_half, max_bore_half)
    # Slot-opening mm is accepted for API parity with the config validator
    # but the geometry clamp above is the authoritative overlap guard.
    _ = slot_opening_mm
    return bore_tip_half, shoulder_half


def _cross_xy(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _sub_xy(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def _xy(point: GeometryIRPoint) -> tuple[float, float]:
    return (point.x_mm, point.y_mm)


def _shoed_annular_loop(
    loop_id: str,
    bore_radius_mm: float,
    shoulder_radius_mm: float,
    outer_radius_mm: float,
    bore_start_rad: float,
    bore_end_rad: float,
    shoulder_start_rad: float,
    shoulder_end_rad: float,
    outer_start_rad: float,
    outer_end_rad: float,
) -> GeometryIRLoop:
    """Shoed tooth/slot loop with a sharp shoulder into the tapered body.

    Loop order (counter-clockwise, mirrors ``_tapered_annular_loop``):
    ``bore_tip_start -> bore_tip_end -> shoe_side_end -> shoulder_end ->
    outer_end -> outer_start -> shoulder_start -> shoe_side_start ->
    bore_tip_start``. The bore arc is the widened shoe tip; the short radial
    shoe sides make ``tooth_shoe_height_mm`` visible as a real ledge before
    the optional local arcs round into the tapered body lines.
    """
    bore_start = _point(bore_radius_mm, bore_start_rad)
    bore_end = _point(bore_radius_mm, bore_end_rad)
    shoe_side_end = _point(shoulder_radius_mm, bore_end_rad)
    shoulder_end = _point(shoulder_radius_mm, shoulder_end_rad)
    outer_end = _point(outer_radius_mm, outer_end_rad)
    outer_start = _point(outer_radius_mm, outer_start_rad)
    shoulder_start = _point(shoulder_radius_mm, shoulder_start_rad)
    shoe_side_start = _point(shoulder_radius_mm, bore_start_rad)
    center = GeometryIRPoint(0.0, 0.0)
    bore_sweep = _positive_angle_delta(bore_start_rad, bore_end_rad)
    outer_sweep = _positive_angle_delta(outer_start_rad, outer_end_rad)
    segments: list[GeometryIRSegment] = []
    points: list[GeometryIRPoint] = [bore_start]

    def add_segment(segment: GeometryIRSegment) -> None:
        segments.append(segment)
        points.append(segment.end)

    add_segment(
        GeometryIRSegment(
            "arc",
            bore_start,
            bore_end,
            center,
            bore_radius_mm,
            math.degrees(bore_sweep),
        )
    )
    add_segment(GeometryIRSegment("line", bore_end, shoe_side_end))
    add_segment(GeometryIRSegment("line", shoe_side_end, shoulder_end))
    add_segment(GeometryIRSegment("line", shoulder_end, outer_end))
    add_segment(
        GeometryIRSegment(
            "arc",
            outer_end,
            outer_start,
            center,
            outer_radius_mm,
            -math.degrees(outer_sweep),
        )
    )
    add_segment(GeometryIRSegment("line", outer_start, shoulder_start))
    add_segment(GeometryIRSegment("line", shoulder_start, shoe_side_start))
    add_segment(GeometryIRSegment("line", shoe_side_start, bore_start))
    if points[-1] == points[0]:
        points.pop()

    return GeometryIRLoop(
        loop_id=loop_id,
        kind="arc_band",
        segments=tuple(segments),
        points_mm=tuple(points),
    )


def _loop_area_mm2(loop: GeometryIRLoop) -> float:
    """Signed line/arc loop area, returned as a positive physical area."""
    total = 0.0
    for segment in loop.segments:
        start = _xy(segment.start)
        end = _xy(segment.end)
        if segment.kind == "line":
            total += 0.5 * _cross_xy(start, end)
            continue

        center = segment.center
        radius = segment.radius_mm
        if center is None or radius is None or radius <= 0.0:
            total += 0.5 * _cross_xy(start, end)
            continue
        center_xy = _xy(center)
        if segment.sweep_deg is not None:
            sweep_rad = math.radians(segment.sweep_deg)
        else:
            start_angle = math.atan2(start[1] - center_xy[1], start[0] - center_xy[0])
            end_angle = math.atan2(end[1] - center_xy[1], end[0] - center_xy[0])
            sweep_rad = end_angle - start_angle
        total += 0.5 * (
            _cross_xy(center_xy, _sub_xy(end, start))
            + radius**2 * sweep_rad
        )
    return abs(total)


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    if len(points) < 3:
        return 0.0
    twice_area = 0.0
    for idx, (x1, y1) in enumerate(points):
        x2, y2 = points[(idx + 1) % len(points)]
        twice_area += x1 * y2 - x2 * y1
    return abs(twice_area) * 0.5


def _point(radius_mm: float, angle_rad: float) -> GeometryIRPoint:
    x, y = _polar_point(radius_mm, angle_rad)
    return GeometryIRPoint(x, y)


def _polar_point(radius_mm: float, angle_rad: float) -> tuple[float, float]:
    return (
        radius_mm * math.cos(angle_rad),
        radius_mm * math.sin(angle_rad),
    )


def _unit_vector_deg(angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg)
    return (math.cos(angle_rad), math.sin(angle_rad))


def _magnet_edge_angles(geom: MotorGeometry) -> list[float]:
    edges: list[float] = []
    for magnet in geom.magnets:
        edges.extend(
            (
                magnet.center_angle_rad - magnet.half_width_rad,
                magnet.center_angle_rad + magnet.half_width_rad,
            )
        )
    return edges


def _normalized_unique_angles(angles_rad: list[float] | tuple[float, ...]) -> list[float]:
    normalized = sorted(angle % (2 * math.pi) for angle in angles_rad if math.isfinite(angle))
    out: list[float] = []
    for angle in normalized:
        if out and abs(angle - out[-1]) < 1.0e-10:
            continue
        out.append(angle)
    if len(out) > 1 and abs((out[0] + 2 * math.pi) - out[-1]) < 1.0e-10:
        out.pop()
    return out


def _positive_angle_delta(start_rad: float, end_rad: float) -> float:
    delta = (end_rad - start_rad) % (2 * math.pi)
    if delta <= 1.0e-12:
        delta = 2 * math.pi
    return delta


def _angle_delta(left_rad: float, right_rad: float) -> float:
    delta = right_rad - left_rad
    while delta <= 0:
        delta += 2 * math.pi
    return delta
