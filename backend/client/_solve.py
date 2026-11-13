"""Run solves in this Python process or in a running coilEM app, and sweep operating points."""

from __future__ import annotations

import ast
import csv
import json
import math
import multiprocessing
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, overload

import numpy as np

from backend.client._errors import CoilemError, InputError, MainModuleError, SolveError
from backend.client._inputs import Motor, OperatingPoint, solve_options_for
from backend.client._results import Result
from backend.models.config import MotorConfig, SolveOptionsConfig, SolveParams

QUALITIES: tuple[str, ...] = get_args(SolveParams.model_fields["solve_quality"].annotation)
MESH_DENSITIES: tuple[str, ...] = get_args(SolveParams.model_fields["mesh_density"].annotation)

# Solver settings the app gives every new design where they differ from the
# request schema's defaults (frontend/src/public/model.ts DEFAULT_CONFIG). The
# app solves only with the mesh rebuilt at each rotor position; the schema's
# fixed_mesh default is refused for surface-magnet rotors. Applied only where
# a request leaves the field unset.
APP_SOLVE_DEFAULTS: dict[str, Any] = {"rotor_rotation_model": "remesh_per_step", "corner_refinement": True}

ProgressCallback = Callable[[int, int, "str | None"], Any]
MotorLike = Motor | Mapping[str, Any] | str | Path


def _as_motor(motor: MotorLike) -> Motor:
    if isinstance(motor, Motor):
        return motor
    if isinstance(motor, Mapping):
        return Motor.from_request(motor)
    if isinstance(motor, (str, Path)):
        return Motor.load(motor)
    raise InputError(f"motor must be a Motor, a request mapping or a JSON path, not {type(motor).__name__}", field="motor")


