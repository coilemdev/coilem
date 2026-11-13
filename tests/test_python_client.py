"""The Python client: typed inputs, request JSON, results, sweeps and one small real solve."""

from __future__ import annotations

import csv
import json
import math
import socket
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from backend import client as coilem
from backend.client import _solve
from backend.client._results import FIELD_KEYS

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted(ROOT.glob("benchmarks/*/fixtures/*.json"))
SPM_FIXTURE = ROOT / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json"
IPM_FIXTURE = ROOT / "benchmarks/macos-native-20261015-738d951/fixtures/ipm_flat_8p12s_fsae_contract__native.json"


def _spm_motor() -> coilem.Motor:
    """The geometry of SPM_FIXTURE, typed in."""

    return coilem.Motor(
        topology="SPM",
        stator=coilem.Stator(
            OD_mm=100, ID_mm=60, slot_count=12, stack_length_mm=50,
            slot_opening_mm=2, tooth_width_mm=9, yoke_thickness_mm=8,
        ),
        rotor=coilem.Rotor(OD_mm=54, pole_count=8, magnet_thickness_mm=2.5, magnet_width_mm=16.5, magnet_embrace=0.833),
        winding=coilem.Winding(type="concentrated", layers=1, turns_per_coil=12),
    )


# -- Request JSON --------------------------------------------------------------------


def test_every_benchmark_fixture_round_trips(tmp_path) -> None:
    assert len(FIXTURES) > 100
    failures = []
    for index, path in enumerate(FIXTURES):
        original = json.loads(path.read_text(encoding="utf-8"))
        motor = coilem.Motor.load(path)
        saved = motor.save(tmp_path / f"{index}.json")
        if motor.to_request() != original or json.loads(saved.read_text(encoding="utf-8")) != original:
            failures.append(path.relative_to(ROOT).as_posix())
        elif coilem.Motor.load(saved) != motor:
            failures.append(f"{path.relative_to(ROOT).as_posix()} (reload)")
    assert failures == []


def test_the_app_wrapped_request_shape_loads() -> None:
    plain = json.loads(SPM_FIXTURE.read_text(encoding="utf-8"))
    motor = coilem.Motor.from_request({"config": plain, "project_name": "demo", "solver": "magneto2d"})
    assert motor.to_request() == {**plain, "solver": "magneto2d"}
    with pytest.raises(coilem.InputError) as caught:
        coilem.Motor.from_request({"config": plain, "extra": 1})
    assert caught.value.field == "extra"


def test_design_files_saved_by_the_app_load_and_old_ones_are_refused() -> None:
    import re

    from backend.client._inputs import DESIGN_FILE_SCHEMA_VERSION

    schema = re.search(r"COILEM_SCHEMA_VERSION = (\d+);", (ROOT / "frontend/src/api/projectSchema.ts").read_text(encoding="utf-8"))
    assert schema is not None and int(schema[1]) == DESIGN_FILE_SCHEMA_VERSION
    design = ROOT / "frontend/src/public/examples/spm_outrunner_14p12s.coilem"
    motor = coilem.Motor.load(design)
    assert motor.rotor_layout == "outer" and coilem.check(motor) == []
    assert motor.to_request() == json.loads(design.read_text(encoding="utf-8"))
    old = {**motor.to_request(), "openem_schema_version": 2}
    with pytest.raises(coilem.InputError) as caught:
        coilem.Motor.from_request(old)
    assert caught.value.field == "openem_schema_version" and "save it" in str(caught.value)


def test_typed_sections_give_the_fixture_geometry() -> None:
    typed, loaded = _spm_motor(), coilem.Motor.load(SPM_FIXTURE)
    for section in ("stator", "winding", "materials"):
        assert getattr(typed, section).model_dump() == getattr(loaded, section).model_dump(), section
    # The fixture also stores interior-magnet fields that a surface-magnet rotor does not use.
    surface_fields = {"OD_mm", "ID_mm", "pole_count", "magnet_thickness_mm", "magnet_width_mm", "magnet_embrace"}
    assert typed.rotor.model_dump(include=surface_fields) == loaded.rotor.model_dump(include=surface_fields)
    assert typed.topology == "SPM" and typed.operating_point is None and typed.analyses is None
    assert repr(typed) == "Motor(SPM, 8 poles / 12 slots, inner rotor, stack 50 mm)"


