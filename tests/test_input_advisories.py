"""Input interpretation is explicit without moving magnets or changing requests."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.geometry_drawer import compute_v_shape_magnet_placements
from backend.input_advisories import geometry_input_advisories, partial_sweep_advisory, vshape_input_facts
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
    assert any("magnet_embrace" in warning and "not used" in warning for warning in preview.metadata["geometry_warnings"])
    assert cfg.model_dump() == original
    changed = cfg.model_copy(deep=True)
    changed.rotor.magnet_embrace = 0.25
    assert compute_v_shape_magnet_placements(changed) == compute_v_shape_magnet_placements(cfg)


def test_partial_window_warning_survives_selected_analysis_and_is_not_added_to_complete_cycles():
    cfg = MotorConfig.model_validate(json.loads((FIXTURES / "ipm_vshape_8p12s_baseline_contract__native.json").read_text()))
    result = result_for(cfg)
    result.solve_metadata.loaded_cycle_complete = False
    result.solve_metadata.torque_sweep_computed = True

    class Solver:
        def solve(self, *args, **kwargs):
            return deepcopy(result)

    solved = solve_selected_analyses(Solver(), cfg)
    assert partial_sweep_advisory(False) in solved.warnings
    assert all(message in solved.warnings for message in geometry_input_advisories(cfg))
    assert partial_sweep_advisory(True) is None
    assert partial_sweep_advisory(None) is None
