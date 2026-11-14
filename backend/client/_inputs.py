"""Typed inputs: the motor, its operating point and the analyses to run."""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from backend.client._errors import InputError, input_error_from_validation
from backend.models.config import (
    MaterialsConfig,
    MotorConfig,
    RotorConfig,
    SolveOptionsConfig,
    SolveParams,
    StatorConfig,
    WindingConfig,
    WireSpec,
)

# Each section class is the app's own model, so the fields, units, limits and
# defaults are exactly those of the Design page. The subclasses only turn a
# pydantic error into an InputError that names the field with its section.
# Type checkers see the inherited keyword signature; at run time __init__ is
# wrapped.


class Stator(StatorConfig):
    """Stator geometry. Lengths in mm; see each field's description for its limits."""

    if not TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            try:
                super().__init__(**data)
            except ValidationError as exc:
                raise input_error_from_validation(exc, prefix="stator") from None


class Rotor(RotorConfig):
    """Rotor geometry and magnets. Lengths in mm, angles in degrees."""

    if not TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            try:
                super().__init__(**data)
            except ValidationError as exc:
                raise input_error_from_validation(exc, prefix="rotor") from None


class Wire(WireSpec):
    """The conductor of one turn, used for slot fill and phase resistance."""

    if not TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            try:
                super().__init__(**data)
            except ValidationError as exc:
                raise input_error_from_validation(exc, prefix="winding.wire") from None


class Winding(WindingConfig):
    """Stator winding. ``turns_per_coil`` is the conductor count of one coil side."""

    if not TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            try:
                super().__init__(**data)
            except ValidationError as exc:
                raise input_error_from_validation(exc, prefix="winding") from None


class Materials(MaterialsConfig):
    """Steel, magnet and conductor choices. The defaults are M350-50A, N42 and copper."""

    if not TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            try:
                super().__init__(**data)
            except ValidationError as exc:
                raise input_error_from_validation(exc, prefix="materials") from None


# Analysis names accepted by solve(..., analyses=[...]) and the request flag
# each one sets.
ANALYSES: dict[str, str] = {
    "torque": "torque_sweep",
    "back_emf": "back_emf",
    "cogging": "cogging_torque",
    "losses": "losses_efficiency",
    "thd": "thd_analysis",
    "flux_density": "flux_density",
}

_MOTOR_KEYS = frozenset(MotorConfig.model_fields)

# The app's .coilem design files are a motor request plus a few metadata keys.
# The app migrates older files when it opens them (for example the tooth-width
# change of schema 3); the client reads this schema only. Kept equal to
# COILEM_SCHEMA_VERSION in frontend/src/api/projectSchema.ts by a test.
DESIGN_FILE_SCHEMA_VERSION = 4


