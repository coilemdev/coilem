"""Saved run setups in ``.coilem`` design files, applied with the app's rules.

A design file saved by the app carries its setup library under ``run_setups``:
named setups that restore the operating point and requested outputs, and
optionally the accuracy, mesh and solver settings. This module reads that
library and mirrors the app (``frontend/src/public/solveProfiles.ts``):

- :func:`apply_setup` applies a setup as the setup picker does;
- :func:`setup_matches` says whether a design's settings are still exactly a
  setup, as the app decides which setup labels a run;
- a requested setup that is missing, unreadable or made for another reference
  model is refused before anything is solved.

``tests/test_run_setups.py`` checks this module against
``tests/fixtures/run_setup_parity.json``, which
``frontend/scripts/test-run-setup-parity.mjs`` generates from the app's own
functions. The app's built-in Prius reference setups ship in
``reference_setups.json``, written by the same script.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from backend.client._errors import InputError

OPERATING_KEYS: tuple[str, ...] = (
    "rated_speed_rpm",
    "current_amplitude_A",
    "current_amplitude_convention",
    "current_angle_deg",
    "magnet_temperature_C",
    "winding_temperature_C",
    "mechanical_loss_W",
    "excitation_mode",
    "phase_connection",
    "commutation_advance_deg",
    "motor_input_dc_bus_V",
)
NUMERICAL_KEYS: tuple[str, ...] = (
    "solve_quality",
    "rotor_sweep_range_deg",
    "rotor_step_deg",
    "mesh_density",
    "mesh_source",
    "mesher",
    "corner_refinement",
    "mesh_build",
    "rotor_rotation_model",
    "torque_method",
    "nonlinear_solver",
    "linear_solver_preconditioner",
    "max_nonlinear_iterations",
    "magneto2d_workers",
)
OUTPUT_KEYS: tuple[str, ...] = (
    "torque_sweep",
    "back_emf",
    "flux_density",
    "cogging_torque",
    "losses_efficiency",
    "torque_speed_envelope",
    "thd_analysis",
)
REQUIRED_PARAMETERS: tuple[str, ...] = (
    "rated_speed_rpm",
    "current_amplitude_A",
    "current_amplitude_convention",
    "current_angle_deg",
    "excitation_mode",
    "phase_connection",
    "commutation_advance_deg",
)
ENUMS: dict[str, tuple[str, ...]] = {
    "current_amplitude_convention": ("rms", "peak", "plateau"),
    "excitation_mode": ("sinusoidal", "ideal_six_step_120"),
    "phase_connection": ("wye",),
    "solve_quality": ("quick", "standard", "fine", "custom"),
    "mesh_density": ("coarse", "normal", "fine", "very_fine"),
    "mesh_source": ("native",),
    "mesher": ("gmsh",),
    "mesh_build": ("precise", "fast"),
    "rotor_rotation_model": ("remesh_per_step",),
    "torque_method": ("contour", "arkkio", "weighted_stress"),
    "nonlinear_solver": ("picard", "newton"),
    "linear_solver_preconditioner": ("direct", "ic0", "jacobi"),
}
# Settings the app keeps unset (null) at their catalogue default.
UNSET_DEFAULTS: dict[str, float] = {"magnet_temperature_C": 20, "winding_temperature_C": 20, "mechanical_loss_W": 0}
# The fixed torque and linear-solver settings of public Magneto2D requests (frontend/src/public/model.ts).
PUBLIC_MAGNETO2D_SETTINGS: dict[str, str] = {"torque_method": "weighted_stress", "linear_solver_preconditioner": "direct"}
MAX_SETUPS = 100
PRIUS_REFERENCE = "pyleecan_prius_2004"
REFERENCE_CASES: dict[str, tuple[str | None, ...]] = {
    PRIUS_REFERENCE: ("prius-2004-tutorial-bemf-v1", "prius-2004-loaded-torque-v1"),
    "lrk_12s14p": (None, "lrk-12s14p-fixed-current-v1"),
}
REFERENCE_REVISION = "prius-2004-v1"
SOLVERS: tuple[str, ...] = ("magneto2d", "elmer")
# The only solver scripted and command-line solves use.
SCRIPT_SOLVER = "magneto2d"


class _Absent:
    """A field a setup or design leaves out, which the app treats unlike null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"


