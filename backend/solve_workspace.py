"""Durable, local solve-run storage for the public coilEM application.

The solver cache is disposable implementation detail.  This module owns the
user-facing run record under an OS-appropriate data directory and only exposes
completed runs after every required file has been written successfully.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend import __version__
from backend.custom_materials import CustomSteel
from backend.field_artifacts import resolve_solve_cache_artifact_id
from backend.material_contract import electrical_steel_preflight_records
from backend.public_report import (
    build_public_run_csv,
    build_public_run_pdf,
    write_replayable_run_package,
)

RUN_MANIFEST_SCHEMA = "coilem.solve_run.v2"
RUN_REQUEST_SCHEMA = "coilem.solve_request.v1"
PROJECT_SCHEMA_VERSION = 4
RUN_ARTIFACT_PREFIX = "run."
DEFAULT_RETENTION_RUNS_PER_PROJECT = 25
DEFAULT_WORKSPACE_MAX_BYTES = 10 * 1024 * 1024 * 1024

_SAFE_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ACTIVE_RUNS_LOCK = threading.Lock()
_ACTIVE_PARTIAL_RUNS: set[Path] = set()


class SolveWorkspaceError(RuntimeError):
    """Raised when a durable solve run cannot be stored or resolved safely."""


class SolveWorkspaceCapacityError(SolveWorkspaceError):
    """Raised when retained local runs have filled the configured workspace."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(payload: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(payload))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size_bytes(path: Path) -> int:
    total = 0
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file() and _inside(path, candidate):
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


