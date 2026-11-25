"""Thermal public boundary, immutable exports and solve-lane ownership."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.public_main import app
from backend.public_routes import solve as solve_routes
from backend.thermal_rating import ThermalRating, ThermalRatingPoint
from tests._private_evidence import requires_private_evidence
from tests.test_performance_routes import _events
from tests.test_public_cancellation import CLIENT_LEAVES, _serve_to_a_client_that_leaves
from tests.test_temperature_maps import TemperatureSolver
from tests.test_thermal_network import inputs, records


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def point_body():
    config, _, _, iron = records()
    return dict(request={"config": config.model_dump(mode="json")},
                source={"summary": {"avg_torque_Nm": 1, "iron_loss": iron.model_dump(mode="json")}},
                inputs=inputs(cooling="forced_air", housing_h_W_m2K=50).model_dump(mode="json"), design_name="Registered test")


def test_point_freezes_all_statuses_and_exports_same_numbers(client):
    response = client.post("/performance/thermal/point", json=point_body())
    assert response.status_code == 200, response.text
    analysis = response.json()
    restored = client.get(f"/performance/thermal/record/{analysis['id']}").json()
    assert restored == analysis
    scope = analysis["result"]["rotor_heating"]
    assert scope["basis"] == "heat_transfer_only"
    assert scope["internal_loss_status"] == "not_modelled"
    feedback = analysis["result"]["copper_feedback"]
    assert feedback["copper_loss_W"] > feedback["reference_copper_loss_W"]
    assert feedback["copper_active_loss_W"] == analysis["result"]["nodes"]["winding"]["heat_W"]
    assert feedback["copper_end_winding_loss_W"] == analysis["result"]["nodes"]["end_winding"]["heat_W"]
    assert feedback["temperature_residual_K"] < 1e-6
    assert analysis["computation_identity"]["thermal_point_processing"]["thermal_network.py"]
    assert any("supplied run summary" in note for note in analysis["result"]["notes"])
    text = client.get(f"/performance/thermal/report/{analysis['id']}/csv").text
    rows = list(csv.reader(io.StringIO(text)))
    assert any(row[0] == "thermal" and row[1] == "nodes.winding.temperature_C" for row in rows)
    assert any("Uncalibrated estimate" in str(row) for row in rows)
    multiplier = next(row for row in rows if row[0] == "thermal" and row[1] == "inputs.calibration_multiplier")
    assert "cannot identify several uncertain heat paths" in multiplier[4]
    pdf = client.get(f"/performance/thermal/report/{analysis['id']}/pdf").content
    extracted = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Steady-state thermal estimate" in extracted
    assert "Copper-temperature feedback" in extracted
    assert "Rotor and magnet heating scope" in extracted
    assert "Heat transfer only at rotor/magnets" in extracted
    assert "internal losses are omitted, not known to be zero" in " ".join(extracted.split())
    assert next(row[3] for row in rows if row[:2] == ["thermal", "rotor_heating.internal_loss_status"]) == "not_modelled"
    for name in ("rotor", "magnets", "airgap", "bearings", "end_air"):
        node = analysis["result"]["nodes"][name]
        assert node["status"] == "experimental"
        exported = next(row[3] for row in rows if row[:2] == ["thermal", f"nodes.{name}.temperature_C"])
        assert float(exported) == node["temperature_C"]
    assert "current, iron loss and thermal paths held fixed" in extracted
    hot_loss_row = next(row for row in rows if row[:2] == ["thermal", "copper_feedback.copper_loss_W"])
    assert float(hot_loss_row[3]) == feedback["copper_loss_W"]
    current_row = next(row for row in rows if row[:2] == ["thermal", "copper_feedback.phase_current_rms_A"])
    assert current_row[2] == "A rms"
    alpha_row = next(row for row in rows if row[:2] == ["thermal", "copper_feedback.temperature_coefficient_per_K"])
    assert alpha_row[2] == "1/K"
    assert f"{feedback['copper_loss_W']:.4g}" in extracted
    assert "cannot identify several uncertain heat paths" in extracted
    assert "supplied run summary" in extracted
    assert "missing rotor heat" in extracted.lower() or "eddy-current" in extracted
    assert "temperature prediction is not included" not in extracted
    assert client.get("/performance/thermal/record/not-an-analysis").status_code == 404


def test_saved_run_restores_thermal_and_exports_original_report_rows(client):
    from backend.solve_workspace import SolveWorkspace
    from tests.test_solve_workspace import _result

    body = point_body()
    config = body["request"]["config"]
    result = _result()
    result["solve_metadata"]["timestamp"] = "2026-11-24T17:30:00.123456Z"
    result["summary"].update(body["source"]["summary"])
    writer = SolveWorkspace().begin_run(project_name="Saved motor", config=config, submitted_request=body["request"])
    run = writer.complete(result)
    body["saved_run"] = {"project_slug": run.project_slug, "run_id": run.run_id}
    body["source"] = {}  # The saved result is authoritative.
    response = client.post("/performance/thermal/point", json=body)
    assert response.status_code == 200, response.text
    record = response.json()
    latest = f"/performance/thermal/latest/{run.project_slug}/{run.run_id}"
    assert client.get(latest + "/point").json()["id"] == record["id"]
    assert client.get(latest + "/rating").json() is None
    csv_url = f"/performance/thermal/report/{record['id']}/csv"
    rows = list(csv.reader(io.StringIO(client.get(csv_url).text)))
    assert any(row[:2] == ["identity", "run_id"] and row[3] == run.run_id for row in rows)
    assert any(row[:2] == ["identity", "completed_at"] and row[3] == run.completed_at for row in rows)
    assert sum(row[:2] == ["torque_waveform", "torque_Nm"] for row in rows) == 2
    assert any(row[:2] == ["thermal", "nodes.winding.temperature_C"] for row in rows)

    # A historical point has the exact original summary and timestamp, but no saved_run link.
    ref = body.pop("saved_run")
    body["source"] = {"summary": result["summary"], "solve_metadata": result["solve_metadata"]}
    old = client.post("/performance/thermal/point", json=body).json()
    export = client.get(f"/performance/thermal/report/{old['id']}/csv", params=ref)
    assert export.status_code == 200 and run.run_id in export.text
    body["source"]["solve_metadata"]["timestamp"] = "another solve"
    other = client.post("/performance/thermal/point", json=body).json()
    assert client.get(f"/performance/thermal/report/{other['id']}/csv", params=ref).status_code == 409


def test_a_refused_input_is_named_in_the_response_and_the_server_log(client, caplog):
    body = point_body()
    body["inputs"]["extra_rotor_heat_to_magnets_fraction"] = 31337
    with caplog.at_level("WARNING", logger="coilem.api"):
        response = client.post("/performance/thermal/point", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "inputs", "extra_rotor_heat_to_magnets_fraction"]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Rejected POST /performance/thermal/point" in logged
    assert "body.inputs.extra_rotor_heat_to_magnets_fraction" in logged
    assert "31337" not in logged, "The log names the field, not the value"


def test_missing_fields_and_invalid_identity_do_not_claim_solver(client, monkeypatch):
    from backend.public_routes import performance

    body = point_body()
    body["inputs"]["housing_h_W_m2K"] = 0
    assert client.post("/performance/thermal/point", json=body).status_code == 422

    def broken(*args):
        raise ValueError("Cannot identify map physics: missing source")

    monkeypatch.setattr(performance, "map_scope_key", broken)
    assert client.post("/performance/thermal/point", json=point_body()).status_code == 409
    assert not solve_routes._ACTIVE_SOLVE["running"]


def test_thermal_stream_owns_and_releases_lane_and_records_result(client, monkeypatch):
    from backend.public_routes import thermal

    class FakeSolver:
        solve = TemperatureSolver()
        def cancel_active_solve(self):
            pass

    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args: FakeSolver())

    def fake_rating(bracket, settings, limits, **kwargs):
        return ThermalRating(inputs=settings, limits=limits, coupling=kwargs["coupling"], control="mtpa",
            source_scope_keys=(bracket.low.scope_key, bracket.high.scope_key), status_reason="Experimental test record",
            points=[ThermalRatingPoint(speed_rpm=rpm, status="unavailable", status_reason="No measured evidence", limiting_constraint="test")
                    for rpm in (0, 1000)])

    monkeypatch.setattr(thermal, "thermal_rating", fake_rating)
    body = point_body()
    body.pop("source")
    body["limits"] = dict(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000)
    body["speed_samples"] = 2
    events = _events(client.post("/performance/thermal/stream", json=body).text)
    assert events[-1][0] == "complete", events[-1]
    analysis = events[-1][1]
    assert analysis["kind"] == "rating"
    thermal_sources = analysis["computation_identity"]["thermal_rating_processing"]
    assert thermal_sources["thermal_network.py"] and thermal_sources["thermal_rating.py"]
    assert not solve_routes._ACTIVE_SOLVE["running"]
    assert client.get(f"/performance/thermal/report/{analysis['id']}/pdf").status_code == 200


# Ceiling for the stream tests' waits. Each wait ends on an event or a
# condition; the ceiling only bounds a hang, so a slow runner never reaches it.
_WAIT_S = 60.0


async def _until(predicate) -> None:
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=_WAIT_S)


def _rating_body():
    body = point_body()
    body.pop("source")
    body.update(limits=dict(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000), speed_samples=2)
    return body


@pytest.mark.parametrize("disconnect", ["close", "cancel"])
def test_disconnect_during_rating_search_stops_worker_and_frees_lane_after_it_returns(monkeypatch, tmp_path, disconnect):
    """A client leaving between native solves stops the search and its solver; the lane waits for the worker.

    ``close`` closes the response iterator at a yield (GeneratorExit), as when
    the server's send fails; ``cancel`` cancels the task awaiting the next event.
    Every wait ends on an event or condition, never a short fixed timeout.
    """
    import threading

    from fastapi import HTTPException

    from backend import thermal_rating as rating_module
    from backend.public_routes import thermal

    in_search, resume_search, native_cancelled = threading.Event(), threading.Event(), threading.Event()
    on_pause = []  # Called on the worker thread once the search holds.

    class SearchSolver:
        def __init__(self):
            self.solve = TemperatureSolver()

        def cancel_active_solve(self):
            native_cancelled.set()

    queues = []

    class ProgressQueue(asyncio.Queue):
        """The stream's progress queue, noting when the stream waits on it empty."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.waited_empty = asyncio.Event()
            queues.append(self)

        async def get(self):
            if self.empty():
                self.waited_empty.set()
            return await super().get()

    solver = SearchSolver()
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(solve_routes, "_ACTIVE_SOLVE", {"running": False, "cancelled": False, "solver": None, "run_writer": None})
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args: solver)
    monkeypatch.setattr(thermal.asyncio, "Queue", ProgressQueue)
    native_at_pause = []
    real_coupled_point = rating_module.coupled_point

    def pausing_coupled_point(*args, speed_rpm, **kwargs):
        if speed_rpm > 0 and not in_search.is_set():
            # Speed 0 is searched and verified; hold before the next speed's search.
            native_at_pause.append(len(solver.solve.calls))
            in_search.set()
            for notify in on_pause:
                notify()
            if not resume_search.wait(timeout=_WAIT_S):
                raise RuntimeError("Test did not resume the search")
        return real_coupled_point(*args, speed_rpm=speed_rpm, **kwargs)

    monkeypatch.setattr(rating_module, "coupled_point", pausing_coupled_point)
    body = _rating_body()
    body["speed_samples"] = 3
    request = thermal.ThermalRatingRequest.model_validate(body)

    async def scenario():
        loop = asyncio.get_running_loop()
        search_paused = asyncio.Event()
        # Scheduled after the progress the worker sent before it paused, so
        # all of that progress is on the stream's queue once this is set.
        on_pause.append(lambda: loop.call_soon_threadsafe(search_paused.set))
        response = await thermal.thermal_stream(request)
        events = response.body_iterator
        pending = None
        try:
            assert '"stage":"Starting"' in await anext(events)
            # The next event starts the worker; the stream then sits at a yield.
            assert "cold and hot" in await asyncio.wait_for(anext(events), timeout=_WAIT_S)
            await asyncio.wait_for(search_paused.wait(), timeout=_WAIT_S)
            assert native_at_pause[0] >= 58, "Both bracket maps are solved before the search"
            assert solve_routes._ACTIVE_SOLVE["running"] and not solve_routes._ACTIVE_SOLVE["cancelled"]
            if disconnect == "close":
                await events.aclose()
            else:
                # Take the progress the paused worker queued, then cancel
                # while the stream waits for more.
                (queue,) = queues
                while not queue.empty():
                    await asyncio.wait_for(anext(events), timeout=_WAIT_S)
                queue.waited_empty.clear()
                pending = asyncio.create_task(anext(events))
                await asyncio.wait_for(queue.waited_empty.wait(), timeout=_WAIT_S)
                assert not pending.done()
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert native_cancelled.is_set()
            assert solve_routes._ACTIVE_SOLVE["cancelled"], "The search's stop predicate is set"
            assert solve_routes._ACTIVE_SOLVE["running"] and solve_routes._ACTIVE_SOLVE["solver"] is solver
            with pytest.raises(HTTPException) as conflict:
                solve_routes._claim_solve(SearchSolver())
            assert conflict.value.status_code == 409

            resume_search.set()
            await _until(lambda: not solve_routes._ACTIVE_SOLVE["running"])
            assert len(solver.solve.calls) == native_at_pause[0], "No native solve after the disconnect"
            assert not list((tmp_path / "thermal_analyses").glob("*.json")), "No record for an abandoned job"
            replacement = SearchSolver()
            solve_routes._claim_solve(replacement)
            assert solve_routes._ACTIVE_SOLVE["solver"] is replacement and not solve_routes._ACTIVE_SOLVE["cancelled"]
            solve_routes._release_solve(replacement)
        finally:
            resume_search.set()
            if pending is not None and not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
            await events.aclose()
            await _until(lambda: not solve_routes._ACTIVE_SOLVE["running"])

    asyncio.run(scenario())


