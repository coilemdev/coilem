"""Feature gates owned by the local application core."""

from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    """Parse an opt-in boolean environment variable."""

    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def thermal_enabled() -> bool:
    """Return whether private development thermal paths are explicitly on.

    Thermal is post-launch and therefore defaults off. The public release
    entry point does not mount thermal routes even if this private-development
    override is set.
    """

    return env_bool("OPENEM_THERMAL_ENABLED", False)
