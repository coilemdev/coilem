"""Selected analyses control planning, computation and the saved result contract."""

import csv
import io
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.models import MotorConfig, SolveResult
from backend.models.waveforms import BackEMFWaveform, TorqueWaveform
from backend.public_main import app
from backend.public_report import build_public_run_csv, build_public_run_pdf
from backend.solve_estimate import planned_work
from backend.solver import Magneto2DSolver, _iron_loss_record
from backend.solver._helpers import _aggregate_per_angle_mesh_sweep, _cogging_sweep_series
from backend.sweep_planning import cogging_angle_grid, full_cycle_back_emf_angle_grid, loaded_angle_grid

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json").read_text())


def config(**analyses):
    raw = deepcopy(BASE)
    raw["solve_params"].update(solve_quality="custom", rotor_step_deg=30, rotor_sweep_range_deg=360)
    raw["solve_options"].update(torque_sweep=False, back_emf=False, cogging_torque=False,
                                 losses_efficiency=False, thd_analysis=False, flux_density=False)
    raw["solve_options"].update(analyses)
    return MotorConfig.model_validate(raw)


def native(angle):
    return {
        "config_summary": {}, "mesh_info": {"num_triangles": 1000},
        "operating_point": {"resolved_phase_current_peak_a": 0.0},
        "solve_info": {"total_time_ms": 10},
        "results": {
            "torque_nm": 0.001, "torque_weighted_stress_nm": 0.001,
            "peak_b_tooth_t": 1.2, "peak_b_yoke_t": 1.0,
            **{f"flux_linkage_{phase}_wb": 0.03 * math.cos(math.radians(angle) + offset)
               for phase, offset in zip("abc", (0, -2 * math.pi / 3, 2 * math.pi / 3))},
        },
    }


def result_for(cfg):
    loaded = loaded_angle_grid(cfg)
    no_load = full_cycle_back_emf_angle_grid(cfg, loaded) if cfg.solve_options.back_emf else []
    report = _aggregate_per_angle_mesh_sweep(
        cfg, [native(angle) for angle in loaded], [native(angle) for angle in no_load] or None,
        loaded, no_load_angles_elec_deg=no_load or None, mesh_generation_time_ms=0, include_visual_frames=False,
    )
    if cfg.solve_options.cogging_torque:
        angles = cogging_angle_grid(cfg)
        period = angles[-1]
        reports = [{"results": {"torque_nm": math.sin(2 * math.pi * angle / period),
                                "torque_weighted_stress_nm": math.sin(2 * math.pi * angle / period)}} for angle in angles]
        report["sweep"].update(_cogging_sweep_series(reports, angles))
    return Magneto2DSolver.build_result_from_reports(cfg, report, native(0))


@pytest.mark.parametrize("analysis", ["back_emf", "cogging_torque"])
def test_standalone_no_load_analysis_has_one_static_preview_and_no_loaded_sweep(analysis):
    cfg = config(**{analysis: True})
    assert loaded_angle_grid(cfg) == [0.0]
    work = planned_work(cfg)
    assert work["loaded"] == 1
    assert work["no_load"] == (12 if analysis == "back_emf" else 25)
    result = result_for(cfg)
    assert result.summary.avg_torque_Nm is None
    assert result.summary.torque_ripple_pct is None
    assert result.summary.Kt_Nm_per_A is None
    assert result.summary.dq_flux_linkage is None
    assert result.torque_waveform.torque_Nm == []
    assert result.solve_metadata.torque_sweep_computed is False
    assert result.solve_metadata.rotor_positions == 1
    assert result.summary.loss_breakdown is None and result.summary.iron_loss is None
    if analysis == "back_emf":
        assert len(result.back_emf_waveform.electrical_angle_deg) == 12
        assert result.summary.back_emf_fundamental_V > 0
        assert result.summary.Ke_Vs_per_rad_mech > 0
        assert result.summary.cogging is None
    else:
        assert result.summary.cogging is not None
        assert result.summary.cogging.peak_to_peak_of_loaded_pct is None
        assert result.summary.back_emf_fundamental_V is None
        assert result.back_emf_waveform.electrical_angle_deg == []
    # Saved standalone results remain valid when reloaded, including empty unrequested waveforms.
    assert SolveResult.model_validate_json(result.model_dump_json()).summary == result.summary


def test_losses_request_their_loaded_fields_even_with_torque_display_off():
    cfg = config(losses_efficiency=True)
    assert len(loaded_angle_grid(cfg)) == 12
    result = result_for(cfg)
    assert result.summary.avg_torque_Nm is None and result.torque_waveform.torque_Nm == []
    assert result.summary.loss_breakdown is not None
    assert result.summary.winding_resistance is not None


def test_disabling_losses_skips_both_estimators(monkeypatch):
    from backend import solver

    def unexpected(*args, **kwargs):
        pytest.fail("Unrequested losses must not run their estimators")

    monkeypatch.setattr(solver, "estimate_iron_loss_and_density", unexpected)
    monkeypatch.setattr(solver, "operating_point_losses", unexpected)
    cfg = config(back_emf=True)
    assert _iron_loss_record(cfg, [], []) == (None, None)
    assert result_for(cfg).summary.loss_breakdown is None


def test_default_torque_and_bemf_keep_resistance_without_running_losses():
    result = result_for(config(torque_sweep=True, back_emf=True))
    assert result.summary.winding_resistance.phase_resistance_ohm > 0
    from backend.winding_resistance import winding_resistance

    assert result.summary.winding_resistance == winding_resistance(config(torque_sweep=True, back_emf=True))
    assert result.summary.loss_breakdown is None


