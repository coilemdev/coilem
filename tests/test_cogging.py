"""Cogging torque through the public app (#185): the sweep's grid, its record,
and the same numbers in Results, the run PDF and the CSV."""

from __future__ import annotations

import csv
import io
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.cogging import cogging_period, cogging_record
from backend.models import MotorConfig, SolveResult
from backend.models.performance import COGGING_TORQUE_STATUS_REASON
from backend.public_policy import public_config_support_error
from backend.public_report import _number, _plain, build_public_run_csv, build_public_run_pdf
from backend.public_routes.solve import _public_result_payload
from backend.solve_estimate import planned_work
from backend.solver._helpers import COGGING_TORQUE_METHOD, _cogging_sweep_series
from backend.sweep_planning import COGGING_POSITIONS_PER_PERIOD, cogging_angle_grid

pypdf = pytest.importorskip("pypdf")

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json").read_text(encoding="utf-8"))
# The 8p/12s example's cogging sweep at the Standard preset (docs/COGGING_CONVERGENCE.md).
EXAMPLE_SWEEP_PATH = ROOT / "tests/fixtures/cogging_example_8p12s.json"


def _example_sweep() -> dict:
    return json.loads(EXAMPLE_SWEEP_PATH.read_text(encoding="utf-8"))


def _config(quality: str = "standard", cogging: bool = True, **solve_options) -> MotorConfig:
    raw = deepcopy(EXAMPLE)
    raw["solve_params"]["solve_quality"] = quality
    raw["solve_options"].update(cogging_torque=cogging, **solve_options)
    return MotorConfig.model_validate(raw)


def _analytic(positions: int, *, slots: int = 12, poles: int = 8) -> tuple[list[float], list[float]]:
    """Two cogging harmonics over one period, both ends included."""

    period_elec, _, _ = cogging_period(slots, poles)
    angles = [period_elec * index / positions for index in range(positions + 1)]
    torque = [
        0.8 * math.sin(2 * math.pi * angle / period_elec) + 0.15 * math.cos(4 * math.pi * angle / period_elec + 0.3)
        for angle in angles
    ]
    return angles, torque


def test_the_cogging_period_is_one_lcm_cycle() -> None:
    assert cogging_period(12, 8) == (60.0, 15.0, 24)
    assert cogging_period(48, 8) == (30.0, 7.5, 48)
    assert cogging_period(9, 8) == (20.0, 5.0, 72)


@pytest.mark.parametrize("quality", ["quick", "standard", "fine", "custom"])
def test_each_preset_states_its_positions_per_period(quality: str) -> None:
    grid = cogging_angle_grid(_config(quality))
    positions = COGGING_POSITIONS_PER_PERIOD[quality]
    # One inclusive cogging period: the end repeats the start, 180·gcd(S, P)/S electrical.
    assert len(grid) == positions + 1
    assert grid[0] == 0.0
    assert grid[-1] == pytest.approx(60.0)
    assert all(b - a == pytest.approx(60.0 / positions) for a, b in zip(grid, grid[1:]))
    assert cogging_angle_grid(_config(quality, cogging=False)) == []


def test_an_analytic_waveform_repeats_every_period_and_averages_to_zero() -> None:
    angles, torque = _analytic(24)
    record = cogging_record(angles, torque, slot_count=12, pole_count=8, method="weighted_stress")
    assert record is not None
    assert record.fundamental_order == 24
    assert (record.period_elec_deg, record.period_mech_deg) == (60.0, 15.0)
    assert record.positions_per_period == 24
    assert record.endpoint_mismatch_Nm == pytest.approx(0.0, abs=1e-12)
    assert record.mean_Nm == pytest.approx(0.0, abs=1e-12)
    # The DFT returns each harmonic's peak amplitude at its order per mechanical revolution.
    assert [harmonic.order for harmonic in record.harmonics[:3]] == [24, 48, 72]
    assert record.first_harmonic_Nm == pytest.approx(0.8)
    assert record.harmonics[1].amplitude_Nm == pytest.approx(0.15)
    assert record.harmonics[2].amplitude_Nm == pytest.approx(0.0, abs=1e-12)
    assert record.peak_to_peak_Nm == pytest.approx(max(torque) - min(torque))
    assert record.peak_Nm == pytest.approx(max(abs(value) for value in torque))
    assert (record.status, record.status_reason) == ("experimental", COGGING_TORQUE_STATUS_REASON)
    # No current: nothing to compare with.
    assert record.loaded_mean_torque_Nm is None and record.peak_to_peak_of_loaded_pct is None
    loaded = cogging_record(angles, torque, slot_count=12, pole_count=8, method="arkkio", loaded_mean_torque_Nm=-10.0, loaded_current_A=42.4)
    assert loaded is not None
    assert loaded.peak_to_peak_of_loaded_pct == pytest.approx(10.0 * record.peak_to_peak_Nm)


