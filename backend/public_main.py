"""Allowlisted local API entry point for the public coilEM distribution."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend import __version__
from backend.custom_materials import SteelImportRequest, import_steel
from backend.elmer.capabilities import discover_elmer
from backend.platform_info import get_platform_info
from backend.public_material_catalog import (
    PublicMaterialCatalogResponse,
    build_public_material_catalog,
)
from backend.public_policy import public_elmer_enabled
from backend.public_routes.halbach import (
    halbach_capability_payload,
)
from backend.public_routes.halbach import (
    router as halbach_router,
)
from backend.public_routes.preview import router as preview_router
from backend.public_routes.runs import router as runs_router
from backend.public_routes.solve import router as solve_router
from backend.public_routes.tutorials import router as tutorials_router
from backend.public_security import public_request_rejection, public_ui_origins

# Route templates, not request URLs: the allowlist test compares this set against
# every ``route.path`` the app serves, so entries carry path parameters
# (``{artifact_id}``) but never a query string. Query parameters are validated by
# the route signatures instead, and the SSE routes are ordinary GET/POST paths
# here — the streaming response does not change the served path.
PUBLIC_API_PATHS = frozenset(
    {
        "/health",
        "/halbach/export/{export_kind}",
        "/halbach/linear/mesh-preview",
        "/halbach/linear/preview",
        "/halbach/linear/solve",
        "/halbach/linear/solve/stream",
        "/halbach/linear/solve/validate",
        "/halbach/mesh-preview",
        "/halbach/preview",
        "/halbach/solve",
        "/halbach/solve/stream",
        "/halbach/solve/validate",
        "/materials",
        "/materials/import",
        "/openapi.json",
        "/preview",
        "/runs",
        "/runs/{project_slug}/{run_id}",
        "/runs/{project_slug}/{run_id}/comparison",
        "/runs/{project_slug}/{run_id}/open-folder",
        "/runs/{project_slug}/{run_id}/package.zip",
        "/runs/{project_slug}/{run_id}/report.csv",
        "/runs/{project_slug}/{run_id}/report.pdf",
        "/solve",
        "/solve/cancel",
        "/solve/field-composition/armature",
        "/solve/field-composition/armature/stream",
        "/solve/field-frame/{artifact_id}",
        "/solve/playback-frame/{artifact_id}",
        "/solve/stream",
        "/solve/validate",
        "/solver/mesh-preview",
        "/tutorials/airgap-tax/solve",
        "/tutorials/current-field/solve",
        "/tutorials/chapter-1-capstone/solve",
        "/tutorials/field-force/magnet-only/solve",
        "/tutorials/field-force/motor/solve",
        "/tutorials/field-force/solve",
        "/tutorials/field-force/wire-only/solve",
        "/tutorials/follow-the-flux/solve",
        "/tutorials/iron-saturation/solve",
        "/tutorials/iron-saturation/spm-tooth/solve",
        "/tutorials/iron-saturation/tooth/solve",
        "/tutorials/lesson-1/field-composition/armature",
        "/tutorials/lesson-1/field-composition/pm",
        "/tutorials/lesson-1/mesh-preview",
        "/tutorials/lesson-1/solve/stream",
        "/tutorials/rotating-field/motor-geometry",
        "/tutorials/rotating-field/motor-sweep",
        "/tutorials/rotating-field/sweep",
        "/tutorials/rotor-chase/solve",
        "/tutorials/three-phase-motor/geometry",
        "/tutorials/three-phase-motor/sweep",
    }
)

app = FastAPI(
    title="coilEM Local API",
    description="Local Magneto2D API with feature-gated Elmer testing support.",
    version=__version__,
    docs_url=None,
    redoc_url=None,
)

PUBLIC_UI_ORIGINS = public_ui_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(PUBLIC_UI_ORIGINS),
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def guard_public_requests(request: Request, call_next):
    """Reject untrusted browser actions and preserve CORS cache separation.

    Playback WebPs are intentionally browser-cacheable. A response to a worker
    or other request without an Origin header otherwise lacks ``Vary: Origin``;
    Chromium can then reuse that headerless response for a later cross-origin
    fetch and reject it even though the origin is allowlisted.
    """

    rejection = public_request_rejection(request, PUBLIC_UI_ORIGINS)
    if rejection is not None:
        code, error = rejection
        return JSONResponse(
            {"detail": {"error_code": error, "message": "This API accepts trusted local requests only."}},
            status_code=code,
            headers={"Vary": "Origin", "Cache-Control": "no-store"},
        )
    response = await call_next(request)
    vary_values = {
        value.strip().lower()
        for value in response.headers.get("Vary", "").split(",")
        if value.strip()
    }
    if "origin" not in vary_values:
        response.headers.append("Vary", "Origin")
    return response


app.include_router(preview_router)
app.include_router(halbach_router)
app.include_router(runs_router)
app.include_router(solve_router)
app.include_router(tutorials_router)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, Any]:
    """Return local runtime facts and safe optional-solver availability."""

    platform_info = get_platform_info()
    elmer_enabled = public_elmer_enabled()
    elmer = (
        {
            "feature_enabled": True,
            **(await asyncio.to_thread(discover_elmer)).safe_health_payload(),
        }
        if elmer_enabled
        else {
            "feature_enabled": False,
            "available": False,
            "qualified": False,
            "adapter_ready": False,
            "reason": "Elmer is disabled for this launch.",
        }
    )
    return {
        "status": "ok",
        "mode": "local",
        "solver": "magneto2d",
        "network_required": False,
        "platform": {
            "system": platform_info["system"],
            "machine": platform_info["machine"],
        },
        "version": __version__,
        "capabilities": {
            "elmer": elmer,
            "halbach_array_2d": halbach_capability_payload(),
        },
    }


@app.get("/materials", tags=["system"])
async def list_materials() -> PublicMaterialCatalogResponse:
    """List public materials and the immutable models visualized by the UI."""

    return build_public_material_catalog()


@app.post("/materials/import", tags=["materials"])
async def import_material(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a project-local steel without installing or replacing catalog data."""
    try:
        material = import_steel(SteelImportRequest.model_validate(body))
    except (ValueError, ValidationError) as exc:
        message = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(status_code=400, detail={"error_code": "INVALID_MATERIAL_CURVE", "message": message}) from exc
    return {"material": material.model_dump(), "warnings": [
        f"Data ends at {material.bh_curve[-1][0]:g} T; higher fields use linear extrapolation of the final segment.",
        "User-supplied magnetization curve. Core-loss and temperature data are not included.",
    ]}


def start() -> None:
    """Start the public API on a loopback interface only."""

    import uvicorn

    raw_port = os.environ.get("COILEM_LOCAL_API_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("COILEM_LOCAL_API_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("COILEM_LOCAL_API_PORT must be between 1 and 65535.")
    uvicorn.run(app, host="127.0.0.1", port=port)