def test_replace_and_requests_leave_the_motor_unchanged() -> None:
    motor = coilem.Motor.load(SPM_FIXTURE)
    before = motor.to_request()
    longer = motor.replace(stator={"stack_length_mm": 80}, materials=coilem.Materials(magnet_grade="N52"))
    coilem.build_request(motor, coilem.OperatingPoint(current_A=5))
    motor.to_request()["stator"]["slot_count"] = 99
    assert motor.to_request() == before
    assert longer.stator.stack_length_mm == 80 and longer.stator.slot_count == 12
    assert longer.materials.magnet_grade == "N52"
    assert longer.to_request()["solve_params"]["femm_workers"] == 1  # keys this version does not read are kept


def test_build_request_layers_the_settings_over_the_saved_ones() -> None:
    motor = coilem.Motor.load(SPM_FIXTURE)
    assert motor.operating_point == coilem.OperatingPoint(current_A=20, current_angle_deg=30, speed_rpm=3000)
    body = coilem.build_request(
        motor,
        coilem.OperatingPoint(current_A=5, current_angle_deg=45, speed_rpm=1500, magnet_temperature_C=80),
        analyses=["torque", "cogging"],
        quality="quick",
        mesh="coarse",
        solve_params={"nonlinear_solver": "picard"},
    )
    params = body["solve_params"]
    assert (params["current_amplitude_A"], params["current_angle_deg"], params["rated_speed_rpm"]) == (5, 45, 1500)
    assert (params["magnet_temperature_C"], params["solve_quality"], params["mesh_density"]) == (80, "quick", "coarse")
    assert params["nonlinear_solver"] == "picard" and params["torque_method"] == "weighted_stress"
    assert {key for key, on in body["solve_options"].items() if on} == {"torque_sweep", "cogging_torque"}
    # A motor with no saved settings is solved at 0 A with the app's defaults.
    bare = coilem.build_request(_spm_motor())
    assert bare["solve_params"]["current_amplitude_A"] == 0 and "solve_options" not in bare


@pytest.mark.parametrize(
    ("make", "field"),
    [
        (lambda m: coilem.Stator(OD_mm=100, ID_mm=60, slot_count=4, stack_length_mm=50, slot_opening_mm=2,
                                 tooth_width_mm=9, yoke_thickness_mm=8), "stator.slot_count"),
        (lambda m: coilem.Winding(turns_per_coil=0), "winding.turns_per_coil"),
        (lambda m: coilem.Wire(wire_bare_diameter_mm=20), "winding.wire.wire_bare_diameter_mm"),
        (lambda m: coilem.Materials(magnet_grade="N99"), "materials.magnet_grade"),
        (lambda m: coilem.OperatingPoint(current_A=-1), "operating_point.current_A"),
        (lambda m: coilem.OperatingPoint(speed_rpm=40000), "operating_point.speed_rpm"),
        (lambda m: coilem.OperatingPoint().replace(curent_A=1), "operating_point.curent_A"),
        (lambda m: m.replace(rotor={"OD_mm": 70}), "rotor"),
        (lambda m: m.replace(stator={"slot_count": "twelve"}), "stator.slot_count"),
        (lambda m: m.replace(statorr={}), "statorr"),
        (lambda m: coilem.build_request(m, analyses=["torq"]), "analyses"),
        (lambda m: coilem.build_request(m, quality="ultra"), "quality"),
        (lambda m: coilem.build_request(m, solve_params={"rotor_step_deg": 0.1}), "solve_params.rotor_step_deg"),
        (lambda m: coilem.check(m.replace(rotor={"pole_count": 7})), "rotor.pole_count"),
        (lambda m: coilem.check(m.replace(materials={"stator_steel": "M270"})), "materials"),
        (lambda m: coilem.sweep(m, current_A=[10, 2000]), "operating_point.current_A"),
    ],
)
def test_input_errors_name_the_field(make, field) -> None:
    with pytest.raises(coilem.InputError) as caught:
        make(_spm_motor())
    assert caught.value.field == field
    assert str(caught.value).startswith(field)
    assert isinstance(caught.value, ValueError)


def test_check_accepts_the_fixtures_used_by_the_examples() -> None:
    for path in (SPM_FIXTURE, IPM_FIXTURE):
        assert coilem.check(coilem.Motor.load(path)) == []


