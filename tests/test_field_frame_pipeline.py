"""Frame jobs follow completed native angles without changing their ordering."""

from __future__ import annotations

import json
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.solver as solver
from backend.models import MotorConfig, SolveOptionsConfig

pytestmark = pytest.mark.pr
FIXTURE = Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json"


@pytest.fixture
def frame_pipeline(monkeypatch, tmp_path):
    config = MotorConfig.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    config.solve_options = config.solve_options or SolveOptionsConfig()
    assert config.solve_params is not None
    config.solve_options.back_emf = True
    config.solve_options.thd_analysis = False
    config.solve_options.cogging_torque = False
    config.solve_options.flux_density = False
    config.solve_options.losses_efficiency = False
    config.solve_options.torque_sweep = True
    config.solve_params.stream_noload_field_lines = True
    config.solve_params.current_amplitude_A = 10.0
    state = SimpleNamespace(
        config=config, persist=True, native_hook=None, frame_calls=[], aggregate=None,
        frame_started={index: threading.Event() for index in range(2)},
        native_returned=set(),
        accepted={(lane, angle): threading.Event() for lane in ("loaded", "noload") for angle in (0.0, 60.0)},
        lock=threading.Lock(),
    )
    for switch in (
        "COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
        "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL",
    ):
        monkeypatch.delenv(switch, raising=False)

    class Producer:
        source = "gmsh"
        display_name = "Gmsh"

        @staticmethod
        def build(config, angle):
            return {"angle": angle}, 0

    def native(config, **kwargs):
        lane = "noload" if config.solve_params.current_amplitude_A == 0 else "loaded"
        angle = float(kwargs["rotor_angle_deg"]) * (config.rotor.pole_count // 2)
        if state.native_hook is not None:
            state.native_hook(lane, angle)
        report = {"lane": lane, "angle": angle, "results": {"torque_nm": angle, "torque_weighted_stress_nm": angle}}
        directory = kwargs["persist_artifacts_dir"]
        if state.persist and directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{kwargs['artifact_prefix']}_report.json").write_text(json.dumps(report), encoding="utf-8")
        with state.lock:
            state.native_returned.add((lane, angle))
        return report

    def frame(index, loaded, angle, noload, cache, live, capture=False):
        loaded_report = solver._read_field_frame_report(loaded)
        assert loaded_report["lane"] == "loaded" and loaded_report["angle"] == angle
        if config.solve_params.stream_noload_field_lines and (
            config.solve_options.back_emf or config.solve_options.thd_analysis or config.solve_options.cogging_torque
        ):
            assert noload is not None, "PM frame dispatch must wait for its no-load partner"
            noload_report = solver._read_field_frame_report(noload)
            assert noload_report["lane"] == "noload" and noload_report["angle"] == angle
            assert ("noload", angle) in state.native_returned
        with state.lock:
            state.frame_calls.append((index, loaded, noload))
        state.frame_started[index].set()
        value = {"frame_index": index, "angle": angle}
        return index, value, value if live else None, None, None

    def aggregate(*args, **kwargs):
        state.aggregate = kwargs
        return {"sweep": {}, "field_line_frames": kwargs["precomputed_field_line_frames"]}

    def progress(*args):
        detail = args[9] if len(args) > 9 and isinstance(args[9], dict) else {}
        kind = detail.get("solve_kind")
        lane = "noload" if kind == "no_load" else kind
        key = (lane, float(args[4])) if kind in ("loaded", "no_load") else None
        if key in state.accepted:
            state.accepted[key].set()

    @contextmanager
    def frame_pool(workers, *, start_method=None):
        assert start_method == "spawn", "overlapped field jobs must not fork a multithreaded solver"
        with ThreadPoolExecutor(max_workers=workers) as pool:
            yield pool

    monkeypatch.setattr(solver, "estimate_magneto2d_sweep_angle_grid", lambda config: [0.0, 60.0])
    monkeypatch.setattr(solver, "_full_cycle_back_emf_angle_grid", lambda *args: [0.0, 60.0])
    monkeypatch.setattr(solver, "_gmsh_imported_mesh_pipeline_enabled", lambda *args: True)
    monkeypatch.setattr(solver, "_gmsh_pipeline_worker_count", lambda name, *args, **kwargs: 1 if kwargs.get("uses_process_pool") else 4)
    monkeypatch.setattr(solver, "_angle_mesh_cache_enabled", lambda: False)
    monkeypatch.setattr(solver, "gmsh_mesh_reuse_enabled", lambda: False)
    monkeypatch.setattr(solver, "gmsh_solve_reuse_enabled", lambda: False)
    monkeypatch.setattr(solver, "_zero_current_solve_mesh_artifact", lambda artifact: dict(artifact))
    monkeypatch.setattr(solver, "build_solve_mesh_evidence", lambda *args, **kwargs: {"geometry_sha256": "stand-in"})
    monkeypatch.setattr(solver, "_assert_imported_mesh_consumed_by_rust", lambda *args, **kwargs: None)
    monkeypatch.setattr(solver, "_magneto2d_summary_cache_dir", lambda *args: None)
    monkeypatch.setattr(solver, "_iron_loss_record", lambda *args: (None, None))
    monkeypatch.setattr(solver, "run_magneto2d_report", native)
    monkeypatch.setattr(solver, "_aggregate_per_angle_mesh_sweep", aggregate)
    monkeypatch.setattr(solver, "_build_field_line_frame_in_subprocess", frame)
    monkeypatch.setattr(solver, "_build_field_line_frame_from_sources_in_subprocess", frame)
    monkeypatch.setattr(solver, "cancellable_process_pool", frame_pool)
    state.run = lambda: solver._solve_with_per_angle_producer_meshes(
        config, Producer(), solve_cache_dir=tmp_path / "solve_cache" / "pipeline", on_progress=progress,
    )
    return state


@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
def test_pipeline_uses_file_sources_only_for_persisted_parallel_frame_jobs(frame_pipeline, monkeypatch, persist, parallel):
    state = frame_pipeline
    state.persist = persist
    if not parallel:
        monkeypatch.setenv("COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL", "0")

    report, _ = state.run()

    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1]
    assert Counter(index for index, _, _ in state.frame_calls) == {0: 1, 1: 1}
    for _, loaded, noload in state.frame_calls:
        for source in (loaded, noload):
            if persist and parallel:
                assert isinstance(source, solver._FieldFrameReportSource)
                assert Path(source.path).is_file()
            else:
                assert isinstance(source, dict)


