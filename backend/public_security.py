"""Request provenance checks for the unauthenticated, local-only public API.

CORS controls response visibility, not whether a simple browser request runs.
Reject untrusted origins and rebinding hosts before any route can have effects.
Local command-line clients without browser headers remain supported.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from starlette.requests import Request

_LOOPBACK_AUTHORITY = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?", re.IGNORECASE)
DEFAULT_UI_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)


def is_loopback_authority(value: str) -> bool:
    match = _LOOPBACK_AUTHORITY.fullmatch(value)
    return match is not None and (match[1] is None or 1 <= int(match[1]) <= 65535)


def _configured_ui_origin() -> str | None:
    extra = os.environ.get("COILEM_LOCAL_UI_ORIGIN")
    if extra is None:
        return None
    try:
        parsed = urlsplit(extra)
        valid = (
            parsed.scheme == "http"
            and is_loopback_authority(parsed.netloc)
            and parsed.port is not None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and extra == f"http://{parsed.netloc}"
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("COILEM_LOCAL_UI_ORIGIN must be an HTTP loopback origin with a port and no path.")
    return extra


def public_ui_origins() -> tuple[str, ...]:
    """Allow one explicit local UI port override, never a remote/wildcard origin."""
    extra = _configured_ui_origin()
    return DEFAULT_UI_ORIGINS if extra is None else tuple(dict.fromkeys((*DEFAULT_UI_ORIGINS, extra)))


def bound_ui_origin(port: int) -> str:
    """The one origin the packaged launcher serves and opens; never ``localhost``."""
    return f"http://127.0.0.1:{port}"


def launcher_ui_origins(port: int) -> tuple[str, ...]:
    """The launcher trusts its own origin, not the development UI ports.

    An explicit ``COILEM_LOCAL_UI_ORIGIN`` is still honored.
    """
    extra = _configured_ui_origin()
    return tuple(dict.fromkeys((bound_ui_origin(port), *((extra,) if extra else ()))))


def public_request_rejection(
    request: Request,
    allowed_origins: tuple[str, ...],
    *,
    host_port: int | None = None,
) -> tuple[int, str] | None:
    """Return ``(status, error_code)`` for an untrusted request, else ``None``.

    ``host_port`` pins the ``Host`` port to the launcher's bound socket.
    """
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not is_loopback_authority(hosts[0]):
        return 400, "INVALID_LOCAL_HOST"
    if host_port is not None:
        match = _LOOPBACK_AUTHORITY.fullmatch(hosts[0])
        if match is None or match[1] is None or int(match[1]) != host_port:
            return 400, "INVALID_LOCAL_HOST"
    origins = request.headers.getlist("origin")
    if origins:
        if len(origins) != 1 or origins[0] not in allowed_origins:
            return 403, "UNTRUSTED_ORIGIN"
    elif request.headers.get("sec-fetch-site", "").lower() in {"cross-site", "same-site"}:
        # Covers navigations and no-cors browser requests with no Origin header.
        return 403, "UNTRUSTED_BROWSER_REQUEST"
    return None
