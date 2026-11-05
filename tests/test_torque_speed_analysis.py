"""The selected map runs independently, persists and resumes on the solve lane."""

import asyncio
import io
import json
import os
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.field_artifacts import encode_solve_cache_artifact_id, protect_result_cache
from backend.flux_linkage_map import map_scope_key
from backend.models import SolveResult
from backend.models.config import TorqueSpeedAnalysisConfig
from backend.public_main import app
from backend.public_report import build_public_run_csv, build_public_run_pdf
from backend.public_routes import solve as solve_routes
from backend.selected_analyses import solve_selected_analyses
from backend.solver import _prune_solve_cache
from backend.solver_contract import SolveCancelledError
from tests.test_analysis_options import config, result_for
from tests.test_flux_linkage_map import FakeSolver


def map_config():
    cfg = config()
    cfg.solve_options.torque_speed_envelope = True
    cfg.torque_speed_analysis = TorqueSpeedAnalysisConfig.model_validate({
        "preset": "preview", "control": "mtpa",
        "limits": {"dc_bus_V": 48, "peak_current_A": 20, "continuous_current_A": 10, "max_speed_rpm": 7200},
    })
    return cfg


class SelectedSolver:
    def __init__(self, **kwargs):
        self.points = FakeSolver(**kwargs)
        self.base_configs = []

    def solve(self, cfg, **kwargs):
        assert not cfg.solve_options.torque_speed_envelope, "Map points must not recursively request a map"
        if not kwargs:
            assert cfg.solve_options.torque_sweep and cfg.solve_options.losses_efficiency
            return self.points(cfg)
        self.base_configs.append(cfg)
        if kwargs.get("on_progress"):
            kwargs["on_progress"](1, 1, None, "magneto2d_complete")
        return result_for(cfg)

    def cancel_active_solve(self):
        pass


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))


def test_map_only_runs_its_dependencies_and_serializes_without_operating_point_outputs():
    cfg, solver = map_config(), SelectedSolver()
    progress = []
    result = solve_selected_analyses(solver, cfg, on_progress=lambda *args, **kwargs: progress.append((args, kwargs)))
    assert len(solver.points.calls) == 29
    assert not solver.base_configs[0].solve_options.torque_sweep
    assert result.summary.avg_torque_Nm is None and result.summary.loss_breakdown is None
    assert result.torque_waveform.torque_Nm == [] and result.back_emf_waveform.phase_a_V == []
    saved = SolveResult.model_validate_json(result.model_dump_json()).torque_speed_analysis
    assert len(saved.map.points) == 35
    assert saved.winding_resistance.phase_resistance_ohm > 0
    assert saved.envelope.curves[0].torque_Nm[0] > 0
    assert saved.efficiency_map.control == "mtpa"
    map_progress = [args for args, _ in progress if len(args) > 3 and args[3] == "torque_speed_map"]
    assert map_progress[0][:2] == (0, 29) and map_progress[-1][:2] == (29, 29)
    assert map_progress[-1][-1]["analysis_fraction"] < 1
    arguments = dict(project=cfg.model_dump(mode="json"), request={"resolved_config": cfg.model_dump(mode="json")},
                     result=result.model_dump(mode="json"), material={}, manifest={})
    assert b"torque_speed_analysis,envelope.curves[0].torque_Nm[0]" in build_public_run_csv(**arguments)
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(build_public_run_pdf(**arguments))).pages)
    assert "Torque-speed map" in text and "Torque-speed envelope" in text


