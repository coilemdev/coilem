"""FEMM geometry drawing methods.

Extracted from femm_solver.py for maintainability.
Contains all methods related to drawing motor geometry in FEMM:
- Full geometry (stator, rotor, magnets, slots)
- Circle and magnet block primitives
- Winding current application
- Boundary conditions
"""

from __future__ import annotations

import logging
import math
import os

from backend.geometry_drawer import (
    MotorGeometry,
    compute_3phase_current_density,
    current_angle_elec_deg_for_rotor_elec,
)
from backend.geometry_ir import (
    _angle_delta,
    _shoed_annular_loop,
    _slot_wall_angle_at_radius,
    _tooth_shoe_half_angles,
    shaft_material_key,
)
from backend.logging_utils import tagged_log
from backend.models import MotorConfig
from backend.winding_utils import distributed_slot_layer_assignments

logger = logging.getLogger(__name__)


def _femm_meshsize_override_mm(env_var: str) -> float | None:
    """Read a FEMM per-block meshsize override from an env var.

    Used by the cogging-reference convergence study (task #26) to force
    finer meshing on specific regions (airgap, magnets) without touching
    the Pydantic config schema. When unset, regions use FEMM's default
    auto-mesh (automesh=1, meshsize=0). When set to a float > 0, that
    region uses automesh=0 with the given target edge length in mm.
    Setting 0 or a non-numeric value restores the default.
    """
    raw = os.environ.get(env_var)
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _slot_label_count(config: MotorConfig, slot_index: int) -> int:
    if config.winding.type == "distributed" and config.winding.layers >= 2:
        return len(
            distributed_slot_layer_assignments(
                slot_index,
                config.stator.slot_count,
                config.rotor.pole_count,
                config.winding.layers,
                coil_span=config.winding.coil_span,
            )
        )
    return 1


def _slot_current_assignments(config: MotorConfig, slot) -> list[dict[str, int | str]]:
    if config.winding.type == "distributed" and config.winding.layers >= 2:
        return [
            {
                "layer": assignment.layer,
                "phase": assignment.phase,
                "direction": assignment.direction,
            }
            for assignment in distributed_slot_layer_assignments(
                slot.slot_index,
                config.stator.slot_count,
                config.rotor.pole_count,
                config.winding.layers,
                coil_span=config.winding.coil_span,
            )
        ]
    return [
        {
            "layer": int(getattr(slot, "layer", 1)),
            "phase": slot.phase,
            "direction": slot.direction,
        }
    ]


def _slot_layer_label_radius(
    inner_radius_mm: float,
    outer_radius_mm: float,
    layer: int,
    layers: int,
) -> float:
    n_layers = max(1, layers)
    layer_idx = max(1, min(layer, n_layers)) - 1
    radial_span = max(0.0, outer_radius_mm - inner_radius_mm)
    return inner_radius_mm + radial_span * (layer_idx + 0.5) / n_layers


def _draw_slot_wall_loop(femm, loop, maxseg_deg: float) -> None:
    """Draw only the slot-wall parts of a shoed IR loop into FEMM.

    The stator bore and slot-bottom circles are drawn separately. Local
    non-origin arcs are the shoe fillets and must be drawn here.
    """
    for segment in loop.segments:
        if (
            segment.kind == "arc"
            and segment.center is not None
            and abs(segment.center.x_mm) <= 1e-9
            and abs(segment.center.y_mm) <= 1e-9
        ):
            continue

        x1, y1 = segment.start.x_mm, segment.start.y_mm
        x2, y2 = segment.end.x_mm, segment.end.y_mm
        if math.hypot(x2 - x1, y2 - y1) <= 1e-9:
            continue
        femm.mi_addnode(x1, y1)
        femm.mi_addnode(x2, y2)
        if segment.kind == "line":
            femm.mi_drawline(x1, y1, x2, y2)
            continue

        sweep_deg = float(segment.sweep_deg or 0.0)
        if abs(sweep_deg) <= 1e-9:
            continue
        if sweep_deg < 0.0:
            femm.mi_drawarc(x2, y2, x1, y1, abs(sweep_deg), maxseg_deg)
        else:
            femm.mi_drawarc(x1, y1, x2, y2, abs(sweep_deg), maxseg_deg)