def test_a_busy_lane_refuses_the_thermal_stream_with_409_before_any_event(client, monkeypatch):
    class Idle:
        def cancel_active_solve(self):
            pass

    monkeypatch.setattr(solve_routes, "_ACTIVE_SOLVE", {"running": False, "cancelled": False, "solver": None, "run_writer": None})
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args: Idle())
    holder = Idle()
    solve_routes._claim_solve(holder)
    response = client.post("/performance/thermal/stream", json=_rating_body())
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "SOLVE_ALREADY_RUNNING"
    assert solve_routes._ACTIVE_SOLVE["solver"] is holder


@pytest.mark.parametrize("leave", CLIENT_LEAVES)
def test_a_client_leaving_as_the_thermal_stream_starts_frees_the_lane(monkeypatch, tmp_path, leave):
    """The lane is claimed before the stream; a client leaving as the response
    starts (the body never runs, or is held at its first event) must not leave
    it claimed, and no worker may start (review of #51)."""
    from fastapi import HTTPException

    from backend.public_routes import thermal

    class Solver:
        def __init__(self):
            self.solve = TemperatureSolver()

        def cancel_active_solve(self):
            pass

    solver = Solver()
    workers_started = []
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(solve_routes, "_ACTIVE_SOLVE", {"running": False, "cancelled": False, "solver": None, "run_writer": None})
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args: solver)

    def no_worker(function, *args, **kwargs):
        workers_started.append(function)
        raise AssertionError("No worker may start for a client that left")

    monkeypatch.setattr(solve_routes, "_run_solver_thread", no_worker)
    body = _rating_body()

    async def scenario():
        if leave == "app-headers":
            await _serve_to_a_client_that_leaves(app, leave, path="/performance/thermal/stream", body=json.dumps(body).encode())
            return
        response = await thermal.thermal_stream(thermal.ThermalRatingRequest.model_validate(body))
        assert solve_routes._ACTIVE_SOLVE["solver"] is solver
        with pytest.raises(HTTPException) as conflict:
            solve_routes._claim_solve(Solver())
        assert conflict.value.status_code == 409
        await _serve_to_a_client_that_leaves(response, leave)

    asyncio.run(scenario())
    assert workers_started == [] and solver.solve.calls == []
    assert not solve_routes._ACTIVE_SOLVE["running"] and solve_routes._ACTIVE_SOLVE["solver"] is None
    replacement = Solver()
    solve_routes._claim_solve(replacement)
    assert solve_routes._ACTIVE_SOLVE["solver"] is replacement
    solve_routes._release_solve(replacement)