def test_a_grid_that_is_not_one_period_has_no_record() -> None:
    angles, torque = _analytic(24)
    assert cogging_record(angles[:-3], torque[:-3], slot_count=12, pole_count=8, method="contour") is None
    assert cogging_record(angles, torque, slot_count=12, pole_count=10, method="contour") is None
    # A half-open period is one period too.
    half_open = cogging_record(angles[:-1], torque[:-1], slot_count=12, pole_count=8, method="contour")
    assert half_open is not None and half_open.positions_per_period == 24
    assert half_open.endpoint_mismatch_Nm is None


def test_reused_endpoints_have_no_remesh_noise_measurement() -> None:
    angles, torque = _analytic(24)
    independent = cogging_record(angles, torque, slot_count=12, pole_count=8, method="weighted_stress")
    reused = cogging_record(angles, torque, slot_count=12, pole_count=8, method="weighted_stress", independent_endpoints=False)
    assert independent is not None and reused is not None
    assert independent.endpoint_mismatch_Nm == pytest.approx(0.0, abs=1e-12)
    assert reused.endpoint_mismatch_Nm is None
    # Only the diagnostic is suppressed; the physical waveform metrics are preserved.
    assert reused.model_dump(exclude={"endpoint_mismatch_Nm"}) == independent.model_dump(exclude={"endpoint_mismatch_Nm"})