def _femm_mesh_density(config: MotorConfig) -> str:
    solve_params = getattr(config, "solve_params", None)
    density = getattr(solve_params, "mesh_density", "normal") or "normal"
    return str(density)


def _femm_airgap_width_mm(geom: MotorGeometry) -> float:
    return max(0.05, geom.stator_ID_r - _femm_airgap_inner_radius_mm(geom))


def _femm_airgap_inner_radius_mm(geom: MotorGeometry) -> float:
    if str(geom.topology).upper() == "IPM":
        return geom.rotor_OD_r
    return max((mag.outer_radius_mm for mag in geom.magnets), default=geom.rotor_OD_r)


def _femm_magnet_thickness_mm(config: MotorConfig, geom: MotorGeometry) -> float:
    if geom.magnets:
        return max(
            0.05,
            max(mag.outer_radius_mm - mag.inner_radius_mm for mag in geom.magnets),
        )
    return max(0.05, float(getattr(config.rotor, "magnet_thickness_mm", 0.0) or 0.0))


def _femm_density_arc_maxseg_deg(config: MotorConfig) -> float:
    """Return FEMM arc max-segment angle for the selected density.

    FEMM auto-mesh is still constrained by the arc segmentation we draw into
    the .fem file. Keep the default at the historical 1 degree and only relax
    it for coarse diagnostics.
    """

    return {
        "coarse": 12,
        "normal": 1,
        "fine": 0.5,
        "very_fine": 0.25,
    }.get(_femm_mesh_density(config), 1)


