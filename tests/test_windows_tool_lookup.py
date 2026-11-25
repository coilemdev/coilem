"""Developer commands can still find Git and Node after a Windows mesh (#316)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.pr
@pytest.mark.skipif(os.name != "nt", reason="Windows executable lookup")
def test_developer_tools_after_gmsh(tmp_path):
    if not all(shutil.which(tool) for tool in ("git", "node")):
        pytest.skip("requires Git and Node on PATH")
    # A long search path puts both tools beyond the prefix retained by Gmsh
    # 4.15.2. Keep the native environment change inside a disposable process.
    padding = os.pathsep.join(str(tmp_path / f"unused-{i}") for i in range(20))
    script = """
import subprocess
import gmsh
from tools.experimental_solve import _git
from tools.release.artifacts import tool_version

head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
node = subprocess.check_output(["node", "--version"], text=True).strip()
gmsh.initialize()
gmsh.finalize()
assert _git("rev-parse", "HEAD") == head
assert tool_version("node", "--version") == node
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PATH": padding + os.pathsep + os.environ["PATH"]},
        check=True, timeout=60,
    )