def _slug(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    cleaned = cleaned.strip("._-")
    return (cleaned or fallback)[:96]


def _validate_segment(value: str, *, label: str) -> str:
    if not _SAFE_SEGMENT_RE.fullmatch(value):
        raise SolveWorkspaceError(f"invalid {label}")
    return value


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _register_active_partial(path: Path) -> None:
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_PARTIAL_RUNS.add(path.resolve())


def _unregister_active_partial(path: Path) -> None:
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_PARTIAL_RUNS.discard(path.resolve())


def _is_active_partial(path: Path) -> bool:
    with _ACTIVE_RUNS_LOCK:
        return path.resolve() in _ACTIVE_PARTIAL_RUNS


def _atomic_write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_bytes(
        path,
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
        + b"\n",
    )


def user_data_root() -> Path:
    """Return coilEM's durable data root without touching the filesystem."""

    override = os.environ.get("COILEM_USER_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system()
    if system == "Darwin":
        return (Path.home() / "Library" / "Application Support" / "coilEM").resolve()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
        return (base / "coilEM").resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return (base / "coilem").resolve()


def _application_commit() -> str:
    configured = os.environ.get("COILEM_BUILD_COMMIT")
    if configured:
        return configured.strip()
    repo_root = Path(__file__).resolve().parents[1]
    snapshot_manifest = repo_root / "snapshot-manifest.json"
    try:
        snapshot_commit = json.loads(snapshot_manifest.read_text(encoding="utf-8")).get("source_commit")
    except (OSError, json.JSONDecodeError):
        snapshot_commit = None
    if isinstance(snapshot_commit, str) and re.fullmatch(r"[0-9a-f]{40}", snapshot_commit):
        return snapshot_commit
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _material_records(config: Mapping[str, Any]) -> list[dict[str, object]]:
    materials = config.get("materials")
    if not isinstance(materials, Mapping):
        return []
    roles = {
        "stator": str(materials.get("stator_steel", "")),
        "rotor": str(materials.get("rotor_steel", "")),
    }
    records = electrical_steel_preflight_records(
        roles,
        consumer="coilem.solve_workspace",
    )
    custom = materials.get("custom_steels", {})
    for material_id in sorted(set(roles.values())):
        if material_id.startswith("custom:"):
            material = CustomSteel.model_validate(custom.get(material_id))
            record = material.preflight_record([role for role, key in roles.items() if key == material_id])
            record["consumer"] = "coilem.solve_workspace"
            records.append(record)
    return records


def _project_payload(config: Mapping[str, Any], project_name: str) -> dict[str, Any]:
    return {
        "openem_schema_version": PROJECT_SCHEMA_VERSION,
        "openem_version": __version__,
        "name": project_name.removesuffix(".openem"),
        **deepcopy(dict(config)),
    }


def _encode_run_artifact_id(project_slug: str, run_id: str, relative_path: str) -> str:
    payload = json.dumps(
        [project_slug, run_id, relative_path],
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{RUN_ARTIFACT_PREFIX}{token}"


def _decode_run_artifact_id(artifact_id: str) -> tuple[str, str, str]:
    if not artifact_id.startswith(RUN_ARTIFACT_PREFIX):
        raise SolveWorkspaceError("invalid run artifact id")
    token = artifact_id.removeprefix(RUN_ARTIFACT_PREFIX)
    try:
        padded = token + ("=" * (-len(token) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SolveWorkspaceError("invalid run artifact id") from exc
    if not (isinstance(payload, list) and len(payload) == 3 and all(isinstance(value, str) for value in payload)):
        raise SolveWorkspaceError("invalid run artifact id")
    return payload[0], payload[1], payload[2]


@dataclass(frozen=True)
class RunLocation:
    project_slug: str
    run_id: str
    path: Path
    completed_at: str | None = None

    def public_record(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_MANIFEST_SCHEMA,
            "project_slug": self.project_slug,
            "run_id": self.run_id,
            "path": str(self.path),
            "completed_at": self.completed_at,
        }


class SolveRunWriter:
    """Build one run in a hidden partial directory, then publish atomically."""

    def __init__(
        self,
        workspace: SolveWorkspace,
        *,
        project_name: str,
        config: Mapping[str, Any],
        submitted_request: Mapping[str, Any],
    ) -> None:
        self.workspace = workspace
        self.project_name = project_name.strip() or "Untitled"
        self.project_slug = _slug(self.project_name.removesuffix(".openem"), fallback="untitled")
        self.config = deepcopy(dict(config))
        self.submitted_request = deepcopy(dict(submitted_request))
        self.started_at = _utc_text()
        self.application_commit = _application_commit()
        self.run_id, self.partial_path, self.final_path = workspace._allocate_run_paths(self.project_slug)
        self._closed = False
        self._artifact_records: list[dict[str, Any]] = []

        self.partial_path.mkdir(parents=True, exist_ok=False)
        _register_active_partial(self.partial_path)
        try:
            _atomic_write_json(
                self.partial_path / "manifest.json",
                self._manifest(status="running"),
            )
            _atomic_write_json(
                self.partial_path / "project.openem",
                _project_payload(self.config, self.project_name),
            )
            _atomic_write_json(
                self.partial_path / "request.json",
                {
                    "schema_version": RUN_REQUEST_SCHEMA,
                    "submitted": self.submitted_request,
                    "resolved_config": self.config,
                },
            )
        except BaseException:
            _unregister_active_partial(self.partial_path)
            raise

    def _mark_closed(self) -> None:
        self._closed = True
        _unregister_active_partial(self.partial_path)

    def _manifest(
        self,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
        material_records: list[dict[str, object]] | None = None,
        failure: Mapping[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        project = _project_payload(self.config, self.project_name)
        request = {
            "schema_version": RUN_REQUEST_SCHEMA,
            "submitted": self.submitted_request,
            "resolved_config": self.config,
        }
        material_records = material_records or []
        solver_name = ""
        if result is not None and isinstance(result.get("solve_metadata"), Mapping):
            solver_name = str(result["solve_metadata"].get("solver_name", ""))
        bindings: dict[str, str] = {
            "project_sha256": _sha256_json(project),
            "resolved_request_sha256": _sha256_json(request),
            "material_sha256": _sha256_json(material_records),
            "application_commit_sha256": _sha256_bytes(self.application_commit.encode("utf-8")),
        }
        if result is not None:
            bindings["result_sha256"] = _sha256_json(result)
            bindings["solver_version_sha256"] = _sha256_bytes(solver_name.encode("utf-8"))
        solve_params = self.config.get("solve_params")
        solve_params = solve_params if isinstance(solve_params, Mapping) else {}
        excitation_mode = str(solve_params.get("excitation_mode") or "sinusoidal")
        excitation_provenance = {
            "mode": excitation_mode,
            "current_amplitude_A": solve_params.get("current_amplitude_A"),
            "current_amplitude_convention": solve_params.get(
                "current_amplitude_convention"
            ),
            "commutation_advance_deg": (
                solve_params.get("commutation_advance_deg")
                if excitation_mode == "ideal_six_step_120"
                else None
            ),
            "phase_connection": (
                solve_params.get("phase_connection")
                if excitation_mode == "ideal_six_step_120"
                else None
            ),
        }

        manifest: dict[str, Any] = {
            "schema_version": RUN_MANIFEST_SCHEMA,
            "status": status,
            "project_name": self.project_name,
            "project_slug": self.project_slug,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": (completed_at or _utc_text() if status == "complete" else None),
            "files": {
                "project": "project.openem",
                "request": "request.json",
                "result": "result.json" if result is not None else None,
                "material": "material.json" if material_records else None,
                "report": "report/summary.json" if result is not None else None,
                "pdf": "report/report.pdf" if result is not None else None,
                "csv": "report/report.csv" if result is not None else None,
                "package": "report/run-package.zip" if result is not None else None,
            },
            "artifacts": self._artifact_records,
            "provenance": {
                "application_version": __version__,
                "application_commit": self.application_commit,
                "solver_name": solver_name or None,
                "excitation": excitation_provenance,
                "platform": {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                },
            },
            "bindings": bindings,
            "retention": {
                "policy": "manual_or_keep_latest_per_project",
                "default_keep_latest": DEFAULT_RETENTION_RUNS_PER_PROJECT,
                "solve_cache_is_disposable": True,
            },
            "result_current": False,
            "result_current_reason": (
                "Stored results are immutable evidence. Load the project and start an explicit new solve to establish a current result."
            ),
        }
        if failure:
            manifest["failure"] = dict(failure)
        return manifest

    def _retain_artifacts(self, result: dict[str, Any]) -> None:
        copied: dict[str, tuple[str, str]] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                artifact_id = value.get("artifact_id")
                if isinstance(artifact_id, str) and artifact_id and not artifact_id.startswith(RUN_ARTIFACT_PREFIX):
                    try:
                        source = resolve_solve_cache_artifact_id(artifact_id)
                    except ValueError:
                        source = None
                    if source is not None and source.is_file():
                        source_key = str(source.resolve())
                        retained = copied.get(source_key)
                        if retained is None:
                            suffixes = "".join(source.suffixes[-2:]) or ".bin"
                            source_hash = _sha256_file(source)
                            relative = f"artifacts/{len(copied) + 1:04d}-{source_hash[:12]}{suffixes}"
                            target = self.partial_path / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
                            retained_id = _encode_run_artifact_id(
                                self.project_slug,
                                self.run_id,
                                relative,
                            )
                            retained = (relative, retained_id)
                            copied[source_key] = retained
                            self._artifact_records.append(
                                {
                                    "relative_path": relative,
                                    "sha256": _sha256_file(target),
                                    "size_bytes": target.stat().st_size,
                                }
                            )
                        value["artifact_id"] = retained[1]
                        value["relative_path"] = retained[0]
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(result)

    def complete(self, result: Mapping[str, Any]) -> RunLocation:
        if self._closed:
            raise SolveWorkspaceError("solve run writer is already closed")
        stored_result = deepcopy(dict(result))
        self._retain_artifacts(stored_result)
        materials = _material_records(self.config)
        project = _project_payload(self.config, self.project_name)
        request = {
            "schema_version": RUN_REQUEST_SCHEMA,
            "submitted": self.submitted_request,
            "resolved_config": self.config,
        }
        material = {
            "schema_version": "coilem.solve_materials.v1",
            "records": materials,
        }
        completed_at = _utc_text()
        manifest = self._manifest(
            status="complete",
            result=stored_result,
            material_records=materials,
            completed_at=completed_at,
        )

        _atomic_write_json(self.partial_path / "result.json", stored_result)
        _atomic_write_json(self.partial_path / "material.json", material)
        report = {
            "schema_version": "coilem.solve_report_summary.v1",
            "project_name": self.project_name,
            "run_id": self.run_id,
            "completed_at": completed_at,
            "material_records": materials,
            "summary": stored_result.get("summary"),
            "solve_metadata": stored_result.get("solve_metadata"),
        }
        _atomic_write_json(self.partial_path / "report" / "summary.json", report)
        report_arguments = {
            "project": project,
            "request": request,
            "result": stored_result,
            "material": material,
            "manifest": manifest,
        }
        pdf_bytes = build_public_run_pdf(**report_arguments)
        csv_bytes = build_public_run_csv(**report_arguments)
        _atomic_write_bytes(
            self.partial_path / "report" / "report.pdf",
            pdf_bytes,
        )
        _atomic_write_bytes(self.partial_path / "report" / "report.csv", csv_bytes)
        manifest["exports"] = {
            "schema_version": "coilem.solve_exports.v1",
            "source": "immutable_stored_run",
            "pdf_sha256": _sha256_bytes(pdf_bytes),
            "csv_sha256": _sha256_bytes(csv_bytes),
            # The archive contains this manifest, so its own byte hash cannot
            # be embedded without a circular dependency.  The package copy
            # records this field as null; the authoritative on-disk manifest
            # is finalized with the archive hash immediately afterward.
            "package_sha256": None,
            "deterministic_except_stored_run_timestamps": True,
        }
        _atomic_write_json(self.partial_path / "manifest.json", manifest)
        package_path = self.partial_path / "report" / "run-package.zip"
        write_replayable_run_package(
            self.partial_path,
            package_path,
            completed_at=completed_at,
        )
        manifest["exports"]["package_sha256"] = _sha256_file(package_path)
        _atomic_write_json(self.partial_path / "manifest.json", manifest)
        if self.workspace.usage_bytes() > self.workspace.max_bytes:
            for generated in (
                self.partial_path / "artifacts",
                self.partial_path / "report",
            ):
                if generated.is_dir():
                    shutil.rmtree(generated)
            for generated in (
                self.partial_path / "result.json",
                self.partial_path / "material.json",
            ):
                try:
                    generated.unlink()
                except FileNotFoundError:
                    pass
            self._artifact_records.clear()
            self.fail(
                error_code="RUN_STORAGE_LIMIT",
                message=(
                    "The durable solve workspace reached its configured size limit. Delete an older run or raise COILEM_SOLVE_WORKSPACE_MAX_BYTES."
                ),
            )
            raise SolveWorkspaceCapacityError(
                "durable solve workspace size limit exceeded"
            )
        os.replace(self.partial_path, self.final_path)
        self._mark_closed()
        return RunLocation(
            project_slug=self.project_slug,
            run_id=self.run_id,
            path=self.final_path,
            completed_at=completed_at,
        )

    def fail(
        self,
        *,
        error_code: str,
        message: str,
        cancelled: bool = False,
    ) -> None:
        if self._closed:
            return
        try:
            _atomic_write_json(
                self.partial_path / "manifest.json",
                self._manifest(
                    status="cancelled" if cancelled else "failed",
                    failure={
                        "error_code": error_code,
                        "message": message,
                        "recorded_at": _utc_text(),
                    },
                ),
            )
        finally:
            self._mark_closed()


class SolveWorkspace:
    """Resolve and manage durable runs below one configured data root."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        max_bytes: int | None = None,
    ) -> None:
        self.root = (root or user_data_root()).expanduser().resolve()
        self.solves_root = self.root / "solves"
        if max_bytes is None:
            configured = os.environ.get("COILEM_SOLVE_WORKSPACE_MAX_BYTES")
            try:
                max_bytes = int(configured) if configured else DEFAULT_WORKSPACE_MAX_BYTES
            except ValueError as exc:
                raise SolveWorkspaceError("COILEM_SOLVE_WORKSPACE_MAX_BYTES must be an integer") from exc
        if max_bytes <= 0:
            raise SolveWorkspaceError("durable solve workspace size limit must be positive")
        self.max_bytes = max_bytes

    def usage_bytes(self) -> int:
        self._require_safe_path(self.solves_root)
        if not self.solves_root.is_dir():
            return 0
        return _directory_size_bytes(self.solves_root)

    def storage_policy(self) -> dict[str, Any]:
        used = self.usage_bytes()
        return {
            "max_bytes": self.max_bytes,
            "used_bytes": used,
            "available_bytes": max(0, self.max_bytes - used),
            "accepting_new_runs": used < self.max_bytes,
            "automatic_durable_run_deletion": False,
            "recommended_keep_latest_per_project": (DEFAULT_RETENTION_RUNS_PER_PROJECT),
        }

    def begin_run(
        self,
        *,
        project_name: str,
        config: Mapping[str, Any],
        submitted_request: Mapping[str, Any],
    ) -> SolveRunWriter:
        self._require_safe_path(self.solves_root)
        self.solves_root.mkdir(parents=True, exist_ok=True)
        if self.usage_bytes() >= self.max_bytes:
            raise SolveWorkspaceCapacityError(
                "durable solve workspace size limit reached; delete an older run before solving"
            )
        return SolveRunWriter(
            self,
            project_name=project_name,
            config=config,
            submitted_request=submitted_request,
        )

    def _allocate_run_paths(self, project_slug: str) -> tuple[str, Path, Path]:
        _validate_segment(project_slug, label="project")
        project_root = self.solves_root / project_slug
        self._require_safe_path(project_root)
        project_root.mkdir(parents=True, exist_ok=True)
        for _ in range(20):
            timestamp = _utc_now().strftime("%Y%m%dt%H%M%S%fz")
            run_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
            final = project_root / run_id
            partial = project_root / f".{run_id}.partial"
            if not final.exists() and not partial.exists():
                return run_id, partial, final
        raise SolveWorkspaceError("could not allocate a unique solve run id")

    def _require_safe_path(self, candidate: Path) -> None:
        from backend.local_file_safety import require_contained_path

        try:
            require_contained_path(self.root, candidate)
        except ValueError as exc:
            raise SolveWorkspaceError("solve workspace contains an unsafe linked path") from exc

    def resolve_run(
        self,
        project_slug: str,
        run_id: str,
        *,
        include_partial: bool = False,
    ) -> Path:
        project_slug = _validate_segment(project_slug, label="project")
        run_id = _validate_segment(run_id, label="run id")
        project_root = self.solves_root / project_slug
        candidates = [project_root / run_id]
        if include_partial:
            candidates.append(project_root / f".{run_id}.partial")
        for candidate in candidates:
            if candidate.is_dir() and _inside(self.solves_root, candidate):
                self._require_safe_path(candidate)
                return candidate.resolve()
        raise FileNotFoundError("solve run not found")

    def resolve_artifact(
        self,
        project_slug: str,
        run_id: str,
        relative_path: str,
    ) -> Path:
        run = self.resolve_run(project_slug, run_id)
        relative = Path(relative_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise SolveWorkspaceError("invalid artifact path")
        candidate = run / relative
        self._require_safe_path(candidate)
        candidate = candidate.resolve()
        if not _inside(run, candidate) or not candidate.is_file():
            raise FileNotFoundError("run artifact not found")
        return candidate

    def load_run(self, project_slug: str, run_id: str) -> dict[str, Any]:
        run = self.resolve_run(project_slug, run_id)

        def read_json(name: str) -> Any:
            path = self.resolve_artifact(project_slug, run_id, name)
            return json.loads(path.read_text(encoding="utf-8"))

        manifest = read_json("manifest.json")
        if manifest.get("status") != "complete":
            raise SolveWorkspaceError("solve run is not complete")
        project = read_json("project.openem")
        request = read_json("request.json")
        result = read_json("result.json")
        material = read_json("material.json")
        material_records = material.get("records", [])
        solver_name = ""
        if isinstance(result.get("solve_metadata"), Mapping):
            solver_name = str(result["solve_metadata"].get("solver_name", ""))
        provenance = manifest.get("provenance", {})
        application_commit = str(provenance.get("application_commit", "")) if isinstance(provenance, Mapping) else ""
        observed_bindings = {
            "project_sha256": _sha256_json(project),
            "resolved_request_sha256": _sha256_json(request),
            "material_sha256": _sha256_json(material_records),
            "result_sha256": _sha256_json(result),
            "solver_version_sha256": _sha256_bytes(solver_name.encode("utf-8")),
            "application_commit_sha256": _sha256_bytes(application_commit.encode("utf-8")),
        }
        expected_bindings = manifest.get("bindings", {})
        binding_mismatches = [
            key for key, observed in observed_bindings.items() if not isinstance(expected_bindings, Mapping) or expected_bindings.get(key) != observed
        ]
        artifact_mismatches: list[str] = []
        artifacts = manifest.get("artifacts", [])
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, Mapping):
                    artifact_mismatches.append("invalid artifact record")
                    continue
                relative = artifact.get("relative_path")
                expected_hash = artifact.get("sha256")
                if not isinstance(relative, str) or not isinstance(expected_hash, str):
                    artifact_mismatches.append("invalid artifact record")
                    continue
                try:
                    artifact_path = self.resolve_artifact(
                        project_slug,
                        run_id,
                        relative,
                    )
                    observed_hash = _sha256_file(artifact_path)
                except (FileNotFoundError, OSError, SolveWorkspaceError):
                    observed_hash = ""
                if observed_hash != expected_hash:
                    artifact_mismatches.append(relative)
        export_mismatches: list[str] = []
        files = manifest.get("files")
        export_bindings = manifest.get("exports")
        if isinstance(files, Mapping) and isinstance(export_bindings, Mapping):
            for export_name in ("pdf", "csv", "package"):
                relative = files.get(export_name)
                expected_hash = export_bindings.get(f"{export_name}_sha256")
                if not isinstance(relative, str) or not isinstance(expected_hash, str):
                    export_mismatches.append(export_name)
                    continue
                try:
                    export_path = self.resolve_artifact(
                        project_slug,
                        run_id,
                        relative,
                    )
                    observed_hash = _sha256_file(export_path)
                except (FileNotFoundError, OSError, SolveWorkspaceError):
                    observed_hash = ""
                if observed_hash != expected_hash:
                    export_mismatches.append(export_name)

        input_changes: list[str] = []
        if application_commit != _application_commit():
            input_changes.append("application_commit")
        resolved_config = request.get("resolved_config")
        if isinstance(resolved_config, Mapping):
            try:
                current_material_hash = _sha256_json(_material_records(resolved_config))
            except Exception:
                current_material_hash = ""
            if current_material_hash != observed_bindings["material_sha256"]:
                input_changes.append("material_curve")
        return {
            "schema_version": RUN_MANIFEST_SCHEMA,
            "manifest": manifest,
            "project": project,
            "request": request,
            "result": result,
            "saved_run": RunLocation(
                project_slug,
                run_id,
                run,
                completed_at=(str(manifest.get("completed_at")) if manifest.get("completed_at") else None),
            ).public_record(),
            "integrity": {
                "valid": (not binding_mismatches and not artifact_mismatches and not export_mismatches),
                "binding_mismatches": binding_mismatches,
                "artifact_mismatches": artifact_mismatches,
                "export_mismatches": export_mismatches,
            },
            "freshness": {
                "result_current": False,
                "changed_bound_inputs": input_changes,
                "requires_explicit_solve": True,
            },
        }

    def load_run_comparison(self, project_slug: str, run_id: str) -> dict[str, Any]:
        """Load the compact, immutable subset used by the public comparison UI."""

        loaded = self.load_run(project_slug, run_id)
        integrity = loaded.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("valid") is not True:
            raise SolveWorkspaceError(
                "The stored run failed its integrity check and cannot be compared."
            )

        run = Path(loaded["saved_run"]["path"])
        manifest = loaded["manifest"]
        if not isinstance(manifest, Mapping):
            raise SolveWorkspaceError("The stored run manifest is invalid.")

        report_summary = json.loads(
            self.resolve_artifact(project_slug, run_id, "report/summary.json").read_text(encoding="utf-8")
        )
        waveforms: dict[str, dict[str, dict[int, float]]] = {
            "torque_waveform": {},
            "back_emf_waveform": {},
            "cogging_waveform": {},
        }
        with self.resolve_artifact(project_slug, run_id, "report/report.csv").open(
            "r",
            encoding="utf-8",
            newline="",
        ) as report_csv:
            next(report_csv, None)  # report schema preamble
            for row in csv.DictReader(report_csv):
                section = row.get("section", "")
                if section not in waveforms:
                    continue
                field = row.get("field", "")
                try:
                    sample_index = int(row.get("sample_index", ""))
                    value = float(row.get("value", ""))
                except (TypeError, ValueError):
                    continue
                waveforms[section].setdefault(field, {})[sample_index] = value

        compact_waveforms: dict[str, dict[str, list[float]]] = {}
        for section, fields in waveforms.items():
            result_field = (
                "cogging_torque_waveform"
                if section == "cogging_waveform"
                else section
            )
            compact_waveforms[result_field] = {
                field: [values[index] for index in sorted(values)]
                for field, values in fields.items()
            }

        return {
            "schema_version": RUN_MANIFEST_SCHEMA,
            "project_name": manifest.get("project_name"),
            "result": {
                "summary": report_summary.get("summary", {}),
                "solve_metadata": report_summary.get("solve_metadata", {}),
                **compact_waveforms,
            },
            "saved_run": RunLocation(
                project_slug,
                run_id,
                run,
                completed_at=(
                    str(manifest.get("completed_at"))
                    if manifest.get("completed_at")
                    else None
                ),
            ).public_record(),
        }

    def resolve_export(
        self,
        project_slug: str,
        run_id: str,
        export_name: str,
    ) -> Path:
        """Resolve a verified export from an exact, complete run schema."""

        if export_name not in {"pdf", "csv", "package"}:
            raise SolveWorkspaceError("unsupported run export")
        loaded = self.load_run(project_slug, run_id)
        manifest = loaded["manifest"]
        if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA:
            raise SolveWorkspaceError(
                "This stored run uses an older manifest. Open its project and start a new analysis to migrate it before exporting."
            )
        integrity = loaded.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("valid") is not True:
            raise SolveWorkspaceError(
                "The stored run failed its integrity check. Restore the missing artifact or start a new analysis before exporting."
            )
        files = manifest.get("files")
        relative = files.get(export_name) if isinstance(files, Mapping) else None
        if not isinstance(relative, str):
            raise SolveWorkspaceError(
                f"This stored run has no {export_name} export. Open its project and start a new analysis to create the current export set."
            )
        try:
            return self.resolve_artifact(project_slug, run_id, relative)
        except FileNotFoundError as exc:
            raise SolveWorkspaceError(
                f"The stored {export_name} export is missing. Open the project and start a new analysis to rebuild the immutable run."
            ) from exc

    def list_runs(self, *, include_partial: bool = True) -> list[dict[str, Any]]:
        self._require_safe_path(self.solves_root)
        if not self.solves_root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for project_root in self.solves_root.iterdir():
            if not project_root.is_dir() or not _SAFE_SEGMENT_RE.fullmatch(project_root.name) or not _inside(self.solves_root, project_root):
                continue
            for run in project_root.iterdir():
                is_partial = run.name.startswith(".") and run.name.endswith(".partial")
                if is_partial and not include_partial:
                    continue
                if not run.is_dir() or not _inside(self.solves_root, run):
                    continue
                run_id = run.name[1:-8] if is_partial else run.name
                if not _SAFE_SEGMENT_RE.fullmatch(run_id):
                    continue
                manifest_path = run / "manifest.json"
                try:
                    self._require_safe_path(manifest_path)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, SolveWorkspaceError):
                    continue
                provenance = manifest.get("provenance")
                solver_name = (
                    provenance.get("solver_name")
                    if isinstance(provenance, Mapping)
                    else None
                )
                record = {
                    "project_slug": project_root.name,
                    "run_id": run_id,
                    "path": str(run.resolve()),
                    "size_bytes": _directory_size_bytes(run),
                    "status": manifest.get("status", "unknown"),
                    "project_name": manifest.get("project_name"),
                    "started_at": manifest.get("started_at"),
                    "completed_at": manifest.get("completed_at"),
                }
                if isinstance(solver_name, str) and solver_name:
                    record["solver_name"] = solver_name
                records.append(record)
        return sorted(
            records,
            key=lambda record: str(record.get("started_at") or ""),
            reverse=True,
        )

    def delete_run(
        self,
        project_slug: str,
        run_id: str,
        *,
        confirmation: str,
    ) -> None:
        if confirmation != run_id:
            raise SolveWorkspaceError("run deletion confirmation does not match")
        run = self.resolve_run(project_slug, run_id, include_partial=True)
        if not _inside(self.solves_root, run):
            raise SolveWorkspaceError("solve run escapes configured root")
        if _is_active_partial(run):
            raise SolveWorkspaceError(
                "an active solve run cannot be deleted; cancel it before deleting its incomplete data"
            )
        shutil.rmtree(run)

    def open_run_folder(self, project_slug: str, run_id: str) -> Path:
        run = self.resolve_run(project_slug, run_id)
        system = platform.system()
        if system == "Windows":
            if not hasattr(os, "startfile"):
                raise SolveWorkspaceError("opening folders is unavailable on this platform")
            os.startfile(str(run))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(run)])
        else:
            subprocess.Popen(["xdg-open", str(run)])
        return run


def resolve_run_artifact_id(
    artifact_id: str,
    *,
    workspace: SolveWorkspace | None = None,
) -> Path:
    project_slug, run_id, relative_path = _decode_run_artifact_id(artifact_id)
    return (workspace or SolveWorkspace()).resolve_artifact(
        project_slug,
        run_id,
        relative_path,
    )
