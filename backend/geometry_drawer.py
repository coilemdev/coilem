"""Shared motor geometry construction for previews and mesh producers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.excitation import (
    IDEAL_SIX_STEP_120,
    phase_current_sample_dict,
    resolve_phase_current_sample,
    terminal_to_slot_current_scale,
)
from backend.models import MotorConfig
from backend.winding_utils import distributed_layer_tag, distributed_slot_assignment

# Narrowest slot body the drawer will emit. Past this the tooth has eaten the
# slot and the floor engages, so the drawn geometry stops matching the fields —
# validation rejects a tooth that wide rather than letting it degenerate.
MIN_SLOT_BODY_WIDTH_MM = 0.5


@dataclass
class MagnetPlacement:
    """Describes one magnet's position and orientation."""
    pole_index: int
    center_angle_rad: float
    polarity: str  # "N" or "S"
    # IPM: rectangular pocket inside rotor
    radial_center_mm: float
    half_width_rad: float
    inner_radius_mm: float
    outer_radius_mm: float
    # Magnetization direction (degrees, FEMM convention)
    magnetization_angle_deg: float
    shape: str = "arc_rect"
    side: str | None = None
    corners_mm: tuple[tuple[float, float], ...] | None = None
    pocket_corners_mm: tuple[tuple[float, float], ...] | None = None
    pocket_label_mm: tuple[float, float] | None = None
    # How much of the requested magnet_width_mm had to be cut so the slab
    # stays inside the rotor (V-shape outer-bridge fit). None when it fits.
    length_clamped_mm: float | None = None


@dataclass
class RotorAirPocketPlacement:
    """Describes one non-magnetic rotor pocket around buried magnets."""

    pocket_index: int
    pole_index: int
    corners_mm: tuple[tuple[float, float], ...]
    magnet_indices: tuple[int, ...] = ()
    label_mm: tuple[float, float] | None = None


@dataclass
class SlotPlacement:
    """Describes one stator slot region."""
    slot_index: int
    center_angle_rad: float
    inner_radius_mm: float
    outer_radius_mm: float
    half_width_rad: float
    phase: str  # "A", "B", "C"
    direction: str  # "in", "out"
    layer: int = 1
    current_density_A_mm2: float = 0.0
    inner_half_width_rad: float | None = None
    outer_half_width_rad: float | None = None
    mouth_width_mm: float | None = None
    body_width_mm: float | None = None

    def half_width_at_radius(self, radius_mm: float) -> float:
        """Return the slot half-angle at a radius inside the tooth block."""
        if self.inner_half_width_rad is None or self.outer_half_width_rad is None:
            return self.half_width_rad

        radial_span = self.outer_radius_mm - self.inner_radius_mm
        if radial_span <= 1e-9:
            return self.inner_half_width_rad

        t = (radius_mm - self.inner_radius_mm) / radial_span
        t = max(0.0, min(1.0, t))
        return (
            self.inner_half_width_rad
            + t * (self.outer_half_width_rad - self.inner_half_width_rad)
        )

    def edge_angles_at_radius(self, radius_mm: float) -> tuple[float, float]:
        """Return left/right slot wall angles at the supplied radius."""
        half_width = self.half_width_at_radius(radius_mm)
        return (
            self.center_angle_rad - half_width,
            self.center_angle_rad + half_width,
        )

    def edge_points(self) -> tuple[tuple[float, float], ...]:
        """Return inner-left, inner-right, outer-right, outer-left points."""
        inner_left, inner_right = self.edge_angles_at_radius(self.inner_radius_mm)
        outer_left, outer_right = self.edge_angles_at_radius(self.outer_radius_mm)
        return (
            (
                self.inner_radius_mm * math.cos(inner_left),
                self.inner_radius_mm * math.sin(inner_left),
            ),
            (
                self.inner_radius_mm * math.cos(inner_right),
                self.inner_radius_mm * math.sin(inner_right),
            ),
            (
                self.outer_radius_mm * math.cos(outer_right),
                self.outer_radius_mm * math.sin(outer_right),
            ),
            (
                self.outer_radius_mm * math.cos(outer_left),
                self.outer_radius_mm * math.sin(outer_left),
            ),
        )

    def represented_area_mm2(self) -> float:
        """Approximate the FEMM slot block area represented by this placement."""
        radial_span = max(0.0, self.outer_radius_mm - self.inner_radius_mm)
        if self.mouth_width_mm is not None and self.body_width_mm is not None:
            return 0.5 * (self.mouth_width_mm + self.body_width_mm) * radial_span
        mean_r = 0.5 * (self.inner_radius_mm + self.outer_radius_mm)
        return 2.0 * mean_r * self.half_width_rad * radial_span


@dataclass
class MotorGeometry:
    """Complete motor geometry description computed from MotorConfig."""
    # Radii
    stator_OD_r: float
    stator_ID_r: float
    rotor_OD_r: float
    shaft_r: float
    airgap_mm: float

    # Magnets
    magnets: list[MagnetPlacement] = field(default_factory=list)
    rotor_air_pockets: list[RotorAirPocketPlacement] = field(default_factory=list)

    # Slots (with winding assignment)
    slots: list[SlotPlacement] = field(default_factory=list)

    # Derived
    pole_count: int = 8
    slot_count: int = 48
    topology: str = "IPM"


def compute_geometry(config: MotorConfig) -> MotorGeometry:
    """Compute motor geometry from configuration.

    This is the single source of truth for magnet positions, slot positions,
    and winding assignments. Both preview.py and solver.py should consume this.

    Args:
        config: Motor configuration

    Returns:
        MotorGeometry with all placement data
    """
    stator = config.stator
    rotor = config.rotor

    stator_OD_r = stator.OD_mm / 2
    stator_ID_r = stator.ID_mm / 2
    rotor_OD_r = rotor.OD_mm / 2
    shaft_r = rotor.ID_mm / 2 if rotor.ID_mm is not None else rotor_OD_r * 0.2
    airgap_mm = stator_ID_r - rotor_OD_r
    slotless_stator = False

    # ── Magnet placements ────────────────────────────────────────────────
    if (
        config.topology == "IPM"
        and getattr(rotor, "ipm_topology", "flat_buried") == "pyleecan_holem50"
    ):
        magnets, rotor_air_pockets = compute_pyleecan_holem50_placements(config)
    else:
        magnets = _compute_magnet_placements(config)
        rotor_air_pockets = []

    # ── Slot placements with winding assignment ──────────────────────────
    slots = [] if slotless_stator else _compute_slot_placements(config)

    return MotorGeometry(
        stator_OD_r=stator_OD_r,
        stator_ID_r=stator_ID_r,
        rotor_OD_r=rotor_OD_r,
        shaft_r=shaft_r,
        airgap_mm=airgap_mm,
        magnets=magnets,
        rotor_air_pockets=rotor_air_pockets,
        slots=slots,
        pole_count=rotor.pole_count,
        slot_count=stator.slot_count,
        topology=config.topology,
    )


