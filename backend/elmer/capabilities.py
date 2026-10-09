"""Deterministic discovery and provenance for external Elmer executables."""

from __future__ import annotations

import hashlib
import importlib
import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

from .errors import ElmerUnavailableError

ELMER_SOLVER_BINARY = "ElmerSolver"
ELMER_GRID_BINARY = "ElmerGrid"
ELMER_HOME_ENV = "COILEM_ELMER_HOME"
ELMER_ALLOW_UNQUALIFIED_ENV = "COILEM_ELMER_ALLOW_UNQUALIFIED"
QUALIFIED_RUNTIME_RELEASE = "26.2"
DEFAULT_USER_INSTALL = Path.home() / ".local" / "openem-elmer" / QUALIFIED_RUNTIME_RELEASE

_VERSION_RE = re.compile(r"\bVersion\s*:\s*([^\s,(]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ElmerCapabilities:
    available: bool
    qualified: bool
    solver_path: str | None
    grid_path: str | None
    solver_version: str | None
    grid_version: str | None
    platform: str
    architecture: str
    solver_sha256: str | None = None
    grid_sha256: str | None = None
    reason: str | None = None
    adapter_ready: bool = True
    gmsh_available: bool = True
    meshio_available: bool = True
    dependency_reason: str | None = None

    def require_available(self, *, qualified: bool = True) -> "ElmerCapabilities":
        if not self.available:
            raise ElmerUnavailableError(self.reason or "Elmer is unavailable")
        if qualified and not self.qualified:
            raise ElmerUnavailableError(
                self.reason or f"Elmer {self.solver_version or 'unknown'} is not qualified"
            )
        if not self.adapter_ready:
            raise ElmerUnavailableError(
                self.dependency_reason
                or self.reason
                or "Elmer's Python mesh adapter dependencies are unavailable"
            )
        return self

    def health_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mesh_converter_available"] = self.grid_path is not None
        payload["profile"] = "openem_elmer_motor_2d/v1"
        return payload

    def safe_health_payload(self) -> dict[str, object]:
        """Return capability details that are safe for unauthenticated health routes."""

        payload = self.health_payload()
        for local_only_key in (
            "solver_path",
            "grid_path",
            "solver_sha256",
            "grid_sha256",
        ):
            payload.pop(local_only_key, None)
        return payload


def _adapter_dependency_status() -> tuple[bool, bool, str | None]:
    """Probe Python-side dependencies needed after binary discovery.

    Importing the modules, rather than checking package metadata alone, also
    catches missing native Gmsh libraries. Error text is intentionally reduced
    to module and exception type so the public health route cannot expose local
    filesystem paths from an import failure.
    """

    availability: dict[str, bool] = {}
    failures: list[str] = []
    for module_name in ("gmsh", "meshio"):
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - exact native import errors vary by host
            availability[module_name] = False
            failures.append(f"{module_name} ({type(exc).__name__})")
        else:
            availability[module_name] = True
    reason = (
        "Missing or unloadable Elmer adapter dependencies: " + ", ".join(failures)
        if failures
        else None
    )
    return availability["gmsh"], availability["meshio"], reason


def _with_adapter_readiness(capabilities: ElmerCapabilities) -> ElmerCapabilities:
    gmsh_available, meshio_available, dependency_reason = _adapter_dependency_status()
    adapter_ready = bool(
        capabilities.available and gmsh_available and meshio_available
    )
    return replace(
        capabilities,
        adapter_ready=adapter_ready,
        gmsh_available=gmsh_available,
        meshio_available=meshio_available,
        dependency_reason=dependency_reason,
        reason=(
            capabilities.reason
            or (dependency_reason if capabilities.available else None)
        ),
    )

def _candidate_binary(home: str | Path | None, name: str) -> str | None:
    if home:
        root = Path(home).expanduser()
        names = [name]
        if os.name == "nt":
            extensions = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
            names.extend(f"{name}{extension.lower()}" for extension in extensions if extension)
        candidates = tuple(
            directory / candidate_name
            for directory in (root / "bin", root)
            for candidate_name in names
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        return None
    resolved = shutil.which(name)
    return str(Path(resolved).resolve()) if resolved else None


def _probe_version(path: str) -> str | None:
    try:
        completed = subprocess.run(
            [path],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = f"{completed.stdout}\n{completed.stderr}"
    match = _VERSION_RE.search(output)
    return match.group(1) if match else None


def _sha256(path: str | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _binary_cache_key(path: str) -> tuple[str, int, int]:
    """Key executable inspection by resolved path and on-disk identity."""

    try:
        stat = Path(path).stat()
    except OSError:
        return path, -1, -1
    return path, stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=16)
def _inspect_elmer_pair(
    solver_key: tuple[str, int, int],
    grid_key: tuple[str, int, int],
    *,
    allow_unqualified: bool,
    system: str,
    machine: str,
) -> ElmerCapabilities:
    """Probe and hash an unchanged runtime pair once across health polls."""

    solver_path = solver_key[0]
    grid_path = grid_key[0]
    solver_version = _probe_version(solver_path)
    grid_version = _probe_version(grid_path)
    solver_release = solver_version.split("-", 1)[0] if solver_version else None
    grid_release = grid_version.split("-", 1)[0] if grid_version else None
    qualified = bool(
        solver_release == QUALIFIED_RUNTIME_RELEASE
        and grid_release == QUALIFIED_RUNTIME_RELEASE
    )
    reason = None
    if solver_version is None:
        reason = f"Could not determine ElmerSolver version from {solver_path}"
    elif grid_version is None:
        reason = f"Could not determine ElmerGrid version from {grid_path}"
    elif not qualified and not allow_unqualified:
        reason = (
            f"Elmer runtime pair solver={solver_version}, grid={grid_version} "
            f"does not match qualified release {QUALIFIED_RUNTIME_RELEASE}"
        )
    return ElmerCapabilities(
        available=True,
        qualified=qualified or allow_unqualified,
        solver_path=solver_path,
        grid_path=grid_path,
        solver_version=solver_version,
        grid_version=grid_version,
        platform=system,
        architecture=machine,
        solver_sha256=_sha256(solver_path),
        grid_sha256=_sha256(grid_path),
        reason=reason,
    )


def discover_elmer(*, configured_home: str | Path | None = None) -> ElmerCapabilities:
    """Discover both required executables without importing Elmer libraries."""

    home = configured_home or os.environ.get(ELMER_HOME_ENV)
    if home:
        solver_path = _candidate_binary(home, ELMER_SOLVER_BINARY)
        grid_path = _candidate_binary(home, ELMER_GRID_BINARY)
    else:
        default_solver = _candidate_binary(DEFAULT_USER_INSTALL, ELMER_SOLVER_BINARY)
        default_grid = _candidate_binary(DEFAULT_USER_INSTALL, ELMER_GRID_BINARY)
        if default_solver or default_grid:
            home = DEFAULT_USER_INSTALL
            solver_path = default_solver
            grid_path = default_grid
        else:
            solver_path = _candidate_binary(None, ELMER_SOLVER_BINARY)
            grid_path = _candidate_binary(None, ELMER_GRID_BINARY)
    system = platform.system()
    machine = platform.machine()
    if not solver_path or not grid_path:
        missing = [
            name
            for name, path in ((ELMER_SOLVER_BINARY, solver_path), (ELMER_GRID_BINARY, grid_path))
            if path is None
        ]
        source = f" under {home}" if home else " on PATH"
        return _with_adapter_readiness(
            ElmerCapabilities(
                available=False,
                qualified=False,
                solver_path=solver_path,
                grid_path=grid_path,
                solver_version=None,
                grid_version=None,
                platform=system,
                architecture=machine,
                reason=f"Missing {', '.join(missing)}{source}",
            )
        )

    allow_unqualified = os.environ.get(ELMER_ALLOW_UNQUALIFIED_ENV, "").strip() == "1"
    return _with_adapter_readiness(
        _inspect_elmer_pair(
            _binary_cache_key(solver_path),
            _binary_cache_key(grid_path),
            allow_unqualified=allow_unqualified,
            system=system,
            machine=machine,
        )
    )
