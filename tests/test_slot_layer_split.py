"""Two-layer slots split into equal-area layer regions that mesh conformally (#91).

Distributed double layers stack radially; tooth coils sit side by side on the
slot centre line. Before #91 the radial split broke each slot wall at
mid-radius while the tooth kept one unbroken edge, so slot and tooth never
shared nodes along the wall (4416 unmatched edges on 8p48s; +0.86% torque and
back-EMF against the same machine wound in one layer), and tooth shoes
switched the split off entirely.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import pytest

from backend.geometry_ir import build_geometry_ir, slot_layer_assignments, slot_layer_split
from backend.gmsh_solver import GMSH_AVAILABLE, run_gmsh_mesh_preview
from backend.models import MotorConfig
from backend.preview import generate_preview

pytestmark = pytest.mark.pr

BENCHMARK = Path("benchmarks/main-20261009-bad71d9/fixtures")
CONCENTRATED = Path("tests/fixtures/spm_8p12s_concentrated.json")

CASES = {
    "distributed-full-pitch": (BENCHMARK / "spm_8p24s_distributed_femm_validation.json", {}),
    "distributed-chorded-shoe": (
        BENCHMARK / "spm_8p48s_chorded_5_6.json",
        {"stator": {"tooth_shoe_enabled": True, "tooth_shoe_overhang_mm": 0.5}},
    ),
    "tooth-coils": (CONCENTRATED, {"winding": {"layers": 2}}),
    "tooth-coils-shoe": (
        CONCENTRATED,
        {"winding": {"layers": 2}, "stator": {"tooth_shoe_enabled": True, "tooth_shoe_overhang_mm": 0.5}},
    ),
}


def _config(path: Path, overrides: dict, **winding) -> MotorConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["materials"].update(stator_steel="M350-50A", rotor_steel="M350-50A")
    for section, values in overrides.items():
        data[section].update(values)
    data["winding"].update(winding)
    data["solve_params"]["mesh_density"] = "coarse"
    return MotorConfig.model_validate(data)


def _slot_regions(config: MotorConfig) -> dict[int, list]:
    by_slot: dict[int, list] = {}
    for region in build_geometry_ir(config).regions:
        if region.kind == "SlotWinding":
            slot = int(region.region_id.split("_")[2])
            by_slot.setdefault(slot, []).append(region)
    return by_slot


@pytest.mark.parametrize("case", CASES, ids=str)
def test_each_slot_splits_into_two_equal_area_layers(case: str) -> None:
    path, overrides = CASES[case]
    config = _config(path, overrides)
    ir = build_geometry_ir(config)
    assert ir.validation_report().issues == ()
    assert ir.metadata["slot_layer_split"] == slot_layer_split(config)
    whole = _slot_regions(_config(path, overrides, layers=1, coil_span=None))
    for slot, regions in _slot_regions(config).items():
        assert [region.region_id for region in regions] == [
            f"slot_winding_{slot}_layer1",
            f"slot_winding_{slot}_layer2",
        ]
        assert regions[0].area_mm2 == pytest.approx(regions[1].area_mm2, rel=1e-6)
        assert regions[0].area_mm2 + regions[1].area_mm2 == pytest.approx(whole[slot][0].area_mm2, rel=1e-9)
        expected = [
            f"winding:{side.phase}:{side.direction}:slot{slot}:layer{side.layer}"
            for side in slot_layer_assignments(config, slot)
        ]
        assert [region.source_group for region in regions] == expected


def test_split_direction_follows_the_winding() -> None:
    assert slot_layer_split(_config(*CASES["distributed-full-pitch"])) == "radial"
    assert slot_layer_split(_config(*CASES["tooth-coils"])) == "tangential"
    assert slot_layer_split(_config(CONCENTRATED, {})) is None
    # Single-layer slots keep one whole-slot region.
    regions = _slot_regions(_config(CONCENTRATED, {}))
    assert all(len(slot) == 1 and slot[0].region_id == f"slot_winding_{index}" for index, slot in regions.items())


def _area_centroid(points: list[list[float]]) -> tuple[float, float]:
    ring = points[:-1] if points[0] == points[-1] else points
    pairs = list(zip(ring, ring[1:] + ring[:1]))
    crosses = [x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs]
    twice_area = sum(crosses)
    return (
        sum((x0 + x1) * c for ((x0, _), (x1, _)), c in zip(pairs, crosses)) / (3 * twice_area),
        sum((y0 + y1) * c for ((_, y0), (_, y1)), c in zip(pairs, crosses)) / (3 * twice_area),
    )


def _inside(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _markers(config: MotorConfig) -> list[tuple[tuple[float, float], list[list[float]], object]]:
    """Each in/out marker's centre, its glyph points, and the coil side it sits in."""
    preview = generate_preview(config)
    sides = [region for region in preview.regions if region.region_type.startswith("slot_")]
    glyphs = [region for region in preview.regions if region.region_type == "winding_symbol"]
    markers: list[tuple[tuple[float, float], list[list[float]], object]] = []
    for glyph in glyphs:
        ring = glyph.points[:-1]
        if glyph.label.endswith("(in)"):
            # The dot is a regular octagon around the centre.
            centre = (sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring))
        else:
            # Each bar of the cross runs from +size to -size through the centre.
            centre = ((ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2)
            if markers and math.dist(centre, markers[-1][0]) < 1e-9:
                markers[-1][1].extend(ring)
                continue
        owners = [side for side in sides if _inside(centre, side.points)]
        assert len(owners) == 1, f"{glyph.label} marker at {centre} is not inside exactly one coil side"
        markers.append((centre, list(ring), owners[0]))
    assert len(markers) == len(sides)
    assert {id(side) for _, _, side in markers} == {id(side) for side in sides}
    return markers


@pytest.mark.parametrize("case", CASES, ids=str)
def test_each_marker_sits_at_the_centroid_of_its_own_coil_side(case: str) -> None:
    for centre, glyph, side in _markers(_config(*CASES[case])):
        assert math.dist(centre, _area_centroid(side.points)) < 0.01, side.label
        assert all(_inside(tuple(point), side.points) for point in glyph), side.label


def test_whole_slot_marker_stays_at_mid_radius_on_the_slot_centre_line() -> None:
    config = _config(CONCENTRATED, {})
    bore_r = config.stator.ID_mm / 2
    slot_bottom_r = config.stator.OD_mm / 2 - config.stator.yoke_thickness_mm
    pitch = 2 * math.pi / config.stator.slot_count
    for centre, glyph, side in _markers(config):
        slot = int(side.label.split()[1]) - 1
        expected_r = (bore_r + slot_bottom_r) / 2
        assert math.dist(centre, (expected_r * math.cos(slot * pitch), expected_r * math.sin(slot * pitch))) < 1e-9
        assert all(_inside(tuple(point), side.points) for point in glyph), side.label


@pytest.mark.skipif(not GMSH_AVAILABLE, reason="gmsh is not installed")
@pytest.mark.parametrize("case", CASES, ids=str)
def test_split_slots_mesh_conformally(case: str) -> None:
    preview = run_gmsh_mesh_preview(_config(*CASES[case]))
    nodes, triangles = preview["nodes_mm"], preview["triangles"]
    edges = Counter()
    for a, b, c in triangles:
        for start, end in ((a, b), (b, c), (c, a)):
            edges[(min(start, end), max(start, end))] += 1
    radii = [math.hypot(x, y) for x, y in nodes]
    inner, outer = min(radii) + 1e-3, max(radii) - 1e-3
    # Only the outer boundary (and an inner rotor bore) may have edges with one triangle.
    unmatched = [edge for edge, count in edges.items() if count == 1 and all(inner < radii[n] < outer for n in edge)]
    assert unmatched == []