@pytest.mark.parametrize(("poles", "mesh_reuse", "solve_reuse", "back_emf", "independent"), [
    (4, True, True, False, False),
    (4, True, False, False, False),
    (4, False, False, False, True),
    (8, True, True, False, True),
    (4, True, True, True, False),
])
def test_pipeline_records_whether_cogging_endpoints_share_a_mesh(monkeypatch, poles, mesh_reuse, solve_reuse, back_emf, independent) -> None:
    """Exercise actual slot grouping and attachment without allocating real FEM fields."""
    from backend import solver

    config = _config(back_emf=back_emf, thd_analysis=False)
    config.rotor.pole_count = poles

    class Producer:
        source = "gmsh"
        display_name = "Gmsh"

        @staticmethod
        def build(config, angle):
            return {"angle": angle}, 0

    def report(config, **kwargs):
        angle = kwargs["rotor_angle_deg"]
        return {"results": {"torque_nm": angle, "torque_weighted_stress_nm": angle}}

    monkeypatch.setattr(solver, "estimate_magneto2d_sweep_angle_grid", lambda _: [0.0, 60.0])
    monkeypatch.setattr(solver, "_gmsh_imported_mesh_pipeline_enabled", lambda *args: True)
    monkeypatch.setattr(solver, "_gmsh_pipeline_worker_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(solver, "_angle_mesh_cache_enabled", lambda: False)
    monkeypatch.setattr(solver, "gmsh_mesh_reuse_enabled", lambda: mesh_reuse)
    monkeypatch.setattr(solver, "gmsh_solve_reuse_enabled", lambda: solve_reuse)
    monkeypatch.setattr(solver, "_rotate_gmsh_artifact_for_config", lambda artifact, config, angle: {"angle": angle})
    monkeypatch.setattr(solver, "_zero_current_solve_mesh_artifact", lambda artifact: artifact)
    monkeypatch.setattr(solver, "slot_current_pattern_matches", lambda *args: False)
    monkeypatch.setattr(solver, "derive_congruent_solve_report", lambda base, **kwargs: deepcopy(base))
    monkeypatch.setattr(solver, "build_solve_mesh_evidence", lambda *args, **kwargs: {"geometry_sha256": "test"})
    monkeypatch.setattr(solver, "run_magneto2d_report", report)
    monkeypatch.setattr(solver, "_assert_imported_mesh_consumed_by_rust", lambda *args, **kwargs: None)
    monkeypatch.setattr(solver, "_aggregate_per_angle_mesh_sweep", lambda *args, **kwargs: {"sweep": {}})
    monkeypatch.setattr(solver, "solver_setting", lambda name, default=None: "1" if name == "COILEM_MAGNETO2D_COMPACT_QA_REPORT" else default)
    sweep, _ = solver._solve_with_per_angle_producer_meshes(config, Producer(), solve_cache_dir=None, clockwise_positive=True)
    raw = sweep["sweep"]
    assert raw["cogging_endpoints_independent"] is independent
    record = cogging_record(
        raw["cogging_rotor_positions_elec_deg"], raw["cogging_torque_waveform_nm"],
        slot_count=12, pole_count=poles, method=raw["cogging_torque_method"],
        independent_endpoints=raw["cogging_endpoints_independent"],
    )
    assert record is not None
    assert (record.endpoint_mismatch_Nm is not None) is independent


@pytest.mark.parametrize("independent", [True, False, None], ids=["independent", "reused", "historical-cache"])
def test_postprocessing_preserves_endpoint_independence(independent) -> None:
    from backend.solver import Magneto2DSolver
    from backend.solver._helpers import _aggregate_per_angle_mesh_sweep

    config = _config(back_emf=False, thd_analysis=False, flux_density=False)
    native = {
        "config_summary": {}, "mesh_info": {"num_triangles": 1000},
        "operating_point": {"resolved_phase_current_peak_a": 5.0},
        "solve_info": {"total_time_ms": 10},
        "results": {"torque_nm": 1.0, "torque_arkkio_nm": 1.0, "peak_b_tooth_t": 1.0, "peak_b_yoke_t": 1.0},
    }
    report = _aggregate_per_angle_mesh_sweep(config, [native, native], None, [0.0, 180.0],
                                             mesh_generation_time_ms=0, include_visual_frames=False)
    angles, torque = _analytic(24)
    report["sweep"].update(_cogging_sweep_series([
        {"results": {"torque_nm": value, "torque_weighted_stress_nm": value}} for value in torque
    ], angles, independent_endpoints=independent is True))
    if independent is None:
        del report["sweep"]["cogging_endpoints_independent"]
    result = Magneto2DSolver.build_result_from_reports(config, report, native)
    assert result.summary.cogging is not None
    assert (result.summary.cogging.endpoint_mismatch_Nm is not None) is (independent is True)


def test_the_sweep_series_select_the_cogging_method_and_remove_only_the_period_mean() -> None:
    angles, torque = _analytic(12)
    reports = [
        {"results": {"torque_nm": value, "torque_contour_nm": value + 0.01, "torque_arkkio_nm": value + 0.02,
                     "torque_area_mst_nm": value + 0.03, "torque_weighted_stress_nm": value + 0.04}}
        for value in torque
    ]
    series = _cogging_sweep_series(reports, angles)
    assert series["cogging_torque_method"] == COGGING_TORQUE_METHOD
    expected = {"contour": 0.01, "arkkio": 0.02, "mst": 0.03, "weighted_stress": 0.04}[COGGING_TORQUE_METHOD]
    assert series["cogging_torque_waveform_nm"] == pytest.approx([value + expected for value in torque])
    assert series["cogging_torque_nm"] == pytest.approx(max(torque) - min(torque))
    # The mean over the period, without the repeated end, leaves the analytic waveform.
    assert series["cogging_torque_weighted_stress_centered_waveform_nm"] == pytest.approx(torque, abs=1e-12)
    assert series["cogging_rotor_positions_elec_deg"] == angles


def test_the_public_policy_accepts_cogging_on_magneto2d_only() -> None:
    config = _config()
    assert public_config_support_error(config, require_solve_params=True) is None
    error = public_config_support_error(config, require_solve_params=True, solver_id="elmer")
    assert error is not None and error.field == "solve_options.cogging_torque"


def test_the_public_validate_route_accepts_cogging_and_states_its_positions() -> None:
    from backend.public_main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    raw = deepcopy(EXAMPLE)
    raw["solve_params"].update(solve_quality="standard", corner_refinement=True)
    raw["solve_options"]["cogging_torque"] = True
    response = client.post("/solve/validate", json=raw)
    assert response.status_code == 200, response.text
    assert response.json()["cogging_positions_per_period"] == COGGING_POSITIONS_PER_PERIOD["standard"]


def test_the_estimate_counts_the_cogging_solves() -> None:
    without = planned_work(_config(cogging=False, back_emf=True))
    with_cogging = planned_work(_config(back_emf=True))
    grid = cogging_angle_grid(_config())
    # The Back-EMF grid (7.5 deg here) already solves the cogging angles it shares.
    shared = {round(angle, 6) for angle in grid} & {round(7.5 * index, 6) for index in range(48)}
    assert with_cogging["no_load"] - without["no_load"] == len(grid) - len(shared)
    assert with_cogging["mesh_jobs"] > without["mesh_jobs"]


def _assert_close(actual, expected) -> None:
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _assert_close(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for item, other in zip(actual, expected):
            _assert_close(item, other)
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12)
    else:
        assert actual == expected


def _stored_result() -> dict:
    sweep = _example_sweep()
    record = cogging_record(
        sweep["electrical_angle_deg"],
        sweep["torque_Nm"],
        slot_count=12,
        pole_count=8,
        method=sweep["method"],
        loaded_mean_torque_Nm=sweep["loaded_mean_torque_Nm"],
        loaded_current_A=sweep["loaded_current_A"],
    )
    assert record is not None
    # The Results test (frontend/scripts/test-cogging-view.mjs) reads this stored record.
    # Platforms round the DFT differently in the last bits, so floats match to 1e-9.
    _assert_close(record.model_dump(mode="json"), sweep["record"])
    angles = sweep["electrical_angle_deg"]
    return {
        "summary": {
            "avg_torque_Nm": sweep["loaded_mean_torque_Nm"],
            "torque_ripple_pct": 10.5,
            "cogging_torque_Nm": record.peak_to_peak_Nm,
            "cogging": record.model_dump(mode="json"),
            "back_emf_fundamental_V": 50.0,
            "peak_flux_density_teeth_T": 1.6,
            "peak_flux_density_yoke_T": 1.3,
            "solve_time_s": 30.0,
        },
        "torque_waveform": {"electrical_angle_deg": [0.0, 7.5], "torque_Nm": [10.6, 10.7]},
        "cogging_torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": sweep["torque_Nm"]},
        "back_emf_waveform": {"electrical_angle_deg": [0.0, 7.5], "phase_a_V": [0.0, 1.0], "phase_b_V": [0.0, 1.0], "phase_c_V": [0.0, 1.0]},
        "solve_metadata": {
            "solver_name": "magneto2d",
            "mesh_element_count": 30000,
            "rotor_positions": 2,
            "timestamp": "2026-11-03T00:00:00Z",
            "current_amplitude_A": sweep["loaded_current_A"],
        },
    }


