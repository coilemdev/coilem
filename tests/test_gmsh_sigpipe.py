"""Meshing must not let a broken pipe kill the process that ran Gmsh.

libgmsh's initialization sets SIGPIPE back to the default action (terminate),
and gmsh.finalize() does not undo it. The launcher meshes in its own process,
so after the first preview a write to a solver pipe or client socket that
closed during Ctrl+C shutdown killed the server with SIGPIPE (exit -13 in the
release acceptance run) and left its launcher record behind.
"""

from __future__ import annotations

import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from backend.gmsh_solver import GMSH_AVAILABLE

pytestmark = pytest.mark.pr

REPO_ROOT = Path(__file__).resolve().parents[1]

_WRITE_AFTER_MESHING = """
import os, threading
from backend.gmsh_solver import _GMSH_API_LOCK, gmsh, initialize_gmsh

def mesh_session():
    with _GMSH_API_LOCK:
        initialize_gmsh()
        gmsh.finalize()

# The launcher meshes in FastAPI worker threads, not on the main thread.
worker = threading.Thread(target=mesh_session)
worker.start()
worker.join()
read_end, write_end = os.pipe()
os.close(read_end)
try:
    os.write(write_end, b"x")
except BrokenPipeError:
    print("broken pipe raised")
"""


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason="no SIGPIPE on this platform")
@pytest.mark.skipif(not GMSH_AVAILABLE, reason="gmsh is not installed")
def test_broken_pipe_after_meshing_raises_instead_of_killing_the_process() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _WRITE_AFTER_MESHING],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, f"exit={completed.returncode}\n{completed.stderr}"
    assert completed.stdout.strip() == "broken pipe raised"


def test_backend_starts_gmsh_only_through_initialize_gmsh() -> None:
    # One call: the one inside initialize_gmsh itself.
    direct = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "backend").rglob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.search(r"\bgmsh\.initialize\(", line)
    ]
    assert direct == ["backend/gmsh_solver.py"], direct