class FEMMGeometryMixin:
    """Mixin providing geometry drawing methods for FEMMSolver."""

    def _femm_density_meshsize_mm(
        self,
        config: MotorConfig,
        geom: MotorGeometry,
        region: str,
    ) -> float | None:
        """Return a FEMM block mesh size for a density preset.

        ``None`` preserves FEMM's adaptive auto-mesh behavior. This keeps
        existing normal-density runs bit-for-bit aligned with the historical
        setup while letting coarse/fine presets become explicit FEMM controls.
        """

        if region == "airgap":
            override = _femm_meshsize_override_mm("FEMM_AIRGAP_MESHSIZE_MM")
            if override is not None:
                return override
        elif region == "magnet":
            override = _femm_meshsize_override_mm("FEMM_MAGNET_MESHSIZE_MM")
            if override is not None:
                return override

        density = _femm_mesh_density(config)
        if density == "normal":
            return None

        od_mm = max(1.0, float(config.stator.OD_mm))
        airgap_width = _femm_airgap_width_mm(geom)
        magnet_thickness = _femm_magnet_thickness_mm(config, geom)

        if density == "coarse":
            global_size = _clamp(od_mm * 0.05, 2.0, 5.0)
            sizes = {
                "air": global_size,
                "steel": global_size,
                "slot": _clamp(od_mm * 0.035, 1.5, 3.5),
                "rotor_core": global_size,
                "shaft": global_size,
                "airgap": _clamp(airgap_width * 1.25, 0.75, 2.0),
                "magnet": _clamp(magnet_thickness * 1.25, 1.0, 2.5),
            }
        elif density == "fine":
            global_size = _clamp(od_mm * 0.012, 0.6, 1.5)
            sizes = {
                "air": global_size,
                "steel": global_size,
                "slot": _clamp(od_mm * 0.008, 0.45, 1.0),
                "rotor_core": global_size,
                "shaft": global_size,
                "airgap": _clamp(airgap_width * 0.45, 0.25, 0.8),
                "magnet": _clamp(magnet_thickness * 0.45, 0.3, 0.9),
            }
        elif density == "very_fine":
            global_size = _clamp(od_mm * 0.008, 0.35, 1.0)
            sizes = {
                "air": global_size,
                "steel": global_size,
                "slot": _clamp(od_mm * 0.005, 0.25, 0.65),
                "rotor_core": global_size,
                "shaft": global_size,
                "airgap": _clamp(airgap_width * 0.25, 0.15, 0.5),
                "magnet": _clamp(magnet_thickness * 0.25, 0.2, 0.6),
            }
        else:
            return None

        return sizes.get(region, global_size)

    def _set_femm_blockprop(
        self,
        femm,
        material_name: str,
        config: MotorConfig,
        geom: MotorGeometry,
        region: str,
        *,
        circuit_name: str = "<None>",
        magnetization_direction: float = 0,
        group: int = 0,
        turns: int = 0,
    ) -> float | None:
        meshsize_mm = self._femm_density_meshsize_mm(config, geom, region)
        if meshsize_mm is None:
            femm.mi_setblockprop(
                material_name,
                1,
                0,
                circuit_name,
                magnetization_direction,
                group,
                turns,
            )
            return None

        femm.mi_setblockprop(
            material_name,
            0,
            meshsize_mm,
            circuit_name,
            magnetization_direction,
            group,
            turns,
        )
        return meshsize_mm

    def _draw_full_geometry(
        self, femm, config: MotorConfig, geom: MotorGeometry,
        rotor_offset_deg: float = 0.0
    ):
        """Draw complete motor geometry in FEMM.

        Milestone 1: Stator + rotor + airgap circles
        Milestone 2: + magnet blocks with alternating N/S polarity
        Milestone 3: + stator slot regions (simplified pie sectors)
        """
        offset_rad = math.radians(rotor_offset_deg)
        self._femm_current_arc_maxseg_deg = _femm_density_arc_maxseg_deg(config)

        # ── Geometry debug summary ───────────────────────────────────────
        tagged_log(f"[GEOM] Drawing geometry: rotor_offset={rotor_offset_deg:.2f}°")
        tagged_log(f"[GEOM] Circles: stator_OD_r={geom.stator_OD_r:.2f}, "
              f"stator_ID_r={geom.stator_ID_r:.2f}, "
              f"rotor_OD_r={geom.rotor_OD_r:.2f}, "
              f"shaft_r={geom.shaft_r:.2f}")
        slotless_stator = bool(config.debug and config.debug.slotless_noload_diagnostic)
        slot_outer_r_preview = geom.slots[0].outer_radius_mm if geom.slots else geom.stator_OD_r
        if slotless_stator:
            tagged_log("[GEOM] slotless stator diagnostic active — smooth iron ring from bore to OD")
        else:
            tagged_log(f"[GEOM] slot_outer_r={slot_outer_r_preview:.2f} (separates yoke from teeth)")
        tagged_log(f"[GEOM] Slots: {len(geom.slots)}, Magnets: {len(geom.magnets)}")
        if geom.magnets:
            m = geom.magnets[0]
            tagged_log(f"[GEOM] Magnet inner_r={m.inner_radius_mm:.2f}, "
                  f"outer_r={m.outer_radius_mm:.2f}, "
                  f"half_width={math.degrees(m.half_width_rad):.2f}°")
        label_count = 0

        # ── Stator outer boundary ────────────────────────────────────────
        self._draw_circle(femm, geom.stator_OD_r)

        # ── Stator bore (inner diameter) ─────────────────────────────────
        if slotless_stator:
            self._draw_circle(femm, geom.stator_ID_r)

        # ── Rotor outer surface ──────────────────────────────────────────
        self._draw_circle(femm, geom.rotor_OD_r)

        # ── Shaft ────────────────────────────────────────────────────────
        self._draw_circle(femm, geom.shaft_r)

        from v3_adapter import draw_stator_regions
        slot_outer_r = geom.slots[0].outer_radius_mm if geom.slots else geom.stator_OD_r
        if not slotless_stator:
            draw_stator_regions(femm, config, geom, self._femm_current_arc_maxseg_deg)

        for pocket in geom.rotor_air_pockets:
            self._draw_polygon(
                femm,
                self._rotate_points(pocket.corners_mm, offset_rad),
            )

        # ── Magnet blocks (Milestone 2) ──────────────────────────────────
        for mag in geom.magnets:
            angle = mag.center_angle_rad + offset_rad
            self._draw_magnet_block(femm, mag, angle)

        # ── Apply boundary condition on ALL 4 arcs of outer circle ────────
        # _draw_circle creates 4 quarter arcs with endpoints at cardinal
        # positions. We must select and apply boundary to each one.
        r = geom.stator_OD_r
        for bx, by in [(r, 0), (0, r), (-r, 0), (0, -r)]:
            # Pick midpoint of each quarter arc for reliable selection
            pass
        # Simpler: select all 4 arcs via selectarcsegment near their midpoints
        mid_pts = [
            (r * math.cos(math.radians(45)), r * math.sin(math.radians(45))),   # Q1 mid
            (r * math.cos(math.radians(135)), r * math.sin(math.radians(135))), # Q2 mid
            (r * math.cos(math.radians(225)), r * math.sin(math.radians(225))), # Q3 mid
            (r * math.cos(math.radians(315)), r * math.sin(math.radians(315))), # Q4 mid
        ]
        for mx, my in mid_pts:
            femm.mi_selectarcsegment(mx, my)
        femm.mi_setarcsegmentprop(self._femm_current_arc_maxseg_deg, "ZeroA", 0, 0)
        femm.mi_clearselected()

        stator_steel_name = getattr(self, "_stator_steel_material_name", "StatorSteel")
        rotor_steel_name = getattr(self, "_rotor_steel_material_name", "RotorSteel")

        # ── Block labels ─────────────────────────────────────────────────
        # Every bounded region needs exactly one label.
        #
        # Regions (with 12 slots, 8 magnets):
        #   1. Exterior (outside stator OD) → Air
        #   2. Stator yoke ring (slot_outer_r to stator_OD_r) → stator steel
        #   3. 12 teeth (between slot walls, bore to slot_outer_r) → stator steel
        #   4. 12 slots (between slot walls, bore to slot_outer_r) → Coil (from _apply_winding_current)
        #   5. Airgap (bore to rotor OD) → Air
        #   6. Rotor core (rotor OD to shaft, minus magnets) → rotor steel
        #      - Need one label per inter-magnet gap
        #   7. Shaft (center) → Air
        #   8. 8 magnet regions → Magnet

        # 1. Exterior — air outside stator OD boundary
        ext_r = geom.stator_OD_r + 5  # 5mm outside the boundary
        femm.mi_addblocklabel(ext_r, 0)
        femm.mi_selectlabel(ext_r, 0)
        self._set_femm_blockprop(femm, "Air", config, geom, "air")
        femm.mi_clearselected()
        label_count += 1
        tagged_log(f"[LABEL] #{label_count} Exterior Air at ({ext_r:.1f}, 0)")

        # 2. Stator yoke ring — one label anywhere in the ring
        yoke_r = (geom.stator_ID_r + geom.stator_OD_r) / 2 if slotless_stator else (slot_outer_r + geom.stator_OD_r) / 2
        femm.mi_addblocklabel(yoke_r, 0)
        femm.mi_selectlabel(yoke_r, 0)
        self._set_femm_blockprop(femm, stator_steel_name, config, geom, "steel")
        femm.mi_clearselected()
        label_count += 1
        tagged_log(f"[LABEL] #{label_count} {'SlotlessStator' if slotless_stator else 'Yoke'} {stator_steel_name} at ({yoke_r:.1f}, 0)")

        # 3. Teeth — one label per tooth (between adjacent slot walls)
        if not slotless_stator:
            for i in range(len(geom.slots)):
                next_i = (i + 1) % len(geom.slots)
                tooth_r = (geom.stator_ID_r + slot_outer_r) / 2
                right_of_i = (
                    geom.slots[i].center_angle_rad
                    + geom.slots[i].half_width_at_radius(tooth_r)
                )
                left_of_next = (
                    geom.slots[next_i].center_angle_rad
                    - geom.slots[next_i].half_width_at_radius(tooth_r)
                )
                if left_of_next < right_of_i:
                    left_of_next += 2 * math.pi
                tooth_center = (right_of_i + left_of_next) / 2
                tx = tooth_r * math.cos(tooth_center)
                ty = tooth_r * math.sin(tooth_center)
                femm.mi_addblocklabel(tx, ty)
                femm.mi_selectlabel(tx, ty)
                self._set_femm_blockprop(femm, stator_steel_name, config, geom, "steel")
                femm.mi_clearselected()
                label_count += 1
                if i == 0:
                    tagged_log(f"[LABEL] #{label_count} Tooth[{i}] {stator_steel_name} at ({tx:.1f}, {ty:.1f}) "
                          f"angle={math.degrees(tooth_center):.1f}°")
            tagged_log(f"[LABEL] ... {len(geom.slots)} tooth labels total")

        # 4. Slots — handled by _apply_winding_current (called after this method)

        # 5. Airgap — between stator bore and rotor OD
        if len(geom.magnets) >= 2:
            a1 = geom.magnets[0].center_angle_rad + offset_rad
            a2 = geom.magnets[1].center_angle_rad + offset_rad
            safe_angle = (a1 + a2) / 2
        else:
            safe_angle = math.radians(7)

        gap_r = (geom.stator_ID_r + geom.rotor_OD_r) / 2
        gx = gap_r * math.cos(safe_angle)
        gy = gap_r * math.sin(safe_angle)
        femm.mi_addblocklabel(gx, gy)
        femm.mi_selectlabel(gx, gy)
        airgap_mesh_mm = self._set_femm_blockprop(femm, "Air", config, geom, "airgap")
        femm.mi_clearselected()
        label_count += 1
        mesh_note = (
            f" airgap_meshsize={airgap_mesh_mm} mm"
            if airgap_mesh_mm is not None else " airgap_meshsize=auto"
        )
        tagged_log(f"[LABEL] #{label_count} Airgap Air at ({gx:.1f}, {gy:.1f}) "
              f"safe_angle={math.degrees(safe_angle):.1f}°, gap_r={gap_r:.1f}{mesh_note}")

        # 6. Rotor core — ONE connected region (steel below/between/above magnets)
        #    Magnet sides only span inner_r to outer_r; gaps between magnets
        #    connect the core ring (below magnets) to inter-magnet wedges and
        #    bridges (above magnets). Place label below magnets at safe_angle.
        if geom.magnets:
            mag_inner_r = geom.magnets[0].inner_radius_mm
            rc_r = (geom.shaft_r + mag_inner_r) / 2  # Below magnets, in core ring
        else:
            rc_r = (geom.rotor_OD_r + geom.shaft_r) / 2
        rcx = rc_r * math.cos(safe_angle)
        rcy = rc_r * math.sin(safe_angle)
        femm.mi_addblocklabel(rcx, rcy)
        femm.mi_selectlabel(rcx, rcy)
        self._set_femm_blockprop(femm, rotor_steel_name, config, geom, "rotor_core")
        femm.mi_clearselected()
        label_count += 1
        tagged_log(f"[LABEL] #{label_count} RotorCore {rotor_steel_name} at ({rcx:.1f}, {rcy:.1f}) rc_r={rc_r:.1f}")

        # 7. Shaft. Baseline is air/non-magnetic; OPENEM_SHAFT_MATERIAL can
        # switch this to rotor steel for parity probes.
        shaft_material = shaft_material_key(config)
        shaft_block_name = (
            rotor_steel_name
            if shaft_material.startswith("steel:rotor:")
            else "Air"
        )
        femm.mi_addblocklabel(0, 0)
        femm.mi_selectlabel(0, 0)
        self._set_femm_blockprop(femm, shaft_block_name, config, geom, "shaft")
        femm.mi_clearselected()
        label_count += 1
        tagged_log(f"[LABEL] #{label_count} Shaft {shaft_block_name} at (0, 0)")

        rotor_pocket_names: list[str] = getattr(self, "_rotor_air_pocket_label_names", []) or []
        for pocket_idx, pocket in enumerate(geom.rotor_air_pockets):
            label = pocket.label_mm or self._polygon_centroid(pocket.corners_mm)
            lx, ly = self._rotate_point(label, offset_rad)
            femm.mi_addblocklabel(lx, ly)
            femm.mi_selectlabel(lx, ly)
            block_name = (
                rotor_pocket_names[pocket_idx]
                if pocket_idx < len(rotor_pocket_names)
                else "Air"
            )
            self._set_femm_blockprop(femm, block_name, config, geom, "magnet_pocket_air")
            femm.mi_clearselected()
            label_count += 1
            if pocket_idx == 0:
                tagged_log(
                    f"[LABEL] #{label_count} {block_name} at ({lx:.1f}, {ly:.1f})"
                )

        # 8a. V-IPM pocket-air cavities. These are separate air regions
        # around each slanted magnet slab and need explicit labels so the
        # imported physics contract can preserve MagnetPocketAir semantics.
        pocket_names: list[str] = getattr(self, "_magnet_pocket_air_label_names", []) or []
        for mi, mag in enumerate(geom.magnets):
            if mag.pocket_label_mm is None:
                continue
            lx, ly = self._rotate_point(mag.pocket_label_mm, offset_rad)
            femm.mi_addblocklabel(lx, ly)
            femm.mi_selectlabel(lx, ly)
            block_name = pocket_names[mi] if mi < len(pocket_names) else "Air"
            self._set_femm_blockprop(femm, block_name, config, geom, "magnet_pocket_air")
            femm.mi_clearselected()
            label_count += 1
            if mi == 0:
                tagged_log(
                    f"[LABEL] #{label_count} {block_name} at ({lx:.1f}, {ly:.1f})"
                )

        # 8. Magnets — at magnet centers with magnetization direction.
        # Uses the per-magnet alias names registered in _setup_problem
        # (N1, S1, N2, ...) so the post-processor shows a per-pole text
        # label when "View → Block Labels" is toggled on. Falls back to
        # the generic "Magnet" material if the aliases weren't registered
        # (e.g., called from a test that stubs _setup_problem).
        magnet_names: list[str] = getattr(self, "_magnet_label_names", []) or []
        for mi, mag in enumerate(geom.magnets):
            angle = mag.center_angle_rad + offset_rad
            if mag.corners_mm is not None:
                lx, ly = self._rotate_point(self._polygon_centroid(mag.corners_mm), offset_rad)
            else:
                label_r = mag.radial_center_mm
                lx = label_r * math.cos(angle)
                ly = label_r * math.sin(angle)
            femm.mi_addblocklabel(lx, ly)
            femm.mi_selectlabel(lx, ly)
            mag_dir = (mag.magnetization_angle_deg + math.degrees(offset_rad)) % 360
            block_name = magnet_names[mi] if mi < len(magnet_names) else "Magnet"
            self._set_femm_blockprop(
                femm,
                block_name,
                config,
                geom,
                "magnet",
                magnetization_direction=mag_dir,
            )
            femm.mi_clearselected()
            label_count += 1
            if mi == 0:
                tagged_log(f"[LABEL] #{label_count} {block_name}[{mi}] ({mag.polarity}) at ({lx:.1f}, {ly:.1f}) "
                      f"angle={math.degrees(angle):.1f}°, mag_dir={mag_dir:.1f}°")
        tagged_log(f"[LABEL] ... {len(geom.magnets)} magnet labels total "
              f"(aliases: {', '.join(magnet_names) if magnet_names else 'Magnet only'})")
        tagged_log(f"[GEOM] Total labels from _draw_full_geometry: {label_count}")
        slot_label_count = sum(_slot_label_count(config, slot.slot_index) for slot in geom.slots)
        tagged_log(f"[GEOM] Expected additional slot labels from _apply_winding_current: {slot_label_count}")
        expected = label_count + slot_label_count
        tagged_log(f"[GEOM] Expected total region labels: {expected}")

    def _draw_circle(self, femm, radius: float):
        """Draw a full circle using 4 quarter arcs."""
        maxseg_deg = getattr(self, "_femm_current_arc_maxseg_deg", 1.0)
        femm.mi_drawarc(radius, 0, 0, radius, 90, maxseg_deg)
        femm.mi_drawarc(0, radius, -radius, 0, 90, maxseg_deg)
        femm.mi_drawarc(-radius, 0, 0, -radius, 90, maxseg_deg)
        femm.mi_drawarc(0, -radius, radius, 0, 90, maxseg_deg)

    def _draw_magnet_block(self, femm, mag, angle_rad: float):
        """Draw a magnet region for one pole.

        For IPM: rectangular pocket inside rotor with bridge above.
        For SPM: arc segment on rotor surface.

        Uses arcs for inner/outer edges (matching the circular boundaries)
        and radial lines for the sides. This avoids chord-vs-arc slivers.
        """
        if getattr(mag, "corners_mm", None) is not None:
            offset_rad = angle_rad - mag.center_angle_rad
            if getattr(mag, "pocket_corners_mm", None) is not None:
                self._draw_polygon(femm, self._rotate_points(mag.pocket_corners_mm, offset_rad))
            self._draw_polygon(femm, self._rotate_points(mag.corners_mm, offset_rad))
            return

        inner_r = mag.inner_radius_mm
        outer_r = mag.outer_radius_mm
        half_w = mag.half_width_rad

        a1 = angle_rad - half_w
        a2 = angle_rad + half_w

        # Four corners
        p1 = (inner_r * math.cos(a1), inner_r * math.sin(a1))
        p2 = (inner_r * math.cos(a2), inner_r * math.sin(a2))
        p3 = (outer_r * math.cos(a2), outer_r * math.sin(a2))
        p4 = (outer_r * math.cos(a1), outer_r * math.sin(a1))

        # Explicit nodes at all 4 corners to ensure proper junctions
        for px, py in (p1, p2, p3, p4):
            femm.mi_addnode(px, py)

        # Side lines (radial)
        femm.mi_drawline(p1[0], p1[1], p4[0], p4[1])  # left side
        femm.mi_drawline(p2[0], p2[1], p3[0], p3[1])  # right side

        # Inner edge: arc from p1 to p2 at inner_r
        sweep_deg = math.degrees(2 * half_w)
        maxseg_deg = getattr(self, "_femm_current_arc_maxseg_deg", 1.0)
        femm.mi_drawarc(p1[0], p1[1], p2[0], p2[1], sweep_deg, maxseg_deg)

        # Outer edge: arc from p4 to p3 at outer_r
        femm.mi_drawarc(p4[0], p4[1], p3[0], p3[1], sweep_deg, maxseg_deg)

    def _draw_polygon(self, femm, points: tuple[tuple[float, float], ...]):
        """Draw a closed straight-sided polygon in FEMM."""
        for px, py in points:
            femm.mi_addnode(px, py)
        for idx, (x1, y1) in enumerate(points):
            x2, y2 = points[(idx + 1) % len(points)]
            femm.mi_drawline(x1, y1, x2, y2)

    @staticmethod
    def _polygon_centroid(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
        return (
            sum(x for x, _ in points) / len(points),
            sum(y for _, y in points) / len(points),
        )

    @staticmethod
    def _rotate_point(point: tuple[float, float], angle_rad: float) -> tuple[float, float]:
        if abs(angle_rad) <= 1e-12:
            return point
        x, y = point
        c = math.cos(angle_rad)
        s = math.sin(angle_rad)
        return (x * c - y * s, x * s + y * c)

    def _rotate_points(
        self,
        points: tuple[tuple[float, float], ...],
        angle_rad: float,
    ) -> tuple[tuple[float, float], ...]:
        if abs(angle_rad) <= 1e-12:
            return points
        return tuple(self._rotate_point(point, angle_rad) for point in points)

    def _apply_winding_current(
        self, femm, config: MotorConfig, geom: MotorGeometry,
        elec_angle_deg: float
    ):
        """Apply 3-phase winding current density to slot regions (Milestone 3).

        Each slot gets its own material with J set via mi_addmaterial (5th arg),
        NOT via mi_setblockprop (that's the turns parameter — different field).
        Bug reference: Sprint 3 smoke test Bug #2.

        S45-01 current-angle convention (S46 sign ruling):
        current_angle_deg is gamma from the q-axis. Positive gamma is
        flux-weakening advance, so the source angle is
        theta_e = rotor_elec - 90° + gamma for all topologies.
        """
        current_angle_for_calc = current_angle_elec_deg_for_rotor_elec(config, elec_angle_deg)
        if config.solve_params is not None:
            logger.info(
                "[SOLVE] current_angle_deg=%s, resolved=%.1f "
                "(gamma from q-axis; positive is flux-weakening advance)",
                config.solve_params.current_angle_deg,
                current_angle_for_calc,
            )

        if config.solve_params and config.solve_params.excitation_mode == "ideal_six_step_120":
            from backend.geometry_drawer import compute_3phase_current_density_for_rotor_elec

            currents = compute_3phase_current_density_for_rotor_elec(config, elec_angle_deg)
        else:
            currents = compute_3phase_current_density(config, current_angle_for_calc)

        for i, slot in enumerate(geom.slots):
            if config.winding.type == "distributed" and config.winding.layers >= 2:
                assignments = _slot_current_assignments(config, slot)
                for assignment in assignments:
                    layer = int(assignment["layer"])
                    slot_r = _slot_layer_label_radius(
                        slot.inner_radius_mm,
                        slot.outer_radius_mm,
                        layer,
                        len(assignments),
                    )
                    lx = slot_r * math.cos(slot.center_angle_rad)
                    ly = slot_r * math.sin(slot.center_angle_rad)

                    phase = str(assignment["phase"])
                    direction = str(assignment["direction"])
                    J = currents.get(phase, 0.0)
                    if direction == "out":
                        J = -J

                    slot_mat = f"Coil_s{i}_l{layer}"
                    femm.mi_addmaterial(slot_mat, 1, 1, 0, J, 0, 0, 0, 1, 0, 0, 0, 0, 0)

                    femm.mi_addblocklabel(lx, ly)
                    femm.mi_selectlabel(lx, ly)
                    self._set_femm_blockprop(femm, slot_mat, config, geom, "slot")
                    femm.mi_clearselected()

                    if i == 0 and layer == 1:
                        tagged_log(f"[SLOT] Slot[0] layer={layer} phase={phase} dir={direction} "
                              f"J={J:.1f} at ({lx:.1f}, {ly:.1f}) "
                              f"angle={math.degrees(slot.center_angle_rad):.1f} deg "
                              f"r={slot_r:.1f} (inner={slot.inner_radius_mm:.1f}, outer={slot.outer_radius_mm:.1f})")
                continue

            slot_r = (slot.inner_radius_mm + slot.outer_radius_mm) / 2
            lx = slot_r * math.cos(slot.center_angle_rad)
            ly = slot_r * math.sin(slot.center_angle_rad)

            J = currents.get(slot.phase, 0.0)
            if slot.direction == "out":
                J = -J  # Reverse current direction

            # Each slot needs its own material with the correct J value.
            # J is the 5th argument of mi_addmaterial (after H_c).
            slot_mat = f"Coil_s{i}"
            femm.mi_addmaterial(slot_mat, 1, 1, 0, J, 0, 0, 0, 1, 0, 0, 0, 0, 0)

            femm.mi_addblocklabel(lx, ly)
            femm.mi_selectlabel(lx, ly)
            self._set_femm_blockprop(femm, slot_mat, config, geom, "slot")
            femm.mi_clearselected()

            if i == 0:
                tagged_log(f"[SLOT] Slot[0] phase={slot.phase} dir={slot.direction} "
                      f"J={J:.1f} at ({lx:.1f}, {ly:.1f}) "
                      f"angle={math.degrees(slot.center_angle_rad):.1f}° "
                      f"r={slot_r:.1f} (inner={slot.inner_radius_mm:.1f}, outer={slot.outer_radius_mm:.1f})")
        slot_label_count = sum(_slot_label_count(config, slot.slot_index) for slot in geom.slots)
        tagged_log(f"[SLOT] ... {slot_label_count} slot labels placed")

    def _apply_boundary(self, femm, geom: MotorGeometry):
        """Apply zero vector potential boundary on stator outer circle."""
        # Already applied in _draw_full_geometry via selectarcsegment
        pass