def magnet_radial_center_mm(config: MotorConfig) -> float:
    """Return the radial centerline used to place a one-piece magnet.

    SPM magnets ride on the rotor surface, so the width is taken at the middle of
    the magnet's radial span — *outside* the rotor core. Straight flat-buried IPM
    magnets sit in a rectangular pocket under the bridge, so their centre is
    *inside* it.  Their tangential pocket corners are farther from the shaft than
    the outer-face midpoint; account for that curvature so ``bridge_thickness_mm``
    remains the minimum radial steel bridge and the pocket cannot pierce the rotor
    OD. Fit validation measures at this same centerline so its pole-pitch budget
    stays aligned with the geometry builder.

    Not meaningful for V-shape, where ``magnet_width_mm`` is a slab length rather
    than an arc; that topology has its own pocket/bridge containment checks.
    """

    rotor = config.rotor
    if config.topology == "IPM":
        ipm_topology = getattr(rotor, "ipm_topology", "flat_buried")
        flat_shape = getattr(rotor, "flat_buried_magnet_shape", "straight")
        if ipm_topology == "flat_buried" and flat_shape != "legacy_arc":
            clearance = getattr(rotor, "pocket_clearance_mm", 0.0) or 0.0
            pocket_half_width = rotor.magnet_width_mm / 2 + clearance
            pocket_half_depth = rotor.magnet_thickness_mm / 2 + clearance
            corner_radius = rotor.OD_mm / 2 - rotor.bridge_thickness_mm
            center_outer_face_radius = math.sqrt(
                max(0.0, corner_radius**2 - pocket_half_width**2)
            )
            return center_outer_face_radius - pocket_half_depth
        return (
            rotor.OD_mm / 2
            - rotor.bridge_thickness_mm
            - (getattr(rotor, "pocket_clearance_mm", 0.0) or 0.0)
            - rotor.magnet_thickness_mm / 2
        )
    return rotor.OD_mm / 2 + rotor.magnet_thickness_mm / 2


def _compute_magnet_placements(config: MotorConfig) -> list[MagnetPlacement]:
    """Compute magnet placements for all poles."""
    rotor = config.rotor
    if config.topology == "IPM":
        ipm_topology = getattr(rotor, "ipm_topology", "flat_buried")
        flat_shape = getattr(rotor, "flat_buried_magnet_shape", "straight")
        if ipm_topology == "flat_buried" and flat_shape != "legacy_arc":
            return compute_flat_buried_magnet_placements(config)
        if ipm_topology == "v_shape":
            return compute_v_shape_magnet_placements(config)

    pole_count = rotor.pole_count
    pole_pitch_rad = 2 * math.pi / pole_count
    magnet_thickness = rotor.magnet_thickness_mm
    magnet_width = rotor.magnet_width_mm
    ipm_angle_offset_rad = math.radians(
        getattr(rotor, "magnet_angle_deg", 0.0) or 0.0
    )
    # One definition of the width-bearing radius, shared with validation.
    radial_center = magnet_radial_center_mm(config)

    magnets = []

    for pole_idx in range(pole_count):
        angle_rad = pole_idx * pole_pitch_rad
        if config.topology == "IPM":
            angle_rad += ipm_angle_offset_rad
        polarity = "N" if pole_idx % 2 == 0 else "S"

        if config.topology == "IPM":
            # IPM: rectangular pockets inside rotor
            inner_r = radial_center - magnet_thickness / 2
            outer_r = radial_center + magnet_thickness / 2
        else:
            # SPM: arc segments on rotor surface
            inner_r = rotor.OD_mm / 2
            outer_r = rotor.OD_mm / 2 + magnet_thickness

        half_width_rad = (magnet_width / 2) / radial_center if radial_center > 0 else 0

        # Magnetization angle: radially outward for N, radially inward for S
        # FEMM convention: 0 deg = +x, 90 deg = +y
        mag_angle_deg = math.degrees(angle_rad)
        if polarity == "S":
            mag_angle_deg = (mag_angle_deg + 180) % 360

        magnets.append(MagnetPlacement(
            pole_index=pole_idx,
            center_angle_rad=angle_rad,
            polarity=polarity,
            radial_center_mm=radial_center,
            half_width_rad=half_width_rad,
            inner_radius_mm=inner_r,
            outer_radius_mm=outer_r,
            magnetization_angle_deg=mag_angle_deg,
        ))

    return magnets


def compute_flat_buried_magnet_placements(config: MotorConfig) -> list[MagnetPlacement]:
    """Compute one straight tangential magnet bar per flat-IPM pole.

    ``magnet_width_mm`` is the physical length of the rectangular bar along the
    local tangential axis; ``magnet_thickness_mm`` is its radial thickness.  The
    optional clearance produces a larger rectangular air pocket around the bar.
    This keeps Design preview, Gmsh, FEMM, Elmer, Magneto2D, thermal geometry,
    and exports on the same shape instead of drawing a flat bar while solving an
    annular sector.
    """
    rotor = config.rotor
    pole_pitch_rad = 2 * math.pi / rotor.pole_count
    magnet_width = rotor.magnet_width_mm
    magnet_thickness = rotor.magnet_thickness_mm
    pocket_clearance = getattr(rotor, "pocket_clearance_mm", 0.0) or 0.0
    angle_offset_rad = math.radians(
        getattr(rotor, "magnet_angle_deg", 0.0) or 0.0
    )
    radial_center = magnet_radial_center_mm(config)
    magnets: list[MagnetPlacement] = []

    for pole_idx in range(rotor.pole_count):
        pole_angle = pole_idx * pole_pitch_rad + angle_offset_rad
        polarity = "N" if pole_idx % 2 == 0 else "S"
        radial = (math.cos(pole_angle), math.sin(pole_angle))
        tangential = (-math.sin(pole_angle), math.cos(pole_angle))
        center = (radial_center * radial[0], radial_center * radial[1])
        corners = _ensure_counterclockwise(
            _oriented_rectangle_corners(
                center,
                tangential,
                radial,
                magnet_width,
                magnet_thickness,
            )
        )
        pocket_corners = (
            _ensure_counterclockwise(
                _oriented_rectangle_corners(
                    center,
                    tangential,
                    radial,
                    magnet_width + 2 * pocket_clearance,
                    magnet_thickness + 2 * pocket_clearance,
                )
            )
            if pocket_clearance > 0
            else None
        )
        pocket_label = (
            (
                center[0]
                + radial[0] * (magnet_thickness / 2 + pocket_clearance / 2),
                center[1]
                + radial[1] * (magnet_thickness / 2 + pocket_clearance / 2),
            )
            if pocket_clearance > 0
            else None
        )
        envelope = pocket_corners if pocket_corners is not None else corners
        min_r, max_r = _polygon_radius_bounds(envelope)
        half_width = _polygon_half_angle(envelope, pole_angle)
        magnetization_angle_deg = math.degrees(pole_angle) % 360
        if polarity == "S":
            magnetization_angle_deg = (magnetization_angle_deg + 180) % 360

        magnets.append(
            MagnetPlacement(
                pole_index=pole_idx,
                center_angle_rad=pole_angle,
                polarity=polarity,
                radial_center_mm=radial_center,
                half_width_rad=half_width,
                inner_radius_mm=min_r,
                outer_radius_mm=max_r,
                magnetization_angle_deg=magnetization_angle_deg,
                shape="polygon",
                corners_mm=corners,
                pocket_corners_mm=pocket_corners,
                pocket_label_mm=pocket_label,
            )
        )

    return magnets


