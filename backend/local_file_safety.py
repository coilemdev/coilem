"""Containment checks for user-owned local run files."""

from pathlib import Path


def require_contained_path(root: Path, candidate: Path) -> Path:
    """Reject links, junctions and traversal below an explicitly trusted root.

    The root's ancestors may be OS aliases (for example macOS /tmp). This is
    protection against pre-existing links, not a sandbox against another process
    running as the same OS user and racing filesystem changes.
    """
    root = root.absolute()
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValueError("local file escapes its configured root") from exc
    if ".." in relative.parts:
        raise ValueError("local file path contains traversal")
    current = root
    for part in ("", *relative.parts):
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("linked local files and directories are unsupported")
    return candidate