def build_request(
    motor: MotorLike,
    operating_point: OperatingPoint | None = None,
    *,
    analyses: str | Iterable[str] | None = None,
    quality: str | None = None,
    mesh: str | None = None,
    solve_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The request JSON that :func:`solve` sends, without solving.

    The motor's saved solve settings are the starting point; fields they
    leave unset take the app's new-design settings (:data:`APP_SOLVE_DEFAULTS`)
    and then the schema defaults. The operating point, ``quality``, ``mesh``
    and then ``solve_params`` (any other ``solve_params`` field, by its request
    name) are applied over them, and ``analyses`` replaces the saved analysis
    selection. A motor with no saved settings and no operating point is
    solved at 0 A.
    """

    body = _as_motor(motor).to_request()
    params = dict(body.get("solve_params") or {})
    if operating_point is None and not params:
        operating_point = OperatingPoint()
    for key, value in APP_SOLVE_DEFAULTS.items():
        params.setdefault(key, value)
    if operating_point is not None:
        if not isinstance(operating_point, OperatingPoint):
            raise InputError("operating_point must be an OperatingPoint", field="operating_point")
        params.update(operating_point.to_solve_params())
    if quality is not None:
        if quality not in QUALITIES:
            raise InputError(f"quality must be one of {', '.join(QUALITIES)} (got {quality!r})", field="quality")
        params["solve_quality"] = quality
    if mesh is not None:
        if mesh not in MESH_DENSITIES:
            raise InputError(f"mesh must be one of {', '.join(MESH_DENSITIES)} (got {mesh!r})", field="mesh")
        params["mesh_density"] = mesh
    if solve_params is not None:
        if not isinstance(solve_params, Mapping):
            raise InputError("solve_params must be a mapping of solve_params field names to values", field="solve_params")
        params.update(solve_params)
    body["solve_params"] = params
    if analyses is not None:
        body["solve_options"] = solve_options_for(analyses, body.get("solve_options"))
    Motor.from_request(body)  # Validates the whole request; errors name solve_params.<field>.
    return body


def prepared_config(body: Mapping[str, Any]) -> MotorConfig:
    """Apply the checks and normalisation of the app's ``/solve`` route to a request.

    These are the same steps, in the same order, as the route's validation
    for the built-in Magneto2D solver, so a script solves exactly what the
    app would. Field-line frames for the app's playback are not requested.
    """

    from backend.magneto2d_adapter import get_magneto2d_support_error
    from backend.public_policy import (
        PublicConfigError,
        normalize_public_mesh_preview_config,
        parse_public_solve_request,
        public_config_support_error,
    )

    try:
        config, _, solver_id = parse_public_solve_request(dict(body))
        if solver_id != "magneto2d":
            raise PublicConfigError(
                "In-process solves use the built-in Magneto2D solver; pass server= to use the app's solver choice.",
                field="solver",
            )
        support_error = public_config_support_error(config, require_solve_params=True, solver_id=solver_id)
        if support_error is not None:
            raise support_error
    except PublicConfigError as exc:
        message = str(exc)
        if exc.field and not message.startswith(exc.field):
            message = f"{exc.field}: {message}"
        raise InputError(message, field=exc.field) from None
    config = normalize_public_mesh_preview_config(config)
    reason = get_magneto2d_support_error(config)
    if reason is not None:
        raise InputError(f"This design is outside the Magneto2D solve boundary: {reason}")
    assert config.solve_params is not None
    return config.model_copy(
        update={
            "solve_params": config.solve_params.model_copy(
                update={"stream_noload_field_lines": False, "field_composition_source": "resultant"}
            )
        }
    )


def _raise_for_geometry(config: MotorConfig) -> None:
    from backend.geometry import validate_geometry

    errors = validate_geometry(config)
    if errors:
        problems = [(error.field, error.message) for error in errors]
        text = "; ".join(f"{field}: {message}" if field else message for field, message in problems)
        raise InputError(text, field=errors[0].field, suggestion=errors[0].suggestion, problems=problems)


def check(
    motor: MotorLike,
    operating_point: OperatingPoint | None = None,
    *,
    analyses: str | Iterable[str] | None = None,
    quality: str | None = None,
    mesh: str | None = None,
    solve_params: Mapping[str, Any] | None = None,
) -> list[str]:
    """Run the app's pre-solve checks without solving.

    Raises :class:`InputError` for anything the app would refuse to solve,
    and returns the app's non-blocking winding warnings.
    """

    from backend.geometry import winding_feasibility_warnings

    config = prepared_config(
        build_request(motor, operating_point, analyses=analyses, quality=quality, mesh=mesh, solve_params=solve_params)
    )
    _raise_for_geometry(config)
    return list(winding_feasibility_warnings(config))


# -- Worker processes and the main module ------------------------------------------

_MAIN_GUARD_HELP = (
    "coilEM solves start worker processes, and each worker imports the program's main file again. "
    "Save the code in a .py file and call solve() from under `if __name__ == \"__main__\":`, "
    "or pass server=... to solve in a running coilEM app instead."
)


def _start_method() -> str:
    # The solver's pools use spawn on Windows and the platform default elsewhere.
    return "spawn" if os.name == "nt" else multiprocessing.get_start_method()


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            test = node.test
            if len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                sides = (test.left, test.comparators[0])
                if any(isinstance(side, ast.Name) and side.id == "__name__" for side in sides) and any(
                    isinstance(side, ast.Constant) and side.value == "__main__" for side in sides
                ):
                    return True
    return False


def check_main_module() -> None:
    """Raise :class:`MainModuleError` when the solver's worker processes could not start.

    Worker processes started with ``spawn`` or ``forkserver`` (always on
    Windows) import the main program again. A program read from stdin cannot
    be imported, and a script without an ``if __name__ == "__main__":`` block
    would start another solve in every worker. Interactive sessions,
    notebooks and ``python -m`` packages need no guard.
    """

    if getattr(multiprocessing.current_process(), "_inheriting", False):
        raise MainModuleError("solve() was called while a worker process was importing the main file. " + _MAIN_GUARD_HELP)
    if _start_method() not in {"spawn", "forkserver"}:
        return
    main = sys.modules.get("__main__")
    if main is None:
        return
    spec = getattr(main, "__spec__", None)
    spec_name = getattr(spec, "name", None)
    if spec_name is not None:
        if spec_name == "__main__" or spec_name.endswith(".__main__"):
            return  # multiprocessing does not run these again in workers
        path = getattr(spec, "origin", None)
    else:
        path = getattr(main, "__file__", None)
    if path is None:
        return  # interactive interpreter, notebook or `python -c`
    file = Path(path)
    if not file.is_file():
        raise MainModuleError(
            f"The program's main module is {path!r}, which worker processes cannot import "
            "(for example a script piped through stdin). " + _MAIN_GUARD_HELP
        )
    if file.suffix.lower() not in {".py", ".pyw"}:
        return
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return
    if not _has_main_guard(tree):
        raise MainModuleError(f"{file.name} has no `if __name__ == \"__main__\":` block. " + _MAIN_GUARD_HELP)


# -- In-process solve -----------------------------------------------------------------


def _short(exc: BaseException, limit: int = 600) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _solve_error(exc: Exception) -> CoilemError:
    from backend.gmsh_solver import GmshUnavailableError
    from backend.magneto2d_adapter import Magneto2DExecutionError, Magneto2DUnsupportedError
    from backend.solver_contract import SolveCancelledError

    if isinstance(exc, Magneto2DUnsupportedError):
        return InputError(f"This design is outside the Magneto2D solve boundary: {_short(exc)}")
    if isinstance(exc, GmshUnavailableError):
        return SolveError("Gmsh is required for coilEM solves and could not be loaded.", error_code="GMSH_UNAVAILABLE")
    if isinstance(exc, SolveCancelledError):
        return SolveError("The solve was cancelled.", error_code="SOLVER_CANCELLED")
    if isinstance(exc, Magneto2DExecutionError):
        if "failed to converge" in str(exc).lower():
            return SolveError(
                f"Magneto2D found no stable magnetic-field solution within the iteration limit: {_short(exc)}",
                error_code="NONLINEAR_CONVERGENCE_FAILED",
                suggestion="Try solve_params={'nonlinear_solver': 'newton'} or a finer mesh.",
            )
        return SolveError(f"Magneto2D failed: {_short(exc)}", error_code="SOLVER_FAILED")
    if isinstance(exc, ValueError):
        return InputError(f"The solver could not build this design: {_short(exc)}")
    return SolveError(f"The solve failed unexpectedly: {type(exc).__name__}: {_short(exc)}", error_code="SOLVE_FAILED")


def _lean(config: MotorConfig, fields: bool) -> bool:
    """Whether a solve can skip the field-frame pass the app's viewers use.

    The losses and the steel flux-density statistics are computed in that
    pass, so it still runs when either is requested; every other number is
    the same either way.
    """

    if fields:
        return False
    options = config.solve_options or SolveOptionsConfig()
    return not (options.losses_efficiency or options.flux_density)


def _solve_in_process(body: dict[str, Any], on_progress: ProgressCallback | None, *, fields: bool = False) -> dict[str, Any]:
    check_main_module()
    config = prepared_config(body)
    _raise_for_geometry(config)

    from backend.selected_analyses import solve_selected_analyses
    from backend.solver import Magneto2DSolver

    callback_errors: list[BaseException] = []
    progress = None
    if on_progress is not None:
        user_callback = on_progress

        def progress(*args: Any, **_: Any) -> None:
            stage = args[3] if len(args) > 3 and isinstance(args[3], str) else None
            try:
                user_callback(int(args[0] or 0), int(args[1] or 0), stage)
            except BaseException as exc:
                callback_errors.append(exc)
                raise

    solver = Magneto2DSolver(launch_surface=True, visual_outputs=not _lean(config, fields))
    try:
        result = solve_selected_analyses(solver, config, on_progress=progress)
    except KeyboardInterrupt:
        solver.cancel_active_solve()
        raise
    except Exception as exc:
        if callback_errors and exc is callback_errors[-1]:
            raise
        raise _solve_error(exc) from exc
    return result.model_dump(mode="json")


# -- Solve in a running app -------------------------------------------------------------


def _http_error(exc: urllib.error.HTTPError) -> CoilemError:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = message = field = suggestion = None
    if isinstance(detail, dict):
        code, message = detail.get("error_code"), detail.get("message")
        field, suggestion = detail.get("field"), detail.get("suggestion")
    elif isinstance(detail, list) and detail and isinstance(detail[0], dict):
        location = [str(part) for part in detail[0].get("loc", ()) if part != "body"]
        field, message = ".".join(location) or None, detail[0].get("msg")
    elif isinstance(detail, str):
        message = detail
    message = str(message or f"coilEM answered HTTP {exc.code}")
    if field and not message.startswith(field):
        message = f"{field}: {message}"
    if exc.code in (400, 422):
        return InputError(message, field=field, suggestion=suggestion)
    return SolveError(message, error_code=str(code or f"HTTP_{exc.code}"), field=field, suggestion=suggestion)


def _solve_over_http(server: str, body: dict[str, Any], timeout_s: float | None) -> dict[str, Any]:
    base = server.rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    request = urllib.request.Request(
        f"{base}/solve",
        data=json.dumps(body, allow_nan=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    # The app listens on this computer only; never send its requests through a proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from None
    except TimeoutError as exc:
        raise SolveError(
            f"coilEM at {base} did not answer within {timeout_s:g} s; the solve may still be running in the app.",
            error_code="SOLVE_TIMEOUT",
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SolveError(
            f"Could not reach coilEM at {base} ({reason}). Start the app, or leave out server= to solve in this Python process.",
            error_code="SERVER_UNREACHABLE",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise SolveError(f"coilEM at {base} answered without a solve result.", error_code="BAD_RESPONSE")
    return payload


# -- Public entry points --------------------------------------------------------------


def solve(
    motor: MotorLike,
    operating_point: OperatingPoint | None = None,
    *,
    analyses: str | Iterable[str] | None = None,
    quality: str | None = None,
    mesh: str | None = None,
    solve_params: Mapping[str, Any] | None = None,
    server: str | None = None,
    on_progress: ProgressCallback | None = None,
    timeout_s: float | None = 3600.0,
    fields: bool = False,
) -> Result:
    """Solve a motor at one operating point.

    Args:
        motor: A :class:`Motor`, a request mapping, or the path of a request JSON file.
        operating_point: Current, current angle, speed and temperatures. Defaults
            to the motor's saved point, or 0 A when it has none.
        analyses: Names from :data:`ANALYSES` to run, for example
            ``["torque", "back_emf", "cogging"]``. Defaults to the motor's saved
            selection, or the app's defaults.
        quality: ``"quick"``, ``"standard"``, ``"fine"`` or ``"custom"``
            (then set ``rotor_step_deg`` and ``rotor_sweep_range_deg`` in ``solve_params``).
        mesh: ``"coarse"``, ``"normal"``, ``"fine"`` or ``"very_fine"``.
        solve_params: Any other ``solve_params`` field by its request name,
            for example ``{"nonlinear_solver": "picard"}``.
        server: URL of a running coilEM app, such as ``"http://127.0.0.1:2645"``
            (the ``coilem`` launcher's default port).
            The solve then runs in the app and is saved in its run history.
            Leave it out to solve in this Python process.
        on_progress: ``callback(done, total, stage)`` for in-process solves.
        timeout_s: How long to wait for the app's answer when ``server`` is given.
        fields: Also build the field pictures for the app's viewers
            (field-line frames, playback). Left out by default: the solve
            then skips the field-frame pass unless the losses or flux-density
            analysis needs it, which saves a large part of the solve time,
            and every number in the result is the same.

    Raises:
        InputError: The request is not accepted; ``.field`` names the input.
        SolveError: The solve started but did not finish; ``.error_code`` says why.
        MainModuleError: In-process solves need an ``if __name__ == "__main__":``
            guard in the calling script on Windows (see :func:`check_main_module`).
    """

    body = build_request(motor, operating_point, analyses=analyses, quality=quality, mesh=mesh, solve_params=solve_params)
    if server is None:
        data = _solve_in_process(body, on_progress, fields=fields)
    else:
        if on_progress is not None:
            raise InputError("on_progress reports in-process solves only; the app's /solve route sends no progress", field="on_progress")
        data = _solve_over_http(str(server), body, timeout_s)
    result = Result(data, request=body)
    return result if fields else result.without_fields()


@dataclass(frozen=True)
class SweepPoint:
    """One point of a sweep: its operating point and either a result or the error it raised."""

    operating_point: OperatingPoint
    result: Result | None = None
    error: CoilemError | None = None

    @property
    def ok(self) -> bool:
        return self.result is not None


class Sweep(Sequence[SweepPoint]):
    """The points of a current / current-angle sweep, in the order solved (current-major)."""

    def __init__(self, points: Iterable[SweepPoint], currents_A: Sequence[float], angles_deg: Sequence[float]) -> None:
        self.points: tuple[SweepPoint, ...] = tuple(points)
        self.currents_A: tuple[float, ...] = tuple(currents_A)
        self.angles_deg: tuple[float, ...] = tuple(angles_deg)

    @overload
    def __getitem__(self, index: int) -> SweepPoint: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[SweepPoint]: ...

    def __getitem__(self, index: int | slice) -> SweepPoint | Sequence[SweepPoint]:
        return self.points[index]

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self) -> Iterator[SweepPoint]:
        return iter(self.points)

    @property
    def failed(self) -> list[SweepPoint]:
        return [point for point in self.points if not point.ok]

    def rows(self) -> list[dict[str, Any]]:
        """One dict per point: the operating point, the headline numbers and any error."""

        rows = []
        for point in self.points:
            op = point.operating_point
            row: dict[str, Any] = {"current_A": op.current_A, "current_angle_deg": op.current_angle_deg, "speed_rpm": op.speed_rpm}
            row.update(point.result.metrics() if point.result is not None else dict.fromkeys(Result.METRIC_NAMES))
            row["error"] = str(point.error) if point.error is not None else ""
            rows.append(row)
        return rows

    def to_csv(self, path: str | Path) -> Path:
        """Write :meth:`rows` as CSV; missing values are empty cells."""

        path = Path(path)
        rows = self.rows()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["current_A", "current_angle_deg"])
            writer.writeheader()
            for row in rows:
                writer.writerow({key: "" if value is None else value for key, value in row.items()})
        return path

    def grid(self, metric: str) -> np.ndarray:
        """A metric from :meth:`Result.metrics` as a (currents × angles) array; NaN where unavailable."""

        if metric not in Result.METRIC_NAMES:
            raise InputError(f"Unknown metric {metric!r}; choose from {', '.join(Result.METRIC_NAMES)}", field="metric")
        values = np.full((len(self.currents_A), len(self.angles_deg)), np.nan)
        for index, point in enumerate(self.points):
            value = point.result.metrics()[metric] if point.result is not None else None
            if value is not None:
                values[divmod(index, len(self.angles_deg))] = value
        return values

    def best(self, metric: str = "average_torque_Nm") -> SweepPoint:
        """The solved point with the largest value of ``metric``."""

        candidates = [
            (value, point)
            for point in self.points
            if point.result is not None and (value := point.result.metrics().get(metric)) is not None and math.isfinite(value)
        ]
        if not candidates:
            raise ValueError(f"No solved point has a value for {metric!r}")
        return max(candidates, key=lambda item: item[0])[1]


def _values(value: float | Iterable[float], name: str) -> tuple[float, ...]:
    items = [value] if isinstance(value, (int, float)) else list(value)
    if not items:
        raise InputError(f"{name}: give at least one value", field=name)
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise InputError(f"{name}: every value must be a finite number (got {item!r})", field=name)
    return tuple(float(item) for item in items)


def sweep(
    motor: MotorLike,
    *,
    current_A: float | Iterable[float],
    current_angle_deg: float | Iterable[float] = 0.0,
    operating_point: OperatingPoint | None = None,
    analyses: str | Iterable[str] | None = None,
    quality: str | None = None,
    mesh: str | None = None,
    solve_params: Mapping[str, Any] | None = None,
    server: str | None = None,
    stop_on_error: bool = False,
    on_point: Callable[[int, int, SweepPoint], Any] | None = None,
    fields: bool = False,
    timeout_s: float | None = 3600.0,
) -> Sweep:
    """Solve every combination of phase current and current angle.

    ``operating_point`` supplies the other fields (speed, temperatures);
    it defaults to the motor's saved point. Every point is checked before the
    first solve. A point that fails is kept with its error and the sweep goes
    on, unless ``stop_on_error`` is set. ``on_point(index, total, point)`` is
    called after each point. As in :func:`solve`, the field pictures are
    left out unless ``fields`` is set, which keeps long sweeps fast and small
    in memory. Points share this process's mesh cache: after the first point
    each rotor position re-uses its mesh and only the slot currents change.
    The other arguments are those of :func:`solve`.
    """

    motor = _as_motor(motor)
    base = operating_point or motor.operating_point or OperatingPoint()
    currents = _values(current_A, "current_A")
    angles = _values(current_angle_deg, "current_angle_deg")
    points = [base.replace(current_A=current, current_angle_deg=angle) for current in currents for angle in angles]
    # Validation and each solve read these names; an iterator must be consumed only once.
    if analyses is not None and not isinstance(analyses, str):
        analyses = tuple(analyses)
    options = {"analyses": analyses, "quality": quality, "mesh": mesh, "solve_params": solve_params}
    for point in points:
        build_request(motor, point, **options)
    if server is None:
        check_main_module()
    entries: list[SweepPoint] = []
    for index, point in enumerate(points):
        try:
            result = solve(motor, point, server=server, timeout_s=timeout_s, fields=fields, **options)
            entry = SweepPoint(point, result=result)
        except (InputError, SolveError) as exc:
            if stop_on_error:
                raise
            entry = SweepPoint(point, error=exc)
        entries.append(entry)
        if on_point is not None:
            on_point(index, len(points), entry)
    return Sweep(entries, currents, angles)