def compute_v_shape_magnet_placements(config: MotorConfig) -> list[MagnetPlacement]:
    """Compute paired slab magnets for a V-shape IPM rotor.

    The V apex is measured inward from the rotor OD along the pole centerline.
    ``magnet_width_mm`` is interpreted as slab length, and
    ``magnet_thickness_mm`` as slab thickness normal to the slab axis.
    """
    rotor = config.rotor
    pole_count = rotor.pole_count
    pole_pitch_rad = 2 * math.pi / pole_count
    rotor_outer_r = rotor.OD_mm / 2
    magnet_length = rotor.magnet_width_mm
    magnet_thickness = rotor.magnet_thickness_mm
    pocket_clearance = getattr(rotor, "pocket_clearance_mm", 0.0) or 0.0
    inner_web = getattr(rotor, "inner_web_thickness_mm", 0.0) or 0.0
    outer_bridge = getattr(rotor, "outer_bridge_thickness_mm", 0.0) or 0.0
    v_depth = getattr(rotor, "v_depth_mm", 0.0) or 0.0
    v_half_angle_rad = math.radians((getattr(rotor, "v_angle_deg", 0.0) or 0.0) / 2)
    angle_offset_rad = math.radians(getattr(rotor, "magnet_angle_deg", 0.0) or 0.0)
    apex_r = rotor_outer_r - v_depth

    magnets: list[MagnetPlacement] = []

    for pole_idx in range(pole_count):
        pole_angle = pole_idx * pole_pitch_rad + angle_offset_rad
        polarity = "N" if pole_idx % 2 == 0 else "S"
        radial = (math.cos(pole_angle), math.sin(pole_angle))
        tangential = (-math.sin(pole_angle), math.cos(pole_angle))
        apex = (apex_r * radial[0], apex_r * radial[1])

        for sign, side in ((1.0, "left"), (-1.0, "right")):
            axis = _unit(
                (
                    math.cos(v_half_angle_rad) * radial[0]
                    + sign * math.sin(v_half_angle_rad) * tangential[0],
                    math.cos(v_half_angle_rad) * radial[1]
                    + sign * math.sin(v_half_angle_rad) * tangential[1],
                )
            )
            # Normal with positive radial component. This gives each half of
            # the V a distinct magnetization vector while pointing N poles
            # generally toward the airgap.
            normal = _unit(
                (
                    math.sin(v_half_angle_rad) * radial[0]
                    - sign * math.cos(v_half_angle_rad) * tangential[0],
                    math.sin(v_half_angle_rad) * radial[1]
                    - sign * math.cos(v_half_angle_rad) * tangential[1],
                )
            )
            inner_center = (
                apex[0] + sign * (inner_web / 2) * tangential[0],
                apex[1] + sign * (inner_web / 2) * tangential[1],
            )
            # The pocket (or the bare magnet when there is no clearance) must
            # stay below the outer bridge line, otherwise the slab pokes
            # through the rotor surface and every downstream consumer gets a
            # self-intersecting rotor. Solve |far_corner(L)| = fit_radius for
            # both far corners and clamp the slab length to the tighter root;
            # validation still reports the misfit via length_clamped_mm.
            fit_radius = rotor_outer_r - outer_bridge
            effective_length = magnet_length
            length_clamped: float | None = None
            if fit_radius > 0:
                half_t = magnet_thickness / 2 + pocket_clearance
                max_length = magnet_length
                for corner_sign in (1.0, -1.0):
                    ax = (
                        inner_center[0]
                        + pocket_clearance * axis[0]
                        + corner_sign * half_t * normal[0]
                    )
                    ay = (
                        inner_center[1]
                        + pocket_clearance * axis[1]
                        + corner_sign * half_t * normal[1]
                    )
                    along = ax * axis[0] + ay * axis[1]
                    disc = along * along - (ax * ax + ay * ay) + fit_radius * fit_radius
                    root = -along + math.sqrt(disc) if disc > 0 else 0.0
                    max_length = min(max_length, root)
                if max_length < magnet_length - 1e-9:
                    effective_length = max(max_length, 0.5)
                    length_clamped = magnet_length - effective_length
            center = (
                inner_center[0] + (effective_length / 2) * axis[0],
                inner_center[1] + (effective_length / 2) * axis[1],
            )
            corners = _oriented_rectangle_corners(
                center, axis, normal, effective_length, magnet_thickness
            )
            pocket_corners = (
                _oriented_rectangle_corners(
                    center,
                    axis,
                    normal,
                    effective_length + 2 * pocket_clearance,
                    magnet_thickness + 2 * pocket_clearance,
                )
                if pocket_clearance > 0
                else None
            )
            pocket_label = (
                (
                    center[0] + normal[0] * (magnet_thickness / 2 + pocket_clearance / 2),
                    center[1] + normal[1] * (magnet_thickness / 2 + pocket_clearance / 2),
                )
                if pocket_clearance > 0
                else None
            )
            min_r, max_r = _polygon_radius_bounds(
                pocket_corners if pocket_corners is not None else corners
            )
            center_angle = math.atan2(center[1], center[0])
            radial_center = math.hypot(center[0], center[1])
            half_width = _polygon_half_angle(
                pocket_corners if pocket_corners is not None else corners,
                center_angle,
            )
            mag_angle_deg = math.degrees(math.atan2(normal[1], normal[0])) % 360
            if polarity == "S":
                mag_angle_deg = (mag_angle_deg + 180) % 360

            magnets.append(
                MagnetPlacement(
                    pole_index=pole_idx,
                    center_angle_rad=center_angle,
                    polarity=polarity,
                    radial_center_mm=radial_center,
                    half_width_rad=half_width,
                    inner_radius_mm=min_r,
                    outer_radius_mm=max_r,
                    magnetization_angle_deg=mag_angle_deg,
                    shape="polygon",
                    side=side,
                    corners_mm=corners,
                    pocket_corners_mm=pocket_corners,
                    pocket_label_mm=pocket_label,
                    length_clamped_mm=length_clamped,
                )
            )

    return magnets


