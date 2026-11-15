"""Input interpretation is explicit without moving magnets or changing requests."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.geometry_drawer import compute_v_shape_magnet_placements
from backend.input_advisories import (
    drawn_magnet_coverage,
    geometry_input_advisories,
    geometry_mesh_advisories,
    partial_sweep_advisory,
    vshape_input_facts,
)
from backend.models import MotorConfig
from backend.preview import generate_preview
from backend.selected_analyses import solve_selected_analyses
from tests.test_analysis_options import result_for

FIXTURES = Path("benchmarks/windows-rc-20261013-1fac3a1/fixtures")


@pytest.mark.parametrize("name", ["baseline_contract", "thin_bridge_contract", "wide_angle_high_output_v1"])
def test_vshape_reports_minimum_and_actual_bridge_without_changing_the_design(name):
    body = json.loads((FIXTURES / f"ipm_vshape_8p12s_{name}__native.json").read_text())
    cfg = MotorConfig.model_validate(body)
    original = cfg.model_dump()
    facts = vshape_input_facts(cfg)
    assert facts["actual_outer_bridge_mm"] >= facts["minimum_outer_bridge_mm"]
    assert facts["actual_outer_bridge_mm"] > facts["minimum_outer_bridge_mm"] + 0.5
    preview = generate_preview(cfg)
    assert preview.metadata["interpreted_rotor_inputs"] == facts
    assert any("Saved magnet coverage" in note and "not used" in note for note in preview.metadata["input_notes"])
    assert preview.metadata["geometry_warnings"] == geometry_mesh_advisories(cfg)
    assert all("magnet_embrace" not in message for message in preview.metadata["input_notes"])
    assert cfg.model_dump() == original
    changed = cfg.model_copy(deep=True)
    changed.rotor.magnet_embrace = 0.25
    assert compute_v_shape_magnet_placements(changed) == compute_v_shape_magnet_placements(cfg)


@pytest.mark.parametrize("cycle_flag", [None, False])
def test_partial_window_warning_survives_selected_analysis_and_is_not_added_to_complete_cycles(cycle_flag):
    cfg = MotorConfig.model_validate(json.loads((FIXTURES / "ipm_vshape_8p12s_baseline_contract__native.json").read_text()))
    result = result_for(cfg)
    result.solve_metadata.loaded_cycle_complete = cycle_flag
    result.solve_metadata.torque_sweep_computed = True

    class Solver:
        def solve(self, *args, **kwargs):
            return deepcopy(result)

    solved = solve_selected_analyses(Solver(), cfg)
    assert solved.solve_metadata.loaded_cycle_complete is False
    assert partial_sweep_advisory(False) in solved.warnings
    assert solved.input_notes == geometry_input_advisories(cfg)
    assert all(message in solved.warnings for message in geometry_mesh_advisories(cfg))
    assert not any(note in solved.warnings for note in solved.input_notes)
    assert partial_sweep_advisory(True) is None
    assert partial_sweep_advisory(None) is None

    result.solve_metadata.loaded_cycle_complete = None
    result.torque_waveform.electrical_angle_deg = [0, 90, 180, 270, 360]
    result.torque_waveform.torque_Nm = [1, 1, 1, 1, 1]
    complete = solve_selected_analyses(Solver(), cfg)
    assert complete.solve_metadata.loaded_cycle_complete is True
    assert partial_sweep_advisory(False) not in complete.warnings


SPM_FIXTURE = Path("benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json")
FLAT_FIXTURE = Path("frontend/src/public/examples/validation_ipm_14p_flat_buried_large.openem")


def _config(path: Path) -> MotorConfig:
    body = json.loads(path.read_text())
    body = body.get("config", body)
    return MotorConfig.model_validate({key: value for key, value in body.items() if key in MotorConfig.model_fields})


@pytest.mark.parametrize(("path", "rotor", "drawn"), [
    (SPM_FIXTURE, "surface-magnet", "74%"),
    (FLAT_FIXTURE, "flat buried IPM", "78%"),
])
def test_a_saved_coverage_the_geometry_does_not_draw_is_noted(path, rotor, drawn):
    # #285 item 2: Magnet Width sets these rotors' coverage, so a different saved
    # magnet_embrace changes nothing and is named, not dropped silently.
    cfg = _config(path)
    coverage = drawn_magnet_coverage(cfg)
    assert abs(cfg.rotor.magnet_embrace - coverage) > 0.02
    [note] = geometry_input_advisories(cfg)
    assert note.startswith(f"Saved magnet coverage ({cfg.rotor.magnet_embrace:.0%}) is not used for {rotor} rotors.")
    assert note.endswith(f"Magnet Width sets the coverage: {drawn} as drawn.")
    assert generate_preview(cfg).metadata["input_notes"] == [note]
    # The saved value really is unused: the drawn rotor does not move with it.
    changed = cfg.model_copy(deep=True)
    changed.rotor.magnet_embrace = 0.3
    assert generate_preview(changed).regions == generate_preview(cfg).regions
    # A saved value that matches the drawing, within rounding, gets no note.
    changed.rotor.magnet_embrace = coverage + 0.015
    assert geometry_input_advisories(changed) == []


def test_reference_rotors_that_use_the_saved_coverage_get_no_note():
    prius = _config(Path("frontend/src/public/examples/ornl_prius_2004_holem50.coilem"))
    assert prius.rotor.ipm_topology == "pyleecan_holem50"
    assert drawn_magnet_coverage(prius) is None and geometry_input_advisories(prius) == []
