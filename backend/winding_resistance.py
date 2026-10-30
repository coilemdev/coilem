"""Phase resistance, mean turn length and slot fill of the stator winding.

Turns follow coilEM's convention (backend.winding_utils.series_turns_per_path):
``turns_per_coil`` is the conductor count of one slot, so one phase has
slot_count · turns_per_coil / 6 series turns, split evenly among its parallel
paths. With a paths, the phase is a paths in parallel of N/a turns each:

    R = rho · N · MLT / (A_turn · a²)

Mean turn length (MLT) is two active legs of the stack length plus two end
turns. Each end turn is modelled as a half circle across the circumferential
arc between the coil's two coil sides, at area centroids in the geometry IR,
plus any straight axial extension out of the slot and back. A tooth coil's
sides are the slot halves next to its tooth. A distributed coil runs from one
layer to the other, so its sides are taken at the whole slots' centroids, a
coil span apart.

Slot fill is bare copper over the gross slot polygon. Published fill factors
often use a net slot area after liner and wedge, so they read higher.

Conductor data are the standard values for winding wire:
  * copper: IEC 60028 annealed copper, 1/58 Ohm·mm²/m and 0.00393 /K at 20 °C;
  * aluminium: IEC 60889 hard-drawn aluminium, 0.028264 Ohm·mm²/m and
    0.00403 /K at 20 °C.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

from backend.geometry_ir import GeometryIR, build_geometry_ir
from backend.geometry_ir_tessellation import polygon_centroid, tessellate_ir_region
from backend.models import MotorConfig, WindingCoil
from backend.models.performance import WindingResistance

REFERENCE_TEMPERATURE_C = 20.0
# A common design guideline for random-wound round wire, not a standard;
# set winding.wire.slot_fill_limit for needle-wound or hairpin coils.
DEFAULT_COPPER_FILL_LIMIT = 0.45
_SLOT_SIDE = re.compile(r":slot(\d+)(?::layer(\d+))?$")


@dataclass(frozen=True)
class ConductorProperties:
    resistivity_20c_ohm_m: float
    temperature_coefficient_per_k: float


CONDUCTORS = {
    "copper": ConductorProperties(resistivity_20c_ohm_m=1.0e-6 / 58.0, temperature_coefficient_per_k=0.00393),
    "aluminum": ConductorProperties(resistivity_20c_ohm_m=0.028264e-6, temperature_coefficient_per_k=0.00403),
}


def winding_resistance(
    config: MotorConfig,
    *,
    geometry_ir: GeometryIR | None = None,
    winding_coils: Sequence[WindingCoil] | None = None,
) -> WindingResistance:
    """Resistance and fill of the configured winding, from its geometry and wire."""

    stator, winding = config.stator, config.winding
    ir = geometry_ir if geometry_ir is not None else build_geometry_ir(config)
    sides, slot_areas = _slot_sides(ir)
    if not slot_areas:
        raise ValueError("the stator has no slot winding regions")
    slot_area_mm2 = sum(slot_areas.values()) / len(slot_areas)
    coils = list(winding_coils) if winding_coils is not None else _winding_coils(config)
    if not coils:
        raise ValueError("the winding has no coils")

    conductor_name = config.materials.conductor if config.materials else "copper"
    conductor = CONDUCTORS[conductor_name]
    conductors_per_slot = winding.turns_per_coil
    paths = winding.parallel_paths
    series_turns = stator.slot_count * conductors_per_slot / 6.0
    wire = winding.wire
    fill_limit = wire.slot_fill_limit if wire is not None and wire.slot_fill_limit is not None else DEFAULT_COPPER_FILL_LIMIT
    notes: list[str] = []

    if wire is not None:
        wire_source = "specified"
        strand_diameter_mm = wire.wire_bare_diameter_mm
        strands = wire.strands_in_hand
        turn_area_mm2 = strands * math.pi * strand_diameter_mm**2 / 4.0
    else:
        wire_source = "derived"
        strands = 1
        turn_area_mm2 = fill_limit * slot_area_mm2 / conductors_per_slot
        strand_diameter_mm = math.sqrt(4.0 * turn_area_mm2 / math.pi)
        notes.append(
            f"No wire is set, so the wire size is derived to fill {fill_limit:.0%} of the slot with copper. "
            "Set the wire to compute the real resistance."
        )

    copper_fill = conductors_per_slot * turn_area_mm2 / slot_area_mm2
    wire_fill = None
    if wire is not None and wire.insulation_build_mm is not None:
        insulated_diameter_mm = strand_diameter_mm + wire.insulation_build_mm
        wire_fill = conductors_per_slot * strands * math.pi * insulated_diameter_mm**2 / 4.0 / slot_area_mm2
    fits = copper_fill <= fill_limit + 1e-12 and (wire_fill is None or wire_fill <= 1.0)
    if copper_fill > fill_limit + 1e-12:
        notes.append(f"The copper fills {copper_fill:.0%} of the slot, above the {fill_limit:.0%} limit.")
    if wire_fill is not None and wire_fill > 1.0:
        notes.append(f"The insulated wire needs {wire_fill:.0%} of the slot area, so it cannot fit.")

    extension_mm = wire.end_turn_extension_mm if wire is not None and wire.end_turn_extension_mm is not None else 0.0
    end_turn_mm = sum(_end_turn_length_mm(coil, sides) for coil in coils) / len(coils) + 2.0 * extension_mm
    stack_mm = stator.stack_length_mm
    mean_turn_mm = 2.0 * stack_mm + 2.0 * end_turn_mm

    resistance_20c = conductor.resistivity_20c_ohm_m * series_turns * mean_turn_mm * 1e-3 / (turn_area_mm2 * 1e-6 * paths**2)
    solve_params = config.solve_params
    temperature_c = (
        solve_params.winding_temperature_C
        if solve_params is not None and solve_params.winding_temperature_C is not None
        else REFERENCE_TEMPERATURE_C
    )
    resistance = resistance_20c * (1.0 + conductor.temperature_coefficient_per_k * (temperature_c - REFERENCE_TEMPERATURE_C))

    return WindingResistance(
        wire_source=wire_source,
        conductor=conductor_name,
        strand_diameter_mm=strand_diameter_mm,
        strands_in_hand=strands,
        turn_copper_area_mm2=turn_area_mm2,
        conductors_per_slot=conductors_per_slot,
        series_turns_per_phase=series_turns,
        parallel_paths=paths,
        slot_area_mm2=slot_area_mm2,
        copper_fill=copper_fill,
        copper_fill_limit=fill_limit,
        wire_fill=wire_fill,
        fits=fits,
        stack_length_mm=stack_mm,
        end_turn_length_mm=end_turn_mm,
        mean_turn_length_mm=mean_turn_mm,
        active_fraction=2.0 * stack_mm / mean_turn_mm,
        phase_resistance_20C_ohm=resistance_20c,
        temperature_coefficient_per_K=conductor.temperature_coefficient_per_k,
        winding_temperature_C=temperature_c,
        phase_resistance_ohm=resistance,
        notes=notes,
    )


Point = tuple[float, float]


def _slot_sides(ir: GeometryIR) -> tuple[dict[int, list[tuple[Point, float]]], dict[int, float]]:
    """Area centroid and area of every coil-side region, and the gross area of every slot."""

    sides: dict[int, list[tuple[Point, float]]] = {}
    areas: dict[int, float] = {}
    for region in ir.regions:
        if region.kind != "SlotWinding":
            continue
        match = _SLOT_SIDE.search(region.source_group or "")
        if match is None:
            continue
        slot = int(match.group(1))
        points = tessellate_ir_region(region)
        area, centroid = _area_and_centroid(points)
        sides.setdefault(slot, []).append((centroid, area))
        areas[slot] = areas.get(slot, 0.0) + area
    return sides, areas


def _end_turn_length_mm(coil: WindingCoil, sides: dict[int, list[tuple[Point, float]]]) -> float:
    """Half circle across the arc between the coil's two coil sides."""

    regions_in = sides.get(coil.slot_in)
    regions_out = sides.get(coil.slot_out)
    if not regions_in or not regions_out:
        raise ValueError(f"coil {coil.coil_index} names a slot with no winding region")
    if coil.tooth_wound:
        # Of a split slot's two halves, the tooth coil holds the one beside its tooth.
        first, second = min(
            ((a, b) for a, _ in regions_in for b, _ in regions_out),
            key=lambda pair: math.dist(pair[0], pair[1]),
        )
    else:
        first, second = _slot_centroid(regions_in), _slot_centroid(regions_out)
    radius = (math.hypot(*first) + math.hypot(*second)) / 2.0
    angle = abs(math.atan2(first[1], first[0]) - math.atan2(second[1], second[0]))
    angle = min(angle, 2.0 * math.pi - angle)
    return math.pi / 2.0 * angle * radius