def compute_pyleecan_holem50_placements(
    config: MotorConfig,
) -> tuple[list[MagnetPlacement], list[RotorAirPocketPlacement]]:
    """Compute Pyleecan HoleM50 magnet and pocket placement polygons.

    This mirrors Pyleecan's HoleM50 point construction for the Prius fixture.
    The generated topology has two magnets and one enclosing air pocket per
    pole when W1=0, matching Toyota_Prius.json.
    """

    rotor = config.rotor
    pole_count = rotor.pole_count
    pole_pitch_rad = 2 * math.pi / pole_count
    angle_offset_rad = math.radians(
        getattr(rotor, "magnet_angle_deg", 0.0) or 0.0
    )
    base = _pyleecan_holem50_base_points(rotor)
    base_air_pockets = _pyleecan_holem50_air_pockets(base, rotor)
    base_magnets = (
        (
            "right",
            _ensure_counterclockwise(
                tuple(_complex_point(base[key]) for key in ("Z3", "Z4", "Z5", "Z6", "Z8b", "Z8c"))
            ),
            ("Z8b", "Z8c"),
            ("Z5", "Z4"),
        ),
        (
            "left",
            _ensure_counterclockwise(
                tuple(_complex_point(base[key]) for key in ("Z3s", "Z4s", "Z5s", "Z6s", "Z8bs", "Z8cs"))
            ),
            ("Z8bs", "Z8cs"),
            ("Z5s", "Z4s"),
        ),
    )

    magnets: list[MagnetPlacement] = []
    pockets: list[RotorAirPocketPlacement] = []

    for pole_idx in range(pole_count):
        pole_angle = pole_idx * pole_pitch_rad + angle_offset_rad
        polarity = "N" if pole_idx % 2 == 0 else "S"
        magnet_indices: list[int] = []

        for side, base_corners, top_keys, bottom_keys in base_magnets:
            corners = _ensure_counterclockwise(
                _rotate_polygon(base_corners, pole_angle)
            )
            center = _polygon_centroid(corners)
            center_angle = math.atan2(center[1], center[0])
            radial_center = math.hypot(center[0], center[1])
            min_r, max_r = _polygon_radius_bounds(corners)
            top_mid = _rotate_point_xy(
                _midpoint(
                    _complex_point(base[top_keys[0]]),
                    _complex_point(base[top_keys[1]]),
                ),
                pole_angle,
            )
            bottom_mid = _rotate_point_xy(
                _midpoint(
                    _complex_point(base[bottom_keys[0]]),
                    _complex_point(base[bottom_keys[1]]),
                ),
                pole_angle,
            )
            normal = _unit(
                (
                    top_mid[0] - bottom_mid[0],
                    top_mid[1] - bottom_mid[1],
                )
            )
            mag_angle_deg = math.degrees(math.atan2(normal[1], normal[0])) % 360
            if polarity == "S":
                mag_angle_deg = (mag_angle_deg + 180) % 360

            magnet_indices.append(len(magnets))
            magnets.append(
                MagnetPlacement(
                    pole_index=pole_idx,
                    center_angle_rad=center_angle,
                    polarity=polarity,
                    radial_center_mm=radial_center,
                    half_width_rad=_polygon_half_angle(corners, center_angle),
                    inner_radius_mm=min_r,
                    outer_radius_mm=max_r,
                    magnetization_angle_deg=mag_angle_deg,
                    shape="polygon",
                    side=side,
                    corners_mm=corners,
                )
            )

        _ = magnet_indices
        for base_pocket in base_air_pockets:
            pocket_corners = _ensure_counterclockwise(
                _rotate_polygon(base_pocket, pole_angle)
            )
            pockets.append(
                RotorAirPocketPlacement(
                    pocket_index=len(pockets),
                    pole_index=pole_idx,
                    corners_mm=pocket_corners,
                    label_mm=_polygon_centroid(pocket_corners),
                )
            )

    return magnets, pockets


