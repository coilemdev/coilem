"""Private Elmer FEM adapter for coilEM's 2D motor workflow.

Imports stay deliberately light: capability checks and the public runtime do
not import meshio or start external Elmer processes.
"""

from .capabilities import ElmerCapabilities, discover_elmer
from .errors import (
    ElmerCaseGenerationError,
    ElmerError,
    ElmerExecutionError,
    ElmerMeshConversionError,
    ElmerMeshExportError,
    ElmerNonConvergenceError,
    ElmerResultParseError,
    ElmerUnavailableError,
    ElmerUnsupportedError,
)

__all__ = [
    "ElmerCapabilities",
    "ElmerCaseGenerationError",
    "ElmerError",
    "ElmerExecutionError",
    "ElmerMeshConversionError",
    "ElmerMeshExportError",
    "ElmerNonConvergenceError",
    "ElmerResultParseError",
    "ElmerUnavailableError",
    "ElmerUnsupportedError",
    "discover_elmer",
]
