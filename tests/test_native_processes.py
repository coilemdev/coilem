"""Native solver processes: checkout-independent cwd and shutdown cancellation."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from backend import magneto2d_adapter as adapter
from backend.magneto2d_adapter import _state
from backend.solver_environment import solver_process_environment

REPO_ROOT = Path(__file__).resolve().parents[1]
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


@pytest.fixture(autouse=True)
def reset_shutdown():
    yield
    _state._NATIVE_SHUTDOWN.clear()


def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


def test_teaching_solves_are_tracked_and_stopped_at_shutdown_only(tmp_path: Path) -> None:
    from backend.tutorial_fields import _run_teaching_solver

    outcome: dict[str, object] = {}
    worker = threading.Thread(
        target=lambda: outcome.update(completed=_run_teaching_solver(subprocess.run, SLEEPER, cwd=tmp_path))
    )
    started = time.monotonic()
    worker.start()
    _wait_for(lambda: len(_state._ACTIVE_NATIVE_PROCESSES) == 1)
    adapter.cancel_active_magneto2d_processes()  # /solve/cancel must not stop a lesson
    time.sleep(0.2)
    assert len(_state._ACTIVE_NATIVE_PROCESSES) == 1
    adapter.shutdown_native_processes()
    worker.join(10)
    assert not worker.is_alive() and time.monotonic() - started < 10
    assert outcome["completed"].returncode != 0
    assert not _state._ACTIVE_NATIVE_PROCESSES
    with pytest.raises(adapter.Magneto2DExecutionError, match="shutting down"):
        _run_teaching_solver(subprocess.run, SLEEPER, cwd=tmp_path)


def test_teaching_solver_timeout_kills_the_child(tmp_path: Path) -> None:
    from backend.tutorial_fields import _run_teaching_solver

    with pytest.raises(subprocess.TimeoutExpired):
        _run_teaching_solver(subprocess.run, SLEEPER, cwd=tmp_path, timeout=0.3)
    assert not _state._ACTIVE_NATIVE_PROCESSES


def test_injected_teaching_runner_gets_the_temporary_cwd(tmp_path: Path) -> None:
    from backend.tutorial_fields import _run_teaching_solver

    calls = []
    _run_teaching_solver(lambda command, **kwargs: calls.append(kwargs), ["magneto2d"], cwd=tmp_path, timeout=5)
    assert calls == [{"cwd": str(tmp_path), "capture_output": True, "text": True, "check": False, "timeout": 5}]


def test_cylindrical_halbach_process_is_tracked_and_runs_outside_the_checkout(monkeypatch, tmp_path: Path) -> None:
    from backend.halbach import solver as halbach_solver

    launched: dict[str, object] = {}

    def start(command, **kwargs):
        launched.update(kwargs)
        return adapter.start_native_process(SLEEPER, **kwargs)

    monkeypatch.setattr(halbach_solver, "ensure_magneto2d_binary", lambda: Path("magneto2d"))
    monkeypatch.setattr(halbach_solver, "start_native_process", start)
    outcome: dict[str, object] = {}

    def solve() -> None:
        try:
            halbach_solver._run_field_problem({"schema_version": "test"}, artifact_directory=tmp_path / "artifacts")
        except RuntimeError as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=solve)
    worker.start()
    _wait_for(lambda: len(_state._ACTIVE_NATIVE_PROCESSES) == 1)
    adapter.shutdown_native_processes()
    worker.join(10)
    assert not worker.is_alive()
    assert "Magneto2D field solve failed" in str(outcome["error"])
    assert Path(launched["cwd"]) == tmp_path / "artifacts"
    assert not Path(launched["cwd"]).resolve().is_relative_to(REPO_ROOT)


def test_motor_solves_run_in_a_temporary_directory(monkeypatch, tmp_path: Path) -> None:
    from backend.models import MotorConfig

    config = MotorConfig.model_validate(json.loads((REPO_ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text()))
    observed = []

    def runner(command, **kwargs):
        observed.append(Path(kwargs["cwd"]))
        Path(command[command.index("-o") + 1]).write_text("{}")
        return subprocess.CompletedProcess(command, 0, "", "")

    adapter.run_magneto2d_report(config, sweep=False, solve_mesh_artifact={}, runner=runner)
    assert observed and not observed[0].resolve().is_relative_to(REPO_ROOT)


def test_motor_processes_are_stopped_by_cancel_and_shutdown(tmp_path: Path) -> None:
    outcome: dict[str, object] = {}
    worker = threading.Thread(
        target=lambda: outcome.update(
            completed=adapter._run_magneto2d_command(subprocess.run, SLEEPER, cwd=tmp_path, env=solver_process_environment())
        )
    )
    worker.start()
    _wait_for(lambda: len(_state._ACTIVE_MAGNETO2D_PROCESSES) == 1)
    adapter.cancel_active_magneto2d_processes()
    worker.join(10)
    assert not worker.is_alive() and outcome["completed"].returncode != 0


def test_shutdown_stops_a_process_registered_after_it_began(tmp_path: Path) -> None:
    adapter.shutdown_native_processes()
    process = subprocess.Popen(SLEEPER)
    with adapter.track_native_process(process):
        assert process.wait(10) != 0
