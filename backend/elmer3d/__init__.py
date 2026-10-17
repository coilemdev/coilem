"""Experimental, explicit-file Elmer 3D integration (not the public 2D solver)."""

from .model import Case3D
from .solver import solve_case

__all__ = ["Case3D", "solve_case"]
