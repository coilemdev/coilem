"""Typed Elmer adapter failures."""


class ElmerError(RuntimeError):
    """Base class for actionable Elmer failures."""


class ElmerUnavailableError(ElmerError):
    """Required Elmer executables or capabilities are unavailable."""


class ElmerUnsupportedError(ElmerError):
    """The motor request lies outside the qualified Elmer contract."""


class ElmerMeshExportError(ElmerError):
    """The canonical solve mesh could not be exported losslessly."""


class ElmerMeshConversionError(ElmerError):
    """ElmerGrid failed or lost required physical groups."""


class ElmerCaseGenerationError(ElmerError):
    """Typed physics inputs could not produce a valid SIF."""


class ElmerExecutionError(ElmerError):
    """ElmerSolver exited unsuccessfully."""


class ElmerNonConvergenceError(ElmerExecutionError):
    """ElmerSolver exhausted the frozen nonlinear policy."""


class ElmerResultParseError(ElmerError):
    """Required scalar or field output is absent or malformed."""