def _start_pipeline(state):
    result = Future()

    def run():
        try:
            result.set_result(state.run())
        except BaseException as exc:
            result.set_exception(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def _wait_for(event, result, message):
    if not event.wait(3):
        if result.done():
            result.result()
        pytest.fail(message)


@pytest.mark.parametrize("first_lane", ["loaded", "noload"])
def test_pm_frame_starts_after_both_lanes_while_later_native_solves_are_blocked(frame_pipeline, first_lane):
    state = frame_pipeline
    release_partner, release_later = threading.Event(), threading.Event()
    partner_started, later_started = threading.Event(), threading.Event()
    partner = "noload" if first_lane == "loaded" else "loaded"

    def native_hook(lane, angle):
        if angle != 0.0:
            later_started.set()
            assert release_later.wait(10), "later native solve was never released"
        elif lane == partner:
            partner_started.set()
            assert release_partner.wait(10), "first frame's other solve was never released"

    state.native_hook = native_hook
    thread, result = _start_pipeline(state)
    try:
        _wait_for(state.accepted[first_lane, 0.0], result, "first native report was not handled")
        assert partner_started.wait(3) and later_started.wait(3)
        assert not state.frame_started[0].is_set(), "PM frame ran without its no-load/loaded pair"
        release_partner.set()
        _wait_for(state.frame_started[0], result, "eligible frame waited for unrelated later native solves")
        assert not release_later.is_set()
        assert ("loaded", 60.0) not in state.native_returned
    finally:
        release_partner.set()
        release_later.set()
        thread.join(timeout=15)

    assert not thread.is_alive(), "pipeline did not join after all native gates were released"
    report, _ = result.result(timeout=0)
    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1]
    assert Counter(index for index, _, _ in state.frame_calls) == {0: 1, 1: 1}


