"""Environment policy for native solver execution.

The publication build fixes ISOLATED_RUNTIME to True. Numerical diagnostic
switches stay excluded. A narrow disable-only override for Python process
pools provides a compatibility fallback without changing numerical settings
or the native solver's environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal, overload

ISOLATED_RUNTIME = True
POLICY_VERSION = "request-only-v1"
_OS_VARIABLES = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "TZ"})
_PROCESS_POOL_SWITCHES = {
    "mesh": "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
    "playback": "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL",
    "frames": "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL",
}
_DISABLE_VALUES = frozenset({"0", "false", "no", "off"})


def public_process_pool_disabled(pool: Literal["mesh", "playback", "frames"] | None = None) -> bool:
    """Accept only disabling a pool in the installed, isolated application.

    Development keeps its existing solver_setting behavior. In the public
    runtime, the shared switch disables every Python process pool; a specific switch
    disables only its pool. No shell value can force an unapproved pool on.
    These controls are never forwarded to the native solver.
    """
    if not ISOLATED_RUNTIME:
        return False
    names = ["COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL"]
    if pool is not None:
        names.append(_PROCESS_POOL_SWITCHES[pool])
    return any(os.environ.get(name, "").strip().lower() in _DISABLE_VALUES for name in names)


@overload
def solver_setting(name: str, default: str) -> str: ...


@overload
def solver_setting(name: str, default: None = None) -> str | None: ...


def solver_setting(name: str, default: str | None = None) -> str | None:
    """Keep numerical and diagnostic defaults independent of the shell."""
    return default if ISOLATED_RUNTIME else os.environ.get(name, default)


def solver_process_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """In the public runtime, only OS necessities and explicit run options pass."""
    environment = (
        {key: value for key, value in os.environ.items() if key.upper() in _OS_VARIABLES}
        if ISOLATED_RUNTIME else dict(os.environ)
    )
    environment.update(overrides or {})
    return environment


def solver_environment_provenance(overrides: Mapping[str, str]) -> dict[str, Any]:
    """Record request-derived options, never the user's environment or paths."""
    return {
        "policy": POLICY_VERSION if ISOLATED_RUNTIME else "inherited-development",
        "options": dict(sorted(overrides.items())),
    }