ABSENT: Any = _Absent()


def same(a: Any, b: Any) -> bool:
    """JSON equality as the app compares setups: 1 == 1.0, but true is not 1 and null is not absent."""

    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value: Any) -> bool:
    return _number(value) and float(value).is_integer()


def _same_name(a: str, b: str) -> bool:
    return a.lower() == b.lower()


@dataclass(frozen=True)
class RunSetup:
    """One saved run setup.

    ``parameters`` are ``solve_params`` fields by their request names and
    ``outputs`` the ``solve_options`` flags. An operating-only setup
    (``includes_numerics`` False) leaves the design's accuracy, mesh and
    solver settings alone. ``kind`` is ``"reference"`` for the app's built-in
    Prius reference setups and ``"user"`` otherwise.
    """

    id: str
    version: int
    name: str
    includes_numerics: bool
    angle_convention: str
    reference_model: str | None
    parameters: dict[str, Any]
    outputs: dict[str, bool]
    map: dict[str, Any] | None
    solver: str | None = None
    reference_case: Any = ABSENT
    builtin: bool = False
    physical_model: str | None = None
    reference_revision: str | None = None

    @property
    def kind(self) -> str:
        return "reference" if self.builtin else "user"

    def label(self) -> dict[str, Any]:
        """The ``run_setup`` label the app records with a run solved with this setup."""

        return {"id": self.id, "version": self.version, "name": self.name, "kind": self.kind, "includes_numerics": self.includes_numerics}

    def to_dict(self) -> dict[str, Any]:
        """A JSON summary: identity, solver, reference model and the saved settings."""

        return {
            **self.label(),
            "solver": self.solver,
            "reference_model": self.reference_model,
            "reference_case": None if self.reference_case is ABSENT else self.reference_case,
            "angle_convention": self.angle_convention,
            "parameters": copy.deepcopy(self.parameters),
            "outputs": copy.deepcopy(self.outputs),
            "torque_speed_analysis": copy.deepcopy(self.map),
        }


class SetupFormatError(ValueError):
    """A saved setup or setup library that this version cannot read."""


def parse_torque_speed_settings(value: Any) -> dict[str, Any]:
    """Check saved torque–speed map settings as the app does (``parseTorqueSpeedSettings``)."""

    if not isinstance(value, Mapping):
        raise SetupFormatError("Invalid torque–speed map settings.")
    limits = value.get("limits")

    def positive(key: str, maximum: float) -> bool:
        number = limits.get(key) if isinstance(limits, Mapping) else None
        return _number(number) and 0 < number <= maximum

    if (
        not isinstance(limits, Mapping)
        or value.get("preset") not in ("preview", "standard")
        or value.get("control") not in ("mtpa", "least_loss")
        or not positive("dc_bus_V", 2000)
        or limits["dc_bus_V"] < 1
        or not positive("peak_current_A", 5000)
        or not positive("max_speed_rpm", 100000)
        or not positive("modulation_index_max", 2 / math.sqrt(3))
        or (limits.get("continuous_current_A") is not None and not positive("continuous_current_A", limits["peak_current_A"]))
    ):
        raise SetupFormatError("Invalid torque–speed map settings: check the grid, control and drive limits.")
    return copy.deepcopy(dict(value))


