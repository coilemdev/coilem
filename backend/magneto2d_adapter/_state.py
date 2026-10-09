"""Shared native process state and adapter exceptions."""
from __future__ import annotations

import os
import re
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MAGNETO2D_MANIFEST = REPO_ROOT / "solvers" / "magneto2d" / "Cargo.toml"
MAGNETO2D_BINARY = (
    REPO_ROOT
    / "solvers"
    / "magneto2d"
    / "target"
    / "release"
    / ("magneto2d.exe" if os.name == "nt" else "magneto2d")
)
_MAGNETO2D_BUILD_LOCK = threading.Lock()

SWEEP_PROGRESS_RE = re.compile(
    r"\[(?P<position>\d+)/(?P<total>\d+)\]"
    r"(?:.*?\belec=(?P<elec_deg>[-+0-9.eE]+)°)?"
    r".*?\b(?:arkkio|contour|mst(?:_torque)?)=(?P<torque>[-+0-9.eE]+)Nm"
    r"(?:.*?Ψa_noload=(?P<psi_a>[-+0-9.eE]+)Wb)?"
    r"(?:.*?Ψb_noload=(?P<psi_b>[-+0-9.eE]+)Wb)?"
    r"(?:.*?Ψc_noload=(?P<psi_c>[-+0-9.eE]+)Wb)?"
)
LIVE_FIELD_FRAME_PREFIX = "COILEM_FIELD_FRAME "
LIVE_FIELD_MESH_PREFIX = "COILEM_FIELD_MESH "
SOLVE_CONTEXT_PREFIX = "COILEM_SOLVE_CONTEXT "
SOLVE_ITERATION_PROGRESS_PREFIX = "COILEM_SOLVE_ITER "
LIVE_FIELD_CONTOUR_BANDS_PER_SIDE = 8
MAGNETO2D_INTERACTIVE_NONLINEAR_TOL = "0.075"
MAGNETO2D_FINE_NONLINEAR_TOL = "0.05"
_ACTIVE_MAGNETO2D_PROCESS_LOCK = threading.Lock()
_ACTIVE_MAGNETO2D_PROCESSES: "set[subprocess.Popen]" = set()

_MAX_SOLVE_MESH_CACHE_SIZE = 16
_SOLVE_MESH_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()



class Magneto2DUnsupportedError(ValueError):
    """Raised when a config falls outside the frozen magneto2d MVP subset."""


class Magneto2DExecutionError(RuntimeError):
    """Raised when the magneto2d Rust subprocess returns a non-zero exit."""