def test_a_speed_whose_direct_solve_fails_is_unavailable_in_the_record_and_both_exports(client, monkeypatch):
    from backend.public_routes import thermal

    class FakeSolver:
        solve = TemperatureSolver()
        def cancel_active_solve(self):
            pass

    real_rating = thermal.thermal_rating

    def broken(_config):
        raise RuntimeError("Magneto2D stopped: forced test failure")

    def failing_direct_solve(bracket, settings, limits, **kwargs):
        # The maps solve; every direct check of a limiting point raises. A small grid keeps it quick.
        return real_rating(bracket, settings, limits, **(kwargs | dict(direct_solve=broken, current_samples=2, angle_samples=2)))

    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args: FakeSolver())
    monkeypatch.setattr(thermal, "thermal_rating", failing_direct_solve)
    body = point_body()
    body.pop("source")
    body["inputs"] = inputs(housing_h_W_m2K=1000, end_space_h_W_m2K=1000, airgap_h_W_m2K=500).model_dump(mode="json")
    body["limits"] = dict(dc_bus_V=24, peak_current_A=20, continuous_current_A=1, max_speed_rpm=1000)
    body["speed_samples"] = 2
    events = _events(client.post("/performance/thermal/stream", json=body).text)
    assert events[-1][0] == "complete", events[-1]
    record = events[-1][1]
    checked = [row for row in record["result"]["points"] if row["point"]]
    assert checked, "The search must find a limiting point for the direct solve to check"
    for row in checked:
        assert row["status"] == "unavailable" and row["point"]["status"] == "unavailable"
        assert "Magneto2D stopped: forced test failure" in row["status_reason"]
        assert row["point"]["verification_status"] == "FAIL"

    rows = list(csv.reader(io.StringIO(client.get(f"/performance/thermal/report/{record['id']}/csv").text)))
    pdf = client.get(f"/performance/thermal/report/{record['id']}/pdf").content
    # Paragraphs wrap, so compare with single spaces.
    extracted = " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages).split())
    assert "Magneto2D stopped: forced test failure" in extracted
    for index, row in enumerate(record["result"]["points"]):
        if not row["point"]:
            continue
        torque = next(line for line in rows if line[1] == f"result.points[{index}].point.torque_Nm")
        assert torque[3] == "" and torque[4].startswith("Not reported")
        assert f"{row['point']['torque_Nm']:.4g}" not in extracted