def point_in_polygon(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Return true when a point is inside a polygon using ray casting."""
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        return (1.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def _oriented_rectangle_corners(
    center: tuple[float, float],
    axis: tuple[float, float],
    normal: tuple[float, float],
    length_mm: float,
    thickness_mm: float,
) -> tuple[tuple[float, float], ...]:
    half_l = length_mm / 2
    half_t = thickness_mm / 2
    return (
        (
            center[0] - axis[0] * half_l - normal[0] * half_t,
            center[1] - axis[1] * half_l - normal[1] * half_t,
        ),
        (
            center[0] + axis[0] * half_l - normal[0] * half_t,
            center[1] + axis[1] * half_l - normal[1] * half_t,
        ),
        (
            center[0] + axis[0] * half_l + normal[0] * half_t,
            center[1] + axis[1] * half_l + normal[1] * half_t,
        ),
        (
            center[0] - axis[0] * half_l + normal[0] * half_t,
            center[1] - axis[1] * half_l + normal[1] * half_t,
        ),
    )


def _pyleecan_holem50_base_points(rotor) -> dict[str, complex]:
    r_ext = rotor.OD_mm / 2
    zh = rotor.pole_count
    w0 = float(getattr(rotor, "holem50_w0_mm", 42.0))
    w1 = float(getattr(rotor, "holem50_w1_mm", 0.0))
    w2 = float(getattr(rotor, "holem50_w2_mm", 0.0))
    w3 = float(getattr(rotor, "holem50_w3_mm", 14.0))
    w4 = float(getattr(rotor, "holem50_w4_mm", rotor.magnet_width_mm))
    h0 = float(getattr(rotor, "holem50_h0_mm", 10.96))
    h1 = float(getattr(rotor, "holem50_h1_mm", 1.5))
    h2 = float(getattr(rotor, "holem50_h2_mm", 1.0))
    h3 = float(getattr(rotor, "holem50_h3_mm", rotor.magnet_thickness_mm))
    h4 = float(getattr(rotor, "holem50_h4_mm", 0.0))

    pocket_arc_r = r_ext - h1
    alpham = 2 * math.asin(w0 / (2 * pocket_arc_r))
    harc = pocket_arc_r * (1 - math.cos(alpham / 2))
    gammam = math.atan((h0 - h1 - harc) / (w0 / 2 - w1 / 2))
    hssp = math.pi / zh
    x78 = (h3 - h2) / math.cos(gammam)

    z9 = complex(r_ext - harc - h1, -w0 / 2)
    z8 = complex(r_ext - h0, -w1 / 2)
    z7 = complex(r_ext - h0 - x78, -w1 / 2)
    z1 = pocket_arc_r * _complex_rot(-hssp + math.asin(w3 / (2 * pocket_arc_r)))
    z11 = (z1 * _complex_rot(hssp) + h4) * _complex_rot(-hssp)
    z10 = (z9 * _complex_rot(hssp) + h4) * _complex_rot(-hssp)

    z8a = complex(0.0, -(h3 - h2))
    z8b = complex(w2, 0.0)
    z8c = complex(w2 + w4, 0.0)
    z5 = z8b + complex(0.0, -h3)
    z4 = z8c + complex(0.0, -h3)
    z6 = z5 + complex(0.0, h2)
    z3 = z4 + complex(0.0, h2)
    mag_rotation = math.atan2((z9 - z8).imag, (z9 - z8).real)
    rotated = [
        point * _complex_rot(mag_rotation) + z8
        for point in (z8a, z8b, z6, z5, z4, z3, z8c)
    ]
    z8a, z8b, z6, z5, z4, z3, z8c = rotated

    z3r = z3 * _complex_rot(hssp)
    z1r = z1 * _complex_rot(hssp)
    z6r = z6 * _complex_rot(hssp)
    direction = z6r - z3r
    numerator = (z3r - z1r).imag
    if abs(direction.imag) <= 1.0e-12:
        z2_shift = h3 - h2
    else:
        z2_shift = numerator * direction.real / direction.imag - (z3r - z1r).real
    z2 = (z1r - z2_shift) * _complex_rot(-hssp)

    points = {
        "Z1": z1,
        "Z2": z2,
        "Z3": z3,
        "Z4": z4,
        "Z5": z5,
        "Z6": z6,
        "Z7": z7,
        "Z8": z8,
        "Z9": z9,
        "Z10": z10,
        "Z11": z11,
        "Z8a": z8a,
        "Z8b": z8b,
        "Z8c": z8c,
    }
    for key, value in list(points.items()):
        points[f"{key}s"] = value.conjugate()
    return points


def _pyleecan_holem50_air_pockets(
    points: dict[str, complex],
    rotor,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Return the HoleM50 W1=0 air surfaces S1, S7, and S4."""

    h4 = float(getattr(rotor, "holem50_h4_mm", 0.0))
    w2 = float(getattr(rotor, "holem50_w2_mm", 0.0))
    arc_r = rotor.OD_mm / 2 - float(getattr(rotor, "holem50_h1_mm", 1.5))

    def add_key(out: list[tuple[float, float]], key: str) -> None:
        point = _complex_point(points[key])
        if not out or _point_distance(out[-1], point) > 1.0e-9:
            out.append(point)

    s1: list[tuple[float, float]] = []
    for key in ("Z1", "Z2", "Z3", "Z8c", "Z9"):
        add_key(s1, key)
    if h4 > 0:
        add_key(s1, "Z10")
        _append_circular_arc(s1, _complex_point(points["Z10"]), _complex_point(points["Z11"]), arc_r)
        add_key(s1, "Z1")
    else:
        _append_circular_arc(s1, _complex_point(points["Z9"]), _complex_point(points["Z1"]), arc_r)

    s7: list[tuple[float, float]] = []
    for key in ("Z6", "Z7", "Z6s", "Z8bs"):
        add_key(s7, key)
    if w2 > 0:
        add_key(s7, "Z8s")
    add_key(s7, "Z8b")

    s4: list[tuple[float, float]] = []
    for key in ("Z1s", "Z2s", "Z3s", "Z8cs", "Z9s"):
        add_key(s4, key)
    if h4 > 0:
        add_key(s4, "Z10s")
        _append_circular_arc(
            s4,
            _complex_point(points["Z10s"]),
            _complex_point(points["Z11s"]),
            arc_r,
            clockwise=False,
        )
        add_key(s4, "Z1s")
    else:
        _append_circular_arc(
            s4,
            _complex_point(points["Z9s"]),
            _complex_point(points["Z1s"]),
            arc_r,
            clockwise=False,
        )

    return (
        _ensure_counterclockwise(_dedupe_polygon(tuple(s1))),
        _ensure_counterclockwise(_dedupe_polygon(tuple(s7))),
        _ensure_counterclockwise(_dedupe_polygon(tuple(s4))),
    )


def _complex_rot(angle_rad: float) -> complex:
    return complex(math.cos(angle_rad), math.sin(angle_rad))


def _complex_point(point: complex) -> tuple[float, float]:
    return (float(point.real), float(point.imag))


def _point_distance(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _midpoint(
    left: tuple[float, float],
    right: tuple[float, float],
) -> tuple[float, float]:
    return ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)


def _rotate_point_xy(
    point: tuple[float, float],
    angle_rad: float,
) -> tuple[float, float]:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return (point[0] * c - point[1] * s, point[0] * s + point[1] * c)


def _rotate_polygon(
    polygon: tuple[tuple[float, float], ...],
    angle_rad: float,
) -> tuple[tuple[float, float], ...]:
    if abs(angle_rad) <= 1.0e-12:
        return polygon
    return tuple(_rotate_point_xy(point, angle_rad) for point in polygon)


def _append_circular_arc(
    points: list[tuple[float, float]],
    start: tuple[float, float],
    end: tuple[float, float],
    radius_mm: float,
    *,
    clockwise: bool = True,
    max_step_deg: float = 1.0,
) -> None:
    start_angle = math.atan2(start[1], start[0])
    end_angle = math.atan2(end[1], end[0])
    if clockwise:
        while end_angle >= start_angle:
            end_angle -= 2.0 * math.pi
    else:
        while end_angle <= start_angle:
            end_angle += 2.0 * math.pi
    delta = end_angle - start_angle
    steps = max(1, int(math.ceil(abs(math.degrees(delta)) / max_step_deg)))
    for step in range(1, steps + 1):
        angle = start_angle + delta * step / steps
        point = (radius_mm * math.cos(angle), radius_mm * math.sin(angle))
        if not points or _point_distance(points[-1], point) > 1.0e-9:
            points.append(point)


def _dedupe_polygon(
    polygon: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    out: list[tuple[float, float]] = []
    for point in polygon:
        if out and _point_distance(out[-1], point) <= 1.0e-9:
            continue
        out.append(point)
    if len(out) > 1 and _point_distance(out[0], out[-1]) <= 1.0e-9:
        out.pop()
    return tuple(out)


def _signed_polygon_area(
    polygon: tuple[tuple[float, float], ...],
) -> float:
    area = 0.0
    for idx, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(idx + 1) % len(polygon)]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def _ensure_counterclockwise(
    polygon: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    polygon = _dedupe_polygon(polygon)
    if _signed_polygon_area(polygon) < 0.0:
        return tuple(reversed(polygon))
    return polygon


def _polygon_centroid(
    polygon: tuple[tuple[float, float], ...],
) -> tuple[float, float]:
    area = _signed_polygon_area(polygon)
    if abs(area) <= 1.0e-12:
        return (
            sum(x for x, _ in polygon) / max(1, len(polygon)),
            sum(y for _, y in polygon) / max(1, len(polygon)),
        )
    cx = 0.0
    cy = 0.0
    for idx, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(idx + 1) % len(polygon)]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    scale = 1.0 / (6.0 * area)
    return (cx * scale, cy * scale)


def _polygon_radius_bounds(
    polygon: tuple[tuple[float, float], ...]
) -> tuple[float, float]:
    radii = [math.hypot(x, y) for x, y in polygon]
    return min(radii), max(radii)


def _polygon_half_angle(
    polygon: tuple[tuple[float, float], ...],
    center_angle_rad: float,
) -> float:
    return max(
        abs(_normalize_signed_angle(math.atan2(y, x) - center_angle_rad))
        for x, y in polygon
    )


def _normalize_signed_angle(theta: float) -> float:
    while theta > math.pi:
        theta -= 2 * math.pi
    while theta <= -math.pi:
        theta += 2 * math.pi
    return theta


def _compute_slot_placements(config: MotorConfig) -> list[SlotPlacement]:
    """Compute slot placements with 3-phase winding assignment."""
    stator = config.stator
    rotor = config.rotor
    winding = config.winding

    slot_count = stator.slot_count
    pole_count = rotor.pole_count
    pole_pairs = max(1, pole_count // 2)

    # Slot geometry. The slot mouth is an independent width at the stator bore,
    # while the body width remains the pitch minus tooth-width behind the tip.
    slot_angular_pitch = 2 * math.pi / slot_count
    slot_depth_mm = _slot_radial_depth_mm(config)

    inner_r = stator.ID_mm / 2
    outer_r = inner_r + slot_depth_mm
    slot_body_width_mm = _slot_body_width_mm(config)
    slot_mouth_width_mm = _slot_mouth_width_mm(config)
    max_half_w = 0.499 * slot_angular_pitch
    inner_half_w = min(max_half_w, (slot_mouth_width_mm / 2) / inner_r)
    outer_half_w = min(max_half_w, (slot_body_width_mm / 2) / outer_r)
    mean_r = 0.5 * (inner_r + outer_r)
    mean_half_w = (
        inner_half_w + 0.5 * (outer_half_w - inner_half_w)
        if mean_r > 0
        else 0.0
    )

    slots = []

    # Phase assignment using EMF phasor star method.
    # Each slot's electrical angle determines its phase and direction.
    # This is critical for fractional-slot concentrated windings (e.g. 12s/8p, q=0.5)
    # where consecutive slots are NOT the same phase.
    if winding.type == "concentrated":
        for slot_idx in range(slot_count):
            center_angle = slot_idx * slot_angular_pitch

            # Electrical angle and belt now live in concentrated_slot_phase.
            phase, direction = concentrated_slot_phase(slot_idx, slot_count, pole_pairs)

            slots.append(SlotPlacement(
                slot_index=slot_idx,
                center_angle_rad=center_angle,
                inner_radius_mm=inner_r,
                outer_radius_mm=outer_r,
                half_width_rad=mean_half_w,
                phase=phase,
                direction=direction,
                layer=1,
                inner_half_width_rad=inner_half_w,
                outer_half_width_rad=outer_half_w,
                mouth_width_mm=slot_mouth_width_mm,
                body_width_mm=slot_body_width_mm,
            ))
    else:
        # Distributed winding: integer-slot full-pitch 60-degree phase belts.
        # The map lives in backend.winding_utils (shared with preview and
        # mirrored by solvers/magneto2d/src/sources.rs). The previous inline
        # map (phase blocks per pole PAIR, sign by slot parity) was
        # physically invalid — fundamental kw measured 0.224 at q=2.
        for slot_idx in range(slot_count):
            phase, direction = distributed_slot_assignment(
                slot_idx, slot_count, pole_count
            )
            layer = distributed_layer_tag(slot_idx, winding.layers)
            center_angle = slot_idx * slot_angular_pitch

            slots.append(SlotPlacement(
                slot_index=slot_idx,
                center_angle_rad=center_angle,
                inner_radius_mm=inner_r,
                outer_radius_mm=outer_r,
                half_width_rad=mean_half_w,
                phase=phase,
                direction=direction,
                layer=layer,
                inner_half_width_rad=inner_half_w,
                outer_half_width_rad=outer_half_w,
                mouth_width_mm=slot_mouth_width_mm,
                body_width_mm=slot_body_width_mm,
            ))

    return slots


CONCENTRATED_PHASE_BELTS: tuple[tuple[str, str], ...] = (
    ("A", "in"),
    ("C", "out"),
    ("B", "in"),
    ("A", "out"),
    ("C", "in"),
    ("B", "out"),
)


def concentrated_slot_phase(
    slot_idx: int,
    slot_count: int,
    pole_pairs: int,
) -> tuple[str, str]:
    """Phase and current direction of one slot, from the EMF phasor star.

    Sectors 0..5 map to A+, C-, B+, A-, C+, B- — the canonical positive-sequence
    belt order (A, -C, B, -A, C, -B). The previous B/C-swapped order mirrored the
    winding, putting the spatial phase sequence at A,C,B so the sin(y),
    sin(y-120deg), sin(y-240deg) currents counter-rotated against the rotor: loaded
    torque averaged ~0 over an electrical cycle, oscillating at the 2nd harmonic
    instead of staying constant.

    Extracted so validation counts phases with the same mapping the drawer uses.
    Some slot/pole combinations never reach every belt — 16 slots with 8 poles steps
    90 electrical degrees per slot, which only ever lands in the A and C sectors —
    and a validator with its own copy of this table could not tell.
    """

    if slot_count <= 0:
        return CONCENTRATED_PHASE_BELTS[0]
    elec_angle_deg = (slot_idx * 360.0 * pole_pairs / slot_count) % 360.0
    return CONCENTRATED_PHASE_BELTS[int(elec_angle_deg / 60) % 6]


def _slot_body_width_mm(config: MotorConfig) -> float:
    """Slot body width behind the tooth tips, so the tooth body is tooth_width_mm.

    The subtraction has to happen at the radius the body actually sits at. It used
    to use the bore pitch (pi * ID / slots) while the body is drawn out at
    ID/2 + slot depth, where the pitch arc is much larger — on the 8p/12s example
    31.4mm against 42.9mm. A 17.3mm slot then sat in a 42.9mm pitch and left a
    25.6mm tooth where the field read 14.1, so tooth_width_mm moved the tooth
    without ever equalling it (6mm of field shifted the drawn tooth ~2.6mm).

    Measured at the body radius, the tooth body comes out at tooth_width_mm exactly.
    The bore mouth remains independently pinned to slot_opening_mm, so the bore
    tooth can be either wider or narrower than that yoke-side body. Consumers that
    estimate saturation must compare both sections rather than assuming this input
    is always the minimum.
    """

    body_pitch_mm = slot_body_pitch_mm(config)
    return max(MIN_SLOT_BODY_WIDTH_MM, body_pitch_mm - config.stator.tooth_width_mm)


def _slot_mouth_width_mm(config: MotorConfig) -> float:
    """Configured slot mouth width at the stator bore."""
    stator = config.stator
    tooth_pitch_mm = math.pi * stator.ID_mm / stator.slot_count
    return max(0.5, min(stator.slot_opening_mm, tooth_pitch_mm * 0.998))


def _slot_radial_depth_mm(config: MotorConfig) -> float:
    """Radial depth available for slots/teeth before the back-iron yoke."""
    stator = config.stator
    radial_build_mm = (stator.OD_mm - stator.ID_mm) / 2.0
    return max(0.0, radial_build_mm - stator.yoke_thickness_mm)


def slot_body_pitch_mm(config: MotorConfig) -> float:
    """Pitch arc at the radius the slot body sits at, which is where
    ``tooth_width_mm`` is subtracted. Shared with validation so the limit on the
    field is the same arc the drawer divides up."""
    stator = config.stator
    body_radius_mm = stator.ID_mm / 2 + _slot_radial_depth_mm(config)
    return 2 * math.pi * body_radius_mm / stator.slot_count


def bore_tooth_width_mm(config: MotorConfig) -> float:
    """Physical tooth-tip width at the stator bore.

    ``slot_opening_mm`` names the bore-side slot mouth. The remaining pitch is
    therefore the bore tooth. A tooth shoe extends each flank into that mouth, so
    include its two overhangs when the optional shoe geometry is enabled.
    """

    stator = config.stator
    bore_pitch_mm = math.pi * stator.ID_mm / stator.slot_count
    width_mm = bore_pitch_mm - _slot_mouth_width_mm(config)
    if stator.tooth_shoe_enabled:
        width_mm += 2.0 * stator.tooth_shoe_overhang_mm
    return max(0.0, min(width_mm, bore_pitch_mm))


def slot_width_at_yoke_mm(config: MotorConfig) -> float:
    """Physical slot-body width where the slot terminates beside the yoke."""

    return _slot_body_width_mm(config)


def tooth_width_at_yoke_mm(config: MotorConfig) -> float:
    """Physical tooth width at the slot body beside the yoke.

    This is the section controlled by the persisted ``tooth_width_mm`` field. Use
    the drawn remainder rather than returning the field directly so the value also
    stays truthful at the slot-body safety floor.
    """

    return max(0.0, slot_body_pitch_mm(config) - slot_width_at_yoke_mm(config))


def narrowest_tooth_width_mm(config: MotorConfig) -> float:
    """Narrowest physical tooth section used by analytical saturation checks."""

    stator = config.stator
    bore_width_mm = bore_tooth_width_mm(config)
    yoke_width_mm = tooth_width_at_yoke_mm(config)
    if not stator.tooth_shoe_enabled:
        return min(bore_width_mm, yoke_width_mm)

    bore_r = stator.ID_mm / 2.0
    slot_outer_r = bore_r + _slot_radial_depth_mm(config)
    if slot_outer_r <= bore_r + 1e-9:
        return min(bore_width_mm, yoke_width_mm)

    slot_pitch_rad = 2.0 * math.pi / stator.slot_count
    mouth_half_rad = min(
        0.499 * slot_pitch_rad,
        (_slot_mouth_width_mm(config) / 2.0) / max(bore_r, 1e-9),
    )
    body_inner_half_rad = max(0.0, 0.5 * slot_pitch_rad - mouth_half_rad)
    shoulder_r = min(
        bore_r + stator.tooth_shoe_height_mm,
        slot_outer_r - 1e-6,
    )
    shoulder_fraction = max(
        0.0,
        min(1.0, (shoulder_r - bore_r) / (slot_outer_r - bore_r)),
    )
    shoulder_width_mm = 2.0 * shoulder_r * (
        (1.0 - shoulder_fraction) * body_inner_half_rad
        + shoulder_fraction * yoke_width_mm / (2.0 * slot_outer_r)
    )
    return max(0.0, min(bore_width_mm, shoulder_width_mm, yoke_width_mm))


def tooth_width_geometry_limit_mm(config: MotorConfig) -> float:
    """Largest tooth-width field that remains the drawn tooth's narrowest width.

    Without a shoe, the configured slot mouth fixes the tooth width at the bore,
    so that bore width is the limit. A shoe widens the bore tip and moves the
    transition to ``tooth_shoe_height_mm``. Its shoulder samples the same linear
    angular taper used by :mod:`backend.geometry_ir`; solve the shoulder-width
    equation for the configured body width so advisory code measures the geometry
    the builder actually draws instead of applying the unshoed bore formula.
    """

    stator = config.stator
    bore_r = stator.ID_mm / 2.0
    slot_outer_r = bore_r + _slot_radial_depth_mm(config)
    slot_pitch_rad = 2.0 * math.pi / stator.slot_count
    mouth_half_rad = min(
        0.499 * slot_pitch_rad,
        (_slot_mouth_width_mm(config) / 2.0) / max(bore_r, 1e-9),
    )
    body_inner_half_rad = max(0.0, 0.5 * slot_pitch_rad - mouth_half_rad)
    bore_body_width_mm = 2.0 * bore_r * body_inner_half_rad

    if not stator.tooth_shoe_enabled or slot_outer_r <= bore_r + 1e-9:
        return bore_body_width_mm

    shoulder_r = min(
        bore_r + stator.tooth_shoe_height_mm,
        slot_outer_r - 1e-6,
    )
    radial_span = slot_outer_r - bore_r
    shoulder_fraction = max(
        0.0,
        min(1.0, (shoulder_r - bore_r) / radial_span),
    )

    # At the shoulder, the tooth half-angle is the linear interpolation between
    # the fixed bore-side body angle and tooth_width_mm / (2 * slot_outer_r).
    # Therefore shoulder_width = fixed_width + body_coefficient * tooth_width.
    shoulder_fixed_width_mm = (
        2.0 * shoulder_r * (1.0 - shoulder_fraction) * body_inner_half_rad
    )
    body_coefficient = shoulder_r * shoulder_fraction / slot_outer_r
    if body_coefficient >= 1.0 - 1e-12:
        shoulder_limit_mm = math.inf
    else:
        shoulder_limit_mm = shoulder_fixed_width_mm / (1.0 - body_coefficient)

    bore_tip_half_rad = min(
        body_inner_half_rad + stator.tooth_shoe_overhang_mm / max(bore_r, 1e-9),
        0.5 * slot_pitch_rad - 1e-9,
    )
    bore_tip_limit_mm = 2.0 * bore_r * max(0.0, bore_tip_half_rad)
    return max(0.0, min(shoulder_limit_mm, bore_tip_limit_mm))






def resolve_phase_current_peak(config: MotorConfig) -> float:
    """Resolve solve current into a peak phase current."""
    if config.solve_params is None:
        return 0.0
    current = config.solve_params.current_amplitude_A
    if config.solve_params.current_amplitude_convention == "rms":
        return current * math.sqrt(2)
    if (
        config.solve_params.excitation_mode == IDEAL_SIX_STEP_120
        and config.solve_params.current_amplitude_convention == "plateau"
    ):
        # Compatibility for metadata consumers. Six-step source assembly uses
        # resolve_phase_current_sample and never treats this value as sine peak.
        return current
    return current


def current_angle_elec_deg_for_rotor_elec(
    config: MotorConfig,
    rotor_angle_elec_deg: float,
) -> float:
    """Resolve the stator source-current angle for the unified gamma convention.

    ``current_angle_deg`` is gamma measured from the positive q-axis. Positive
    gamma is flux-weakening advance, and motoring torque is positive for
    ``0 <= gamma < 90``. The applied source angle is therefore
    ``theta_e = rotor_elec - 90 + gamma`` for every topology and winding type.
    At gamma=0 this preserves the historical SPM ``rotor_elec - 90`` source
    angle bit-for-bit.

    The earlier sign convention used ``rotor_elec - (90 + gamma)``, which
    retards the source phasor for positive gamma under this codebase's phase sequence and slot ordering —
    measured as effective advance = -gamma + belt offset on both lanes
    (gamma=-45 had LOWER tooth/yoke B and
    higher IPM torque than +45, i.e. -gamma was the flux-weakening side).
    Adding gamma makes the label match the physics contract stated above.
    """
    gamma_deg = 0.0
    if config.solve_params is not None:
        gamma_deg = float(getattr(config.solve_params, "current_angle_deg", 0.0) or 0.0)
    return float(rotor_angle_elec_deg) - 90.0 + gamma_deg


def current_angle_elec_deg_for_mech(
    config: MotorConfig,
    rotor_angle_mech_deg: float,
) -> float:
    """Resolve source-current angle from rotor mechanical angle."""
    pole_pairs = max(1, int(config.rotor.pole_count) // 2)
    return current_angle_elec_deg_for_rotor_elec(
        config,
        float(rotor_angle_mech_deg) * pole_pairs,
    )


def compute_3phase_current_density(
    config: MotorConfig,
    rotor_angle_elec_deg: float = 0.0,
) -> dict[str, float]:
    """Compute per-phase current density for a resolved electrical angle.

    For torque computation, we apply rated current. For back-EMF (no-load),
    current is zero.

    Args:
        config: Motor configuration
        rotor_angle_elec_deg: Electrical angle of the stator current vector
            in degrees. Callers are responsible for applying any rotor
            position offset or user-specified current angle before passing
            it in.

    Returns:
        Dict mapping phase name to current density in A/mm²
    """
    if config.solve_params is None:
        return {"A": 0.0, "B": 0.0, "C": 0.0}

    I_peak = resolve_phase_current_peak(config)

    # FEMM uses the homogenized slot block as the current-carrying region, so
    # J must be expressed over the full slot area represented by that block.
    # Applying a copper fill factor here would over-inject ampere-turns.
    slot_depth_mm = _slot_radial_depth_mm(config)
    slot_area_mm2 = (
        0.5
        * (_slot_mouth_width_mm(config) + _slot_body_width_mm(config))
        * slot_depth_mm
    )

    winding = config.winding
    turns = winding.turns_per_coil
    parallel = winding.parallel_paths

    # Current per conductor = I_peak / parallel_paths
    I_conductor = I_peak / parallel

    # 3-phase currents at this resolved electrical angle.
    theta = math.radians(rotor_angle_elec_deg)
    I_a = I_conductor * math.sin(theta)
    I_b = I_conductor * math.sin(theta - 2 * math.pi / 3)
    I_c = I_conductor * math.sin(theta - 4 * math.pi / 3)

    # Convert to current density: J = N_turns * I / slot_area
    J_a = turns * I_a / slot_area_mm2 if slot_area_mm2 > 0 else 0
    J_b = turns * I_b / slot_area_mm2 if slot_area_mm2 > 0 else 0
    J_c = turns * I_c / slot_area_mm2 if slot_area_mm2 > 0 else 0

    return {"A": J_a, "B": J_b, "C": J_c}


def compute_3phase_current_density_for_rotor_elec(
    config: MotorConfig,
    rotor_angle_elec_deg: float,
) -> dict[str, float]:
    """Resolve the configured excitation and return per-phase slot J.

    Unlike ``compute_3phase_current_density`` (the frozen sine/source-angle
    helper), this function accepts rotor electrical angle and preserves an
    explicit six-step current triple.
    """
    if config.solve_params is None:
        return {"A": 0.0, "B": 0.0, "C": 0.0}

    sample = resolve_phase_current_sample(config, rotor_angle_elec_deg)
    phase_current = phase_current_sample_dict(sample)
    slot_depth_mm = _slot_radial_depth_mm(config)
    slot_area_mm2 = (
        0.5
        * (_slot_mouth_width_mm(config) + _slot_body_width_mm(config))
        * slot_depth_mm
    )
    if slot_area_mm2 <= 0.0:
        return {"A": 0.0, "B": 0.0, "C": 0.0}

    turns = config.winding.turns_per_coil
    parallel = max(1, config.winding.parallel_paths)
    source_scale = terminal_to_slot_current_scale(config)
    return {
        phase: turns * current_a * source_scale / parallel / slot_area_mm2
        for phase, current_a in phase_current.items()
    }
