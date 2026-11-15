"""Failed congruence synthesis uses, drains and cancels the native solve pool."""

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
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr
FIXTURE = Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json"


@pytest.fixture
def fallback_pipeline(monkeypatch, tmp_path):
    config = MotorConfig.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    config.solve_options = SolveOptionsConfig(
        torque_sweep=True, back_emf=False, cogging_torque=False, flux_density=False,
        thd_analysis=False, losses_efficiency=False,
    )
    assert config.solve_params is not None
    config.solve_params.current_amplitude_A = 10.0
    config.solve_params.stream_noload_field_lines = False
    state = SimpleNamespace(
        config=config, angles=[0.0, 60.0, 120.0], compact=False,
        native_hook=None, cancelled=threading.Event(), lock=threading.Lock(),
        native_started=[], native_returned=set(), native_futures=[],
        active=0, max_active=0, frame_calls=[], frame_pool_entries=0,
        native_events={}, frame_events={}, error_key=None, error_observed=threading.Event(),
        submitted=threading.Event(), queue_cancelled=threading.Event(), aggregate=None,
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

    class NativePool(ThreadPoolExecutor):
        def submit(self, function, *args, **kwargs):
            lane, job = args[:2]
            key = (lane, float(job["angle_elec_deg"]))
            future = super().submit(function, *args, **kwargs)
            original_result = future.result

            def observed_result(*result_args, **result_kwargs):
                if key == state.error_key:
                    state.error_observed.set()
                return original_result(*result_args, **result_kwargs)

            future.result = observed_result
            future.add_done_callback(lambda done: state.queue_cancelled.set() if done.cancelled() else None)
            state.native_futures.append((key, future))
            lanes = 2 if config.solve_options.back_emf else 1
            if len(state.native_futures) == len(state.angles) * lanes:
                state.submitted.set()
            return future

    def native(config, **kwargs):
        lane = "noload" if config.solve_params.current_amplitude_A == 0 else "loaded"
        angle = float(kwargs["rotor_angle_deg"]) * (config.rotor.pole_count // 2)
        key = (lane, angle)
        with state.lock:
            state.native_started.append(key)
            state.active += 1
            state.max_active = max(state.max_active, state.active)
        try:
            if state.native_hook is not None:
                state.native_hook(lane, angle)
            report = {"lane": lane, "angle": angle, "results": {"torque_nm": angle, "torque_weighted_stress_nm": angle}}
            directory = kwargs["persist_artifacts_dir"]
            if directory is not None:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f"{kwargs['artifact_prefix']}_report.json").write_text(json.dumps(report), encoding="utf-8")
            with state.lock:
                state.native_returned.add(key)
            state.native_events.setdefault(key, threading.Event()).set()
            return report
        finally:
            with state.lock:
                state.active -= 1

    def fail_reuse(*args, **kwargs):
        raise ValueError("stand-in report has no reusable per-slot contributions")

    def frame(index, loaded, angle, noload, cache, live, capture=False):
        loaded_report = solver._read_field_frame_report(loaded)
        assert loaded_report["lane"] == "loaded" and loaded_report["angle"] == angle
        if config.solve_params.stream_noload_field_lines:
            assert noload is not None, "fallback frame ran before its no-load partner"
            noload_report = solver._read_field_frame_report(noload)
            assert noload_report["lane"] == "noload" and noload_report["angle"] == angle
            assert ("noload", angle) in state.native_returned
        with state.lock:
            state.frame_calls.append(index)
        state.frame_events.setdefault(index, threading.Event()).set()
        value = {"frame_index": index, "angle": angle}
        return index, value, value if live else None, None, None

    @contextmanager
    def frame_pool(workers, *, start_method=None):
        assert start_method == "spawn"
        state.frame_pool_entries += 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            yield pool

    def aggregate(config, loaded, noload, *args, **kwargs):
        state.aggregate = (loaded, noload, kwargs)
        return {"sweep": {}, "field_line_frames": kwargs["precomputed_field_line_frames"]}

    def check_cancelled():
        if state.cancelled.is_set():
            raise SolveCancelledError("cancel fallback work")

    monkeypatch.setattr(solver, "ThreadPoolExecutor", NativePool)
    monkeypatch.setattr(solver, "estimate_magneto2d_sweep_angle_grid", lambda config: list(state.angles))
    monkeypatch.setattr(solver, "_full_cycle_back_emf_angle_grid", lambda *args: list(state.angles))
    monkeypatch.setattr(solver, "_gmsh_imported_mesh_pipeline_enabled", lambda *args: True)
    monkeypatch.setattr(solver, "_gmsh_pipeline_worker_count", lambda name, *args, **kwargs: 1 if kwargs.get("uses_process_pool") else 2)
    monkeypatch.setattr(solver, "_angle_mesh_cache_enabled", lambda: False)
    monkeypatch.setattr(solver, "gmsh_mesh_reuse_enabled", lambda: True)
    monkeypatch.setattr(solver, "gmsh_solve_reuse_enabled", lambda: True)
    monkeypatch.setattr(solver, "full_cycle_congruent_bases", lambda *args, **kwargs: [])
    monkeypatch.setattr(solver, "slot_current_pattern_matches", lambda *args: True)
    monkeypatch.setattr(solver, "_rotate_gmsh_artifact_for_config", lambda artifact, config, angle: {**artifact, "angle": angle})
    monkeypatch.setattr(solver, "_zero_current_solve_mesh_artifact", lambda artifact: dict(artifact))
    monkeypatch.setattr(solver, "build_solve_mesh_evidence", lambda *args, **kwargs: {"geometry_sha256": "stand-in"})
    monkeypatch.setattr(solver, "_assert_imported_mesh_consumed_by_rust", lambda *args, **kwargs: None)
    monkeypatch.setattr(solver, "_magneto2d_summary_cache_dir", lambda *args: None)
    monkeypatch.setattr(solver, "_iron_loss_record", lambda *args: (None, None))
    monkeypatch.setattr(solver, "run_magneto2d_report", native)
    monkeypatch.setattr(solver, "derive_congruent_solve_report", fail_reuse)
    monkeypatch.setattr(solver, "_aggregate_per_angle_mesh_sweep", aggregate)
    monkeypatch.setattr(solver, "_build_field_line_frame_in_subprocess", frame)
    monkeypatch.setattr(solver, "_build_field_line_frame_from_sources_in_subprocess", frame)
    monkeypatch.setattr(solver, "cancellable_process_pool", frame_pool)
    monkeypatch.setattr(
        solver, "solver_setting",
        lambda name, default=None: "1" if state.compact and name == "COILEM_MAGNETO2D_COMPACT_QA_REPORT" else default,
    )
    state.check_cancelled = check_cancelled
    state.run = lambda: solver._solve_with_per_angle_producer_meshes(
        config, Producer(), solve_cache_dir=tmp_path / "solve_cache" / "fallbacks", check_cancelled=check_cancelled,
    )
    return state


def _start(state):
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


def _native_event(state, lane, angle):
    return state.native_events.setdefault((lane, angle), threading.Event())


def _frame_event(state, index):
    return state.frame_events.setdefault(index, threading.Event())


def test_failed_congruence_fallbacks_execute_concurrently_and_are_fully_drained(fallback_pipeline):
    state = fallback_pipeline
    gate, first_started, second_started = (threading.Event() for _ in range(3))

    def native_hook(lane, angle):
        if angle != 0.0:
            (first_started if angle == 60.0 else second_started).set()
            assert gate.wait(10), "fallback gate was never released"

    state.native_hook = native_hook
    thread, result = _start(state)
    try:
        _wait_for(first_started, result, "first fallback never started")
        _wait_for(second_started, result, "fallbacks ran serially instead of sharing the native pool")
        assert state.max_active == 2
    finally:
        gate.set()
        thread.join(timeout=15)

    assert not thread.is_alive()
    report, _ = result.result(timeout=0)
    assert Counter(state.native_started) == {("loaded", angle): 1 for angle in state.angles}
    assert all(future.done() and not future.cancelled() for _, future in state.native_futures)
    assert [report["angle"] for report in state.aggregate[0]] == state.angles
    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1, 2]
    assert Counter(state.frame_calls) == {0: 1, 1: 1, 2: 1}