def test_exports_leave_out_the_torque_of_every_speed_without_a_result():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    from backend.thermal_reporting import thermal_csv_rows, thermal_story

    def point(torque, winding, magnets, status="experimental", verification="PASS"):
        return dict(status=status, status_reason="Coupled estimate.", torque_Nm=torque, current_peak_A=1.0,
                    winding_temperature_C=winding, magnet_temperature_C=magnets, iterations=4,
                    temperature_residual_K=0.01, verification_status=verification, verification_reason="Direct check.")

    rejected = "A direct solve at this point needs more voltage than the drive limit allows, so the value read from the maps is not reported."
    failed = "A direct solve at this point could not run (forced test failure), so the value read from the maps is not reported."
    rating = dict(kind="thermally_limited_rating", status="experimental", status_reason="Experimental.", inputs={}, limits={},
                  control="mtpa", coupling={}, notes=[], points=[
        dict(speed_rpm=0, status="experimental", status_reason="Coupled estimate.", limiting_constraint="voltage",
             point=point(5.25, 61.5, 44.25), user_magnet_case=None),
        # Rejected by a voltage or temperature violation in its direct solve.
        dict(speed_rpm=500, status="unavailable", status_reason=rejected, limiting_constraint="voltage",
             point=point(7.777, 63.33, 45.55, "unavailable", "FAIL"), user_magnet_case=None),
        # Its direct solve could not run.
        dict(speed_rpm=1000, status="unavailable", status_reason=failed, limiting_constraint="voltage",
             point=point(6.543, 64.44, 46.66, "unavailable", "FAIL"), user_magnet_case=None),
        dict(speed_rpm=1500, status="unavailable", status_reason="voltage", limiting_constraint="voltage",
             point=None, user_magnet_case=None),
    ])
    output = io.BytesIO()
    SimpleDocTemplate(output, pagesize=A4).build(thermal_story(rating, rating=True))
    extracted = " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(output.getvalue())).pages).split())
    assert "5.25" in extracted and "61.5" in extracted
    for value in ("7.777", "63.33", "45.55", "6.543", "64.44", "46.66"):
        assert value not in extracted, value
    assert rejected in extracted and "forced test failure" in extracted
    # The performance report flattens the rating itself; the frozen record nests it under "result".
    for record, root in ((rating, "points"), ({"result": rating}, "result.points")):
        cells = {row[1]: row for row in thermal_csv_rows(record)}
        assert cells[f"{root}[0].point.torque_Nm"][3] == 5.25
        for index in (1, 2):
            for name in ("torque_Nm", "winding_temperature_C", "magnet_temperature_C"):
                assert cells[f"{root}[{index}].point.{name}"][3] == "", name
                assert cells[f"{root}[{index}].point.{name}"][4].startswith("Not reported")
            assert cells[f"{root}[{index}].point.current_peak_A"][3] == 1.0
            assert cells[f"{root}[{index}].status"][3] == "unavailable"


