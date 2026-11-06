"""Rotor layout contract: inner rotors are unchanged; outer rotors are explicit and gated."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import qualification as qualification_module
from backend.geometry_ir import build_geometry_ir
from backend.magneto2d_adapter import build_magneto2d_payload, get_magneto2d_support_error
from backend.models import MotorConfig
from backend.public_policy import public_config_support_error
from backend.rotor_layout import OuterRotorUnsupportedError

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
    shoed = MotorConfig.model_validate({**outer_config(), "stator": {**outer_config()["stator"], "tooth_shoe_enabled": True,
                                                                       "tooth_shoe_overhang_mm": 0.5}})
    with pytest.raises(OuterRotorUnsupportedError, match="Tooth shoes"):
        build_geometry_ir(shoed)
    assert public_config_support_error(config, solver_id="elmer").field == "solver"
    assert public_config_support_error(config, require_solve_params=True) is None
    fixed_mesh = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"rotor_rotation_model": "fixed_mesh"})})
    assert "remesh_per_step" in get_magneto2d_support_error(fixed_mesh)


def test_outer_rotor_is_experimental_where_the_inner_combination_is_qualified(monkeypatch):
    # Single-layer concentrated SPM under sinusoidal current on M350-50A is qualified for inner rotors only.
    monkeypatch.setattr(qualification_module, "evidence_matches_runtime", lambda: True)
    assert qualification_module.classify_qualification(MotorConfig.model_validate(INNER))["status"] == "qualified"
    outer = qualification_module.classify_qualification(MotorConfig.model_validate(outer_config()))
    assert (outer["status"], outer["reason"]) == ("experimental", "Outer-rotor SPM: no benchmark fixture measures an outer rotor yet.")


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


def test_outer_rotor_geometry_checks():
    from backend.geometry import validate_geometry

    assert validate_geometry(MotorConfig.model_validate(outer_config())) == []
    tight = MotorConfig.model_validate(outer_config(ID_mm=27.7))
    assert any("Airgap" in error.message for error in validate_geometry(tight))
    wide = MotorConfig.model_validate(outer_config(magnet_width_mm=6.5))
    assert any(error.field == "rotor.magnet_width_mm" for error in validate_geometry(wide))
