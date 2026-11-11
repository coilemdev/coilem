"""Meshing on short-lived threads must not crash the process.

libgmsh's OpenMP runtime belongs to the first thread that starts Gmsh. Before
``_ensure_gmsh_runtime_owner`` that was whichever thread meshed first; when it
was a solve's own worker thread, the next mesh segfaulted the server. The
check runs in a child process because the failure is a segfault, not an
exception.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from backend import gmsh_solver
from backend.gmsh_solver import GMSH_AVAILABLE

REPO_ROOT = Path(__file__).resolve().parents[1]

_MESH_ON_THREE_SHORT_LIVED_THREADS = """
import threading
from backend.gmsh_solver import _GMSH_API_LOCK, gmsh, initialize_gmsh

def mesh():
    with _GMSH_API_LOCK:
        initialize_gmsh()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("square")
        gmsh.model.occ.addRectangle(0, 0, 0, 10, 10)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0)
        gmsh.model.mesh.generate(2)
        gmsh.finalize()

for _ in range(3):
    worker = threading.Thread(target=mesh)
    worker.start()
    worker.join()
print("meshed three times")
"""


@pytest.mark.skipif(not GMSH_AVAILABLE, reason="needs the Gmsh Python package")
def test_meshing_survives_the_first_meshing_thread_exiting() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _MESH_ON_THREE_SHORT_LIVED_THREADS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "meshed three times" in completed.stdout


def _owner_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "gmsh-runtime-owner" and thread.is_alive()]


def test_a_failed_owner_start_is_raised_and_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    # A start that raises must not latch: the owner thread has exited, so a
    # latched state would let later meshes run without the lifetime guarantee.
    monkeypatch.setattr(gmsh_solver, "_GMSH_RUNTIME_OWNER_STARTED", False)
    owners_before = len(_owner_threads())
    attempts: list[str] = []

    def failing_start() -> None:
        attempts.append("failed")
        raise RuntimeError("gmsh could not start")

    monkeypatch.setattr(gmsh_solver, "_start_gmsh", failing_start)
    with pytest.raises(RuntimeError, match="gmsh could not start"):
        gmsh_solver._ensure_gmsh_runtime_owner()
    assert gmsh_solver._GMSH_RUNTIME_OWNER_STARTED is False
    assert len(_owner_threads()) == owners_before

    class _Finalizable:
        @staticmethod
        def finalize() -> None:
            attempts.append("finalized")

    monkeypatch.setattr(gmsh_solver, "_start_gmsh", lambda: attempts.append("started"))
    monkeypatch.setattr(gmsh_solver, "gmsh", _Finalizable)
    gmsh_solver._ensure_gmsh_runtime_owner()
    assert attempts == ["failed", "started", "finalized"]
    assert gmsh_solver._GMSH_RUNTIME_OWNER_STARTED is True
    # The owner is parked, not finished.
    assert len(_owner_threads()) == owners_before + 1

    gmsh_solver._ensure_gmsh_runtime_owner()
    assert attempts == ["failed", "started", "finalized"]
