"""Fail-closed configuration policy for the public coilEM runtime."""

from __future__ import annotations

import os
from typing import Any, Literal, cast

from pydantic import ValidationError

from backend.magneto2d_adapter import get_magneto2d_winding_support_error
from backend.models import MotorConfig

SUPPORTED_PUBLIC_IPM_TOPOLOGIES = frozenset({"flat_buried", "v_shape"})
SUPPORTED_PUBLIC_STEELS = frozenset({"M350-50A"})
PUBLIC_SOLVER_IDS = frozenset({"magneto2d", "elmer"})
PublicSolverId = Literal["magneto2d", "elmer"]
PUBLIC_ELMER_FEATURE_ENV = "COILEM_ENABLE_ELMER"
_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


class PublicConfigError(ValueError):
    """Raised when a request is outside the public launch boundary."""

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.field = field


def public_elmer_enabled() -> bool:
    """Return whether the optional Elmer surface was explicitly enabled."""

    return os.environ.get(PUBLIC_ELMER_FEATURE_ENV, "").strip().lower() in _TRUE_ENV_VALUES


def _reject_disabled_elmer(requested_solver: str) -> None:
    if requested_solver == "elmer" and not public_elmer_enabled():
        raise PublicConfigError(
            "Elmer is disabled for this build. Set COILEM_ENABLE_ELMER=1 before starting the local API to enable it.",
            field="solver",
        )


def parse_public_motor_config(body: dict[str, Any]) -> MotorConfig:
    """Validate a public request without entering excluded feature modules."""

    if not isinstance(body, dict):
        raise PublicConfigError("Motor configuration must be a JSON object.")

    requested_solver = str(body.get("solver") or "").strip().lower()
    _reject_disabled_elmer(requested_solver)
    if requested_solver and requested_solver not in {"auto", *PUBLIC_SOLVER_IDS}:
        raise PublicConfigError(
            "The public launch supports Magneto2D and a separately installed qualified Elmer runtime.",
            field="solver",
        )

    solve_params = body.get("solve_params")
    if isinstance(solve_params, dict):
        if solve_params.get("magnet_temperature_C") is not None:
            raise PublicConfigError(
                "Manual magnet-temperature modeling is unavailable in this preview.",
                field="solve_params.magnet_temperature_C",
            )
        mesh_source = str(solve_params.get("mesh_source") or "native").strip().lower()
        if mesh_source != "native":
            raise PublicConfigError(
                "The public launch accepts only native Gmsh meshes.",
                field="solve_params.mesh_source",
            )
        mesher = str(solve_params.get("mesher") or "gmsh").strip().lower()
        if mesher != "gmsh":
            raise PublicConfigError(
                "The public launch accepts only the Gmsh mesher.",
                field="solve_params.mesher",
            )
        field_composition_source = str(
            solve_params.get("field_composition_source") or "resultant"
        ).strip().lower()
        if field_composition_source != "resultant":
            raise PublicConfigError(
                "Source-separated fields are requested through the dedicated local composition route.",
                field="solve_params.field_composition_source",
            )

    debug = body.get("debug")
    if isinstance(debug, dict) and any(bool(value) for value in debug.values()):
        raise PublicConfigError(
            "Internal solver diagnostics are unavailable in the public launch.",
            field="debug",
        )

    if body.get("thermal") is not None or body.get("thermal_config") is not None:
        raise PublicConfigError(
            "Thermal analysis is unavailable in this preview.",
            field="thermal",
        )

    try:
        config = MotorConfig.model_validate(body)
    except ValidationError as exc:
        material_errors = [error for error in exc.errors() if error["loc"] and error["loc"][0] == "materials"]
        if material_errors:
            error = material_errors[0]
            raise PublicConfigError(error["msg"], field=".".join(map(str, error["loc"]))) from exc
        raise PublicConfigError(
            "Motor configuration failed schema validation.",
        ) from exc

    support_error = public_config_support_error(
        config,
        solver_id="elmer" if requested_solver == "elmer" else "magneto2d",
    )
    if support_error is not None:
        raise support_error
    return config