@pytest.mark.parametrize("fixture", [SPM_FIXTURE, IPM_FIXTURE], ids=["spm", "ipm"])
def test_the_client_solves_what_the_solve_route_would(fixture) -> None:
    from backend.public_routes.solve import _validated_solve_request

    motor = coilem.Motor.load(fixture).replace(solve_params={"rotor_rotation_model": "fixed_mesh"})
    body = coilem.build_request(motor, quality="quick", analyses=["torque", "back_emf", "cogging"])
    ours = _solve.prepared_config(body).model_dump(mode="json")
    route = _validated_solve_request(body)[0].model_dump(mode="json")
    assert ours["solve_params"].pop("stream_noload_field_lines") is False
    route["solve_params"].pop("stream_noload_field_lines")
    assert ours == route


# -- Results ---------------------------------------------------------------------------


def _result_data() -> dict:
    return {
        "summary": {
            "avg_torque_Nm": 2.5, "torque_ripple_pct": 12.0, "back_emf_fundamental_V": 7.5, "lambda_pm_Wb": 0.01,
            "solve_time_s": 3.0, "peak_flux_density_teeth_T": 1.6, "peak_flux_density_yoke_T": 1.2,
            "dq_flux_linkage": {
                "i_d_A": -10.0, "i_q_A": 17.3, "lambda_d_Wb": 0.008, "lambda_q_Wb": 0.004, "torque_dq_Nm": 2.4,
                "apparent_L_d_H": 2e-4, "apparent_L_q_H": None, "lambda_pm_Wb": 0.01, "status": "experimental",
            },
        },
        "torque_waveform": {"electrical_angle_deg": [0.0, 7.5, 15.0], "torque_Nm": [2.4, 2.5, 2.6]},
        "back_emf_waveform": {
            "electrical_angle_deg": [0.0, 120.0, 240.0], "phase_a_V": [0.0, 6.5, -6.5],
            "phase_b_V": [-6.5, 0.0, 6.5], "phase_c_V": [6.5, -6.5, 0.0], "line_ab_V": None,
        },
        "cogging_torque_waveform": None,
        "solve_metadata": {"mesh_element_count": 1234},
    }


def test_result_accessors_return_numbers_and_arrays(tmp_path) -> None:
    result = coilem.Result(_result_data(), request={"topology": "SPM"})
    assert (result.average_torque_Nm, result.torque_ripple_pct, result.back_emf_fundamental_V) == (2.5, 12.0, 7.5)
    assert result.mesh_elements == 1234 and result.cogging is None and result.cogging_torque is None
    assert isinstance(result.torque.values, np.ndarray) and result.torque.mean == pytest.approx(2.5)
    assert result.torque.angle_deg.tolist() == [0.0, 7.5, 15.0] and result.torque.peak_to_peak == pytest.approx(0.2)
    assert result.back_emf.a.tolist() == [0.0, 6.5, -6.5] and result.back_emf.ab is None
    assert (result.dq.i_d_A, result.dq.L_d_H, result.dq.L_q_H) == (-10.0, 2e-4, None)
    assert tuple(result.metrics()) == coilem.Result.METRIC_NAMES
    assert repr(result) == "Result(torque 2.5 N·m, ripple 12 %, back-EMF 7.5 V)"
    loaded = coilem.Result.load(result.save(tmp_path / "result.json"))
    assert loaded.data == result.data and loaded.request == {"topology": "SPM"}
    pictured = coilem.Result({**_result_data(), "field_line_plot": {"lines": [[0.0, 1.0]] * 1000}})
    assert "field_line_plot" not in coilem.Result.load(pictured.save(tmp_path / "small.json")).data
    assert "field_line_plot" in coilem.Result.load(pictured.save(tmp_path / "full.json", fields=True)).data
    assert pictured.without_fields().metrics() == pictured.metrics()
    with pytest.raises(ValueError, match="no summary"):
        coilem.Result({})


# -- Sweeps (solver replaced) ---------------------------------------------------------


