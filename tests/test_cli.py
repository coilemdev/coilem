"""The headless `coilem` commands: JSON documents, exit codes and the `coilem` package."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend import __version__, launcher
from backend import client as coilem
from backend.client import _cli, _solve

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "tests/fixtures/run_setup_parity.json").read_text(encoding="utf-8"))
SPM_FIXTURE = ROOT / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json"


@pytest.fixture
def design(tmp_path) -> Path:
    """The starter motor saved by the app with four setups, "High Speed" active and unchanged."""

    path = tmp_path / "motor.coilem"
    path.write_text(json.dumps(PARITY["designs"]["high_speed_saved"]), encoding="utf-8")
    return path


def run(capsys, *argv: str) -> tuple[int, dict | None, str]:
    code = _cli.main(list(argv))
    captured = capsys.readouterr()
    document = json.loads(captured.out) if captured.out.strip() else None
    return code, document, captured.err


def _fake_result(**summary) -> dict:
    return {
        "summary": {"avg_torque_Nm": 2.5, "torque_ripple_pct": float("nan"), "back_emf_fundamental_V": None, **summary},
        "torque_waveform": {"electrical_angle_deg": [0.0, 30.0], "torque_Nm": [2.4, 2.6]},
        "solve_metadata": {"mesh_element_count": 10},
    }


# -- Documents ----------------------------------------------------------------------------


def test_version_writes_one_json_document_on_stdout(capsys) -> None:
    code, document, err = run(capsys, "version")
    assert code == 0 and err == ""
    assert document["schema"] == "coilem.cli.version/v1" and document["ok"] is True and document["coilem_version"] == __version__
    assert document["build"]["installation"] in ("source", "package")


def test_schema_describes_inputs_units_setups_and_exit_codes(capsys, tmp_path) -> None:
    out = tmp_path / "schema.json"
    code, document, err = run(capsys, "schema", "--out", str(out))
    assert code == 0 and document is None and "wrote" in err
    schema = json.loads(out.read_text(encoding="utf-8"))
    stator = schema["design"]["$defs"]["StatorConfig"]["properties"]
    assert stator["OD_mm"]["x-unit"] == "mm" and stator["OD_mm"]["minimum"] > 0
    params = schema["design"]["$defs"]["SolveParams"]["properties"]
    assert params["current_amplitude_A"]["x-unit"] == "A" and params["rated_speed_rpm"]["x-unit"] == "rpm"
    assert set(schema["analyses"]["names"]) == set(coilem.ANALYSES)
    assert schema["exit_codes"]["3"].startswith("invalid input") and "SETUP_NOT_FOUND" in schema["error_codes"]
    assert schema["run_setup"]["properties"]["parameters"]["required"][0] == "rated_speed_rpm"
    assert [setup["kind"] for setup in schema["reference_setups"]] == ["reference", "reference"]


def test_redirected_cp1252_stdout_preserves_schema_and_input_errors(tmp_path) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"}
    command = [sys.executable, "-m", "coilem"]
    out = tmp_path / "schema.json"
    subprocess.run([*command, "schema", "--out", str(out)], cwd=ROOT, env=env, capture_output=True, check=True)
    schema = subprocess.run([*command, "schema"], cwd=ROOT, env=env, capture_output=True, check=True)
    assert json.loads(schema.stdout) == json.loads(out.read_text(encoding="utf-8"))
    assert "θ" in out.read_text(encoding="utf-8")

    missing = tmp_path / "θ.coilem"
    failure = subprocess.run([*command, "check", str(missing)], cwd=ROOT, env=env, capture_output=True)
    document = json.loads(failure.stdout)
    assert failure.returncode == document["exit_code"] == 3
    assert document["error"]["error_code"] == "DESIGN_FILE_UNREADABLE"
    assert str(missing) in document["error"]["message"]


def test_check_reports_the_setup_and_effective_settings(capsys, design) -> None:
    code, document, err = run(capsys, "check", str(design))
    assert code == 0 and document["schema"] == "coilem.cli.check/v1"
    assert document["setup"]["source"] == "active" and document["setup"]["run_setup"]["name"] == "High Speed"
    assert document["effective"]["solve_params"]["solve_quality"] == "fine" and document["warnings"] == []
    assert document["design"] == {"path": str(design.resolve()), "name": "high_speed_saved"}
    assert "using run setup 'High Speed'" in err

    code, document, err = run(capsys, "check", str(design), "--setup", "Hot operating point", "--quiet")
    assert code == 0 and err == ""
    assert document["setup"]["source"] == "requested" and document["effective"]["solve_params"]["magnet_temperature_C"] == 120


def test_check_settings_match_the_python_client_and_the_solve_route(capsys, design) -> None:
    from backend.public_routes.solve import _validated_solve_request

    argv = ["--setup", "High Speed", "--set", "current_amplitude_A=25", "--analyses", "torque,back_emf", "--quality", "quick"]
    code, document, _ = run(capsys, "check", str(design), *argv)
    assert code == 0
    options = dict(setup="High Speed", solve_params={"current_amplitude_A": 25}, analyses=["torque", "back_emf"], quality="quick")
    prepared = coilem.prepare(coilem.Motor.load(design), **options)
    assert document["request"] == prepared.request == coilem.build_request(coilem.Motor.load(design), **options)
    assert document["setup"] == prepared.setup.to_dict() and document["setup"]["modified"] is True
    ours = _solve.prepared_config(prepared.request).model_dump(mode="json")
    route = _validated_solve_request(prepared.request)[0].model_dump(mode="json")
    ours["solve_params"].pop("stream_noload_field_lines")
    route["solve_params"].pop("stream_noload_field_lines")
    assert ours == route


def test_active_and_requested_setup_share_catalog_defaults_after_clearing_overrides(capsys, design) -> None:
    saved = json.loads(design.read_text(encoding="utf-8"))
    library = saved["run_setups"]
    active = next(setup for setup in library["profiles"] if setup["id"] == library["activeId"])
    keys = ("magnet_temperature_C", "mechanical_loss_W", "winding_temperature_C")
    for key in keys:
        active["parameters"][key] = None
        saved["solve_params"].pop(key, None)
    saved["solve_params"]["winding_temperature_C"] = None
    original = json.dumps(saved)
    design.write_text(original, encoding="utf-8")

    default_code, default, _ = run(capsys, "check", str(design))
    named_code, named, _ = run(capsys, "check", str(design), "--setup", active["name"])
    assert default_code == named_code == 0
    assert default["effective"] == named["effective"] == coilem.prepare(coilem.Motor.load(design)).effective_settings()
    assert default["setup"]["run_setup"] == named["setup"]["run_setup"] == coilem.prepare(design).setup.label
    assert default["setup"]["modified"] is named["setup"]["modified"] is False
    assert design.read_text(encoding="utf-8") == original

    saved["solve_params"].update(magnet_temperature_C=100, winding_temperature_C=80, mechanical_loss_W=7)
    cleared = coilem.prepare(saved, setup=active["name"])
    assert cleared.effective_settings() == named["effective"]
    assert all(key not in cleared.request["solve_params"] for key in keys)
    assert saved["solve_params"]["magnet_temperature_C"] == 100


def test_setups_lists_the_designs_setups(capsys, design) -> None:
    code, document, _ = run(capsys, "setups", str(design), "--compact")
    assert code == 0 and document["schema"] == "coilem.cli.setups/v1"
    assert document["active"] == {"id": "user-high-speed", "version": 3}
    assert [(row["name"], row["usable"]) for row in document["setups"]] == [
        ("High Speed", True), ("Hot operating point", True), ("Map, operating point only", True), ("Elmer numerics", False),
    ]
    assert "elmer" in document["setups"][3]["reason"] and document["notes"] == []


def test_check_schema_and_setups_do_no_solver_work(capsys, design, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("solver work started")

    monkeypatch.setattr(_solve, "_solve_in_process", refuse)
    monkeypatch.setattr("backend.selected_analyses.solve_selected_analyses", refuse)
    monkeypatch.setattr("backend.solver.Magneto2DSolver.__init__", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    gmsh = pytest.importorskip("gmsh")
    monkeypatch.setattr(gmsh, "initialize", refuse)
    for argv in (["check", str(design), "--setup", "High Speed"], ["schema"], ["setups", str(design)], ["version"]):
        code, document, _ = run(capsys, *argv)
        assert code == 0 and document["ok"], argv


def test_solve_writes_compact_results_with_missing_values_kept_missing(capsys, design, monkeypatch, tmp_path) -> None:
    solved = []

    def fake_in_process(body, on_progress, *, fields=False):
        solved.append((body, fields))
        return _fake_result()

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    out = tmp_path / "result.json"
    code, document, err = run(capsys, "solve", str(design), "--setup", "Hot operating point", "--out", str(out))
    assert code == 0 and document is None and f"wrote {out}" in err
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema"] == "coilem.cli.solve/v1" and written["solver"] == {"name": "magneto2d", "mode": "in_process", "server": None}
    assert written["setup"]["run_setup"]["name"] == "Hot operating point"
    metrics = written["metrics"]
    assert metrics["average_torque_Nm"] == 2.5
    assert metrics["torque_ripple_pct"] is None and metrics["back_emf_fundamental_V"] is None and metrics["cogging_peak_to_peak_Nm"] is None
    assert written["result"]["summary"]["torque_ripple_pct"] is None, "NaN is written as missing, never zero"
    assert written["request"] == solved[0][0] and solved[0][1] is False
    loaded = coilem.Result.load(out)
    assert loaded.average_torque_Nm == 2.5 and loaded.setup["name"] == "Hot operating point"
    assert not list(tmp_path.glob(".*.partial"))


def test_solve_progress_goes_to_stderr_only(capsys, design, monkeypatch) -> None:
    def fake_in_process(body, on_progress, *, fields=False):
        on_progress(1, 2, "magneto2d_sweep")
        on_progress(2, 2, "magneto2d_sweep")
        return _fake_result()

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    code, document, err = run(capsys, "solve", str(design), "--progress", "json")
    assert code == 0 and document["ok"]
    events = [json.loads(line) for line in err.splitlines() if line.startswith("{")]
    assert events == [
        {"event": "progress", "done": 1, "total": 2, "stage": "magneto2d_sweep"},
        {"event": "progress", "done": 2, "total": 2, "stage": "magneto2d_sweep"},
    ]


# -- Errors and exit codes ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "code", "error_code", "field"),
    [
        (["check", "{missing}"], 3, "DESIGN_FILE_UNREADABLE", "design"),
        (["check", "{garbage}"], 3, "DESIGN_FILE_UNREADABLE", None),
        (["check", "{design}", "--setup", "Nope"], 3, "SETUP_NOT_FOUND", "setup"),
        (["check", "{design}", "--profile", "Elmer numerics"], 3, "SETUP_SOLVER_UNAVAILABLE", "setup"),
        (["check", "{design}", "--setup", "Prius · loaded torque reference"], 3, "SETUP_INCOMPATIBLE", "setup"),
        (["check", "{design}", "--set", "no_such_setting=1"], 3, "INVALID_INPUT", "solve_params.no_such_setting"),
        (["check", "{design}", "--set", "current_amplitude_A=-5"], 3, "INVALID_INPUT", "solve_params.current_amplitude_A"),
        (["check", "{design}", "--analyses", "torque,vibration"], 3, "INVALID_INPUT", "analyses"),
        (["solve", "{design}", "--out", "{nowhere}"], 3, "OUTPUT_UNWRITABLE", "out"),
    ],
)
def test_invalid_input_is_one_error_document_and_exit_code_3(capsys, design, tmp_path, argv, code, error_code, field) -> None:
    garbage = tmp_path / "garbage.coilem"
    garbage.write_text("{not json", encoding="utf-8")
    paths = {"design": design, "missing": tmp_path / "missing.coilem", "garbage": garbage, "nowhere": tmp_path / "no" / "result.json"}
    argv = [part.format(**paths) for part in argv]
    exit_code, document, err = run(capsys, *argv)
    assert exit_code == code
    assert document["schema"] == "coilem.cli.error/v1" and document["ok"] is False and document["exit_code"] == code
    error = document["error"]
    assert error["error_code"] == error_code and error["field"] == field
    assert set(error) >= {"error_code", "message", "field", "suggestion"}
    assert err.startswith("coilem: ")


def test_an_error_goes_to_the_out_file_when_one_is_given(capsys, design, tmp_path) -> None:
    out = tmp_path / "result.json"
    code, document, _ = run(capsys, "solve", str(design), "--setup", "Nope", "--out", str(out))
    assert code == 3 and document is None
    assert json.loads(out.read_text(encoding="utf-8"))["error"]["error_code"] == "SETUP_NOT_FOUND"


@pytest.mark.parametrize(
    ("raised", "code", "error_code"),
    [
        (coilem.SolveError("Magneto2D failed: boom", error_code="SOLVER_FAILED"), 4, "SOLVER_FAILED"),
        (coilem.SolveError("no stable solution", error_code="NONLINEAR_CONVERGENCE_FAILED"), 4, "NONLINEAR_CONVERGENCE_FAILED"),
        (coilem.SolveError("The solve was cancelled.", error_code="SOLVER_CANCELLED"), 130, "SOLVER_CANCELLED"),
        (KeyboardInterrupt(), 130, "SOLVER_CANCELLED"),
        (RuntimeError("unexpected"), 1, "INTERNAL_ERROR"),
    ],
)
def test_solve_failures_and_cancellation_have_their_own_exit_codes(capsys, design, monkeypatch, raised, code, error_code) -> None:
    def fake_in_process(body, on_progress, *, fields=False):
        raise raised

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    exit_code, document, _ = run(capsys, "solve", str(design))
    assert exit_code == code and document["error"]["error_code"] == error_code and document["exit_code"] == code


@pytest.mark.parametrize("argv", [[], ["solve"], ["check", "x.coilem", "--set", "current_amplitude_A"], ["solve", "x", "--progress", "loud"]])
def test_command_line_mistakes_exit_2_with_usage_on_stderr(capsys, argv) -> None:
    code = _cli.main(argv)
    captured = capsys.readouterr()
    assert code == 2 and captured.out == "" and "error:" in captured.err


# -- The coilem command and package ------------------------------------------------------------


def test_the_launcher_runs_the_headless_commands_and_keeps_its_own(capsys, monkeypatch) -> None:
    assert launcher.HEADLESS_COMMANDS == _cli.COMMANDS
    assert launcher.main(["version", "--compact"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "coilem.cli.version/v1"
    with pytest.raises(SystemExit) as shown:
        launcher.main(["--version"])
    assert shown.value.code == 0 and f"coilEM {__version__}" in capsys.readouterr().out
    called = []
    monkeypatch.setattr("backend.benchmark_suite.command.main", lambda argv: called.append(argv) or 0)
    assert launcher.main(["benchmark", "--list"]) == 0 and called == [["--list"]]
    with pytest.raises(SystemExit):
        launcher.main(["--help"])
    assert "coilem check | solve | setups | schema | version" in " ".join(capsys.readouterr().out.split())


def test_importing_coilem_starts_nothing() -> None:
    probe = (
        "import json, sys, threading\n"
        "import coilem, backend.client\n"
        "print(json.dumps({'modules': sorted(m for m in ('backend.public_main', 'backend.launcher', 'uvicorn', 'backend.solver', "
        "'backend.selected_analyses') if m in sys.modules), 'threads': threading.active_count(), 'version': coilem.__version__, "
        "'same': coilem.solve is backend.client.solve and coilem.Motor is backend.client.Motor}))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {"modules": [], "threads": 1, "version": __version__, "same": True}


def test_python_m_coilem_runs_the_same_commands(design) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    completed = subprocess.run(
        [sys.executable, "-m", "coilem", "check", str(design), "--setup", "Nope", "--compact"],
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=300,
    )
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["error"]["error_code"] == "SETUP_NOT_FOUND"
    assert completed.stderr.startswith("coilem: No run setup named 'Nope'")


# -- One real solve, three ways ------------------------------------------------------------------


@pytest.mark.weekly
def test_python_cli_and_the_solve_route_solve_the_same_request_to_the_same_numbers(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.public_main import create_app

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))
    design = tmp_path / "motor.coilem"
    design.write_text(json.dumps(PARITY["designs"]["high_speed_saved"]), encoding="utf-8")
    options = ["--setup", "Hot operating point", "--analyses", "torque,back_emf", "--quality", "quick", "--mesh", "coarse"]
    python = coilem.solve(
        coilem.Motor.load(design), setup="Hot operating point", analyses=["torque", "back_emf"], quality="quick", mesh="coarse"
    )
    out = tmp_path / "cli.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "COILEM_USER_DATA_ROOT": str(tmp_path / "cli-data")}
    completed = subprocess.run(
        [sys.executable, "-m", "coilem", "solve", str(design), *options, "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=900,
    )
    assert completed.returncode == 0, completed.stderr
    cli = json.loads(out.read_text(encoding="utf-8"))
    assert cli["request"] == python.request
    with TestClient(create_app(), base_url="http://127.0.0.1:58000") as app:
        response = app.post("/solve", json=python.request)
    assert response.status_code == 200, response.text
    route = coilem.Result(response.json())
    for name in ("average_torque_Nm", "torque_ripple_pct", "back_emf_fundamental_V", "lambda_pm_Wb"):
        assert cli["metrics"][name] == pytest.approx(python.metrics()[name], rel=1e-9)
        assert route.metrics()[name] == pytest.approx(python.metrics()[name], rel=1e-9)
