"""Ctrl+C during a streamed solve stops the server promptly and removes its record (#55).

The worker here is synthetic: after a cancellation it keeps "unwinding" until
the test releases it, like a Windows process pool joining its workers. Before
#55 the open stream waited for it until uvicorn's graceful-shutdown timeout,
and ``asyncio.run`` then waited for its default-executor thread, so the
launcher hit its 20 s deadline and force-exited without removing its record.
"""

from __future__ import annotations

import http.client
import json
import signal
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

import backend.magneto2d_adapter as magneto2d_adapter
from backend import launcher
from backend.models import MotorConfig
from backend.public_main import create_app
from backend.public_routes import solve as routes
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr

CONFIG = MotorConfig.model_validate_json(
    (Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8")
).model_dump(mode="json")


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


def test_shutdown_ends_solve_streams_before_stopping_native_processes(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(routes, "begin_server_shutdown", lambda: calls.append("streams"))
    monkeypatch.setattr(magneto2d_adapter, "shutdown_native_processes", lambda: calls.append("native"))

    launcher._shutdown_native_work()

    assert calls == ["streams", "native"]
