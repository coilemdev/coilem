"""Rotor layout contract: inner rotors are unchanged; outer rotors are explicit and gated."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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
    with pytest.raises(OuterRotorUnsupportedError):
        build_geometry_ir(config)
    assert public_config_support_error(config, solver_id="elmer").field == "solver"
    assert public_config_support_error(config, require_solve_params=True).field == "rotor_layout"
    fixed_mesh = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"rotor_rotation_model": "fixed_mesh"})})
    assert "remesh_per_step" in get_magneto2d_support_error(fixed_mesh)
