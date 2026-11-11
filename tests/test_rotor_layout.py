"""Rotor layout contract: inner rotors are unchanged; outer rotors are explicit and gated."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import qualification as qualification_module
from backend.benchmark_suite.physics import physics_sources
from backend.geometry import validate_geometry
from backend.geometry_drawer import bore_tooth_width_mm, narrowest_tooth_width_mm
from backend.geometry_ir import build_geometry_ir
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.magneto2d_adapter import build_magneto2d_payload, get_magneto2d_support_error
from backend.models import MotorConfig
from backend.public_policy import parse_public_solve_request, public_config_support_error

INNER = json.loads(Path("benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json").read_text(encoding="utf-8"))


def outer_config(**rotor) -> dict:
    """A 12-slot / 14-pole outer rotor near the LRK reference dimensions."""
    raw = copy.deepcopy(INNER)
    raw["topology"] = "SPM"
    raw["rotor_layout"] = "outer"
    raw["stator"].update(OD_mm=25.6, ID_mm=13.0, slot_count=12, stack_length_mm=10.0, slot_opening_mm=1.7,
                         tooth_width_mm=2.6, yoke_thickness_mm=1.75, tooth_shoe_enabled=False)
    raw["rotor"].update(OD_mm=30.78, ID_mm=28.0, magnet_thickness_mm=1.0, magnet_width_mm=4.71, pole_count=14)
    raw["rotor"].update(rotor)
    raw["solve_params"]["rotor_rotation_model"] = "remesh_per_step"
    return raw


def test_inner_rotor_dump_and_payload_omit_the_layout():
    config = MotorConfig.model_validate(INNER)
    assert config.rotor_layout == "inner"
    assert "rotor_layout" not in config.model_dump()
    assert "rotor_layout" not in json.loads(config.model_dump_json())
    assert "rotor_layout" not in build_magneto2d_payload(config)


def test_inner_rotor_keeps_its_size_floors():
    raw = copy.deepcopy(INNER)
    raw["rotor"]["magnet_thickness_mm"] = 1.0
    with pytest.raises(ValidationError, match="at least 2 mm for an inner-rotor"):
        MotorConfig.model_validate(raw)
    raw = copy.deepcopy(INNER)
    raw["stator"]["yoke_thickness_mm"] = 1.0
    with pytest.raises(ValidationError, match="stator.yoke_thickness_mm must be at least 2 mm"):
        MotorConfig.model_validate(raw)


def test_outer_rotor_round_trips_and_reaches_the_solver_payload():
    config = MotorConfig.model_validate(outer_config())
    assert config.rotor_layout == "outer"
    assert MotorConfig.model_validate(config.model_dump()).rotor_layout == "outer"
    assert build_magneto2d_payload(config)["rotor_layout"] == "outer"


@pytest.mark.parametrize(("change", "message"), [
    ({"ID_mm": None}, "requires rotor.ID_mm"),
    ({"ID_mm": 27.5}, "magnet face"),
])
def test_outer_rotor_magnets_must_clear_the_stator(change, message):
    with pytest.raises(ValidationError, match=message):
        MotorConfig.model_validate(outer_config(**change))


def test_outer_rotor_is_spm_only():
    raw = outer_config()
    raw["topology"] = "IPM"
    with pytest.raises(ValidationError, match="SPM surface magnets only"):
        MotorConfig.model_validate(raw)


def test_paths_that_assume_an_inner_rotor_refuse_outer_rotors():
    config = MotorConfig.model_validate(outer_config())
    assert public_config_support_error(config, solver_id="elmer").field == "solver"
    assert public_config_support_error(config, require_solve_params=True) is None
    fixed_mesh = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"rotor_rotation_model": "fixed_mesh"})})
    assert "remesh_per_step" in get_magneto2d_support_error(fixed_mesh)


def test_layout_and_reference_registry_are_hashed_physics() -> None:
    # Both decide what is solved: the layout helper sets excitation, boundaries and
    # the torque sign, and the registry chooses reference implementations. A change
    # to either must lose a qualified label (review on #200).
    sources = set(physics_sources(Path(".")))
    assert {"backend/rotor_layout.py", "backend/reference_models/__init__.py"} <= sources


def test_outer_rotor_is_experimental_where_the_inner_combination_is_qualified(monkeypatch):
    # Single-layer concentrated SPM under sinusoidal current on M350-50A is qualified for inner rotors only.
    monkeypatch.setattr(qualification_module, "evidence_matches_runtime", lambda: True)
    assert qualification_module.classify_qualification(MotorConfig.model_validate(INNER))["status"] == "qualified"
    outer = qualification_module.classify_qualification(MotorConfig.model_validate(outer_config()))
    assert (outer["status"], outer["reason"]) == (
        "experimental", "Outer-rotor SPM: qualification currently covers the registered benchmark requests only.")


def test_rotor_torque_sign_rules():
    from backend.solver import _ui_torque_flips

    # Inner rotors: unchanged clockwise flip for every native metric.
    assert _ui_torque_flips("weighted_stress", clockwise_positive=True, outer_rotor=False)
    assert not _ui_torque_flips("weighted_stress", clockwise_positive=False, outer_rotor=False)
    # Field integrals act on the body inside the gap, an outer rotor's stator.
    assert not _ui_torque_flips("weighted_stress", clockwise_positive=True, outer_rotor=True)
    assert _ui_torque_flips("contour", clockwise_positive=False, outer_rotor=True)
    # Energy derivatives are already rotor torque.
    assert _ui_torque_flips("energy_fd", clockwise_positive=True, outer_rotor=True)
    assert _ui_torque_flips("pm_source_work_fd", clockwise_positive=True, outer_rotor=True)


def test_outer_rotor_phase_axis_is_half_a_cycle_on():
    from backend.excitation import phase_axis_offset_deg

    inner = MotorConfig.model_validate(INNER)
    outer = MotorConfig.model_validate(outer_config())
    inner_like_outer = outer.model_copy(update={"rotor_layout": "inner"})
    assert phase_axis_offset_deg(outer) == phase_axis_offset_deg(inner_like_outer) + 180.0
    assert phase_axis_offset_deg(inner) == phase_axis_offset_deg(inner.model_copy(update={"rotor_layout": "inner"}))


@pytest.mark.parametrize(("slots", "poles", "layers"), [(12, 14, 1), (12, 14, 2), (9, 12, 2)])
def test_parametric_outer_rotor_geometry_covers_its_annulus(slots, poles, layers):
    raw = outer_config()
    raw["stator"]["slot_count"] = slots
    raw["rotor"].update(pole_count=poles, magnet_width_mm=min(4.71, 0.8 * 2 * math.pi * 13.5 / poles))
    raw["winding"].update(type="concentrated", layers=layers)
    config = MotorConfig.model_validate(raw)
    ir = build_geometry_ir(config, rotor_angle_deg=0.0)
    assert ir.rotor_layout == "outer" and ir.validation_report().issues == ()
    covered = sum(region.area_mm2 for region in ir.regions)
    assert covered == pytest.approx(math.pi * ((config.rotor.OD_mm / 2) ** 2 - (config.stator.ID_mm / 2) ** 2), rel=1e-9)
    windings = [region for region in ir.regions if region.kind == "SlotWinding"]
    assert len(windings) == slots * layers
    magnet = next(region for region in ir.regions if region.region_id == "magnet_0")
    assert magnet.magnetization_xy == pytest.approx((-1.0, 0.0))


def test_a_36_slot_40_pole_outrunner_builds_and_64_poles_is_the_cap():
    # Robot-joint and large drone outrunners run 40 poles and more: the dimensions of the
    # 36-slot / 40-pole joint motor in MDPI Electronics 12(2):397 (2023), Table 1.
    raw = outer_config()
    raw["stator"].update(OD_mm=76.4, ID_mm=58.5, slot_count=36, stack_length_mm=7.0, slot_opening_mm=2.5,
                         tooth_width_mm=2.0, yoke_thickness_mm=1.5)
    raw["rotor"].update(ID_mm=81.0, OD_mm=84.0, magnet_thickness_mm=1.8, magnet_width_mm=5.53, pole_count=40)
    raw["winding"].update(type="concentrated", layers=2)
    ir = build_geometry_ir(MotorConfig.model_validate(raw), rotor_angle_deg=0.0)
    assert ir.validation_report().issues == ()
    assert sum(region.kind == "Magnet" for region in ir.regions) == 40
    assert sum(region.kind == "SlotWinding" for region in ir.regions) == 72
    with pytest.raises(ValidationError, match="less than or equal to 64"):
        MotorConfig.model_validate({**raw, "rotor": {**raw["rotor"], "pole_count": 66}})


def _joint_motor(**stator) -> dict:
    """The 36-slot / 40-pole robot-joint outrunner (MDPI Electronics 12(2):397, Table 1) with its tooth shoes:
    parallel 2 mm teeth (a 4.67 mm body opening at the stator OD) and shoes leaving a 2.5 mm mouth."""
    raw = outer_config()
    raw["stator"].update(OD_mm=76.4, ID_mm=58.5, slot_count=36, stack_length_mm=7.0, slot_opening_mm=4.67, tooth_width_mm=2.0,
                         yoke_thickness_mm=1.5, tooth_shoe_enabled=True, tooth_shoe_height_mm=0.7, tooth_shoe_overhang_mm=1.085)
    raw["stator"].update(stator)
    raw["rotor"].update(ID_mm=81.0, OD_mm=84.0, magnet_thickness_mm=1.8, magnet_width_mm=5.53, pole_count=40)
    raw["winding"].update(type="concentrated", layers=2)
    return raw


def test_outer_rotor_tooth_shoes_widen_the_tips_at_the_stator_od():
    config = MotorConfig.model_validate(_joint_motor())
    ir = build_geometry_ir(config, rotor_angle_deg=0.0)
    assert ir.validation_report().issues == ()
    assert sum(region.area_mm2 for region in ir.regions) == pytest.approx(math.pi * (42.0**2 - 29.25**2), rel=1e-9)
    assert sum(region.kind == "SlotWinding" for region in ir.regions) == 72
    # Each tip is the body's 2 mm plus two 1.085 mm overhangs, leaving the 2.5 mm mouth.
    tip_mm = bore_tooth_width_mm(config)
    assert tip_mm == pytest.approx(2 * math.pi * 38.2 / 36 - 4.67 + 2 * 1.085)
    assert 2 * math.pi * 38.2 / 36 - tip_mm == pytest.approx(2.5, abs=1e-6)
    tooth = next(region for region in ir.regions if region.region_id == "stator_tooth_0")
    tip_arc = tooth.loops[0].segments[0]
    assert tip_arc.kind == "arc" and tip_arc.radius_mm == pytest.approx(38.2)
    assert math.radians(tip_arc.sweep_deg) * 38.2 == pytest.approx(tip_mm, rel=1e-9)
    # The body below the shoe keeps the parallel 2 mm teeth; the tooth sample sits in it.
    assert narrowest_tooth_width_mm(config) == pytest.approx(2.0, abs=0.02)
    assert ir.metadata["tooth_sample_radius_mm"] == pytest.approx(0.5 * (30.75 + 37.5))
    mesh = run_gmsh_mesh_preview(config, rotor_angle_deg=0.0)
    assert mesh["mesh_info"]["num_triangles"] > 0


def test_the_bundled_robot_joint_example_is_that_motor():
    example = json.loads(Path("frontend/src/public/examples/joint_outrunner_36s40p.coilem").read_text(encoding="utf-8"))
    config, _, solver = parse_public_solve_request(example)
    joint = MotorConfig.model_validate(_joint_motor())
    assert (solver, config.rotor_layout, config.winding.layers, config.winding.turns_per_coil) == ("magneto2d", "outer", 2, 26)
    for section, fields in (("stator", ("OD_mm", "ID_mm", "slot_count", "stack_length_mm", "slot_opening_mm", "tooth_width_mm",
                                        "yoke_thickness_mm", "tooth_shoe_enabled", "tooth_shoe_height_mm", "tooth_shoe_overhang_mm")),
                            ("rotor", ("ID_mm", "OD_mm", "magnet_thickness_mm", "magnet_width_mm", "pole_count"))):
        for field in fields:
            assert getattr(getattr(config, section), field) == getattr(getattr(joint, section), field), (section, field)
    assert build_geometry_ir(config, rotor_angle_deg=0.0).validation_report().issues == ()


def test_the_bundled_drone_example_is_koo_and_shin_model_b():
    # Model B of the 36-slot / 40-pole drone outrunners in Koo & Shin, Energies 19(16):3845 (2026).
    # Table 1 radii (mm): rotor 46, magnet back 44.2, magnet face 42, stator 41.6, shoe shoulder 40.2,
    # slot bottom 30, hub 27; 5 turns per tooth coil, 17 mm stack. Fig. 2 (to scale) gives the 2.75 mm
    # parallel teeth and the 1.55 mm mouth.
    example = json.loads(Path("frontend/src/public/examples/drone_outrunner_36s40p_b.coilem").read_text(encoding="utf-8"))
    config, _, solver = parse_public_solve_request(example)
    stator, rotor = config.stator, config.rotor
    assert (solver, config.rotor_layout, config.winding.layers, config.winding.turns_per_coil) == ("magneto2d", "outer", 2, 10)
    assert (stator.OD_mm, stator.ID_mm, stator.slot_count, stator.stack_length_mm) == (83.2, 54.0, 36, 17.0)
    assert (rotor.OD_mm, rotor.ID_mm, rotor.magnet_thickness_mm, rotor.pole_count) == (92.0, 88.4, 2.2, 40)
    assert rotor.ID_mm / 2 - rotor.magnet_thickness_mm - stator.OD_mm / 2 == pytest.approx(0.4)
    assert stator.OD_mm / 2 - ((stator.OD_mm - stator.ID_mm) / 2 - stator.yoke_thickness_mm) == pytest.approx(30.0)
    assert stator.OD_mm / 2 - stator.tooth_shoe_height_mm == pytest.approx(40.2)
    assert narrowest_tooth_width_mm(config) == pytest.approx(2.75, abs=0.02)
    assert 2 * math.pi * 41.6 / 36 - bore_tooth_width_mm(config) == pytest.approx(1.55, abs=0.01)
    assert {config.materials.stator_steel, config.materials.rotor_steel} <= set(config.materials.custom_steels)
    assert build_geometry_ir(config, rotor_angle_deg=0.0).validation_report().issues == ()


def test_an_outer_rotor_shoe_must_leave_room_for_the_winding():
    config = MotorConfig.model_validate(_joint_motor(tooth_shoe_height_mm=7.0))
    errors = validate_geometry(config)
    assert [error.field for error in errors] == ["stator.tooth_shoe_height_mm"]
    assert "leaves" in errors[0].message


def test_outer_rotor_geometry_checks():
    assert validate_geometry(MotorConfig.model_validate(outer_config())) == []
    tight = MotorConfig.model_validate(outer_config(ID_mm=27.7))
    assert any("Airgap" in error.message for error in validate_geometry(tight))
    wide = MotorConfig.model_validate(outer_config(magnet_width_mm=6.5))
    assert any(error.field == "rotor.magnet_width_mm" for error in validate_geometry(wide))


def test_outer_rotor_keeps_the_shared_winding_and_slot_opening_checks():
    # Review on #202: outer designs skipped the winding checks, and accepted slot
    # openings that the geometry builder then quietly clamped to the slot pitch.
    from backend.geometry import validate_geometry

    starter = json.loads(Path("frontend/src/public/examples/spm_outrunner_14p12s.coilem").read_text(encoding="utf-8"))
    assert validate_geometry(MotorConfig.model_validate(starter)) == []

    paths = copy.deepcopy(starter)
    paths["winding"]["parallel_paths"] = 3  # four coils per phase do not split three ways
    assert [error.field for error in validate_geometry(MotorConfig.model_validate(paths))] == ["winding.parallel_paths"]

    unbalanced = copy.deepcopy(starter)
    unbalanced["stator"]["slot_count"] = 16
    assert "stator.slot_count" in [error.field for error in validate_geometry(MotorConfig.model_validate(unbalanced))]

    opening = copy.deepcopy(starter)
    opening["stator"]["slot_opening_mm"] = 20.0
    errors = validate_geometry(MotorConfig.model_validate(opening))
    assert [error.field for error in errors] == ["stator.slot_opening_mm"]
    pitch = math.pi * starter["stator"]["OD_mm"] / starter["stator"]["slot_count"]
    assert f"{pitch:.2f}mm slot pitch at the stator OD" in errors[0].message