@pytest.mark.parametrize("blocked_lane", ["loaded", "noload"])
def test_dynamic_fallbacks_wait_for_their_own_partner_and_preserve_angle_order(fallback_pipeline, blocked_lane):
    state = fallback_pipeline
    state.config.solve_options.back_emf = True
    state.config.solve_params.stream_noload_field_lines = True
    gate = threading.Event()

    def native_hook(lane, angle):
        if lane == blocked_lane and angle == 60.0:
            assert gate.wait(10), "paired fallback gate was never released"

    state.native_hook = native_hook
    thread, result = _start(state)
    try:
        other = "noload" if blocked_lane == "loaded" else "loaded"
        _wait_for(_native_event(state, other, 60.0), result, "first fallback partner never completed")
        assert not _frame_event(state, 1).is_set()
        _wait_for(_frame_event(state, 2), result, "unrelated fallback pair was not drained while the earlier pair waited")
        assert not _frame_event(state, 1).is_set()
    finally:
        gate.set()
        thread.join(timeout=15)

    assert not thread.is_alive()
    report, _ = result.result(timeout=0)
    expected = {(lane, angle): 1 for lane in ("loaded", "noload") for angle in state.angles}
    assert Counter(state.native_started) == expected
    assert all(future.done() and not future.cancelled() for _, future in state.native_futures)
    assert [item["angle"] for item in state.aggregate[0]] == state.angles
    assert [item["angle"] for item in state.aggregate[1]] == state.angles
    assert [frame["frame_index"] for frame in report["field_line_frames"]] == [0, 1, 2]
    assert Counter(state.frame_calls) == {0: 1, 1: 1, 2: 1}
    assert state.frame_calls.index(2) < state.frame_calls.index(1)


