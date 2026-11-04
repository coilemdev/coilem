"""The UI and exports describe recorded convergence, with method-specific limits."""

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.convergence_reporting import convergence_report
from backend.models import MotorConfig
from backend.models.config import SolveOptionsConfig
from backend.public_main import app
from backend.public_report import build_public_run_csv, build_public_run_pdf
from backend.public_routes.solve import _public_result_payload
from backend.solve_workspace import SolveWorkspace
from backend.solver import Magneto2DSolver
from tests.test_nonlinear_convergence import record
from tests.test_public_report_exports import _result


def mixed_result():
    result = _result()
    result["solve_metadata"].update(solve_quality="standard", back_emf_computed=True)
    result["loaded_nonlinear_convergence"] = [record(iterations=12), record("newton", 24), record(iterations=99, reused=True), record(iterations=20)]
    result["no_load_nonlinear_convergence"] = [record(iterations=8) for _ in range(4)]
    return result


def rows(report):
    return {row["key"]: row["value"] for row in report["summary"]}


def method_rows(report, method):
    data = next(value for value in report["methods"] if value["method"] == method)
    return {row["key"]: row["value"] for row in (*data["summary"], *data["details"])}


def test_reused_fields_are_not_iteration_samples_and_residual_methods_stay_separate():
    report = convergence_report(mixed_result())
    assert rows(report)["iterations_max_median"] == "24 / 8"
    assert rows(report)["reused_positions"] == "1"
    assert rows(report)["accuracy_plan"] == "Standard"
    assert method_rows(report, "picard")["final_residual_max"] == "0.02"
    assert method_rows(report, "newton")["final_residual_max"] == "0.003"
    assert method_rows(report, "picard")["stopping_ratio_max"] == "0.4"
    assert method_rows(report, "newton")["stopping_ratio_max"] == "0.3"


@pytest.mark.parametrize("iterations,expected", [(79, "ok"), (80, "review"), (100, "review")])
def test_iteration_warning_starts_at_eighty_percent(iterations, expected):
    result = {"loaded_nonlinear_convergence": [record(iterations=iterations)]}
    assert convergence_report(result)["status"] == expected


def test_continuation_checks_each_stage_cap_as_well_as_the_total_cap():
    newton = record("newton", 91)
    newton.update(max_iterations=200, stage_iterations=[90, 1])
    report = convergence_report({"loaded_nonlinear_convergence": [newton]})
    assert report["status"] == "review"
    assert report["positions"][0]["iteration_fraction"] == 0.9
    assert "per-stage" in report["warnings"][0]


def test_unrelaxed_picard_mismatch_is_compared_with_its_actual_tolerance():
    picard = record()
    picard["raw_max_residual"] = 0.5
    report = convergence_report({"loaded_nonlinear_convergence": [picard]})
    assert method_rows(report, "picard")["final_residual_max"] == "0.5"
    assert report["positions"][0]["stopping_ratio"] == 10
    assert report["status"] == "review"


@pytest.mark.parametrize("mismatch,expected", [(0.05, "ok"), (0.05001, "review")])
def test_final_mismatch_warns_only_above_the_recorded_tolerance(mismatch, expected):
    picard = record()
    picard["raw_max_residual"] = mismatch
    assert convergence_report({"loaded_nonlinear_convergence": [picard]})["status"] == expected


def test_newton_absolute_floor_can_pass_even_with_a_large_relative_residual():
    newton = record("newton", 1)
    newton.update(scaled_residual=2.0, rhs_scaled_residual=5e-9, absolute_residual_floor=1e-8)
    report = convergence_report({"loaded_nonlinear_convergence": [newton]})
    assert report["status"] == "ok"
    assert report["positions"][0]["stopping_ratio"] == 0.5
    assert method_rows(report, "newton")["final_residual_max"] == "2"
    assert method_rows(report, "newton")["absolute_floors"] == "1e-8"


def test_extreme_finite_historical_tolerance_cannot_break_json_serialization():
    picard = record()
    picard.update(raw_max_residual=1e308, tolerance=1e-308)
    report = convergence_report({"loaded_nonlinear_convergence": [picard]})
    assert report["status"] == "review"
    json.dumps(report, allow_nan=False)


def test_historical_iteration_counts_and_metadata_cannot_manufacture_residual_evidence():
    result = {"loaded_nonlinear_iterations": [20, 30], "solve_metadata": {"nonlinear_tolerance": 0.01, "nonlinear_worst_final_mismatch": 0.001}}
    report = convergence_report(result)
    assert report["status"] == "not_recorded"
    assert report["methods"] == []
    assert rows(report)["iterations_max_median"] == "Not recorded"
    assert rows(report)["accuracy_plan"] == "Not recorded"


@pytest.mark.parametrize("bad", [None, {}, {**record(), "raw_max_residual": float("nan")}])
def test_missing_or_invalid_positions_do_not_receive_a_green_status(bad):
    report = convergence_report({"loaded_nonlinear_convergence": [record(), bad]})
    assert report["status"] == "partial"
    assert rows(report)["recorded_positions"] == "1 / 2"
    assert report["positions"][1]["record"] is None


