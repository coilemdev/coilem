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


def public_ui_origins() -> tuple[str, ...]:
    """Allow one explicit local UI port override, never a remote/wildcard origin."""
    extra = os.environ.get("COILEM_LOCAL_UI_ORIGIN")
    if extra is None:
        return DEFAULT_UI_ORIGINS
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
    return tuple(dict.fromkeys((*DEFAULT_UI_ORIGINS, extra)))


def public_request_rejection(request: Request, allowed_origins: tuple[str, ...]) -> tuple[int, str] | None:
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not is_loopback_authority(hosts[0]):
        return 400, "INVALID_LOCAL_HOST"
    origins = request.headers.getlist("origin")
    if origins:
        if len(origins) != 1 or origins[0] not in allowed_origins:
            return 403, "UNTRUSTED_ORIGIN"
    elif request.headers.get("sec-fetch-site", "").lower() in {"cross-site", "same-site"}:
        # Covers navigations and no-cors browser requests with no Origin header.
        return 403, "UNTRUSTED_BROWSER_REQUEST"
    return None