def parse_setup(raw: Any) -> RunSetup:
    """Read one saved setup, refusing anything the app would refuse (``parseProfile``)."""

    if not isinstance(raw, Mapping):
        raise SetupFormatError("This file has an invalid saved run setup.")
    setup_id, name, version = raw.get("id"), raw.get("name"), raw.get("version")
    includes_numerics, parameters, outputs = raw.get("includesNumerics"), raw.get("parameters"), raw.get("outputs")
    if (
        not isinstance(setup_id, str)
        or not setup_id
        or len(setup_id) > 200
        or setup_id.startswith("builtin:")
        or raw.get("builtin")
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 100
        or not _integer(version)
        or version < 1
        or not isinstance(includes_numerics, bool)
        or not isinstance(parameters, Mapping)
        or not isinstance(outputs, Mapping)
        or raw.get("angleConvention") not in ("q_axis", "pyleecan_d_axis")
        or "referenceModel" not in raw
        or raw["referenceModel"] not in (None, *REFERENCE_CASES)
        or (includes_numerics and raw.get("solver") not in SOLVERS)
        or (raw["referenceModel"] is not None and raw.get("solver") == "elmer")
    ):
        raise SetupFormatError("This file has an invalid saved run setup.")
    allowed = {*OPERATING_KEYS, *(NUMERICAL_KEYS if includes_numerics else ())}
    if (
        any(key not in allowed or not (value is None or isinstance(value, (bool, str)) or _number(value)) for key, value in parameters.items())
        or any(not isinstance(outputs.get(key), bool) for key in OUTPUT_KEYS)
        or any(key not in OUTPUT_KEYS for key in outputs)
    ):
        raise SetupFormatError("This file has invalid run-setup settings.")
    nullable = {*UNSET_DEFAULTS, "max_nonlinear_iterations"}
    for key, value in parameters.items():
        if key in ENUMS:
            valid = isinstance(value, str) and value in ENUMS[key]
        elif key == "corner_refinement":
            valid = isinstance(value, bool)
        else:
            valid = (key in nullable and value is None) or _number(value)
        if not valid:
            raise SetupFormatError("This file has invalid run-setup values.")
    if any(key not in parameters for key in REQUIRED_PARAMETERS):
        raise SetupFormatError("This file has an incomplete run setup.")
    reference_model = raw["referenceModel"]
    reference_case: Any = ABSENT
    if reference_model is not None:
        reference_case = raw.get("referenceCase")
        if reference_case not in REFERENCE_CASES[reference_model]:
            raise SetupFormatError("This setup names an incompatible reference case.")
    return RunSetup(
        id=setup_id,
        version=int(version),
        name=name.strip(),
        includes_numerics=includes_numerics,
        angle_convention=raw["angleConvention"],
        reference_model=reference_model,
        reference_case=reference_case,
        parameters=copy.deepcopy(dict(parameters)),
        outputs=copy.deepcopy(dict(outputs)),
        map=None if raw.get("map") is None else parse_torque_speed_settings(raw["map"]),
        solver=raw["solver"] if includes_numerics else None,
    )


@dataclass(frozen=True)
class SetupLibrary:
    """The setups a design file carries, read as the app reads them when it opens the file.

    A setup this version cannot read (for example one saved by a newer coilEM)
    is skipped and counted in ``skipped``; ``error`` says why a whole library
    could not be read. Neither stops the design itself from loading.
    """

    scope: str | None = None
    setups: tuple[RunSetup, ...] = ()
    active_id: str | None = None
    active_version: int | None = None
    skipped: int = 0
    error: str | None = None
    unreadable: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)


def _library_header(value: Any) -> tuple[str, list[Any], str | None, int | None]:
    if (
        not isinstance(value, Mapping)
        or not same(value.get("schema"), 1)
        or not isinstance(value.get("scope"), str)
        or len(value["scope"]) > 200
        or not value["scope"]
        or not isinstance(value.get("profiles"), list)
        or not (value.get("activeId") is None or isinstance(value["activeId"], str))
        or not (value.get("activeVersion") is None or (_integer(value["activeVersion"]) and value["activeVersion"] > 0))
    ):
        raise SetupFormatError("This file has an unsupported run-setup format.")
    active_version = value.get("activeVersion")
    return value["scope"], value["profiles"], value.get("activeId"), None if active_version is None else int(active_version)


