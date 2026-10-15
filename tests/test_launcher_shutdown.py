"""Ctrl+C during a streamed solve stops the server promptly and removes its record (#55).

Before #55 the open stream waited for the solver until uvicorn's
graceful-shutdown timeout. After the server stopped, interpreter exit still
joined the solver's process pools, which wait for their running tasks, such
as Gmsh meshes, so the launcher hit its 20 s deadline and force-exited
without removing its record. The in-process test uses a synthetic worker that
keeps "unwinding" until released; the subprocess tests interrupt the real
launcher while a real process-pool task is running.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest
import uvicorn

import backend.magneto2d_adapter as magneto2d_adapter
import backend.solve_workspace as solve_workspace
from backend import launcher
from backend.models import MotorConfig
from backend.public_main import create_app
from backend.public_routes import solve as routes
from backend.solve_workspace import SolveRunWriter, SolveWorkspace, SolveWorkspaceError
from backend.solver import _process_pool
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr

REPO = Path(__file__).resolve().parents[1]
CONFIG = MotorConfig.model_validate_json(
    (Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8")
).model_dump(mode="json")


@pytest.fixture(autouse=True)
def _fresh_exit_latch(monkeypatch):
    """Application exit refuses new process pools; keep that to each test."""
    monkeypatch.setattr(_process_pool, "_EXITING", threading.Event())


class SlowUnwindingWorker:
    """Reports progress, then keeps unwinding after a cancellation until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.thread_name: str | None = None

    def cancel_active_solve(self) -> None:
        self.cancelled.set()

    def solve(self, config, *, on_progress=None, **kwargs):
        self.thread_name = threading.current_thread().name
        try:
            self.started.set()
            if on_progress is not None:
                on_progress(1, 48, 0.25)
            self.cancelled.wait(timeout=30)
            self.release.wait(timeout=60)
            raise SolveCancelledError("Synthetic worker finished unwinding")
        finally:
            self.finished.set()


@pytest.fixture
def worker(monkeypatch, tmp_path):
    worker = SlowUnwindingWorker()
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setattr(routes, "_ACTIVE_SOLVE", {
        "running": False, "cancelled": False, "solver": None, "run_writer": None,
    })
    monkeypatch.setattr(routes, "_SERVER_STOPPING", threading.Event())
    monkeypatch.setattr(routes, "_create_public_solver", lambda *args: worker)
    # Shutdown must not leave this process refusing native solves for later tests.
    monkeypatch.setattr(magneto2d_adapter, "shutdown_native_processes", lambda: None)
    yield worker
    worker.release.set()
    worker.finished.wait(timeout=10)