def test_dynamic_fallback_error_is_observed_and_queued_work_cancelled_before_native_join(fallback_pipeline):
    state = fallback_pipeline
    state.angles = [0.0, 60.0, 120.0, 180.0, 240.0]
    state.error_key = ("loaded", 60.0)
    gate, blocked = threading.Event(), threading.Event()

    def native_hook(lane, angle):
        if angle == 60.0:
            assert blocked.wait(3), "another fallback did not start"
            raise RuntimeError("dynamic fallback failed")
        if angle > 60.0:
            blocked.set()
            assert gate.wait(10), "remaining native fallback gate was never released"

    state.native_hook = native_hook
    thread, result = _start(state)
    try:
        _wait_for(state.submitted, result, "dynamic fallback futures were not all registered")
        _wait_for(state.error_observed, result, "failed fallback result was not observed during native work")
        _wait_for(state.queue_cancelled, result, "queued fallback survived error cleanup until native join")
        assert not gate.is_set()
    finally:
        gate.set()
        thread.join(timeout=15)

    assert not thread.is_alive()
    with pytest.raises(RuntimeError, match="dynamic fallback failed"):
        result.result(timeout=0)
    assert any(future.cancelled() for _, future in state.native_futures)
    assert all(future.done() for _, future in state.native_futures)


def test_compact_no_frame_path_cancels_queued_fallbacks_before_joining_running_work(fallback_pipeline):
    state = fallback_pipeline
    state.compact = True
    state.angles = [0.0, 60.0, 120.0, 180.0]
    gate, first_started, second_started = (threading.Event() for _ in range(3))

    def native_hook(lane, angle):
        if angle != 0.0:
            (first_started if angle == 60.0 else second_started).set()
            assert gate.wait(10), "running fallback gate was never released"

    state.native_hook = native_hook
    thread, result = _start(state)
    try:
        _wait_for(first_started, result, "first fallback never started")
        _wait_for(second_started, result, "second fallback never started")
        _wait_for(state.submitted, result, "queued fallback was not registered")
        state.cancelled.set()
        _wait_for(state.queue_cancelled, result, "compact path joined native work before cancelling its queue")
        assert not gate.is_set()
        assert state.frame_pool_entries == 0
    finally:
        gate.set()
        thread.join(timeout=15)

    assert not thread.is_alive()
    with pytest.raises(SolveCancelledError, match="cancel fallback work"):
        result.result(timeout=0)
    assert ("loaded", 180.0) not in state.native_started
    assert next(future for key, future in state.native_futures if key == ("loaded", 180.0)).cancelled()
    assert all(future.done() for _, future in state.native_futures)
    assert not state.frame_calls


@pytest.mark.parametrize("pole_pitch_reuse", [False, True])
def test_pole_pitch_reuse_meshes_one_base_and_still_solves_every_position(
    fallback_pipeline, monkeypatch, pole_pitch_reuse
):
    state = fallback_pipeline
    # 8 poles on 12 slots: electrical 0, 60, 120 deg are mechanical 0, 15, 30 deg.
    # 30 deg is a slot pitch from 0; 15 deg is two slot pitches less one pole pitch.
    state.config.rotor.pole_count = 8
    turns: list[tuple[float, float, bool]] = []

    def rotate(artifact, config, angle, *, across_pole_pitches=False):
        turns.append((float(artifact["angle"]), float(angle), across_pole_pitches))
        return {**artifact, "angle": angle, "turned_from": artifact["angle"]}

    monkeypatch.setattr(solver, "_rotate_gmsh_artifact_for_config", rotate)
    monkeypatch.setattr(solver, "gmsh_pole_pitch_mesh_reuse_enabled", lambda: pole_pitch_reuse)
    meshes_seen: dict[float, dict] = {}
    native = solver.run_magneto2d_report

    def recording_native(config, **kwargs):
        meshes_seen.setdefault(float(kwargs["rotor_angle_deg"]), kwargs["solve_mesh_artifact"])
        return native(config, **kwargs)

    monkeypatch.setattr(solver, "run_magneto2d_report", recording_native)

    state.run()

    # Every position is solved for real: the stand-in refuses solution reuse.
    assert sorted(angle for lane, angle in state.native_started if lane == "loaded") == [0.0, 60.0, 120.0]
    assert sorted(state.frame_calls) == [0, 1, 2]
    assert set(meshes_seen) == {0.0, 15.0, 30.0}
    if pole_pitch_reuse:
        # One mesh: 15 deg is it turned across a pole pitch, 30 deg turned by a slot pitch.
        assert sorted(turns) == [(0.0, 15.0, True), (0.0, 30.0, False)]
        assert meshes_seen[15.0]["turned_from"] == 0.0
    else:
        # 15 deg is meshed on its own.
        assert turns == [(0.0, 30.0, False)]
        assert "turned_from" not in meshes_seen[15.0]