def read_setup_library(value: Any) -> SetupLibrary:
    """Read a ``run_setups`` library tolerantly (``readProfileDocument``)."""

    if value is None:
        return SetupLibrary()
    try:
        scope, raws, active_id, active_version = _library_header(value)
    except SetupFormatError as exc:
        return SetupLibrary(error=str(exc))
    setups: list[RunSetup] = []
    unreadable: list[Mapping[str, Any]] = []
    for raw in raws:
        try:
            setup = parse_setup(raw)
        except SetupFormatError:
            unreadable.append(raw if isinstance(raw, Mapping) else {})
            continue
        if len(setups) >= MAX_SETUPS or any(other.id == setup.id or _same_name(other.name, setup.name) for other in setups):
            unreadable.append(raw)
        else:
            setups.append(setup)
    return SetupLibrary(scope, tuple(setups), active_id, active_version, len(unreadable), None, tuple(unreadable))


def _reference_setups() -> tuple[RunSetup, ...]:
    text = resources.files("backend.client").joinpath("reference_setups.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    setups = []
    for raw in payload["setups"]:
        setups.append(
            RunSetup(
                id=raw["id"],
                version=int(raw["version"]),
                name=raw["name"],
                includes_numerics=raw["includesNumerics"],
                angle_convention=raw["angleConvention"],
                reference_model=raw["referenceModel"],
                reference_case=raw.get("referenceCase", ABSENT),
                parameters=raw["parameters"],
                outputs=raw["outputs"],
                map=raw.get("map"),
                solver=raw.get("solver"),
                builtin=True,
                physical_model=raw["physicalModel"],
                reference_revision=raw["referenceRevision"],
            )
        )
    return tuple(setups)


REFERENCE_SETUPS: tuple[RunSetup, ...] = _reference_setups()


# -- The app's setup rules ----------------------------------------------------------------


def physical_model(body: Mapping[str, Any]) -> dict[str, Any]:
    """The parts of a design a built-in reference setup is tied to (``physicalModel``)."""

    model: dict[str, Any] = {
        "topology": body.get("topology", ABSENT),
        "rotor_layout": "inner" if body.get("rotor_layout") is None else body["rotor_layout"],
        "geometry_reference": body.get("geometry_reference"),
    }
    for section in ("stator", "rotor", "winding", "materials"):
        if section in body:
            model[section] = body[section]
    return {key: value for key, value in model.items() if value is not ABSENT}


_PHYSICAL_KEYS = ("topology", "rotor_layout", "geometry_reference", "stator", "rotor", "winding", "materials")


def _validated_physical_model(body: Mapping[str, Any]) -> dict[str, Any] | None:
    """The physical model with every field the file leaves out at its default, or None when invalid."""

    from pydantic import ValidationError

    from backend.models.config import MotorConfig

    try:
        config = MotorConfig.model_validate(dict(body)).model_dump(mode="json")
    except ValidationError:
        return None
    return {key: config.get(key) for key in _PHYSICAL_KEYS}


def same_physical_model(reference: str, body: Mapping[str, Any]) -> bool:
    """Whether a design is the motor a reference setup was saved for.

    The app compares the design as it opened it, with every field the file
    leaves out filled in from its defaults; a design file saved by the app
    holds them all. Files written by hand or by an older version may leave
    some out, so a design that differs only there is compared with those
    fields at their defaults.
    """

    saved = json.loads(reference)
    if same(saved, physical_model(body)):
        return True
    ours = _validated_physical_model(body)
    theirs = _validated_physical_model({**body, **saved})
    return ours is not None and theirs is not None and same(ours, theirs)


def _angle_convention(body: Mapping[str, Any]) -> str:
    return "pyleecan_d_axis" if body.get("geometry_reference") == PRIUS_REFERENCE else "q_axis"


def incompatibility(setup: RunSetup, body: Mapping[str, Any]) -> str | None:
    """Why a setup cannot be applied to a design (``profileCompatible``), or None when it can."""

    if setup.reference_model != body.get("geometry_reference"):
        if setup.reference_model is None:
            return "it was saved for a design that is not a published reference model"
        return f"it was saved for the {setup.reference_model} reference model, not this design"
    if setup.angle_convention != _angle_convention(body):
        return "it uses a different current-angle convention"
    if setup.builtin and (
        setup.reference_revision != REFERENCE_REVISION
        or setup.physical_model is None
        or not same_physical_model(setup.physical_model, body)
    ):
        return "it is a reference setup for the unchanged published motor, and this design's geometry, winding or materials differ"
    return None


def _with_unset_defaults(parameters: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(parameters)
    prius = body.get("geometry_reference") == PRIUS_REFERENCE
    for key, default in UNSET_DEFAULTS.items():
        value = result.get(key)
        if key == "magnet_temperature_C" and prius:
            result[key] = default if value is None else value
        else:
            result[key] = None if _number(value) and value == default else value
    return result


def _thd(back_emf: Any, quality: Any) -> Any:
    # back_emf && (quality === 'standard' || quality === 'fine')
    return back_emf and quality in ("standard", "fine") if back_emf else back_emf


def apply_setup(body: Mapping[str, Any], setup: RunSetup) -> dict[str, Any]:
    """Return a copy of a design with a setup applied (``applyProfile``).

    Raises :class:`InputError` with ``error_code`` ``SETUP_INCOMPATIBLE``
    when the setup belongs to another reference model or convention.
    """

    reason = incompatibility(setup, body)
    if reason is not None:
        raise InputError(
            f"The run setup {setup.name!r} cannot be used with this design: {reason}.",
            field="setup",
            error_code="SETUP_INCOMPATIBLE",
            suggestion="List the design's setups with `coilem setups DESIGN` and choose one marked compatible.",
        )
    result = copy.deepcopy(dict(body))
    parameters = {**(result.get("solve_params") or {}), **_with_unset_defaults(copy.deepcopy(setup.parameters), body)}
    if parameters.get("max_nonlinear_iterations") is None:
        parameters.pop("max_nonlinear_iterations", None)
    outputs = {**copy.deepcopy(setup.outputs), "thd_analysis": _thd(setup.outputs["back_emf"], parameters.get("solve_quality"))}
    saved_map = result.get("torque_speed_analysis")
    if setup.map:
        preset = setup.map.get("preset") if setup.includes_numerics else (saved_map or {}).get("preset") or "preview"
        torque_speed = {**copy.deepcopy(setup.map), "preset": preset}
    else:
        torque_speed = saved_map
    result.update(solve_params=parameters, solve_options=outputs, torque_speed_analysis=torque_speed)
    if setup.reference_model:
        result["reference_case"] = None if setup.reference_case is ABSENT else setup.reference_case
    return result


def _captured(body: Mapping[str, Any], includes_numerics: bool, solver: str) -> dict[str, Any]:
    """What capturing a setup from a design would record (``captureProfile``), for comparison."""

    target = solver if includes_numerics else SCRIPT_SOLVER
    elmer = target == "elmer"
    params = {**(body.get("solve_params") or {}), **PUBLIC_MAGNETO2D_SETTINGS}
    saved_options = dict(body.get("solve_options") or {})
    options = {
        **saved_options,
        "cogging_torque": not elmer and bool(saved_options.get("cogging_torque")),
        "losses_efficiency": not elmer and bool(saved_options.get("losses_efficiency")),
        "torque_speed_envelope": not elmer and bool(saved_options.get("torque_speed_envelope")),
    }
    if "back_emf" in saved_options:
        options["thd_analysis"] = _thd(saved_options["back_emf"], params.get("solve_quality"))
    else:
        options.pop("thd_analysis", None)
    torque_speed: Any = None
    if not elmer and saved_options.get("torque_speed_envelope"):
        # The app fills in default drive limits for a design saved without map settings;
        # this client does not, so such a design never counts as matching a setup.
        torque_speed = body.get("torque_speed_analysis") or ABSENT
    keys = (*OPERATING_KEYS, *(NUMERICAL_KEYS if includes_numerics else ()))
    parameters = _with_unset_defaults({key: params[key] for key in keys if key in params}, body)
    if includes_numerics:
        parameters["max_nonlinear_iterations"] = params.get("max_nonlinear_iterations")
    if not includes_numerics:
        options["thd_analysis"] = False
    return {
        "parameters": parameters,
        "outputs": options,
        "map": torque_speed,
        "reference_case": body.get("reference_case") if body.get("geometry_reference") else ABSENT,
    }


def _comparable_map(value: Any, includes_numerics: bool) -> Any:
    if value is ABSENT or not value:
        return value if value is ABSENT else None
    return {**value, "preset": None} if not includes_numerics else value


def setup_matches(setup: RunSetup, body: Mapping[str, Any], solver: str = SCRIPT_SOLVER) -> bool:
    """Whether a design's settings are exactly this setup (``profileMatches``)."""

    if incompatibility(setup, body) is not None:
        return False
    actual = _captured(body, setup.includes_numerics, solver)
    if actual["map"] is ABSENT:
        return False
    actual_case, setup_case = actual["reference_case"], setup.reference_case
    return (
        same(actual["parameters"], _with_unset_defaults(setup.parameters, body))
        and same(actual["outputs"], setup.outputs)
        and same(_comparable_map(actual["map"], setup.includes_numerics), _comparable_map(setup.map, setup.includes_numerics))
        and (not setup.includes_numerics or setup.solver == solver)
        and (actual_case is ABSENT) == (setup_case is ABSENT)
        and (actual_case is ABSENT or same(actual_case, setup_case))
    )


# -- Choosing the setup for a solve ---------------------------------------------------------


@dataclass(frozen=True)
class SetupUse:
    """Which setup a solve used, and how.

    ``source`` is ``"requested"`` (named in the call), ``"active"`` (the
    design's active setup, which still describes its saved settings) or
    ``"design"`` (the design's saved settings, no setup). ``label`` is the
    ``run_setup`` label recorded with the run, or None when the solved
    settings are not exactly a saved setup. ``notes`` explain anything the
    caller may not expect, for example an active setup that was edited
    after it was chosen.
    """

    source: str
    setup: RunSetup | None = None
    label: dict[str, Any] | None = None
    modified: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.setup.id if self.setup else None,
            "version": self.setup.version if self.setup else None,
            "name": self.setup.name if self.setup else None,
            "kind": self.setup.kind if self.setup else None,
            "includes_numerics": self.setup.includes_numerics if self.setup else None,
            "modified": self.modified,
            "run_setup": copy.deepcopy(self.label),
            "notes": list(self.notes),
        }


def library_of(body: Mapping[str, Any]) -> SetupLibrary:
    return read_setup_library(body.get("run_setups"))


def _library_notes(library: SetupLibrary) -> list[str]:
    if library.error:
        return [f"The design's saved run setups could not be read ({library.error})"]
    if library.skipped:
        many = library.skipped != 1
        return [f"{library.skipped} saved run setup{'s' if many else ''} could not be read and {'were' if many else 'was'} skipped."]
    return []


def available_setups(body: Mapping[str, Any]) -> tuple[RunSetup, ...]:
    """The design's own setups followed by the app's built-in reference setups."""

    return (*library_of(body).setups, *REFERENCE_SETUPS)


def find_setup(body: Mapping[str, Any], requested: str) -> RunSetup:
    """A setup by id, or by name ignoring case. Raises :class:`InputError` when there is none."""

    if not isinstance(requested, str) or not requested.strip():
        raise InputError("setup: give the name or id of a saved run setup", field="setup", error_code="SETUP_NOT_FOUND")
    wanted = requested.strip()
    library = library_of(body)
    candidates = (*library.setups, *REFERENCE_SETUPS)
    for setup in candidates:
        if setup.id == wanted:
            return setup
    for setup in candidates:
        if _same_name(setup.name, wanted):
            return setup
    unreadable = [
        raw
        for raw in library.unreadable
        if raw.get("id") == wanted or (isinstance(raw.get("name"), str) and _same_name(raw["name"].strip(), wanted))
    ]
    if unreadable:
        raise InputError(
            f"The run setup {wanted!r} is saved in this design but this version of coilEM cannot read it; "
            "it may have been saved by a newer coilEM.",
            field="setup",
            error_code="SETUP_UNREADABLE",
        )
    names = [setup.name for setup in library.setups]
    known = f" Saved setups: {', '.join(repr(name) for name in names)}." if names else " This design has no saved setups."
    if library.error:
        known = f" The design's setups could not be read ({library.error})"
    raise InputError(
        f"No run setup named {wanted!r}.{known}",
        field="setup",
        error_code="SETUP_NOT_FOUND",
        suggestion="List the design's setups with `coilem setups DESIGN`.",
    )


def resolve_setup(body: Mapping[str, Any], requested: str | None) -> tuple[dict[str, Any], SetupUse]:
    """The design with its setup applied, and which setup that was.

    Precedence: the requested setup, else the design's active setup when it
    still describes the saved settings, else the saved settings. As in the app,
    a design file's own settings are never overwritten by its active setup: an
    active setup edited after it was chosen only loses its label.
    """

    library = library_of(body)
    notes = _library_notes(library)
    if requested is not None:
        setup = find_setup(body, requested)
        if setup.includes_numerics and setup.solver != SCRIPT_SOLVER:
            raise InputError(
                f"The run setup {setup.name!r} solves with {setup.solver}, which scripted and command-line solves do not support.",
                field="setup",
                error_code="SETUP_SOLVER_UNAVAILABLE",
                suggestion="Choose a setup that uses Magneto2D, or an operating-only setup.",
            )
        applied = apply_setup(body, setup)
        label = setup.label() if setup_matches(setup, applied) else None
        return applied, SetupUse("requested", setup, label, notes=tuple(notes))
    if library.active_id is None:
        return copy.deepcopy(dict(body)), SetupUse("design", notes=tuple(notes))
    active = next(
        (setup for setup in (*REFERENCE_SETUPS, *library.setups) if setup.id == library.active_id and setup.version == library.active_version),
        None,
    )
    if active is None:
        notes.append("The design's active run setup could not be read, so its saved settings are used.")
    elif active.includes_numerics and active.solver != SCRIPT_SOLVER:
        notes.append(f"The design's active run setup {active.name!r} uses {active.solver}; its saved settings are solved with Magneto2D.")
    elif not setup_matches(active, body):
        notes.append(
            f"The design's saved settings differ from its active run setup {active.name!r} "
            "(they were edited after it was chosen), so the saved settings are used without that setup's label."
        )
    else:
        return copy.deepcopy(dict(body)), SetupUse("active", active, active.label(), notes=tuple(notes))
    return copy.deepcopy(dict(body)), SetupUse("design", notes=tuple(notes))


def after_changes(use: SetupUse, body: Mapping[str, Any]) -> SetupUse:
    """The setup use once other settings were changed on top of the setup."""

    if use.setup is None or setup_matches(use.setup, body):
        return use
    note = f"Settings given with the solve changed the run setup {use.setup.name!r}, so the run is not labelled with it."
    return SetupUse(use.source, use.setup, None, modified=True, notes=(*use.notes, note))


@dataclass(frozen=True)
class SetupStatus:
    """A setup as listed for one design: whether it can be used, and whether it is the design's active one.

    ``matches_saved`` is True when the design's saved settings are exactly
    this setup, so solving without naming a setup would be labelled with it.
    """

    setup: RunSetup
    active: bool
    usable: bool
    reason: str | None
    matches_saved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.setup.to_dict(),
            "active": self.active,
            "usable": self.usable,
            "reason": self.reason,
            "matches_saved_settings": self.matches_saved,
        }


def setup_statuses(body: Mapping[str, Any]) -> tuple[list[SetupStatus], SetupLibrary]:
    """The design's setups, then the reference setups that fit it, each with whether it can be used."""

    library = library_of(body)
    statuses = []
    for setup in (*library.setups, *REFERENCE_SETUPS):
        reason = incompatibility(setup, body)
        if setup.builtin and reason is not None:
            continue  # Reference setups are listed only for their own published motor.
        if reason is None and setup.includes_numerics and setup.solver != SCRIPT_SOLVER:
            reason = f"it solves with {setup.solver}, which scripted and command-line solves do not support"
        active = setup.id == library.active_id and setup.version == library.active_version
        statuses.append(SetupStatus(setup, active, reason is None, reason, reason is None and setup_matches(setup, body)))
    return statuses, library