def test_out_of_order_ready_frames_are_dispatched_once_and_aggregated_in_angle_order(frame_pipeline):
    state = frame_pipeline
    state.config.solve_options.back_emf = False
    state.config.solve_params.stream_noload_field_lines = False
    release_first = threading.Event()

    def native_hook(lane, angle):
        if angle == 0.0:
            assert release_first.wait(10), "first native solve was never released"

    state.native_hook = native_hook
    thread, result = _start_pipeline(state)
    try:
        _wait_for(state.frame_started[1], result, "ready later angle waited for the earlier native solve")
        assert not state.frame_started[0].is_set()
    finally:
        release_first.set()
        thread.join(timeout=15)

    assert not thread.is_alive(), "pipeline did not join after its native gate was released"
    report, _ = result.result(timeout=0)
    assert [index for index, _, _ in state.frame_calls] == [1, 0]
    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1]


def test_completed_frame_failure_is_observed_while_an_unrelated_native_solve_is_blocked(frame_pipeline, monkeypatch):
    state = frame_pipeline
    release_later, later_started, error_observed = (threading.Event() for _ in range(3))

    def native_hook(lane, angle):
        if angle != 0.0:
            later_started.set()
            assert release_later.wait(10), "later native solve was never released"

    class ObservedFailure(Future):
        def result(self, *args, **kwargs):
            error_observed.set()
            return super().result(*args, **kwargs)

    class FailingFrames:
        @staticmethod
        def submit(function, *args, **kwargs):
            future = ObservedFailure()
            future.set_exception(RuntimeError("field frame failed"))
            return future

    @contextmanager
    def failing_frame_pool(workers, *, start_method=None):
        assert start_method == "spawn", "overlapped field jobs must not fork a multithreaded solver"
        yield FailingFrames()

    state.native_hook = native_hook
    monkeypatch.setattr(solver, "cancellable_process_pool", failing_frame_pool)
    thread, result = _start_pipeline(state)
    try:
        assert later_started.wait(3), "later native solve did not start"
        _wait_for(error_observed, result, "completed frame failure waited for unrelated native solves")
        assert not release_later.is_set()
        assert ("loaded", 60.0) not in state.native_returned
    finally:
        release_later.set()
        thread.join(timeout=15)

    assert not thread.is_alive(), "failed pipeline did not join after its native gate was released"
    with pytest.raises(RuntimeError, match="field frame failed"):
        result.result(timeout=0)


def test_pm_stream_flag_does_not_wait_for_a_no_load_solve_that_was_not_scheduled(frame_pipeline):
    state = frame_pipeline
    state.config.solve_options.back_emf = False
    assert state.config.solve_params.stream_noload_field_lines is True
    release_later = threading.Event()

    def native_hook(lane, angle):
        if angle != 0.0:
            assert release_later.wait(10), "later native solve was never released"

    state.native_hook = native_hook
    thread, result = _start_pipeline(state)
    try:
        _wait_for(state.frame_started[0], result, "frame waited for a no-load partner outside the solve plan")
        assert not release_later.is_set()
        assert ("loaded", 60.0) not in state.native_returned
    finally:
        release_later.set()
        thread.join(timeout=15)

    assert not thread.is_alive(), "pipeline did not join after its native gate was released"
    report, _ = result.result(timeout=0)
    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1]
    assert Counter(index for index, _, _ in state.frame_calls) == {0: 1, 1: 1}
    assert all(noload is None for _, _, noload in state.frame_calls)
    assert state.native_returned == {("loaded", 0.0), ("loaded", 60.0)}
