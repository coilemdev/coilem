"""Serve the built coilEM UI from the launcher's API process.

The UI allowlist is exact and kept apart from ``PUBLIC_API_PATHS``: ``/``, the
client routes defined in ``frontend/src/public/tutorials/lessonRoutes.ts``, the
files copied from ``frontend/public/`` and the hashed build files under
``/assets/``. UI routes stay out of the OpenAPI schema. Every other path,
including unknown API paths and missing assets, keeps the API's 404.

Page fallback is exact-match only, never prefix based: the UI page
``/tutorials/follow-the-flux`` and the API route
``/tutorials/follow-the-flux/solve`` share a prefix.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import FileResponse, RedirectResponse, Response

# "/" plus the canonical and alias lesson paths, and the tutorials catalog.
UI_PAGE_ROUTES = frozenset(
    {
        "/",
        "/tutorials",
        "/tutorials/lesson-1",
        "/tutorials/follow-the-flux",
        "/tutorials/lesson-2",
        "/tutorials/airgap-tax",
        "/tutorials/lesson-3",
        "/tutorials/current-field",
        "/tutorials/lesson-4",
        "/tutorials/iron-saturation",
        "/tutorials/lesson-5",
        "/tutorials/field-force",
        "/tutorials/lesson-6",
        "/tutorials/rotor-chase",
        "/tutorials/torque-production",
        "/tutorials/lesson-7",
        "/tutorials/rotating-field",
        "/tutorials/lesson-8",
        "/tutorials/three-phase-motor",
        "/tutorials/lesson-9",
        "/tutorials/magnetic-circuit",
        "/tutorials/motor-magnetic-circuit",
        "/tutorials/lesson-10",
        "/tutorials/back-emf",
        "/tutorials/back-emf-voltage-headroom",
        "/tutorials/chapter-1-capstone",
        "/tutorials/make-it-move",
        "/tutorials/review-fields",
    }
)
# Copied verbatim from frontend/public/ by the Vite build.
UI_PUBLIC_FILES = frozenset({"/brand/coilem-mark.svg", "/materials/sample-custom-steel.csv"})
UI_ASSET_ROUTE = "/assets/{name}"

# Vite names build files ``<name>-<8-character content hash>.<ext>``.
_HASHED_ASSET_NAME = re.compile(r"^[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+$")
# Explicit types: the OS registry can map ``.js`` to ``text/plain`` on Windows,
# which browsers refuse for module scripts.
_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".mjs": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
_IMMUTABLE = "public, max-age=31536000, immutable"


def media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _file_response(path: Path, cache_control: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type(path),
        headers={"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff"},
    )


def install_ui_routes(app: FastAPI, bundle: Path, *, canonical_origin: str | None = None) -> None:
    """Register the UI allowlist for ``bundle``, a Vite production build.

    With ``canonical_origin`` set, pages requested through another loopback
    name, such as ``localhost``, redirect there: browser-saved state belongs
    to one origin.
    """

    index = bundle / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"UI bundle has no index.html: {bundle}")
    asset_directory = bundle / "assets"
    assets = (
        {entry.name: entry for entry in asset_directory.iterdir() if entry.is_file()}
        if asset_directory.is_dir()
        else {}
    )
    canonical_host = canonical_origin.removeprefix("http://") if canonical_origin else None

    async def page(request: Request) -> Response:
        if canonical_host is not None and request.headers.get("host") != canonical_host:
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"{canonical_origin}{request.url.path}{query}", status_code=307)
        return _file_response(index, "no-store")

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        path = assets.get(name)
        if path is None:
            raise HTTPException(status_code=404)
        return _file_response(path, _IMMUTABLE if _HASHED_ASSET_NAME.fullmatch(name) else "no-cache")

    def public_file(path: Path):
        async def endpoint(request: Request) -> Response:
            return _file_response(path, "no-cache")

        return endpoint

    for route in sorted(UI_PAGE_ROUTES):
        app.add_route(route, page, methods=["GET"], include_in_schema=False)
    for route in sorted(UI_PUBLIC_FILES):
        path = bundle / route.removeprefix("/")
        if path.is_file():
            app.add_route(route, public_file(path), methods=["GET"], include_in_schema=False)
    app.add_route(UI_ASSET_ROUTE, asset, methods=["GET"], include_in_schema=False)