def test_unselected_map_never_starts_fields_and_completed_map_reuses_across_analysis_choices(monkeypatch):
    cfg, solver = map_config(), SelectedSolver()
    cfg.solve_options.torque_speed_envelope = False
    assert solve_selected_analyses(solver, cfg).torque_speed_analysis is None
    assert not solver.points.calls
    cfg.solve_options.torque_speed_envelope = True
    first = solve_selected_analyses(solver, cfg)
    original_scope = map_scope_key(cfg)
    cfg.solve_options.torque_speed_envelope = False
    cfg.solve_options.back_emf = True
    cfg.torque_speed_analysis.limits.dc_bus_V = 60
    assert map_scope_key(cfg) == original_scope
    second = solve_selected_analyses(solver, cfg)
    assert len(solver.points.calls) == 29
    assert second.torque_speed_analysis is None
    assert second.summary.back_emf_fundamental_V > 0
    args = dict(project=cfg.model_dump(mode="json"), request={"resolved_config": cfg.model_dump(mode="json")},
                result=second.model_dump(mode="json"), material={}, manifest={})
    assert b"torque_speed_analysis,map.points" not in build_public_run_csv(**args)
    cfg.solve_options.torque_speed_envelope = True
    reused = solve_selected_analyses(solver, cfg)
    assert len(solver.points.calls) == 29
    assert reused.torque_speed_analysis.map.scope_key == first.torque_speed_analysis.map.scope_key
    assert reused.torque_speed_analysis.envelope.limits.dc_bus_V == 60
    assert first.torque_speed_analysis.settings.limits.dc_bus_V == 48
    assert solve_selected_analyses(solver, cfg, map_supported=False).torque_speed_analysis is None
    from backend import selected_analyses

    def unusable(*args, **kwargs):
        raise ValueError("Historical map is incomplete")

    monkeypatch.setattr(selected_analyses, "torque_speed_envelope", unusable)
    cfg.solve_options.torque_speed_envelope = False
    assert solve_selected_analyses(solver, cfg).torque_speed_analysis is None


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("failed_at", [(10.0, 45.0), (0.0, 0.0)])
def test_failed_map_keeps_base_results_errors_and_successful_points_for_retry(combined, failed_at):
    cfg = map_config()
    cfg.solve_options.back_emf = combined
    cfg.solve_options.torque_sweep = combined
    cfg.solve_options.losses_efficiency = combined
    solver = SelectedSolver(fail_at=failed_at)
    result = solve_selected_analyses(solver, cfg)
    analysis = result.torque_speed_analysis
    assert analysis.status == "partial"
    assert analysis.envelope is None and analysis.efficiency_map is None
    failed = [point for point in analysis.map.points if point.status == "failed"]
    assert len(failed) == (7 if failed_at == (0, 0) else 1)
    assert all(point.error == "mesh failed" for point in failed)
    assert (result.summary.avg_torque_Nm is not None) == combined
    assert (result.summary.back_emf_fundamental_V is not None) == combined
    assert (result.summary.loss_breakdown is not None) == combined
    assert SolveResult.model_validate_json(result.model_dump_json()).torque_speed_analysis == analysis
    args = dict(project=cfg.model_dump(mode="json"), request={"resolved_config": cfg.model_dump(mode="json")},
                result=result.model_dump(mode="json"), material={}, manifest={})
    csv = build_public_run_csv(**args)
    assert b"mesh failed" in csv and b"torque_speed_analysis,status,,partial" in csv
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(build_public_run_pdf(**args))).pages)
    assert "Incomplete map" in text and "mesh failed" in text
    assert "Torque-speed envelope" not in text
    retry = SelectedSolver()
    complete = solve_selected_analyses(retry, cfg)
    assert retry.points.calls == [failed_at]
    assert complete.torque_speed_analysis.status == "complete"
    assert complete.torque_speed_analysis.envelope is not None
    # Retrying never rewrites the immutable earlier result.
    assert result.torque_speed_analysis.status == "partial"


