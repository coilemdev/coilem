"""Environment policy for native solver execution.

The publication build fixes ISOLATED_RUNTIME to True. The private development
tree retains its diagnostic environment switches; they are never inherited by
the published application's native solver or its Python orchestration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, overload

ISOLATED_RUNTIME = True
POLICY_VERSION = "request-only-v1"
_OS_VARIABLES = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "TZ"})


@overload
def solver_setting(name: str, default: str) -> str: ...


@overload
def solver_setting(name: str, default: None = None) -> str | None: ...


def solver_setting(name: str, default: str | None = None) -> str | None:
    """Keep public numerical and orchestration defaults independent of the shell."""
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
