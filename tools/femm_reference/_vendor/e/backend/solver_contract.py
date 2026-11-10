"""Solver-neutral contracts shared by electromagnetic implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from backend.models import MotorConfig, SolveResult

ProgressCallback = Callable[..., Any]


class Solver(ABC):
    """Abstract base class for electromagnetic solvers."""

    @abstractmethod
    def solve(
        self,
        config: MotorConfig,
        on_progress: ProgressCallback | None = None,
        solve_mesh_key: str | None = None,
    ) -> SolveResult:
        """Solve a supported motor configuration."""

    def cancel_active_solve(self) -> None:
        """Best-effort hook for stopping an in-flight solve."""


class SolveCancelledError(RuntimeError):
    """Raised when a running solve is cancelled by the user."""
