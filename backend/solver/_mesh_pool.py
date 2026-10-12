"""Gmsh compatibility names for the shared cancellable solver worker pool."""

from backend.solver._process_pool import (
    cancellable_process_pool as gmsh_mesh_process_pool,
)
from backend.solver._process_pool import (
    check_process_worker_cancelled as check_mesh_worker_cancelled,
)
from backend.solver._process_pool import (
    completed_process_futures as completed_mesh_futures,
)

__all__ = ["check_mesh_worker_cancelled", "completed_mesh_futures", "gmsh_mesh_process_pool"]