def test_sweep_tables_grid_and_best_point(monkeypatch, tmp_path) -> None:
    calls = []
    fields_requested = []

    def fake_solve(motor, point, **kwargs):
        calls.append(point)
        fields_requested.append(kwargs.get("fields"))
        if point.current_A == 20 and point.current_angle_deg == 60:
            raise coilem.SolveError("did not converge", error_code="NONLINEAR_CONVERGENCE_FAILED")
        data = {**_result_data(), "field_line_plot": {"lines": []}}
        data["summary"]["avg_torque_Nm"] = point.current_A * math.cos(math.radians(point.current_angle_deg - 20))
        return coilem.Result(data)

    monkeypatch.setattr(_solve, "solve", fake_solve)
    monkeypatch.setattr(_solve, "check_main_module", lambda: None)
    seen = []
    result = coilem.sweep(
        coilem.Motor.load(SPM_FIXTURE), current_A=[10, 20], current_angle_deg=[0, 30, 60],
        on_point=lambda index, total, point: seen.append((index, total, point.ok)),
    )
    assert [(p.current_A, p.current_angle_deg) for p in calls] == [(10, 0), (10, 30), (10, 60), (20, 0), (20, 30), (20, 60)]
    assert calls[0].speed_rpm == 3000  # the motor's saved operating point supplies the other fields
    assert seen[-1] == (5, 6, False) and len(result.failed) == 1
    assert set(fields_requested) == {False}  # field pictures are left out unless fields=True
    assert result.failed[0].error.error_code == "NONLINEAR_CONVERGENCE_FAILED"
    grid = result.grid("average_torque_Nm")
    assert grid.shape == (2, 3) and math.isnan(grid[1, 2]) and grid[1, 1] == pytest.approx(20 * math.cos(math.radians(10)))
    best = result.best()
    assert (best.operating_point.current_A, best.operating_point.current_angle_deg) == (20, 30)
    rows = list(csv.DictReader(result.to_csv(tmp_path / "sweep.csv").open(encoding="utf-8")))
    assert len(rows) == 6 and rows[5]["average_torque_Nm"] == "" and "did not converge" in rows[5]["error"]
    with pytest.raises(coilem.SolveError):
        coilem.sweep(coilem.Motor.load(SPM_FIXTURE), current_A=20, current_angle_deg=[60], stop_on_error=True)


def test_solves_leave_out_the_field_pictures_unless_asked(monkeypatch) -> None:
    seen = []

    def fake_in_process(body, on_progress, *, fields=False):
        seen.append(fields)
        return {**_result_data(), "field_line_plot": {"lines": []}, "field_line_frames": [{"angle_deg": 0.0}]}

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    motor = coilem.Motor.load(SPM_FIXTURE)
    lean = coilem.solve(motor)
    full = coilem.solve(motor, fields=True)
    assert seen == [False, True]
    assert not set(FIELD_KEYS) & set(lean.data)
    assert {"field_line_plot", "field_line_frames"} <= set(full.data)
    assert lean.metrics() == full.metrics()


@pytest.mark.parametrize("currents", [[10], [10, 20]])
def test_sweep_reuses_analysis_names_from_a_generator(monkeypatch, currents) -> None:
    calls = []

    def fake_in_process(body, on_progress, *, fields=False):
        calls.append(body["solve_options"])
        return _result_data()

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    monkeypatch.setattr(_solve, "check_main_module", lambda: None)
    result = coilem.sweep(
        coilem.Motor.load(SPM_FIXTURE), current_A=currents,
        analyses=(name for name in ["torque", "back_emf"]),
    )
    assert not result.failed and len(calls) == len(currents)
    assert all({key for key, on in options.items() if on} == {"torque_sweep", "back_emf"} for options in calls)


def test_default_analyses_keep_the_field_pass(monkeypatch) -> None:
    seen = []

    def fake_selected(solver, config, **kwargs):
        seen.append(solver._visual_outputs)
        return types.SimpleNamespace(model_dump=lambda **_: _result_data())

    monkeypatch.setattr(_solve, "check_main_module", lambda: None)
    monkeypatch.setattr("backend.selected_analyses.solve_selected_analyses", fake_selected)
    coilem.solve(coilem.Motor.load(SPM_FIXTURE).replace(solve_options=None))
    assert seen == [True]


@pytest.mark.parametrize(
    ("analyses", "fields", "lean"),
    [
        (["torque", "back_emf", "cogging", "thd"], False, True),
        (["torque", "losses"], False, False),  # iron loss is computed in the field-frame pass
        (["torque", "flux_density"], False, False),  # so are the steel flux-density statistics
        (["torque"], True, False),
    ],
)
def test_the_field_frame_pass_runs_only_when_something_needs_it(analyses, fields, lean) -> None:
    body = coilem.build_request(coilem.Motor.load(SPM_FIXTURE), analyses=analyses)
    assert _solve._lean(_solve.prepared_config(body), fields) is lean


# -- Worker processes and the main module ----------------------------------------------


