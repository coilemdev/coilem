"""Public geometry and native Magneto2D mesh-preview routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, status

from backend.geometry import validate_geometry
from backend.gmsh_solver import GmshMeshQAError, GmshUnavailableError
from backend.magneto2d_adapter import (
    Magneto2DExecutionError,
    Magneto2DUnsupportedError,
    get_magneto2d_support_error,
    run_magneto2d_mesh_preview,
)
from backend.models import GeometryPreview, MotorConfig
from backend.preview import generate_preview
from backend.public_policy import (
    PublicConfigError,
    normalize_public_mesh_preview_config,
    parse_public_motor_config,
    public_config_support_error,
)

router = APIRouter()


def _public_config_http_error(exc: PublicConfigError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": str(exc),
            "field": exc.field,
        },
    )


def _raise_for_invalid_geometry(config: MotorConfig) -> None:
    """Reject geometry the mesher cannot build, with the reason and the fix.

    Neither public route used to run this, so an invalid rotor — raising the pole
    count without narrowing the magnets is the easy way in, since magnet_width_mm
    is an absolute arc length and does not follow the pole pitch — went all the way
    into Gmsh and came back as an unhandled mesh-QA area mismatch. The check itself
    already existed and already got this case right; nothing was calling it.
    """

    errors = validate_geometry(config) or []
    if not errors:
        return
    first = errors[0]
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": first.error_code,
            "message": first.message,
            "field": first.field,
            "suggestion": first.suggestion,
            # Everything that is wrong, so fixing one field does not just surface
            # the next round trip's worth of errors one at a time.
            "errors": [
                {
                    "error_code": err.error_code,
                    "message": err.message,
                    "field": err.field,
                    "suggestion": err.suggestion,
                }
                for err in errors
            ],
        },
    )


@router.post("/preview", response_model=GeometryPreview, tags=["preview"])
async def preview(body: dict[str, Any]) -> GeometryPreview:
    """Generate a launch-supported geometry preview without a solver."""

    try:
        config = parse_public_motor_config(body)
        _raise_for_invalid_geometry(config)
        return generate_preview(config)
    except PublicConfigError as exc:
        raise _public_config_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_GEOMETRY",
                "message": str(exc),
                "field": None,
            },
        ) from exc


@router.post("/solver/mesh-preview", tags=["solver"])
async def mesh_preview(body: dict[str, Any]) -> dict[str, Any]:
    """Generate a native Gmsh mesh preview for Magneto2D."""

    try:
        config = parse_public_motor_config(body)
        _raise_for_invalid_geometry(config)
        support_error = public_config_support_error(config, require_solve_params=True)
        if support_error is not None:
            raise support_error
        config = normalize_public_mesh_preview_config(config)
        magneto2d_error = get_magneto2d_support_error(config)
        if magneto2d_error is not None:
            raise PublicConfigError(
                "Configuration is outside the launch-supported Magneto2D mesh boundary.",
            )
    except PublicConfigError as exc:
        raise _public_config_http_error(exc) from exc

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(run_magneto2d_mesh_preview, config),
            timeout=300.0,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error_code": "MESH_PREVIEW_TIMEOUT",
                "message": "Magneto2D mesh preview timed out after 300 seconds.",
            },
        ) from exc
    except Magneto2DUnsupportedError as exc:
        raise _public_config_http_error(
            PublicConfigError(
                "Configuration is outside the launch-supported Magneto2D mesh boundary.",
            )
        ) from exc
    except GmshUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "GMSH_UNAVAILABLE",
                "message": "Gmsh is required for public mesh preview.",
            },
        ) from exc
    except GmshMeshQAError as exc:
        # The mesh QA gate rejecting a build is a statement about the geometry, so
        # it belongs in the response instead of escaping as an untyped 500 that the
        # UI can only render as "Failed to fetch".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "MESH_QA_FAILED",
                "message": f"The generated mesh failed its geometry checks: {exc}",
                "field": None,
            },
        ) from exc
    except Magneto2DExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "MESH_PREVIEW_FAILED",
                "message": "Magneto2D mesh preview failed.",
            },
        ) from exc