@pytest.mark.parametrize("endpoint", ["/solve", "/solve/stream"])
@pytest.mark.parametrize("combined", [False, True])
def test_partial_map_is_saved_and_replayable_through_public_routes(monkeypatch, endpoint, combined):
    cfg = map_config()
    cfg.solve_options.back_emf = combined
    fake = SelectedSolver(fail_at=(10.0, 45.0))
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args, **kwargs: fake)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post(endpoint, json=cfg.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    if endpoint.endswith("stream"):
        event = next(event for event in response.text.split("\n\n") if event.startswith("event: complete"))
        payload = json.loads(event.split("\ndata: ")[1])
    else:
        payload = response.json()
    saved = payload["saved_run"]
    reopened = client.get(f"/runs/{saved['project_slug']}/{saved['run_id']}").json()
    assert reopened["integrity"]["valid"]
    assert reopened["result"]["torque_speed_analysis"] == payload["torque_speed_analysis"]
    assert payload["torque_speed_analysis"]["status"] == "partial"
    assert payload["torque_speed_analysis"]["envelope"] is None
    assert (payload["summary"]["back_emf_fundamental_V"] is not None) == combined


@pytest.mark.parametrize("map_selected", [False, True])
def test_sync_map_uses_batch_deadline_and_operating_point_keeps_its_deadline(monkeypatch, map_selected):
    cfg = map_config()
    cfg.solve_options.torque_speed_envelope = map_selected
    cfg.solve_options.back_emf = True
    fake = SelectedSolver()
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args, **kwargs: fake)
    wait = solve_routes._wait_for_worker
    deadlines = []

    async def record_deadline(future, *, timeout):
        deadlines.append(timeout)
        return await wait(future, timeout=timeout)

    monkeypatch.setattr(solve_routes, "_wait_for_worker", record_deadline)
    response = TestClient(app, base_url="http://127.0.0.1").post("/solve", json=cfg.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert deadlines[0] == (None if map_selected else 1200)
    assert response.json()["saved_run"]


def test_sync_map_can_be_cancelled_and_retried_without_losing_finished_points(monkeypatch, tmp_path):
    started, released = threading.Event(), threading.Event()

    class BlockingPointSolver(SelectedSolver):
        def solve(self, cfg, **kwargs):
            if not kwargs and len(self.points.calls) == 3:
                started.set()
                if not released.wait(5):
                    raise AssertionError("Test did not cancel the map worker")
                raise SolveCancelledError("Cancelled at a map point")
            return super().solve(cfg, **kwargs)

        def cancel_active_solve(self):
            released.set()

    first = BlockingPointSolver()
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args, **kwargs: first)
    cfg = map_config()

    async def scenario():
        pending = asyncio.create_task(solve_routes.solve(cfg.model_dump(mode="json")))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert await solve_routes.cancel_solve() == {"status": "cancelling"}
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(pending, 5)
            assert error.value.status_code == 409
        finally:
            released.set()
            if not pending.done():
                await asyncio.wait_for(pending, 5)

    asyncio.run(scenario())
    manifests = [json.loads(path.read_text()) for path in tmp_path.rglob("manifest.json")]
    assert len(manifests) == 1 and manifests[0]["status"] == "cancelled"
    retry = SelectedSolver()
    complete = solve_selected_analyses(retry, cfg)
    assert len(retry.points.calls) == 26
    assert complete.torque_speed_analysis.status == "complete"


def test_cancelled_map_keeps_finished_points_and_resumes():
    cfg = map_config()
    first = SelectedSolver(cancel_after=3)
    with pytest.raises(SolveCancelledError):
        solve_selected_analyses(first, cfg)
    resumed = SelectedSolver()
    assert solve_selected_analyses(resumed, cfg).torque_speed_analysis is not None
    assert len(first.points.calls) == 3 and len(resumed.points.calls) == 26


def test_map_validation_and_stream_save_replayable_results(monkeypatch):
    client = TestClient(app, base_url="http://127.0.0.1")
    raw = map_config().model_dump(mode="json")
    checked = client.post("/solve/validate", json=raw)
    assert checked.status_code == 200, checked.text
    assert checked.json()["torque_speed_map"] == {"solves": 29, "positions_per_point": 12}
    invalid = deepcopy(raw)
    invalid.pop("torque_speed_analysis")
    assert client.post("/solve/validate", json=invalid).status_code == 400
    fake = SelectedSolver()
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args, **kwargs: fake)
    response = client.post("/solve/stream", json=raw)
    events = response.text.split("\n\n")
    completed = next(event for event in events if event.startswith("event: complete"))
    payload = json.loads(completed.split("\ndata: ")[1])
    saved = payload["saved_run"]
    reopened = client.get(f"/runs/{saved['project_slug']}/{saved['run_id']}").json()
    assert reopened["integrity"]["valid"]
    assert reopened["request"]["resolved_config"]["solve_options"]["torque_speed_envelope"]
    assert reopened["result"]["torque_speed_analysis"] == payload["torque_speed_analysis"]


def test_map_points_cannot_evict_the_initial_preview_before_its_run_is_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_SOLVE_CACHE_MAX_BYTES", "1")
    root = tmp_path / "solve_cache"
    for index, name in enumerate(("magneto2d-preview", "magneto2d-point1", "magneto2d-point2")):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "field.json").write_text("preview")
        os.utime(folder, (index + 1, index + 1))
    preview = root / "magneto2d-preview"
    result = SimpleNamespace(model_dump=lambda **kwargs: {"field_frame_artifact": {
        "artifact_id": encode_solve_cache_artifact_id(preview / "field.json"),
    }})
    with protect_result_cache(result):
        _prune_solve_cache(root)
        assert preview.is_dir() and not (root / "magneto2d-point1").exists()
    _prune_solve_cache(root)
    assert not preview.exists()