def test_invalid_bracket_is_rejected_before_claim(client):
    body = point_body()
    body.pop("source")
    body.update(low_C=100, high_C=20, limits=dict(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000))
    assert client.post("/performance/thermal/stream", json=body).status_code == 422
    assert not solve_routes._ACTIVE_SOLVE["running"]


def test_unstable_feedback_is_saved_and_exported_without_temperatures(client):
    body = point_body()
    body["inputs"]["housing_h_W_m2K"] = .0001
    response = client.post("/performance/thermal/point", json=body)
    assert response.status_code == 200
    record = response.json()
    assert record["result"]["status"] == "unavailable"
    assert "No stable thermal equilibrium" in record["result"]["status_reason"]
    assert not record["result"]["nodes"]
    assert record["result"]["copper_feedback"] is None
    csv_text = client.get(f"/performance/thermal/report/{record['id']}/csv").text
    assert "No stable thermal equilibrium" in csv_text
    assert "nodes.winding.temperature_C" not in csv_text
    pdf = client.get(f"/performance/thermal/report/{record['id']}/pdf").content
    assert "No stable thermal equilibrium" in "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_legacy_point_records_keep_their_values_and_explain_fixed_losses(client):
    import json

    from backend.solve_workspace import user_data_root

    record = client.post("/performance/thermal/point", json=point_body()).json()
    # Emulate an older saved schema without feedback metadata, without recomputing it.
    record["result"].pop("copper_feedback")
    record["result"].pop("rotor_heating")
    for name in ("rotor", "magnets", "airgap", "bearings", "end_air"):
        record["result"]["nodes"][name].update(temperature_C=None, margin_K=None, status="unavailable",
                                               status_reason="Historical declared frequency range missing.")
    path = user_data_root() / "thermal_analyses" / f"{record['id']}.json"
    path.write_text(json.dumps(record))
    assert client.get(f"/performance/thermal/record/{record['id']}").json() == record
    pdf = client.get(f"/performance/thermal/report/{record['id']}/pdf").content
    extracted = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Saved estimate uses fixed copper losses" in extracted
    assert "Historical declared frequency range missing" in extracted
    assert "Heat transfer only at rotor/magnets" not in extracted
    assert json.loads(path.read_text()) == record