def _section(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    raise InputError(f"{name} must be a model such as {name.title()}(...) or a mapping, not {type(value).__name__}", field=name)


def _merged(base: dict[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, BaseModel):
            merged[key] = value.model_dump(mode="json")
        elif isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merged(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class Motor:
    """A motor design as the app saves it: geometry, winding, materials and, optionally, solve settings.

    Build one from typed sections::

        motor = Motor(
            topology="SPM",
            stator=Stator(OD_mm=100, ID_mm=60, slot_count=12, stack_length_mm=50,
                          slot_opening_mm=2, tooth_width_mm=9, yoke_thickness_mm=8),
            rotor=Rotor(OD_mm=54, pole_count=8, magnet_thickness_mm=2.5, magnet_width_mm=16.5),
            winding=Winding(type="concentrated", layers=1, turns_per_coil=12),
        )

    or load a design file saved by the app, a solve request, or a file
    written by :meth:`save`. A Motor is immutable: :meth:`replace` returns a
    changed copy. The request it holds
    is kept as given, including keys this version does not use, so a loaded
    file saves back unchanged.
    """

    __slots__ = ("_body", "_config")
    _body: dict[str, Any]
    _config: MotorConfig

    def __init__(
        self,
        *,
        topology: str,
        stator: Stator | StatorConfig | Mapping[str, Any],
        rotor: Rotor | RotorConfig | Mapping[str, Any],
        winding: Winding | WindingConfig | Mapping[str, Any],
        materials: Materials | MaterialsConfig | Mapping[str, Any] | None = None,
        rotor_layout: str = "inner",
        solve_params: SolveParams | Mapping[str, Any] | None = None,
        solve_options: SolveOptionsConfig | Mapping[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "schema_version": "1.0",
            "topology": topology,
            "rotor_layout": rotor_layout,
            "stator": _section(stator, "stator"),
            "rotor": _section(rotor, "rotor"),
            "winding": _section(winding, "winding"),
            "materials": _section(materials if materials is not None else MaterialsConfig(), "materials"),
        }
        if solve_params is not None:
            body["solve_params"] = _section(solve_params, "solve_params")
        if solve_options is not None:
            body["solve_options"] = _section(solve_options, "solve_options")
        self._adopt(body)

    def _adopt(self, body: Mapping[str, Any]) -> None:
        if not isinstance(body, Mapping):
            raise InputError(f"A motor request must be a JSON object, not {type(body).__name__}")
        owned = copy.deepcopy(dict(body))
        try:
            config = MotorConfig.model_validate(owned)
        except ValidationError as exc:
            raise input_error_from_validation(exc) from None
        self._body = owned
        self._config = config

    @classmethod
    def _from_body(cls, body: Mapping[str, Any]) -> Motor:
        motor = cls.__new__(cls)
        motor._adopt(body)
        return motor

    # -- Request JSON ------------------------------------------------------------

    @classmethod
    def from_request(cls, body: Mapping[str, Any]) -> Motor:
        """Read a solve request or a design file.

        Accepts the plain motor configuration (as in the benchmark fixtures),
        the app's ``{"config": ...}`` solve wrapper, and a ``.coilem`` design
        file saved by this version of the app.
        """

        if isinstance(body, Mapping) and "openem_schema_version" in body:
            version = body["openem_schema_version"]
            if not isinstance(version, int) or version < DESIGN_FILE_SCHEMA_VERSION:
                raise InputError(
                    f"openem_schema_version: this design file uses schema {version!r}; open it in the coilEM app and "
                    f"save it to update it to schema {DESIGN_FILE_SCHEMA_VERSION}, which the Python client reads",
                    field="openem_schema_version",
                )
        if isinstance(body, Mapping) and "config" in body:
            unexpected = set(body) - {"config", "project_name", "solve_mesh_key", "solver", "run_setup", "run_setups"}
            if unexpected:
                raise InputError(f"Unexpected wrapper field(s): {', '.join(sorted(unexpected))}", field=sorted(unexpected)[0])
            config = body["config"]
            if not isinstance(config, Mapping):
                raise InputError("The wrapped request has no motor configuration", field="config")
            unwrapped = dict(config)
            if body.get("solver") is not None:
                unwrapped["solver"] = body["solver"]
            return cls._from_body(unwrapped)
        return cls._from_body(body)

    @classmethod
    def load(cls, path: str | Path) -> Motor:
        """Load a request JSON file or a ``.coilem`` design file (see :meth:`from_request`)."""

        path = Path(path)
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InputError(f"{path}: not valid JSON ({exc.msg} at line {exc.lineno})") from None
        return cls.from_request(body)

    def to_request(self) -> dict[str, Any]:
        """The request JSON as a new dict, ready for the app's ``/solve`` or :meth:`save`."""

        return copy.deepcopy(self._body)

    def save(self, path: str | Path) -> Path:
        """Write the request JSON. Loading the file again gives an equal Motor."""

        path = Path(path)
        path.write_text(json.dumps(self._body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    # -- Changes -----------------------------------------------------------------

    def replace(self, **changes: Any) -> Motor:
        """Return a copy with some inputs changed.

        Mappings are merged into the section, so only the named fields
        change; a model replaces the section; ``None`` removes it::

            longer = motor.replace(stator={"stack_length_mm": 80})
            n52 = motor.replace(materials={"magnet_grade": "N52"})
        """

        body = self.to_request()
        for key, value in changes.items():
            if key not in _MOTOR_KEYS:
                raise InputError(f"{key}: Motor has no input named {key!r}; choose from {', '.join(sorted(_MOTOR_KEYS))}", field=key)
            if value is None:
                body.pop(key, None)
            elif isinstance(value, BaseModel):
                body[key] = value.model_dump(mode="json")
            elif isinstance(value, Mapping):
                current = body.get(key)
                body[key] = _merged(current, value) if isinstance(current, dict) else copy.deepcopy(dict(value))
            else:
                body[key] = value
        return Motor._from_body(body)

    # -- Typed views -------------------------------------------------------------

    @property
    def config(self) -> MotorConfig:
        """The validated configuration, as the app's backend sees it (a copy)."""

        return self._config.model_copy(deep=True)

    @property
    def topology(self) -> str:
        return self._config.topology

    @property
    def rotor_layout(self) -> str:
        return self._config.rotor_layout

    @property
    def stator(self) -> Stator:
        return Stator.model_validate(self._config.stator.model_dump())

    @property
    def rotor(self) -> Rotor:
        return Rotor.model_validate(self._config.rotor.model_dump())

    @property
    def winding(self) -> Winding:
        return Winding.model_validate(self._config.winding.model_dump())

    @property
    def materials(self) -> Materials:
        return Materials.model_validate(self._config.materials.model_dump())

    @property
    def operating_point(self) -> OperatingPoint | None:
        """The operating point saved with the motor, or None when it has no solve settings."""

        params = self._body.get("solve_params")
        return OperatingPoint.from_solve_params(params) if isinstance(params, Mapping) else None

    @property
    def analyses(self) -> tuple[str, ...] | None:
        """The analyses saved with the motor, or None when it has none saved."""

        options = self._config.solve_options
        if options is None:
            return None
        return tuple(name for name, flag in ANALYSES.items() if getattr(options, flag))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Motor) and other._body == self._body

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        config = self._config
        return (
            f"Motor({config.topology}, {config.rotor.pole_count} poles / {config.stator.slot_count} slots, "
            f"{config.rotor_layout} rotor, stack {config.stator.stack_length_mm:g} mm)"
        )


# OperatingPoint field -> request solve_params field.
_OPERATING_POINT_FIELDS: dict[str, str] = {
    "current_A": "current_amplitude_A",
    "current_angle_deg": "current_angle_deg",
    "speed_rpm": "rated_speed_rpm",
    "current_convention": "current_amplitude_convention",
    "magnet_temperature_C": "magnet_temperature_C",
    "winding_temperature_C": "winding_temperature_C",
    "dc_bus_V": "motor_input_dc_bus_V",
}
_REQUEST_TO_OPERATING_POINT = {request: name for name, request in _OPERATING_POINT_FIELDS.items()}


@dataclasses.dataclass(frozen=True)
class OperatingPoint:
    """The electrical operating point of one solve.

    Attributes:
        current_A: Phase current amplitude in A, peak by default (see
            ``current_convention``). 0 gives a no-load run.
        current_angle_deg: Current angle γ in electrical degrees from the
            q-axis; positive advances toward flux weakening (negative i_d).
        speed_rpm: Speed for back-EMF voltage, frequency and losses; 0 is a
            static locked-rotor solve.
        current_convention: ``"peak"``, ``"rms"``, or ``"plateau"`` for
            ideal six-step drive.
        magnet_temperature_C: Magnet temperature for Br/Hc derating; None
            uses room-temperature properties.
        winding_temperature_C: Winding temperature for resistance and copper
            loss; None means 20 °C.
        dc_bus_V: Inverter DC-link voltage for voltage-headroom reporting.

    Every field is checked against the app's limits when the point is made.
    """

    current_A: float = 0.0
    current_angle_deg: float = 0.0
    speed_rpm: int = 3000
    current_convention: str = "peak"
    magnet_temperature_C: float | None = None
    winding_temperature_C: float | None = None
    dc_bus_V: float | None = None

    def __post_init__(self) -> None:
        try:
            SolveParams.model_validate(self.to_solve_params())
        except ValidationError as exc:
            raise input_error_from_validation(exc, prefix="operating_point", rename=_REQUEST_TO_OPERATING_POINT) from None

    def to_solve_params(self) -> dict[str, Any]:
        """The ``solve_params`` fields this operating point sets."""

        params: dict[str, Any] = {}
        for name, request_name in _OPERATING_POINT_FIELDS.items():
            value = getattr(self, name)
            if isinstance(value, float) and name == "speed_rpm" and value.is_integer():
                value = int(value)
            params[request_name] = value
        return params

    @classmethod
    def from_solve_params(cls, params: Mapping[str, Any]) -> OperatingPoint:
        """Read the operating point out of a request's ``solve_params``."""

        values = {name: params[request] for name, request in _OPERATING_POINT_FIELDS.items() if request in params}
        return cls(**values)

    def replace(self, **changes: Any) -> OperatingPoint:
        """Return a copy with some fields changed (and checked)."""

        unknown = set(changes) - {field.name for field in dataclasses.fields(self)}
        if unknown:
            name = sorted(unknown)[0]
            raise InputError(f"operating_point.{name}: OperatingPoint has no field named {name!r}", field=f"operating_point.{name}")
        return dataclasses.replace(self, **changes)


def solve_options_for(analyses: str | Iterable[str], base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The request's ``solve_options`` for a list of analysis names (see :data:`ANALYSES`).

    Named analyses are switched on and every other one off, so the list is
    exactly what runs. Keys of ``base`` that are not analyses are kept.
    """

    names = [analyses] if isinstance(analyses, str) else list(analyses)
    unknown = [name for name in names if name not in ANALYSES]
    if unknown:
        raise InputError(
            f"analyses: unknown analysis {unknown[0]!r}; choose from {', '.join(ANALYSES)}",
            field="analyses",
        )
    if not names:
        raise InputError("analyses: name at least one analysis", field="analyses")
    options = dict(base or {})
    for name, flag in ANALYSES.items():
        options[flag] = name in names
    options["torque_speed_envelope"] = False
    return options
