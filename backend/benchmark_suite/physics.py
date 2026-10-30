"""The sources that decide what a benchmark measured.

Winding layout, current angle and axis, slot and layer geometry, meshes and
angle grids, materials, field extraction and the native solver. A benchmark
record stays valid for any build whose physics sources hash the same, so a
0.4.0 install can be matched against a record measured at an earlier commit
(#71). Changing any of them needs a new record, and a new qualification
report (tests/test_qualification.py).

This module uses only the standard library: ``setup.py`` loads it by path to
stamp the solver's source hashes into an installed package's build identity,
since a wheel carries the Magneto2D executable but not its Rust sources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PHYSICS_PYTHON_SOURCES = (
    "backend/airgap_sampling.py",
    "backend/back_emf_harmonics.py",
    "backend/excitation.py",
    "backend/geometry.py",
    "backend/geometry_drawer.py",
    "backend/geometry_ir.py",
    "backend/geometry_ir_tessellation.py",
    "backend/gmsh_mesh_rotation.py",
    "backend/gmsh_solver.py",
    "backend/magneto2d_adapter/__init__.py",
    "backend/magneto2d_adapter/_state.py",
    "backend/material_catalog.py",
    "backend/material_contract.py",
    "backend/reference_models/prius.py",
    "backend/solver/__init__.py",
    "backend/solver/_helpers.py",
    "backend/solver_contract.py",
    "backend/steel_flux_metrics.py",
    "backend/sweep_planning.py",
    "backend/torque_metrics.py",
    "backend/winding_utils.py",
)
PHYSICS_DATA_SOURCES = (
    "materials/electrical-steel/M350-50A.csv",
    "backend/reference_models/pyleecan_prius_2004.json",
    "backend/reference_models/pyleecan_prius_2004_config.json",
)
SOLVER_LOCK_FILE = "solvers/magneto2d/Cargo.lock"
SOLVER_SOURCE_DIR = "solvers/magneto2d/src"
# Build-identity key holding the solver sources an installed binary was built from.
BUILD_INFO_KEY = "magneto2d_physics_sources"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def solver_physics_sources(root: Path) -> tuple[str, ...]:
    """The Rust sources and lock file the solver's numbers depend on (not tests, teaching or thermal)."""

    sources = (
        path.relative_to(root).as_posix()
        for path in (root / SOLVER_SOURCE_DIR).rglob("*.rs")
        if path.name not in ("tests.rs", "teaching.rs") and "thermal" not in path.relative_to(root).parts
    )
    return (SOLVER_LOCK_FILE, *sorted(sources))


def physics_sources(root: Path) -> tuple[str, ...]:
    """Every physics source of a source checkout, as repository paths."""

    return (*PHYSICS_PYTHON_SOURCES, *PHYSICS_DATA_SOURCES, *solver_physics_sources(root))


def solver_source_hashes(root: Path) -> dict[str, str]:
    """``{path: sha256}`` for the solver sources, as a build stamps them."""

    return {relative: _sha256(root / relative) for relative in solver_physics_sources(root)}