def _main_module(monkeypatch, *, file=None, spec_name=None, start_method="spawn"):
    module = types.ModuleType("__main__")
    if file is not None:
        module.__file__ = str(file)
    module.__spec__ = types.SimpleNamespace(name=spec_name, origin=str(file) if file else None) if spec_name else None
    monkeypatch.setitem(sys.modules, "__main__", module)
    monkeypatch.setattr(_solve, "_start_method", lambda: start_method)


def test_an_unguarded_script_is_refused_before_any_worker_starts(monkeypatch, tmp_path) -> None:
    script = tmp_path / "run_motor.py"
    script.write_text("from backend import client\nclient.solve('motor.json')\n", encoding="utf-8")
    _main_module(monkeypatch, file=script)
    with pytest.raises(coilem.MainModuleError, match=r"run_motor\.py has no `if __name__ == \"__main__\":` block"):
        coilem.check_main_module()
    with pytest.raises(coilem.MainModuleError):
        coilem.solve(coilem.Motor.load(SPM_FIXTURE))


def test_a_script_read_from_stdin_is_refused(monkeypatch) -> None:
    _main_module(monkeypatch, file="<stdin>")
    with pytest.raises(coilem.MainModuleError, match="stdin"):
        coilem.check_main_module()


@pytest.mark.parametrize("case", ["guarded", "reversed-guard", "interactive", "package-main", "fork"])
def test_main_modules_that_workers_can_import_are_accepted(monkeypatch, tmp_path, case) -> None:
    script = tmp_path / "run_motor.py"
    guard = 'if "__main__" == __name__:' if case == "reversed-guard" else 'if __name__ == "__main__":'
    script.write_text(f"from backend import client\n\n{guard}\n    client.solve('motor.json')\n", encoding="utf-8")
    unguarded = tmp_path / "plain.py"
    unguarded.write_text("print('hello')\n", encoding="utf-8")
    if case in {"guarded", "reversed-guard"}:
        _main_module(monkeypatch, file=script)
    elif case == "interactive":
        _main_module(monkeypatch)
    elif case == "package-main":
        _main_module(monkeypatch, file=unguarded, spec_name="mypackage.__main__")
    else:
        _main_module(monkeypatch, file=unguarded, start_method="fork")
    coilem.check_main_module()