def _slot_centroid(regions: list[tuple[Point, float]]) -> Point:
    total = sum(area for _, area in regions)
    if total <= 0:
        return regions[0][0]
    return (
        sum(point[0] * area for point, area in regions) / total,
        sum(point[1] * area for point, area in regions) / total,
    )


def _area_and_centroid(points: list[list[float]]) -> tuple[float, tuple[float, float]]:
    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    twice_area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(twice_area) < 1e-12:
        x, y = polygon_centroid(points)
        return 0.0, (x, y)
    return abs(twice_area) / 2.0, (cx / (3.0 * twice_area), cy / (3.0 * twice_area))


def _winding_coils(config: MotorConfig) -> list[WindingCoil]:
    # The preview owns the coil derivation; import late because it imports this module.
    from backend.preview import _derive_winding_coils, _generate_winding_layout

    stator, rotor, winding = config.stator, config.rotor, config.winding
    layout, metadata = _generate_winding_layout(
        stator.slot_count,
        rotor.pole_count,
        winding.type,
        winding.turns_per_coil,
        stator.ID_mm,
        winding.layers,
        winding.parallel_paths,
        winding.coil_span,
    )
    return _derive_winding_coils(
        layout,
        stator.slot_count,
        winding.type,
        float(metadata.get("coil_span_slots", 1.0) or 1.0),
        rotor.pole_count,
        winding.layers,
    )
