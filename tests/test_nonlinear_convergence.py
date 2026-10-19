"""Native convergence survives aggregation, public mapping and saved-run loading."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.models import MotorConfig
from backend.models.config import SolveOptionsConfig
from backend.models.result import SolveMetadata
from backend.solver import Magneto2DSolver
from backend.solver._helpers import _aggregate_per_angle_mesh_sweep
from backend.solver.convergence import convergence_fields


def record(method="picard", iterations=12, reused=False):
    return dict(
        method=method,
        iterations=iterations,
        max_iterations=100,
        stage_iterations=[iterations],
        stage_iteration_cap=100,
        raw_max_residual=0.02 if method == "picard" else None,
        scaled_residual=0.003 if method == "newton" else None,
        residual_definition="unrelaxed permeability" if method == "picard" else "equation residual",
        tolerance=0.05 if method == "picard" else 0.01,
        stopping_test="recorded comparison",
        solution_reused=reused,
        fallback_from=None,
    )


def test_mapping_preserves_method_specific_residuals_and_missing_positions():
    sweep = {
        "loaded_nonlinear_convergence": [record(), None, record("newton", 90)],
        "no_load_nonlinear_convergence": [record(iterations=99, reused=True)],
        "loaded_nonlinear_iterations": [12, 0, 90],
        "no_load_nonlinear_iterations": [0],
    }
    fields, metadata = convergence_fields(sweep)
    assert fields["loaded_nonlinear_convergence"][1] is None
    assert fields["loaded_nonlinear_convergence"][2].scaled_residual == 0.003
    assert fields["loaded_nonlinear_iterations"] == [12, 0, 90]
    assert metadata["nonlinear_max_iterations_used"] == 90
    assert metadata["nonlinear_median_iterations"] == 51
    assert metadata["nonlinear_worst_final_mismatch"] == 0.02
    assert metadata["nonlinear_worst_tolerance_ratio"] == pytest.approx(0.4)
    # A single tolerance would misdescribe this mixed-method (fallback) sweep.
    assert metadata["nonlinear_tolerance"] is None


def test_historical_convergence_is_not_inferred_from_counts_or_current_defaults():
    fields, metadata = convergence_fields({"loaded_nonlinear_iterations": [10, 20]})
    assert fields["loaded_nonlinear_convergence"] is None
    assert fields["no_load_nonlinear_convergence"] is None
    assert metadata == {"nonlinear_tolerance": None}
    old = SolveMetadata(solver_name="magneto2d", mesh_element_count=100, rotor_positions=2, timestamp=datetime.now(timezone.utc))
    assert old.nonlinear_worst_final_mismatch is None
    assert old.nonlinear_max_iterations_used is None
    assert old.solve_quality is None


def test_aggregate_and_public_result_keep_loaded_and_no_load_evidence():
    cfg = MotorConfig.model_validate_json(Path("tests/fixtures/spm_4p12s_simple.json").read_text())
    cfg.solve_options = SolveOptionsConfig(flux_density=False, thd_analysis=False)
    native = {
        "config_summary": {},
        "mesh_info": {"num_triangles": 1000},
        "operating_point": {"resolved_phase_current_peak_a": 5.0},
        "solve_info": {"total_time_ms": 10, "nonlinear_iterations": 12, "nonlinear_convergence": record()},
        "results": {"torque_nm": 1.0, "torque_arkkio_nm": 1.0, "peak_b_tooth_t": 1.0, "peak_b_yoke_t": 1.0},
    }
    loaded = [deepcopy(native), deepcopy(native)]
    no_load = [deepcopy(native), deepcopy(native)]
    no_load[1]["solve_info"]["nonlinear_convergence"] = record("newton", 8)
    report = _aggregate_per_angle_mesh_sweep(cfg, loaded, no_load, [0.0, 180.0], mesh_generation_time_ms=0, include_visual_frames=False)
    result = Magneto2DSolver.build_result_from_reports(cfg, report, native)
    assert result.loaded_nonlinear_convergence[0].raw_max_residual == 0.02
    assert result.no_load_nonlinear_convergence[1].method == "newton"
    assert result.no_load_nonlinear_convergence[1].scaled_residual == 0.003
    assert result.solve_metadata.nonlinear_max_iterations_used == 12
    assert result.solve_metadata.mesh_density == cfg.solve_params.mesh_density
    assert result.solve_metadata.mesh_element_count == 1000
    assert result.solve_metadata.solve_quality == cfg.solve_params.solve_quality
    payload = json.loads(result.model_dump_json())
    assert payload["loaded_nonlinear_convergence"][0]["raw_max_residual"] == 0.02


def test_nonfinite_recorded_mismatch_is_rejected():
    bad = record()
    bad["raw_max_residual"] = float("nan")
    with pytest.raises(ValueError):
        convergence_fields({"loaded_nonlinear_convergence": [bad]})


@pytest.mark.parametrize("quality,tolerance", [("quick", 0.05), ("standard", 0.01), ("fine", 0.001), ("custom", 0.001)])
def test_backend_preset_tolerance_matches_native_policy(quality, tolerance):
    from backend.magneto2d_adapter import estimate_magneto2d_nonlinear_tolerance

    cfg = MotorConfig.model_validate_json(Path("tests/fixtures/spm_4p12s_simple.json").read_text())
    cfg.solve_params.solve_quality = quality
    assert estimate_magneto2d_nonlinear_tolerance(cfg) == tolerance