def test_the_example_sweep_repeats_every_period_and_averages_to_about_zero() -> None:
    record = _stored_result()["summary"]["cogging"]
    limits = _example_sweep()["limits"]
    # Per-position meshes make neither exact; both stay small against the swing.
    assert record["endpoint_mismatch_Nm"] <= limits["endpoint_mismatch_fraction"] * record["peak_to_peak_Nm"]
    assert abs(record["mean_Nm"]) <= limits["mean_fraction"] * record["peak_to_peak_Nm"]
    assert record["harmonics"][0]["order"] == 24


def test_results_pdf_and_csv_carry_the_same_cogging_record() -> None:
    result = _stored_result()
    record = result["summary"]["cogging"]
    config = deepcopy(EXAMPLE)
    arguments = {"project": config, "request": {"resolved_config": config}, "result": result, "material": {}, "manifest": {}}

    # The public payload keeps what the route used to drop.
    solved = SolveResult.model_validate(result)
    payload = _public_result_payload(solved)
    assert payload["summary"]["cogging"] == solved.summary.cogging.model_dump(mode="json")
    assert payload["summary"]["cogging_torque_Nm"] == record["peak_to_peak_Nm"]
    assert payload["cogging_torque_waveform"]["torque_Nm"] == result["cogging_torque_waveform"]["torque_Nm"]

    rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode("utf-8"))))
    cogging_rows = {row[1]: row for row in rows if row[0] == "cogging"}
    for field, unit in (("peak_to_peak_Nm", "N m"), ("peak_Nm", "N m"), ("first_harmonic_Nm", "N m"),
                        ("peak_to_peak_of_loaded_pct", "%"), ("period_mech_deg", "deg")):
        assert cogging_rows[field][2] == unit
        assert float(cogging_rows[field][3]) == pytest.approx(record[field], rel=1e-11)
    assert cogging_rows["method"][3] == record["method"]
    assert cogging_rows["harmonics[0].order"][3] == "24"
    assert ["status", "cogging_torque", "", "experimental", ""] in rows
    assert ["summary", "cogging_torque_Nm", "N m", format(record["peak_to_peak_Nm"], ".12g"), ""] in rows
    waveform = [row for row in rows if row[0] == "cogging_waveform"]
    mechanical = [float(row[3]) for row in waveform if row[1] == "mechanical_angle_deg"]
    assert mechanical[-1] == pytest.approx(15.0)
    assert len(mechanical) == len(result["cogging_torque_waveform"]["torque_Nm"])

    pdf = build_public_run_pdf(**arguments)
    text = " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())
    assert "Cogging torque" in text
    for field in ("peak_to_peak_Nm", "peak_Nm", "first_harmonic_Nm"):
        assert f"{_number(record[field])} N m" in text
    assert "24 per mechanical revolution" in text
    assert "60 deg elec, 15 deg mech" in text
    assert "Cogging torque: experimental." in text


