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
    assert preview.metadata["phase_axis_offset_elec_deg"] == 15.0


def test_native_mesh_keeps_every_region():
    from backend.gmsh_solver import run_gmsh_mesh_preview

    mesh = run_gmsh_mesh_preview(config(), rotor_angle_deg=0.0)
    ids = set(mesh["solve_mesh_artifact"]["element_region_ids"])
    assert {"stator_yoke", "airgap", "rotor_air", "rotor_core", "magnet_0", "slot_winding_0", "stator_tooth_0"} <= ids
    assert len(ids) == 42


def test_export_tool_reproduces_the_pinned_config():
    from tools.export_lrk_reference import reference_config

    assert reference_config() == CONFIG


def test_fixed_current_case_losses_use_the_held_currents():
    # Review on #201: copper loss read the sinusoidal settings the case ignores,
    # 24R for the bundled 4 A peak settings instead of (0² + 4² + 4²)R = 32R.
    from backend.loss_breakdown import operating_point_losses, phase_current_rms_a

    cfg = config(lrk.FIXED_CURRENT_CASE)
    # The bundled fixed-current file's settings: 4 A peak sinusoidal.
    cfg.solve_params.excitation_mode = "sinusoidal"
    cfg.solve_params.current_amplitude_convention = "peak"
    cfg.solve_params.current_amplitude_A = 4.0
    winding, losses = operating_point_losses(cfg, 0.05, None)
    assert losses.copper_loss_W == pytest.approx(32.0 * winding.phase_resistance_ohm)
    louder = cfg.model_copy(deep=True)
    louder.solve_params.current_amplitude_A = 8.0
    assert phase_current_rms_a(louder) == pytest.approx(phase_current_rms_a(cfg))
    # Without the case, the solve settings apply again.
    generic = cfg.model_copy(update={"reference_case": None})
    assert phase_current_rms_a(generic) == pytest.approx(4.0 / math.sqrt(2.0))

    report = {"operating_point": {"resolved_phase_current_peak_a": cfg.solve_params.current_amplitude_A}}
    lrk.postprocess_report(report, cfg, None)
    # 0/-4/+4 A is the instant of a balanced set where phase A crosses zero.
    assert report["operating_point"]["resolved_phase_current_peak_a"] == pytest.approx(4.0 / math.sin(math.radians(60.0)))