def test_omitted_no_load_sweep_does_not_turn_legacy_placeholders_into_missing_records():
    report = convergence_report(
        {"loaded_nonlinear_convergence": [record(), record()], "no_load_nonlinear_iterations": [0, 0], "solve_metadata": {"back_emf_computed": False}}
    )
    assert report["status"] == "ok"
    assert rows(report)["recorded_positions"] == "2 / 2"


def test_linear_solve_has_no_nonlinear_warning_even_at_its_one_iteration_cap():
    linear = record(iterations=1)
    linear.update(
        method="linear",
        max_iterations=1,
        stage_iterations=[1],
        stage_iteration_cap=1,
        raw_max_residual=None,
        tolerance=0,
        residual_definition="linear material",
        stopping_test="not applicable",
    )
    report = convergence_report({"loaded_nonlinear_convergence": [linear]})
    assert report["status_label"] == "Linear solves"
    assert report["warnings"] == []
    assert rows(report)["iterations_max_median"] == "Not applicable"


def test_position_indices_survive_when_native_and_public_angle_grids_differ():
    report = convergence_report({"loaded_nonlinear_convergence": [record(), record()], "torque_waveform": {"electrical_angle_deg": [0, 30, 60, 90]}})
    assert report["status"] == "partial"
    assert all(p["electrical_angle_deg"] is None for p in report["positions"])


def test_public_solve_and_old_run_load_use_the_export_report_without_mutation(monkeypatch):
    result = mixed_result()
    original = deepcopy(result)
    fresh = _public_result_payload(SimpleNamespace(model_dump=lambda **_: deepcopy(result)))
    assert fresh["solver_convergence"] == convergence_report(result)
    stored = {"result": result, "manifest": {}}
    monkeypatch.setattr(SolveWorkspace, "load_run", lambda *_: stored)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/runs/example/old-run")
    assert response.status_code == 200
    assert response.json()["result"]["solver_convergence"] == fresh["solver_convergence"]
    assert result == original
    assert "solver_convergence" not in stored["result"]


def test_pdf_csv_and_ui_report_share_values_warnings_and_per_position_evidence():
    result = mixed_result()
    original = deepcopy(result)
    report = convergence_report(result)
    arguments = dict(project={}, request={}, result=result, material={}, manifest={})
    csv_rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode())))
    csv_summary = {row[1]: row[3] for row in csv_rows[2:] if row[0] == "convergence"}
    reader = PdfReader(io.BytesIO(build_public_run_pdf(**arguments)))
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    for row in report["summary"]:
        assert csv_summary[row["key"]] == row["value"]
        assert row["label"] in text and row["value"] in text
    for method in report["methods"]:
        for row in (*method["summary"], *method["details"]):
            assert csv_summary[f"{method['method']}.{row['key']}"] == row["value"]
            assert row["label"] in text and row["value"] in text
    assert all(warning in text for warning in report["warnings"])
    assert ["convergence_loaded", "raw_max_residual", "", "0.02", "0"] in csv_rows
    assert ["convergence_loaded", "scaled_residual", "", "0.003", "1"] in csv_rows
    assert ["convergence_no_load", "iterations", "", "8", "0"] in csv_rows
    assert result == original


def test_pdf_convergence_text_snapshot():
    pdf = build_public_run_pdf(project={}, request={}, result=mixed_result(), material={}, manifest={})
    lines = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        for line in (page.extract_text() or "").splitlines():
            if line == "coilEM" or line.startswith(("Immutable run", "Completion time not recorded", "Page ")):
                continue
            lines.append(line.strip())
    text = " ".join(" ".join(lines).split())
    section = text.split("Solver convergence ", 1)[1].split(" Warnings ", 1)[0]
    assert section == Path("tests/fixtures/convergence_report_snapshot.txt").read_text().strip()


@pytest.mark.weekly
@pytest.mark.parametrize("method", ["picard", "newton"])
def test_native_serialized_field_evidence_reaches_the_public_convergence_report(tmp_path, monkeypatch, method):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "user-data"))
    config = MotorConfig.model_validate_json(Path("tests/fixtures/spm_4p12s_simple.json").read_text())
    config.solve_params.solve_quality = "custom"
    config.solve_params.rotor_sweep_range_deg = 2
    config.solve_params.rotor_step_deg = 2
    config.solve_params.mesh_density = "coarse"
    config.solve_params.nonlinear_solver = method
    config.solve_params.magneto2d_workers = 1
    config.solve_options = SolveOptionsConfig(back_emf=False, flux_density=False, thd_analysis=False)
    result = Magneto2DSolver().solve(config)
    payload = _public_result_payload(result)
    report = payload["solver_convergence"]
    assert report["status"] in ("ok", "review")
    assert {p["record"]["method"] for p in report["positions"]} == {method}
    assert all(p["stopping_ratio"] is not None for p in report["positions"])
    assert all(p["record"]["residual_definition"] for p in report["positions"])
    assert all(p["record"]["iterations"] > 0 for p in report["positions"])
