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