# -- Solving in a running app ------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def stub_app():
    """A stand-in for the app's /solve route that answers with canned replies."""

    replies: list[tuple[int, dict]] = []
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server's name
            requests.append({"path": self.path, "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            status, payload = replies.pop(0)
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", replies, requests
    finally:
        server.shutdown()
        server.server_close()


def test_a_solve_in_a_running_app_returns_its_result_and_maps_its_errors(stub_app) -> None:
    url, replies, requests = stub_app
    motor = coilem.Motor.load(SPM_FIXTURE)
    replies.append((200, _result_data()))
    result = coilem.solve(motor, coilem.OperatingPoint(current_A=12), quality="quick", server=url)
    assert result.average_torque_Nm == 2.5
    assert requests[0]["path"] == "/solve" and requests[0]["body"] == result.request
    assert requests[0]["body"]["solve_params"]["current_amplitude_A"] == 12

    replies.append((409, {"detail": {"error_code": "SOLVE_ALREADY_RUNNING", "message": "A local electromagnetic solve is already running."}}))
    with pytest.raises(coilem.SolveError) as busy:
        coilem.solve(motor, server=url)
    assert busy.value.error_code == "SOLVE_ALREADY_RUNNING"

    replies.append((400, {"detail": {"error_code": "UNSUPPORTED_LAUNCH_CONFIG", "message": "No.", "field": "rotor.pole_count"}}))
    with pytest.raises(coilem.InputError) as refused:
        coilem.solve(motor, server=url)
    assert refused.value.field == "rotor.pole_count" and str(refused.value) == "rotor.pole_count: No."

    with pytest.raises(coilem.InputError):
        coilem.solve(motor, server=url, on_progress=lambda *args: None)


def test_an_unreachable_app_is_a_clear_solve_error() -> None:
    with pytest.raises(coilem.SolveError) as caught:
        coilem.solve(coilem.Motor.load(SPM_FIXTURE), server=f"127.0.0.1:{_free_port()}", timeout_s=5)
    assert caught.value.error_code == "SERVER_UNREACHABLE" and "Could not reach coilEM" in str(caught.value)


def test_the_real_app_refuses_an_unsupported_design_with_the_field(tmp_path, monkeypatch) -> None:
    """The app's own /solve route, served on a loopback port; the request is refused before any solve."""

    import uvicorn

    from backend.public_main import create_app

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(bound_port=port), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with pytest.raises(coilem.InputError) as caught:
            coilem.solve(_spm_motor().replace(rotor={"pole_count": 7}), server=f"http://127.0.0.1:{port}")
        assert caught.value.field == "rotor.pole_count"
        assert "even rotor pole count" in str(caught.value)
    finally:
        server.should_exit = True
        thread.join(timeout=20)


# -- One real solve -----------------------------------------------------------------------


@pytest.mark.weekly
def test_default_analyses_preserve_losses_and_flux_statistics_without_pictures(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    motor = _spm_motor()
    options = {
        "quality": "custom", "mesh": "coarse",
        "solve_params": {"rotor_step_deg": 30, "rotor_sweep_range_deg": 360},
    }
    point = coilem.OperatingPoint(current_A=20, current_angle_deg=30)
    lean = coilem.solve(motor, point, **options)
    full = coilem.solve(motor, point, fields=True, **options)
    assert lean.summary["iron_loss"]["iron_loss_W"] > 0
    assert lean.summary["loss_breakdown"]["efficiency_pct"] > 0
    for name in ("iron_loss", "loss_breakdown", "rms_flux_density_teeth_T", "rms_flux_density_yoke_T"):
        assert lean.summary[name] == full.summary[name]
    assert not set(FIELD_KEYS) & set(lean.data)
    assert full.data["field_line_frames"]


@pytest.mark.weekly
def test_a_small_real_solve_reads_torque_back_emf_dq_and_cogging(tmp_path, monkeypatch) -> None:
    from backend.solver import clear_per_angle_gmsh_mesh_cache

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    clear_per_angle_gmsh_mesh_cache()
    progress = []
    result = coilem.solve(
        _spm_motor(),
        coilem.OperatingPoint(current_A=20, current_angle_deg=30),
        analyses=["torque", "back_emf", "cogging"],
        quality="quick",
        mesh="coarse",
        on_progress=lambda done, total, stage: progress.append((done, total, stage)),
    )
    assert progress and progress[-1][0] <= progress[-1][1]
    raw = result.data
    assert result.average_torque_Nm == raw["summary"]["avg_torque_Nm"] > 0
    assert result.torque.values.tolist() == raw["torque_waveform"]["torque_Nm"] and len(result.torque) >= 3
    assert result.back_emf_fundamental_V > 0 and result.back_emf.a.shape == result.back_emf.angle_deg.shape
    dq = result.dq
    assert (dq.i_d_A, dq.i_q_A) == (pytest.approx(-10, abs=0.01), pytest.approx(20 * math.cos(math.radians(30)), abs=0.01))
    assert dq.lambda_pm_Wb is not None and dq.L_d_H is not None and dq.L_q_H is not None
    assert dq.torque_dq_Nm == pytest.approx(result.average_torque_Nm, rel=0.05)
    cogging = result.cogging
    assert cogging is not None and cogging.peak_to_peak_Nm == pytest.approx(result.cogging_torque.peak_to_peak)
    assert result.request["solve_params"]["solve_quality"] == "quick"
    assert not result.data.get("field_line_frames")  # a lean solve: no field-frame pass

    # A second operating point re-uses this process's meshes and no-load solves,
    # and the no-load numbers are exactly the same.
    from backend import solver as solver_module

    lookups = []
    real_lookup = solver_module._noload_report_cache_get

    def spy(key):
        report = real_lookup(key)
        lookups.append(report is not None)
        return report

    monkeypatch.setattr(solver_module, "_noload_report_cache_get", spy)
    again = coilem.solve(
        _spm_motor(),
        coilem.OperatingPoint(current_A=30, current_angle_deg=45),
        analyses=["torque", "back_emf", "cogging"],
        quality="quick",
        mesh="coarse",
    )
    assert lookups and all(lookups)  # every no-load position came from the first solve
    assert again.back_emf.a.tolist() == result.back_emf.a.tolist()
    assert again.cogging_torque.values.tolist() == result.cogging_torque.values.tolist()
    assert again.dq.lambda_pm_Wb == result.dq.lambda_pm_Wb
    assert again.average_torque_Nm != result.average_torque_Nm