def test_a_zero_current_run_reports_the_cogging_sweep_not_its_loaded_swing() -> None:
    result = _stored_result()
    result["solve_metadata"]["current_amplitude_A"] = 0.0
    result["summary"].update(avg_torque_Nm=0.001, torque_ripple_pct=99999.0)
    result["torque_waveform"]["torque_Nm"] = [0.9, -0.9]
    config = deepcopy(EXAMPLE)
    pdf = build_public_run_pdf(project=config, request={"resolved_config": config}, result=result, material={}, manifest={})
    text = " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())
    record = result["summary"]["cogging"]
    assert f"Cogging torque p-p {_plain(record['peak_to_peak_Nm'])} N m" in text
    assert "From the cogging sweep" in text


def test_pdf_and_csv_do_not_turn_an_unavailable_end_mismatch_into_zero() -> None:
    result = _stored_result()
    result["summary"]["cogging"]["endpoint_mismatch_Nm"] = None
    config = deepcopy(EXAMPLE)
    arguments = {"project": config, "request": {"resolved_config": config}, "result": result, "material": {}, "manifest": {}}
    payload = _public_result_payload(SolveResult.model_validate(result))
    assert payload["summary"]["cogging"]["endpoint_mismatch_Nm"] is None
    rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode("utf-8"))))
    assert ["cogging", "endpoint_mismatch_Nm", "N m", "", ""] in rows
    pdf = build_public_run_pdf(**arguments)
    text = " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())
    assert "Unavailable (endpoints not independently meshed)" in text


@pytest.mark.weekly
def test_a_real_solve_of_the_example_returns_its_cogging_period(tmp_path, monkeypatch) -> None:
    """The public pipeline end to end, at Preview: the record reaches the result and the period closes."""

    from backend.solver import Magneto2DSolver

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    config = _config("quick", back_emf=False, thd_analysis=False)
    config.solve_params.mesh_density = "coarse"
    result = Magneto2DSolver(launch_surface=True).solve(config)
    record = result.summary.cogging
    waveform = result.cogging_torque_waveform
    assert record is not None and waveform is not None
    assert record.positions_per_period == COGGING_POSITIONS_PER_PERIOD["quick"]
    assert waveform.electrical_angle_deg == pytest.approx(cogging_angle_grid(config))
    assert record.method == COGGING_TORQUE_METHOD
    assert result.summary.cogging_torque_Nm == record.peak_to_peak_Nm == pytest.approx(max(waveform.torque_Nm) - min(waveform.torque_Nm))
    limits = _example_sweep()["limits"]
    assert record.endpoint_mismatch_Nm <= limits["endpoint_mismatch_fraction"] * record.peak_to_peak_Nm
    assert abs(record.mean_Nm) <= limits["mean_fraction"] * record.peak_to_peak_Nm
    assert record.peak_to_peak_of_loaded_pct is not None
