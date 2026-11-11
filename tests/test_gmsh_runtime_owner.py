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
from pathlib import Path

import pytest

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