def _read_stream(port: int, events: list[tuple[str, dict]], progressed: threading.Event) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    connection.request(
        "POST",
        "/solve/stream",
        body=json.dumps({"config": CONFIG}),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    event = None
    for raw in response:
        line = raw.decode("utf-8").strip()
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event:
            payload = json.loads(line.split(":", 1)[1])
            events.append((event, payload))
            if event == "progress" and payload.get("position") == 1:
                progressed.set()
    connection.close()


def test_ctrl_c_during_a_streamed_solve_stops_within_the_graceful_window(monkeypatch, worker):
    deadline_threads: list[str] = []
    monkeypatch.setattr(launcher, "_exit_after_deadline", lambda: deadline_threads.append("started"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = launcher._launcher_server_class()(uvicorn.Config(
        create_app(bound_port=port),
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=launcher.GRACEFUL_SHUTDOWN_S,
    ))
    serving = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    serving.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started

        events: list[tuple[str, dict]] = []
        progressed = threading.Event()
        client = threading.Thread(target=_read_stream, args=(port, events, progressed), daemon=True)
        client.start()
        assert progressed.wait(timeout=20), events
        # Not the event loop's default executor, which asyncio.run waits for at exit.
        assert worker.thread_name == "coilem-solver"

        # What the launcher does on Ctrl+C (and Ctrl+Break on Windows).
        stopped_at = time.monotonic()
        server.handle_exit(signal.SIGINT, None)
        serving.join(timeout=launcher.GRACEFUL_SHUTDOWN_S)
        elapsed = time.monotonic() - stopped_at

        assert not serving.is_alive(), "the server must stop while the worker is still unwinding"
        assert elapsed < 5, f"graceful shutdown took {elapsed:.1f}s"
        assert not worker.finished.is_set(), "the worker was still unwinding when the server stopped"
        assert worker.cancelled.is_set()
        assert deadline_threads == ["started"]
        client.join(timeout=5)
        assert events[-1][0] == "error"
        assert events[-1][1]["error_code"] == "SOLVER_CANCELLED"
        # The lane stays claimed until the worker returns, as for any cancellation.
        assert routes._ACTIVE_SOLVE["running"]
        worker.release.set()
        assert worker.finished.wait(timeout=10)
    finally:
        worker.release.set()
        server.should_exit = True
        serving.join(timeout=15)


def test_the_deadline_shows_where_shutdown_waits_then_exits(monkeypatch, capfd):
    exits: list[int] = []
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(launcher, "_force_exit", exits.append)

    launcher._exit_after_deadline()

    assert exits == [1]
    stderr = capfd.readouterr().err
    assert "shutdown took longer than 20 s" in stderr
    assert "test_the_deadline_shows_where_shutdown_waits_then_exits" in stderr

    def no_stderr(**kwargs):
        raise ValueError("sys.stderr has no file descriptor")

    monkeypatch.setattr(launcher.faulthandler, "dump_traceback", no_stderr)
    launcher._exit_after_deadline()
    assert exits == [1, 1]


def test_forced_exit_removes_the_launcher_record(monkeypatch, tmp_path):
    exits: list[int] = []

    def fake_exit(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(launcher, "_shutdown_native_work", lambda: None)
    monkeypatch.setattr(launcher.os, "_exit", fake_exit)
    launcher.write_record(tmp_path, 2645)
    monkeypatch.setattr(launcher, "_WRITTEN_RECORD", tmp_path / launcher.RECORD_FILE)

    with pytest.raises(SystemExit):
        launcher._force_exit(1)

    assert exits == [1]
    assert not (tmp_path / launcher.RECORD_FILE).exists(), "os._exit skips launch()'s cleanup"
    assert launcher._WRITTEN_RECORD is None


def test_shutdown_ends_solve_streams_then_stops_native_processes_and_pools(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(routes, "begin_server_shutdown", lambda: calls.append("streams"))
    monkeypatch.setattr(magneto2d_adapter, "shutdown_native_processes", lambda: calls.append("native"))
    monkeypatch.setattr(_process_pool, "terminate_process_pools", lambda: calls.append("pools"))

    launcher._shutdown_native_work()

    assert calls == ["streams", "native", "pools"]


class _RecordingWriter(SolveRunWriter):
    def __init__(self, record) -> None:  # no run directory
        self.record = record

    def fail(self, **kwargs) -> None:
        self.record()


class _RecordingSolver:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def cancel_active_solve(self) -> None:
        self.calls.append("solver")


def _active_solve(monkeypatch, solver, writer) -> threading.Event:
    monkeypatch.setattr(routes, "_ACTIVE_SOLVE", {
        "running": True, "cancelled": False, "solver": solver, "run_writer": writer,
    })
    stopping = threading.Event()
    monkeypatch.setattr(routes, "_SERVER_STOPPING", stopping)
    return stopping


def test_shutdown_records_the_cancellation_before_ending_solve_streams(monkeypatch):
    calls: list[str] = []
    stopping = _active_solve(
        monkeypatch,
        _RecordingSolver(calls),
        _RecordingWriter(lambda: calls.append(f"record (streams ending: {routes._SERVER_STOPPING.is_set()})")),
    )

    routes.begin_server_shutdown()

    # A stream that ends on shutdown then finds the run already recorded.
    assert calls == ["solver", "record (streams ending: False)"]
    assert stopping.is_set()


def test_shutdown_stops_the_solver_and_streams_even_if_recording_fails(monkeypatch):
    calls: list[str] = []

    def denied() -> None:
        calls.append("record")
        raise PermissionError(5, "Access is denied")

    stopping = _active_solve(monkeypatch, _RecordingSolver(calls), _RecordingWriter(denied))

    with pytest.raises(PermissionError):
        routes.begin_server_shutdown()

    assert calls == ["solver", "record"]
    assert stopping.is_set()


def _run_writer(tmp_path: Path) -> SolveRunWriter:
    return SolveWorkspace(tmp_path / "workspace").begin_run(
        project_name="shutdown", config=CONFIG, submitted_request={"config": CONFIG}
    )


def test_concurrent_cancellations_write_the_run_manifest_once(monkeypatch, tmp_path):
    writer = _run_writer(tmp_path)
    original = solve_workspace._atomic_write_json
    counting = threading.Lock()
    active = 0
    overlap: list[int] = []
    statuses: list[str] = []

    def slow_write(path: Path, payload) -> None:
        nonlocal active
        with counting:
            active += 1
            overlap.append(active)
        try:
            time.sleep(0.2)  # long enough for the other cancellation to arrive
            statuses.append(payload["status"])
            original(path, payload)
        finally:
            with counting:
                active -= 1

    monkeypatch.setattr(solve_workspace, "_atomic_write_json", slow_write)
    start = threading.Barrier(2)

    def cancel() -> None:
        start.wait()
        writer.fail(error_code="SOLVER_CANCELLED", message="Solve cancelled by user.", cancelled=True)

    # The stream's error path and the launcher's shutdown, as on Windows in #55,
    # where a second concurrent replace of manifest.json is refused.
    threads = [threading.Thread(target=cancel) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert max(overlap) == 1
    assert statuses == ["cancelled"]
    manifest = json.loads((writer.partial_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "cancelled"


def test_saving_a_run_waits_for_its_cancellation_to_be_recorded(monkeypatch, tmp_path):
    writer = _run_writer(tmp_path)
    original = solve_workspace._atomic_write_json
    writing = threading.Event()
    release = threading.Event()

    def held_write(path: Path, payload) -> None:
        writing.set()
        release.wait(timeout=10)
        original(path, payload)

    monkeypatch.setattr(solve_workspace, "_atomic_write_json", held_write)
    cancelling = threading.Thread(
        target=writer.fail,
        kwargs={"error_code": "SOLVER_CANCELLED", "message": "coilEM is stopping.", "cancelled": True},
    )
    cancelling.start()
    assert writing.wait(timeout=5)

    outcome: list[str] = []

    def save() -> None:
        try:
            writer.complete({})
            outcome.append("saved")
        except SolveWorkspaceError as exc:
            outcome.append(str(exc))

    saving = threading.Thread(target=save)
    saving.start()
    saving.join(timeout=0.3)
    assert saving.is_alive(), "the save must wait for the cancellation being recorded"
    release.set()
    cancelling.join(timeout=10)
    saving.join(timeout=10)

    assert outcome == ["solve run writer is already closed"]


def test_terminating_process_pools_ends_their_running_tasks(monkeypatch):
    unwound = threading.Event()
    pools: list = []
    futures: list = []

    def cancelled_while_a_task_runs() -> None:
        try:
            with _process_pool.cancellable_process_pool(1) as pool:
                pools.append(pool)
                futures.append(pool.submit(time.sleep, 120))
                raise SolveCancelledError("cancelled by the user")
        except SolveCancelledError:
            pass
        finally:
            unwound.set()

    solver = threading.Thread(target=cancelled_while_a_task_runs, daemon=True)
    solver.start()
    try:
        # A user's cancellation lets the running task finish.
        assert not unwound.wait(timeout=1.0)
        assert list(_process_pool._LIVE_POOLS) == pools

        _process_pool.terminate_process_pools()

        assert unwound.wait(timeout=10), "pool shutdown still waited for its running task"
        assert isinstance(futures[0].exception(timeout=5), BrokenProcessPool)
        assert not _process_pool._LIVE_POOLS
        # A pool created after exit began cannot escape it.
        with pytest.raises(SolveCancelledError):
            with _process_pool.cancellable_process_pool(1):
                pass
    finally:
        if not unwound.is_set():
            _process_pool._stop_pool_workers(pools[0])
        solver.join(timeout=10)


def _die_while_sending_a_result(marker: str) -> None:
    """In a pool worker: send part of a result message, then hang until killed."""
    frame = sys._getframe(1)
    while "result_queue" not in frame.f_locals:  # concurrent.futures.process._process_worker
        frame = frame.f_back
    writer = frame.f_locals["result_queue"]._writer
    os.write(writer.fileno(), struct.pack("!i", 1 << 20) + b"part of a large mesh")
    Path(marker).write_text("sent", encoding="utf-8")
    time.sleep(120)


@pytest.mark.skipif(os.name == "nt", reason="Windows pipes carry whole messages")
def test_terminating_a_pool_frees_its_manager_from_a_partial_result(tmp_path):
    # A worker killed while sending a large result left the pool's manager
    # thread waiting in recv() for the rest, and interpreter exit joined that
    # thread, so the launcher hit its 20 s deadline (#55 acceptance).
    marker = tmp_path / "sent"
    unwound = threading.Event()
    pools: list = []

    def solve_cancelled_by_exit() -> None:
        try:
            with _process_pool.cancellable_process_pool(1) as pool:
                pools.append(pool)
                future = pool.submit(_die_while_sending_a_result, str(marker))
                future.result(timeout=60)
        except BaseException:  # noqa: BLE001 - only the unwinding matters here
            pass
        finally:
            unwound.set()

    threading.Thread(target=solve_cancelled_by_exit, daemon=True).start()
    deadline = time.monotonic() + 60
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists()
    time.sleep(0.3)  # let the manager thread start reading the message
    manager = pools[0]._executor_manager_thread
    results = pools[0]._result_queue
    try:
        _process_pool.terminate_process_pools()

        manager.join(timeout=10)
        assert not manager.is_alive(), "the pool's manager thread still waits for the rest of the result"
        assert unwound.wait(timeout=10)
    finally:
        results._writer.close()  # never leave a stuck thread for pytest's own exit
        manager.join(timeout=10)


def test_terminating_a_pool_before_its_workers_start_refuses_them():
    registered, terminated = threading.Event(), threading.Event()
    outcome: list[BaseException] = []
    workers: list[dict] = []

    def submits_after_exit_began() -> None:
        try:
            with _process_pool.cancellable_process_pool(1) as pool:
                workers.append(pool._processes)
                registered.set()
                terminated.wait(timeout=10)
                pool.submit(time.sleep, 120)
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            outcome.append(exc)

    solver = threading.Thread(target=submits_after_exit_began, daemon=True)
    solver.start()
    assert registered.wait(timeout=10)
    _process_pool.terminate_process_pools()
    terminated.set()
    solver.join(timeout=10)

    assert not solver.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], RuntimeError), outcome
    assert workers == [{}], "no worker may start once exit has begun"


# The real launcher, with the solve or its packaging held by a process-pool
# task that runs until it is stopped. Run as a script so Ctrl+C is real.
_INTERRUPTED_LAUNCHER = """
import os
import sys
import threading
import time
from pathlib import Path

import backend.launcher as launcher
import backend.public_field_playback as playback
import backend.resources as resources
import backend.solver._process_pool as process_pool
from backend.public_routes import solve as routes
from backend.solver._process_pool import cancellable_process_pool, completed_process_futures
from backend.solver_contract import SolveCancelledError

POOLS_STOPPED = threading.Event()


def hold(*_args):
    Path(os.environ["COILEM_TEST_POOL_PID"]).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(120)


class PoolHoldingSolver:
    def __init__(self, stage):
        self.stage = stage
        self.cancelled = threading.Event()

    def cancel_active_solve(self):
        self.cancelled.set()

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise SolveCancelledError("Solve cancelled by user.")

    def solve(self, config, *, on_progress=None, **kwargs):
        on_progress(1, 48, 0.25)
        if self.stage != "solving":
            return {"frames": [{"field_frame_artifact": {"artifact_id": "held"}}]}
        with cancellable_process_pool(1) as pool:
            for future in completed_process_futures({pool.submit(hold): 0}, self.check_cancelled):
                future.result()
        return {}


def prepare_playback(stage, cache, artifact_id):
    if stage == "packaging-after-cleanup":
        # Still preparing playback input when shutdown stops the live pools.
        Path(os.environ["COILEM_TEST_PREPARING"]).write_text("1", encoding="utf-8")
        POOLS_STOPPED.wait(timeout=60)
    return cache / "frames" / artifact_id


def stop_pools_then_release(stop_pools):
    stop_pools()
    POOLS_STOPPED.set()


if __name__ == "__main__":
    stage = sys.argv[1]
    cache = Path(os.environ["COILEM_TEST_CACHE"])
    resources.ui_bundle_root = lambda: Path(os.environ["COILEM_TEST_UI"])
    launcher.linux_mesher_problem = lambda: None
    routes._create_public_solver = lambda *args: PoolHoldingSolver(stage)
    stop_pools = process_pool.terminate_process_pools
    process_pool.terminate_process_pools = lambda: stop_pools_then_release(stop_pools)
    # Packaging builds field playback on its process pool.
    playback.resolve_solve_cache_artifact_id = lambda artifact_id: prepare_playback(stage, cache, artifact_id)
    playback._PLAYBACK_PROCESS_MIN_FRAMES = 1
    playback._package_playback_frame = hold
    routes._package_public_result = lambda result: playback.build_public_field_playback(
        result["frames"], mode="armature"
    )
    raise SystemExit(launcher.main(sys.argv[2:]))
"""


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while _process_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve_scripted_launcher(tmp_path: Path, stage: str):
    """Run _INTERRUPTED_LAUNCHER until it serves; return it, its port, its output and the output reader."""

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>coilEM</title>", encoding="utf-8")
    script = tmp_path / "interrupted_launcher.py"
    script.write_text(_INTERRUPTED_LAUNCHER, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "PYTHONUNBUFFERED": "1",
        "COILEM_USER_DATA_ROOT": str(tmp_path / "user-data"),
        "COILEM_TEST_UI": str(ui),
        "COILEM_TEST_CACHE": str(tmp_path / "cache"),
        "COILEM_TEST_POOL_PID": str(tmp_path / "pool-worker.pid"),
        "COILEM_TEST_PREPARING": str(tmp_path / "preparing-playback"),
        "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL": "1",
    }
    env.pop("COILEM_LOCAL_API_PORT", None)
    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, str(script), stage, "--no-browser", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    output: list[str] = []
    ready = threading.Event()

    def drain() -> None:
        assert server.stdout is not None
        for line in server.stdout:
            output.append(line.rstrip())
            if "is running at" in line:
                ready.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    if not ready.wait(timeout=60):
        _stop_scripted_launcher(server, tmp_path)
        pytest.fail("\n".join(output))
    return server, port, output, reader


def _interrupt(server: subprocess.Popen) -> None:
    server.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)


def _stop_scripted_launcher(server: subprocess.Popen, tmp_path: Path) -> None:
    if server.poll() is None:
        server.kill()
        server.wait(timeout=10)
    pid_file = tmp_path / "pool-worker.pid"
    if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
        try:
            os.kill(int(pid_file.read_text(encoding="utf-8")), getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass


@pytest.mark.parametrize("stage", ["solving", "packaging", "packaging-after-cleanup"])
def test_interrupting_the_launcher_stops_a_running_process_pool_task(tmp_path, stage):
    data, pid_file = tmp_path / "user-data", tmp_path / "pool-worker.pid"
    preparing = tmp_path / "preparing-playback"
    late = stage == "packaging-after-cleanup"
    server, port, output, _ = _serve_scripted_launcher(tmp_path, stage)
    try:
        events: list[tuple[str, dict]] = []
        client = threading.Thread(target=_read_stream, args=(port, events, threading.Event()), daemon=True)
        client.start()
        # Interrupt while a pool task runs, or (late) while playback still
        # prepares its input, before its pool exists.
        started_marker = preparing if late else pid_file
        deadline = time.monotonic() + 60
        while not started_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started_marker.exists(), "\n".join(output)
        time.sleep(0.2)  # let the worker record its id fully
        worker = None if late else int(pid_file.read_text(encoding="utf-8"))

        started = time.monotonic()
        _interrupt(server)
        code = server.wait(timeout=60)
        elapsed = time.monotonic() - started

        log = "\n".join(output)
        assert code == 0, f"exit {code} after {elapsed:.1f}s\n{log}"
        assert elapsed < launcher.GRACEFUL_SHUTDOWN_S, f"took {elapsed:.1f}s\n{log}"
        assert not (data / launcher.RECORD_FILE).exists()
        if worker is None:
            assert not pid_file.exists(), "a pool created after shutdown cleanup started a worker"
        else:
            assert _gone_within(worker, 10), "the process-pool worker outlived the launcher"
        client.join(timeout=10)
        if stage != "solving":
            assert ("progress", "packaging_results") in [(name, event.get("stage")) for name, event in events]
        assert events[-1][0] == "error"
        assert events[-1][1]["error_code"] == "SOLVER_CANCELLED"
        manifests = list((data / "solves").rglob("manifest.json"))
        assert any(json.loads(path.read_text(encoding="utf-8"))["status"] == "cancelled" for path in manifests)
    finally:
        _stop_scripted_launcher(server, tmp_path)


@pytest.mark.parametrize("solving", [False, True], ids=["idle", "solving"])
def test_one_ctrl_c_delivered_twice_stops_the_launcher_cleanly(tmp_path, solving):
    """Under uvx the terminal interrupts the process group, then uv forwards the same Ctrl+C about 200 ms later (#76)."""

    pid_file = tmp_path / "pool-worker.pid"
    server, port, output, reader = _serve_scripted_launcher(tmp_path, "solving")
    try:
        if solving:
            threading.Thread(target=_read_stream, args=(port, [], threading.Event()), daemon=True).start()
            deadline = time.monotonic() + 60
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "\n".join(output)

        _interrupt(server)
        time.sleep(0.2)
        _interrupt(server)
        code = server.wait(timeout=60)
        reader.join(timeout=10)

        log = "\n".join(output)
        assert code == 0, f"exit {code}\n{log}"
        assert "forced exit" not in log, log
        assert not (tmp_path / "user-data" / launcher.RECORD_FILE).exists()
    finally:
        _stop_scripted_launcher(server, tmp_path)