@requires_private_evidence("benchmarks/thermal-v0.6/spm_8p12s_concentrated-native.json",
                           "benchmarks/thermal-v0.6/rotor-heat-recomputed.json")
@pytest.mark.xfail(strict=True, reason=(
    "The private native brackets were solved in October 2026, before the 0.5.9 solver. Their map "
    "identity no longer matches this build, so they are refused, as intended. Recollect the "
    "thermal-v0.6 native evidence on the current solver, then remove this mark."))
def test_native_acceptance_requires_current_thermal_processing(monkeypatch):
    import json

    from backend.public_routes import thermal
    from backend.resources import data_file
    from backend.temperature_maps import TemperatureMapBracket

    saved = json.loads(data_file('benchmarks/thermal-v0.6/spm_8p12s_concentrated-native.json').read_text())
    bracket = TemperatureMapBracket.model_validate(saved['bracket'])
    assert thermal._acceptance(bracket).status == 'PASS'
    identity = thermal.thermal_processing_identity()
    monkeypatch.setattr(thermal, 'thermal_processing_identity', lambda: {**identity, 'thermal_network.py':'changed'})
    assert thermal._acceptance(bracket) is None


def test_the_app_fills_in_the_same_input_defaults_as_the_api():
    """The Solve panel compares its setup with a saved result's recorded inputs, defaults included."""
    import re
    from pathlib import Path

    from backend.models.thermal import ThermalInputs

    source = (Path(__file__).resolve().parents[1] / "frontend/src/public/thermal.ts").read_text(encoding="utf-8")
    block = re.search(r"export const THERMAL_REQUEST_DEFAULTS[^=]*=\s*\{(.*?)\n\};", source, re.S).group(1)
    in_app = {name: None if text == "null" else text.strip("'") if text.startswith("'") else float(text)
              for name, text in re.findall(r"(\w+):\s*(null|'[^']*'|-?[0-9.]+)", block)}
    api = {name: field.default for name, field in ThermalInputs.model_fields.items() if not field.is_required()}
    assert in_app == api


@pytest.mark.parametrize("summary", [{"avg_torque_Nm": None}, {}, {"avg_torque_Nm": "high"}])
def test_a_run_without_torque_is_refused_in_words(client, summary):
    body = point_body()
    body["source"]["summary"] = {"iron_loss": body["source"]["summary"]["iron_loss"], **summary}
    response = client.post("/performance/thermal/point", json=body)
    assert response.status_code == 422 and "this run's torque" in response.json()["detail"]
    body["source"]["summary"] = ["not", "a", "summary"]
    assert client.post("/performance/thermal/point", json=body).status_code == 422


def test_the_torque_curve_report_writes_high_speeds_in_full():
    from backend.thermal_reporting import thermal_story

    story = thermal_story(dict(status="experimental", status_reason="Experimental.", inputs={}, notes=[], points=[
        dict(speed_rpm=12000.0, status="experimental", status_reason="Held.", limiting_constraint="voltage",
             point=dict(status="experimental", torque_Nm=1.25, winding_temperature_C=80.0, magnet_temperature_C=60.0))]), rating=True)
    cells = [cell.getPlainText() for cell in story[3]._cellvalues[1]]
    assert cells[:2] == ["12000", "1.25"]  # not 1.2e+04