def parse_public_solve_request(
    body: dict[str, Any],
) -> tuple[MotorConfig, str | None, PublicSolverId]:
    """Parse the direct or frontend-wrapped local solve request shape."""

    if not isinstance(body, dict):
        raise PublicConfigError("Solve request must be a JSON object.")

    config_body = body
    solve_mesh_key = None
    requested_solver = str(body.get("solver") or "magneto2d").strip().lower()
    if "config" in body:
        unexpected = set(body) - {
            "config",
            "project_name",
            "solve_mesh_key",
            "solver",
        }
        if unexpected:
            raise PublicConfigError(
                "Solve request contains unsupported wrapper fields.",
            )
        raw_config = body.get("config")
        if not isinstance(raw_config, dict):
            raise PublicConfigError(
                "Wrapped solve request must contain a motor configuration.",
                field="config",
            )
        config_body = dict(raw_config)
        if body.get("solver") is not None:
            config_body["solver"] = body["solver"]
            requested_solver = str(body["solver"]).strip().lower()

        raw_mesh_key = body.get("solve_mesh_key")
        if raw_mesh_key is not None:
            if not isinstance(raw_mesh_key, str) or not raw_mesh_key.strip():
                raise PublicConfigError(
                    "solve_mesh_key must be a non-empty local cache key.",
                    field="solve_mesh_key",
                )
            solve_mesh_key = raw_mesh_key.strip()

    if requested_solver in {"", "auto"}:
        requested_solver = "magneto2d"
    _reject_disabled_elmer(requested_solver)
    if requested_solver not in PUBLIC_SOLVER_IDS:
        raise PublicConfigError(
            "The requested electromagnetic solver is unavailable in the public application.",
            field="solver",
        )
    return (
        parse_public_motor_config(config_body),
        solve_mesh_key,
        cast(PublicSolverId, requested_solver),
    )


def public_config_support_error(
    config: MotorConfig,
    *,
    require_solve_params: bool = False,
    solver_id: PublicSolverId = "magneto2d",
) -> PublicConfigError | None:
    """Return an actionable public-boundary error, or ``None``."""

    if int(config.rotor.pole_count) % 2:
        return PublicConfigError(
            "The public launch requires an even rotor pole count.",
            field="rotor.pole_count",
        )

    if config.rotor.flux_barrier_count or config.rotor.barrier_widths_mm:
        return PublicConfigError(
            "Explicit flux-barrier fields are not supported by the public launch.",
            field="rotor.flux_barrier_count",
        )

    for component, grade in (
        ("stator", config.materials.stator_steel),
        ("rotor", config.materials.rotor_steel),
    ):
        if grade in config.materials.custom_steels:
            if solver_id != "magneto2d":
                return PublicConfigError("Custom steel currently requires Magneto2D.", field=f"materials.{component}_steel")
        elif grade not in SUPPORTED_PUBLIC_STEELS:
            return PublicConfigError(
                "Choose the bundled M350-50A model or import a custom B-H curve for this steel.",
                field=f"materials.{component}_steel",
            )

    if config.topology == "IPM":
        ipm_topology = str(config.rotor.ipm_topology or "flat_buried")
        if ipm_topology not in SUPPORTED_PUBLIC_IPM_TOPOLOGIES:
            return PublicConfigError(
                "The public launch supports flat-buried and V-shape IPM only.",
                field="rotor.ipm_topology",
            )

    if require_solve_params and config.solve_params is None:
        return PublicConfigError(
            "solve_params is required for native mesh and solve requests.",
            field="solve_params",
        )

    if config.solve_options is not None and config.solve_options.cogging_torque:
        return PublicConfigError(
            "Cogging-torque analysis is not included in this developer preview.",
            field="solve_options.cogging_torque",
        )

    winding_error = get_magneto2d_winding_support_error(config)
    if winding_error is not None:
        solver_label = "Elmer" if solver_id == "elmer" else "Magneto2D"
        if "FEMM" in winding_error:
            winding_error = (
                f"This winding is outside the launch-supported {solver_label} winding boundary. "
                "Use a supported single-layer concentrated or balanced distributed winding."
            )
        elif solver_id == "elmer":
            winding_error = winding_error.replace("Magneto2D", "Elmer")
        return PublicConfigError(winding_error, field="winding")

    return None


def normalize_public_mesh_preview_config(config: MotorConfig) -> MotorConfig:
    """Apply the native IPM remesh policy used by geometry-only previews."""

    solve_params = config.solve_params
    if config.topology != "IPM" or solve_params is None:
        return config
    if solve_params.rotor_rotation_model == "remesh_per_step":
        return config
    return config.model_copy(
        update={
            "solve_params": solve_params.model_copy(
                update={"rotor_rotation_model": "remesh_per_step"},
            )
        }
    )