def test_legacy_omitted_loss_option_retains_loss_builder_default():
    raw = config(torque_sweep=True, back_emf=True).model_dump(mode="json")
    del raw["solve_options"]["losses_efficiency"]
    cfg = MotorConfig.model_validate(raw)
    assert cfg.solve_options.losses_efficiency
    assert result_for(cfg).summary.loss_breakdown is not None


def test_losses_and_cogging_do_not_expose_unrequested_loaded_torque():
    cfg = config(losses_efficiency=True, cogging_torque=True)
    result = result_for(cfg)
    assert result.summary.avg_torque_Nm is None
    assert result.summary.cogging.loaded_mean_torque_Nm is None
    assert result.summary.cogging.peak_to_peak_of_loaded_pct is None
    assert result.summary.cogging.loaded_comparison_reason == "Loaded torque was not requested."
    args = dict(project=cfg.model_dump(mode="json"), request={"resolved_config": cfg.model_dump(mode="json")},
                result=result.model_dump(mode="json"), material={}, manifest={})
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(build_public_run_pdf(**args))).pages)
    assert "Loaded torque was not requested" in text
    assert "0 A run" not in text


def test_validate_reports_each_selected_grid_and_rejects_an_empty_selection():
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/solve/validate", json=config(back_emf=True).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["analysis_positions"] == {"torque_sweep": 0, "back_emf": 12, "cogging_torque": 0, "losses_efficiency": 0}
    response = client.post("/solve/validate", json=config().model_dump(mode="json"))
    assert response.status_code == 400
    assert response.json()["detail"]["field"] == "solve_options"


def test_empty_waveforms_are_valid_but_a_single_sample_is_not_a_sweep():
    TorqueWaveform(electrical_angle_deg=[], torque_Nm=[])
    BackEMFWaveform(electrical_angle_deg=[], phase_a_V=[], phase_b_V=[], phase_c_V=[])
    with pytest.raises(ValueError):
        TorqueWaveform(electrical_angle_deg=[0], torque_Nm=[0])
    with pytest.raises(ValueError):
        BackEMFWaveform(electrical_angle_deg=[0], phase_a_V=[0], phase_b_V=[0], phase_c_V=[0])


def test_standalone_exports_leave_unrequested_metrics_blank_and_omit_their_plots():
    pypdf = pytest.importorskip("pypdf")
    cfg = config(back_emf=True)
    raw = cfg.model_dump(mode="json")
    result = result_for(cfg).model_dump(mode="json")
    arguments = dict(project=raw, request={"resolved_config": raw}, result=result, material={}, manifest={})
    rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode())))
    assert not any(row[0] == "torque_waveform" for row in rows)
    assert next(row[3] for row in rows if row[:2] == ["summary", "avg_torque_Nm"]) == ""
    text = " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(build_public_run_pdf(**arguments))).pages)
    assert "Torque waveform" not in text
    assert "Average torque" not in text
    assert "Three-phase back EMF" in text
    assert result["solve_metadata"]["current_amplitude_A"] == 0
    normalized = " ".join(text.split())
    assert "Phase current 0 A rms" in normalized
    assert "Requested phase current 30 A rms" in normalized
    assert "Phase resistance" in text


def test_elmer_standalone_back_emf_uses_zero_current_and_an_independent_grid(monkeypatch, tmp_path):
    from backend.elmer import adapter
    from backend.elmer.capabilities import ElmerCapabilities
    from backend.elmer.results import ElmerPositionResult

    cfg = config(back_emf=True)
    cfg.solve_params.torque_method = "arkkio"
    cfg.solve_params.rotor_rotation_model = "remesh_per_step"
    capabilities = ElmerCapabilities(
        available=True, qualified=True, solver_path=None, grid_path=None,
        solver_version="26.2", grid_version="26.2", platform="test", architecture="test",
    )
    solver = adapter.ElmerSolver(capabilities=capabilities, run_root=tmp_path)
    calls = []

    def grid(grid_config, *, angles, stage, **kwargs):
        calls.append((stage, angles, grid_config.solve_params.current_amplitude_A))
        return [ElmerPositionResult(
            torque_nm=0.001, torque_per_length_n=0.01, nodal_force_torque_nm=None,
            nodes_mm=[[0, 0], [1, 0], [0, 1]], triangles=[[0, 1, 2]] * 100,
            regions=["stator_tooth"] * 100, element_region_ids=["1"] * 100, az_nodal=[0, 0, 0],
            element_bx_t=[1] * 100, element_by_t=[0] * 100, element_b_magnitude_t=[1] * 100, nodal_b_magnitude_t=[1, 1, 1],
            flux_linkage_a_wb=0.03 * math.cos(math.radians(angle)),
            flux_linkage_b_wb=0.03 * math.cos(math.radians(angle) - 2 * math.pi / 3),
            flux_linkage_c_wb=0.03 * math.cos(math.radians(angle) + 2 * math.pi / 3),
            slot_flux_linkage_contributions=[], peak_b_tooth_t=1, peak_b_yoke_t=0,
            solve_mesh_evidence={},
        ) for angle in angles]

    monkeypatch.setattr(solver, "_run_grid", grid)
    monkeypatch.setattr(adapter, "build_field_line_plot_from_mesh", lambda **kwargs: None)
    result = solver.solve(cfg)
    assert calls == [("torque_sweep", [0.0], 0), ("noload_sweep", list(range(0, 360, 30)), 0)]
    assert result.solve_metadata.current_amplitude_A == 0
    assert result.summary.avg_torque_Nm is None
    assert result.summary.Kt_Nm_per_A is None
    assert result.torque_waveform.torque_Nm == []
    assert result.summary.back_emf_fundamental_V > 0
