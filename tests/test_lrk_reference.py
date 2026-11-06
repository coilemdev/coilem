"""The LRK 12s/14p outer-rotor reference on the normal geometry, preview and mesh path."""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.geometry_ir import build_geometry_ir, slot_layer_assignments
from backend.models import MotorConfig
from backend.reference_models import lrk, reference_model

CONFIG = json.loads(Path("backend/reference_models/lrk_12s14p_config.json").read_text(encoding="utf-8"))


def config(case=None) -> MotorConfig:
    raw = copy.deepcopy(CONFIG)
    raw["reference_case"] = case
    return MotorConfig.model_validate(raw)


def test_reference_is_registered_outer_spm():
    cfg = config()
    assert cfg.rotor_layout == "outer"
    assert reference_model(cfg).reference_id == "lrk_12s14p"
    assert config(lrk.FIXED_CURRENT_CASE).reference_case == lrk.FIXED_CURRENT_CASE


@pytest.mark.parametrize(("section", "field", "value"), [
    ("stator", "slot_count", 15), ("winding", "turns_per_coil", 16), ("materials", "magnet_grade", "N42"),
])
def test_pinned_design_rejects_edits(section, field, value):
    raw = copy.deepcopy(CONFIG)
    raw[section][field] = value
    with pytest.raises(ValidationError):
        MotorConfig.model_validate(raw)


def test_exact_drawing_lowers_to_the_expected_regions():
    ir = build_geometry_ir(config(), rotor_angle_deg=0.0)
    assert ir.rotor_layout == "outer"
    assert Counter(region.kind for region in ir.regions) == {
        "StatorYoke": 1, "StatorTooth": 12, "SlotWinding": 12, "Airgap": 1, "Magnet": 14, "MagnetPocketAir": 1, "RotorCore": 1,
    }
    covered = sum(region.area_mm2 for region in ir.regions)
    assert covered == pytest.approx(math.pi * (15.39**2 - 6.5**2), rel=1e-10)
    assert ir.validation_report().issues == ()
    tagged = [segment for region in ir.regions for loop in region.loops for segment in loop.segments if segment.boundary_tag]
    assert {round(math.hypot(s.start.x_mm, s.start.y_mm), 6) for s in tagged} == {6.5, 15.39}
    assert max(abs(s.sweep_deg) for r in ir.regions for loop in r.loops for s in loop.segments if s.kind == "arc") <= 90.0


def test_turned_stator_carries_the_generic_tooth_coil_map():
    cfg = config()
    for region in build_geometry_ir(cfg, rotor_angle_deg=0.0).regions:
        if region.kind == "SlotWinding":
            _, phase, direction, slot = region.source_group.split(":")
            expected = slot_layer_assignments(cfg, int(slot.removeprefix("slot")))[0]
            assert (phase, direction) == (expected.phase, expected.direction)


@pytest.mark.parametrize("angle", [0.0, 30.0])
def test_pole_zero_north_faces_the_gap_at_the_rotor_angle(angle):
    ir = build_geometry_ir(config(), rotor_angle_deg=angle)
    magnet = next(region for region in ir.regions if region.region_id == "magnet_0")
    assert magnet.source_group == "pm:N:magnet0"
    # Radially inward at the rotor angle: north faces the stator across the gap.
    assert magnet.magnetization_xy == pytest.approx((-math.cos(math.radians(angle)), -math.sin(math.radians(angle))))


def test_preview_is_clean_and_describes_an_outer_rotor():
    from backend.preview import generate_preview

    preview = generate_preview(config())
    assert preview.validation_errors == []
    assert preview.metadata["airgap_mm"] == pytest.approx(0.2)
    assert preview.metadata["radial_layout"] == "outer_rotor"
    assert preview.metadata["outer_radius_mm"] == 15.39
    # The 12s/14p tooth-coil axis (15) plus half a cycle for the outer rotor.
    assert preview.metadata["phase_axis_offset_elec_deg"] == 195.0


def test_native_mesh_keeps_every_region():
    from backend.gmsh_solver import run_gmsh_mesh_preview

    mesh = run_gmsh_mesh_preview(config(), rotor_angle_deg=0.0)
    ids = set(mesh["solve_mesh_artifact"]["element_region_ids"])
    assert {"stator_yoke", "airgap", "rotor_air", "rotor_core", "magnet_0", "slot_winding_0", "stator_tooth_0"} <= ids
    assert len(ids) == 42


def test_export_tool_reproduces_the_pinned_config():
    from tools.export_lrk_reference import reference_config

    assert reference_config() == CONFIG


def test_outer_mesh_pins_exactly_the_rotor_od_and_hub_bore():
    from backend.gmsh_solver import run_gmsh_mesh_preview

    artifact = run_gmsh_mesh_preview(config(), rotor_angle_deg=15.0)["solve_mesh_artifact"]
    mesh = artifact["mesh"]
    radii = {round(math.hypot(*mesh["nodes"][i]), 4) for i in mesh["boundary_nodes"]}
    assert radii == {6.5, 15.39}
    assert mesh["boundary_nodes"] == sorted(set(mesh["boundary_nodes"]))
    info = mesh["info"]
    assert (info["airgap_inner_radius_mm"], info["airgap_outer_radius_mm"]) == (12.8, 13.0)
    assert info["outer_rotor"]["yoke_sample_radius_mm"] < 8.25 < info["outer_rotor"]["tooth_sample_radius_mm"] < 12.8
