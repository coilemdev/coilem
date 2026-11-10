"""Data contracts for motor errors. """

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Error response returned by API."""

    error_code: Literal[
        "INVALID_GEOMETRY",
        "SOLVER_FAILED",
        "MESH_QUALITY_LOW",
        "INVALID_PARAMETER",
        "CONVERGENCE_FAILED",
    ] = Field(..., description="Categorical error code")
    message: str = Field(..., description="Human-readable error message")
    field: Optional[str] = Field(
        default=None, description="JSON path to offending parameter if applicable"
    )
    suggestion: Optional[str] = Field(
        default=None, description="Actionable suggestion for resolving the error"
    )
