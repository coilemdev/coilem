"""Headless ``coilem`` commands for scripts, terminals and coding agents.

    coilem check  motor.coilem --setup "High Speed"
    coilem solve  motor.coilem --setup "High Speed" --out result.json
    coilem thermal motor.coilem --ambient 40 --out thermal.json
    coilem setups motor.coilem
    coilem schema --out motor-schema.json
    coilem version

Each command writes one JSON document to ``--out`` (standard output by
default) and nothing else there; progress and messages go to standard error.
Every document has ``schema`` (for example ``coilem.cli.solve/v1``), ``ok``
and ``coilem_version``. A failed command writes a ``coilem.cli.error/v1``
document with ``error_code``, ``message``, ``field`` and ``suggestion``, and
exits with one of :data:`EXIT_CODES`. The commands use the Python client, so
they check, apply setups and solve exactly as :func:`backend.client.solve`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import platform
import signal
import sys
import time
import traceback
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from backend import __version__
from backend.client._errors import CoilemError, InputError, MainModuleError, SolveError

COMMANDS: tuple[str, ...] = ("check", "solve", "thermal", "setups", "schema", "version")

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_INVALID_INPUT = 3
EXIT_SOLVE_FAILED = 4
EXIT_CANCELLED = 130
EXIT_CODES: dict[int, str] = {
    EXIT_OK: "success",
    EXIT_INTERNAL: "unexpected internal error",
    EXIT_USAGE: "invalid command line (usage printed on standard error)",
    EXIT_INVALID_INPUT: "invalid input: design file, run setup, settings or output path; nothing was solved",
    EXIT_SOLVE_FAILED: "the solve started but failed (solver, convergence, timeout or app not reachable)",
    EXIT_CANCELLED: "cancelled (Ctrl+C, Ctrl+Break or SIGTERM)",
}
ERROR_CODES: dict[str, str] = {
    "INVALID_INPUT": "an input or setting is not accepted; field names it",
    "DESIGN_FILE_UNREADABLE": "the design file is missing or is not JSON",
    "DESIGN_SCHEMA_UNSUPPORTED": "the design file is from an older app version; open and save it in the app",
    "OUTSIDE_SOLVE_BOUNDARY": "the design is outside what the Magneto2D solver supports",
    "SETUP_NOT_FOUND": "no saved run setup has that name or id",
    "SETUP_UNREADABLE": "the run setup is saved but this version cannot read it",
    "SETUP_INCOMPATIBLE": "the run setup was saved for another reference model or convention",
    "SETUP_SOLVER_UNAVAILABLE": "the run setup uses a solver scripted solves do not support",
    "OUTPUT_UNWRITABLE": "the --out file cannot be written",
    "THERMAL_LOSSES_MISSING": "the solved result has no losses or no torque, which the thermal estimate starts from",
    "SOLVER_FAILED": "Magneto2D failed",
    "NONLINEAR_CONVERGENCE_FAILED": "no stable magnetic-field solution within the iteration limit",
    "GMSH_UNAVAILABLE": "Gmsh could not be loaded",
    "SOLVER_CANCELLED": "the solve was cancelled",
    "SOLVE_TIMEOUT": "the app did not answer within --timeout",
    "SERVER_UNREACHABLE": "no coilEM app answered at --server",
    "BAD_RESPONSE": "the app answered without a solve result",
    "SOLVE_FAILED": "the solve failed unexpectedly",
    "INTERNAL_ERROR": "a bug: please report it with the message",
}
DOCUMENT_SCHEMAS: dict[str, str] = {command: f"coilem.cli.{command}/v1" for command in COMMANDS} | {"error": "coilem.cli.error/v1"}
# Unit of a setting, from the suffix of its name.
UNIT_SUFFIXES: dict[str, str] = {
    "mm": "mm",
    "deg": "deg",
    "rpm": "rpm",
    "A": "A",
    "V": "V",
    "W": "W",
    "C": "degC",
    "T": "T",
    "Hz": "Hz",
    "s": "s",
    "pct": "%",
    "Nm": "N·m",
}


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        raise _UsageError(f"{self.prog}: error: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="coilem",
        description=(
            "Headless coilEM commands. Each writes one JSON document to --out or standard output; "
            "progress and messages go to standard error. Run `coilem` with no command to open the app."
        ),
        epilog="Exit codes: " + "; ".join(f"{code} {text}" for code, text in EXIT_CODES.items()),
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND", parser_class=_Parser)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--out", metavar="PATH", help="write the JSON document here instead of standard output")
        sub.add_argument("--compact", action="store_true", help="write the JSON on one line")
        sub.add_argument("--quiet", action="store_true", help="print nothing on standard error except errors")

    def request(sub: argparse.ArgumentParser) -> None:
        from backend.client._solve import MESH_DENSITIES, QUALITIES

        sub.add_argument("design", help="a .coilem design file saved by the app, or a request JSON")
        sub.add_argument(
            "--setup",
            "--profile",
            dest="setup",
            metavar="NAME",
            help="apply this saved run setup (name or id); default: the design's saved settings",
        )
        sub.add_argument("--analyses", metavar="LIST", help="comma-separated analyses to run, e.g. torque,back_emf,cogging")
        sub.add_argument("--quality", choices=QUALITIES, help="rotor-position plan")
        sub.add_argument("--mesh", choices=MESH_DENSITIES, help="mesh density")
        sub.add_argument(
            "--set",
            dest="settings",
            action="append",
            default=[],
            metavar="NAME=VALUE",
            help="set a solve_params field, e.g. --set current_amplitude_A=20 (VALUE is read as JSON when it parses)",
        )
        common(sub)

    check = commands.add_parser("check", help="choose the setup and run the pre-solve checks, without meshing or solving")
    request(check)
    solve = commands.add_parser("solve", help="solve a design and write compact results")
    request(solve)
    solve.add_argument("--server", metavar="URL", help="solve in a running coilEM app, e.g. http://127.0.0.1:2645")
    solve.add_argument("--timeout", type=float, default=3600.0, metavar="SECONDS", help="how long to wait for --server (default 3600)")
    solve.add_argument("--fields", action="store_true", help="also keep the field pictures for the app's viewers (large)")
    solve.add_argument(
        "--progress",
        choices=("auto", "text", "json", "none"),
        default="auto",
        help="progress on standard error: text, JSON lines or none (auto: text on a terminal)",
    )
    thermal = commands.add_parser(
        "thermal",
        help="estimate the steady-state temperature of each part, from a design (solved first) or a solved result",
        description=(
            "Estimate the steady-state temperature of each part. DESIGN is a .coilem design file, which is solved first with the "
            "torque and losses analyses added, or a result file written by `coilem solve` with those analyses, which is not "
            "solved again. Without cooling options the app's still-air starter values are used. The estimate is experimental. "
            "An estimate that cannot be given (for example a motor that would settle far too hot) still exits 0: "
            "read thermal.status and thermal.status_reason."
        ),
    )
    request(thermal)
    thermal.add_argument("--server", metavar="URL", help="solve in a running coilEM app, e.g. http://127.0.0.1:2645")
    thermal.add_argument("--timeout", type=float, default=3600.0, metavar="SECONDS", help="how long to wait for --server (default 3600)")
    thermal.add_argument(
        "--progress",
        choices=("auto", "text", "json", "none"),
        default="auto",
        help="solve progress on standard error: text, JSON lines or none (auto: text on a terminal)",
    )
    thermal.add_argument("--cooling", choices=("still_air", "forced_air", "liquid_jacket"),
                         help="kind of cooling (default still_air); the others need their heat-transfer values with --thermal")
    thermal.add_argument("--ambient", type=float, metavar="C", help="temperature of the air or coolant that carries the heat away (default 25)")
    thermal.add_argument("--insulation", choices=("A", "B", "F", "H"), help="winding insulation class (default F)")
    thermal.add_argument(
        "--thermal",
        dest="thermal_values",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="set a thermal input, e.g. --thermal housing_h_W_m2K=60 (names and units: coilem schema)",
    )
    thermal.add_argument("--thermal-inputs", metavar="PATH", help="a JSON file of thermal inputs; --thermal values are applied over it")
    thermal.add_argument("--no-copper-feedback", action="store_true",
                         help="keep the solved copper loss instead of letting it rise with the winding temperature")
    setups = commands.add_parser("setups", help="list a design's saved run setups and whether each can be used")
    setups.add_argument("design", help="a .coilem design file saved by the app")
    common(setups)
    common(commands.add_parser("schema", help="describe the inputs, units, limits, run setups, documents and exit codes"))
    common(commands.add_parser("version", help="the installed coilEM, Magneto2D and Python versions"))
    return parser


# -- Output ---------------------------------------------------------------------------------


def _finite(value: Any) -> Any:
    """JSON-safe data: non-finite numbers become null (missing), never zero."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value


def _document(command: str, ok: bool, **content: Any) -> dict[str, Any]:
    return {"schema": DOCUMENT_SCHEMAS["error" if not ok else command], "ok": ok, "command": command, "coilem_version": __version__, **content}


def _write(document: Mapping[str, Any], out: str | None, compact: bool) -> None:
    to_stdout = out in (None, "-")
    # Redirected Windows streams can use a legacy code page. JSON escapes keep
    # their bytes portable and round-trip every character, including error paths.
    escape_unicode = to_stdout and (sys.stdout.encoding or "").lower() != "utf-8"
    text = json.dumps(_finite(document), indent=None if compact else 2, ensure_ascii=escape_unicode, allow_nan=False) + "\n"
    if to_stdout:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    path = Path(str(out))
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def _check_out(out: str | None) -> None:
    if out in (None, "-"):
        return
    path = Path(str(out))
    if path.is_dir() or not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
        raise InputError(
            f"--out {out}: cannot write a file there",
            field="out",
            error_code="OUTPUT_UNWRITABLE",
            suggestion="Give a file path in an existing, writable folder.",
        )


def _message(args: argparse.Namespace, text: str) -> None:
    if not getattr(args, "quiet", False):
        print(text, file=sys.stderr, flush=True)


# -- Inputs ---------------------------------------------------------------------------------


def _motor(path: str) -> Any:
    from backend.client._inputs import Motor

    try:
        return Motor.load(path)
    except OSError as exc:
        raise InputError(
            f"{path}: cannot read the design file ({exc.strerror or exc})",
            field="design",
            error_code="DESIGN_FILE_UNREADABLE",
        ) from None


def _settings(pairs: Sequence[str]) -> dict[str, Any] | None:
    from backend.client._inputs import refuse_unknown_inputs
    from backend.models.config import SolveParams

    if not pairs:
        return None
    settings: dict[str, Any] = {}
    for pair in pairs:
        name, separator, text = pair.partition("=")
        name = name.strip()
        if not separator or not name:
            raise _UsageError(f"coilem: error: --set expects NAME=VALUE, got {pair!r}")
        refuse_unknown_inputs(SolveParams, {name: None}, "solve_params")
        try:
            settings[name] = json.loads(text)
        except json.JSONDecodeError:
            settings[name] = text
    return settings


def _analyses(text: str | None) -> list[str] | None:
    if text is None:
        return None
    return [name.strip() for name in text.split(",") if name.strip()]


def _request_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "analyses": _analyses(args.analyses),
        "quality": args.quality,
        "mesh": args.mesh,
        "solve_params": _settings(args.settings),
        "setup": args.setup,
    }


def _design(args: argparse.Namespace, motor: Any) -> dict[str, Any]:
    name = motor.to_request().get("name")
    return {"path": str(Path(args.design).resolve()), "name": name if isinstance(name, str) else None}


# -- Commands -------------------------------------------------------------------------------


def _check(args: argparse.Namespace) -> dict[str, Any]:
    from backend.client._solve import prepare

    options = _request_options(args)
    _check_out(args.out)
    motor = _motor(args.design)
    prepared = prepare(motor, **options)
    _notes(args, prepared.setup)
    return _document(
        "check",
        True,
        design=_design(args, motor),
        setup=prepared.setup.to_dict(),
        effective=prepared.effective_settings(),
        warnings=prepared.warnings,
        request=prepared.request,
    )


def _notes(args: argparse.Namespace, use: Any) -> None:
    label = f"run setup {use.setup.name!r}" if use.setup is not None else "the design's saved settings"
    _message(args, f"coilem: using {label}" + (" (changed by the given settings)" if use.modified else ""))
    for note in use.notes:
        _message(args, f"coilem: note: {note}")


class _Progress:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.last: tuple[str | None, int] | None = None

    def __call__(self, done: int, total: int, stage: str | None) -> None:
        if self.mode == "json":
            print(json.dumps({"event": "progress", "done": done, "total": total, "stage": stage}), file=sys.stderr, flush=True)
            return
        step = int(10 * done / total) if total else 0
        if (stage, step) != self.last:
            self.last = (stage, step)
            print(f"coilem: {stage or 'solving'} {done}/{total}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def _cancel_on_signals() -> Iterator[None]:
    """Turn Ctrl+C, SIGTERM and Ctrl+Break on Windows into the KeyboardInterrupt that cancels a solve.

    SIGINT is set explicitly too: a process started in the background by a
    shell or a job runner inherits SIGINT ignored, and must still cancel.
    """

    def interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    names = ["SIGINT", "SIGTERM", "SIGBREAK"]
    previous = {}
    for name in names:
        number = getattr(signal, name, None)
        if number is not None:
            with contextlib.suppress(ValueError, OSError):
                previous[number] = signal.signal(number, interrupt)
    try:
        yield
    finally:
        for number, handler in previous.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(number, handler)


def _solve(args: argparse.Namespace) -> dict[str, Any]:
    from backend.client._solve import prepare, solve

    options = _request_options(args)
    _check_out(args.out)
    motor = _motor(args.design)
    prepared = prepare(motor, **options)
    _notes(args, prepared.setup)
    mode = args.progress
    if mode == "auto":
        mode = "text" if sys.stderr.isatty() and not args.quiet else "none"
    progress = _Progress(mode) if mode != "none" and args.server is None else None
    started = time.monotonic()
    with _cancel_on_signals():
        result = solve(motor, server=args.server, timeout_s=args.timeout, fields=args.fields, on_progress=progress, **options)
    _message(args, f"coilem: solved in {time.monotonic() - started:.1f} s")
    return _document(
        "solve",
        True,
        solver={"name": "magneto2d", "mode": "server" if args.server else "in_process", "server": args.server},
        design=_design(args, motor),
        setup=result.setup,
        effective=prepared.effective_settings(),
        warnings=prepared.warnings,
        metrics=result.metrics(),
        request=result.request,
        result=result.data,
    )


def _thermal_values(args: argparse.Namespace) -> dict[str, Any]:
    """Thermal inputs from --thermal-inputs, then --thermal NAME=VALUE over them."""

    values: dict[str, Any] = {}
    if args.thermal_inputs:
        try:
            loaded = json.loads(Path(args.thermal_inputs).read_text(encoding="utf-8"))
        except OSError as exc:
            raise InputError(f"{args.thermal_inputs}: cannot read the thermal inputs file ({exc.strerror or exc})",
                             field="thermal_inputs", error_code="DESIGN_FILE_UNREADABLE") from None
        except json.JSONDecodeError as exc:
            raise InputError(f"{args.thermal_inputs}: not JSON ({exc.msg})", field="thermal_inputs", error_code="DESIGN_FILE_UNREADABLE") from None
        if not isinstance(loaded, Mapping):
            raise InputError(f"{args.thermal_inputs}: expected a JSON object of thermal input names and values", field="thermal_inputs")
        # A file saved by this command or by ThermalEstimate.save carries its inputs under "inputs" or "thermal_inputs".
        values.update(loaded.get("thermal_inputs") or loaded.get("inputs") or loaded)
    for pair in args.thermal_values:
        name, separator, text = pair.partition("=")
        name = name.strip()
        if not separator or not name:
            raise _UsageError(f"coilem: error: --thermal expects NAME=VALUE, got {pair!r}")
        try:
            values[name] = json.loads(text)
        except json.JSONDecodeError:
            values[name] = text
    return values


def _is_result_file(path: str) -> bool:
    from backend.client._results import CLI_SOLVE_SCHEMA, RESULT_FILE_SCHEMA

    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False  # The design loader reports an unreadable file in its own words.
    if not isinstance(loaded, Mapping):
        return False
    return loaded.get("schema") in (RESULT_FILE_SCHEMA, CLI_SOLVE_SCHEMA) or isinstance(loaded.get("summary"), Mapping)


def _thermal(args: argparse.Namespace) -> dict[str, Any]:
    from backend.client._inputs import ANALYSES
    from backend.client._results import Result
    from backend.client._solve import prepare, solve
    from backend.client._thermal import thermal

    _check_out(args.out)
    values = _thermal_values(args)
    content: dict[str, Any] = {}
    if _is_result_file(args.design):
        if args.setup or args.analyses or args.quality or args.mesh or args.settings or args.server:
            raise _UsageError("coilem: error: a solved result is not solved again, so the solve options do not apply to it")
        result = Result.load(args.design)
        _message(args, "coilem: using the solved result; nothing is solved")
        content["source"] = {"kind": "result", "path": str(Path(args.design).resolve())}
    else:
        options = _request_options(args)
        motor = _motor(args.design)
        prepared = prepare(motor, **options)
        # The estimate starts from the torque and the losses, so both are solved whatever the design had selected.
        flags = prepared.request.get("solve_options") or {}
        selected = [name for name, flag in ANALYSES.items() if flags.get(flag)]
        options["analyses"] = list(dict.fromkeys([*selected, "torque", "losses"]))
        prepared = prepare(motor, **options)
        _notes(args, prepared.setup)
        mode = args.progress
        if mode == "auto":
            mode = "text" if sys.stderr.isatty() and not args.quiet else "none"
        progress = _Progress(mode) if mode != "none" and args.server is None else None
        started = time.monotonic()
        with _cancel_on_signals():
            result = solve(motor, server=args.server, timeout_s=args.timeout, on_progress=progress, **options)
        _message(args, f"coilem: solved in {time.monotonic() - started:.1f} s")
        content |= {
            "source": {"kind": "solved"}, "design": _design(args, motor), "setup": result.setup,
            "effective": prepared.effective_settings(), "warnings": prepared.warnings, "solve_metrics": result.metrics(),
        }
    estimate = thermal(result, cooling=args.cooling, ambient_C=args.ambient, insulation_class=args.insulation,
                       inputs=values or None, copper_feedback=not args.no_copper_feedback)
    _message(args, f"coilem: thermal estimate (experimental): {estimate.summary_text()}")
    return _document("thermal", True, **content, metrics=estimate.metrics(), thermal_inputs=estimate.inputs,
                     thermal=estimate.data, request=result.request)


def _setups(args: argparse.Namespace) -> dict[str, Any]:
    from backend.client._setups import _library_notes, setup_statuses

    _check_out(args.out)
    motor = _motor(args.design)
    statuses, library = setup_statuses(motor.to_request())
    active = {"id": library.active_id, "version": library.active_version} if library.active_id else None
    return _document(
        "setups",
        True,
        design=_design(args, motor),
        active=active,
        setups=[status.to_dict() for status in statuses],
        notes=_library_notes(library),
    )


def _with_units(schema: Any) -> Any:
    """Add ``x-unit`` to every property whose name ends in a unit suffix (``_mm``, ``_deg``, ...)."""

    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, definition in properties.items():
                suffix = name.rsplit("_", 1)[-1] if "_" in name else ""
                if suffix in UNIT_SUFFIXES and isinstance(definition, dict):
                    definition.setdefault("x-unit", UNIT_SUFFIXES[suffix])
        for value in schema.values():
            _with_units(value)
    elif isinstance(schema, list):
        for value in schema:
            _with_units(value)
    return schema


def _setup_schema() -> dict[str, Any]:
    from backend.client._setups import ENUMS, NUMERICAL_KEYS, OPERATING_KEYS, OUTPUT_KEYS, REFERENCE_CASES, REQUIRED_PARAMETERS

    return {
        "description": (
            "A saved run setup, as stored in a .coilem file's run_setups.profiles. Operating-only setups "
            "(includesNumerics false) hold only the operating keys; others also hold the numerical keys."
        ),
        "type": "object",
        "required": ["id", "version", "name", "includesNumerics", "angleConvention", "referenceModel", "parameters", "outputs"],
        "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 200},
            "version": {"type": "integer", "minimum": 1},
            "name": {"type": "string", "minLength": 1, "maxLength": 100},
            "includesNumerics": {"type": "boolean"},
            "solver": {"enum": ["magneto2d", "elmer"], "description": "required when includesNumerics is true"},
            "angleConvention": {"enum": ["q_axis", "pyleecan_d_axis"]},
            "referenceModel": {"enum": [None, *REFERENCE_CASES]},
            "referenceCase": {"enum": sorted({case for cases in REFERENCE_CASES.values() for case in cases if case}) + [None]},
            "parameters": {
                "type": "object",
                "description": "solve_params fields by request name; see design.$defs.SolveParams for units and limits",
                "operating_keys": list(OPERATING_KEYS),
                "numerical_keys": list(NUMERICAL_KEYS),
                "required": list(REQUIRED_PARAMETERS),
                "enums": {key: list(values) for key, values in ENUMS.items()},
            },
            "outputs": {"type": "object", "required": list(OUTPUT_KEYS), "additionalProperties": False},
            "map": {"description": "torque_speed_analysis settings, or null"},
        },
    }


def _schema(args: argparse.Namespace) -> dict[str, Any]:
    from backend.client._inputs import _OPERATING_POINT_FIELDS, ANALYSES
    from backend.client._setups import REFERENCE_SETUPS
    from backend.client._solve import MESH_DENSITIES, QUALITIES
    from backend.client._thermal import COOLING_MODES, INSULATION_CLASSES, STILL_AIR_STARTER
    from backend.models.config import MotorConfig
    from backend.models.thermal import ThermalInputs

    _check_out(args.out)
    return _document(
        "schema",
        True,
        design=_with_units(MotorConfig.model_json_schema()),
        operating_point={
            "description": "OperatingPoint fields of the Python client and the solve_params field each sets",
            "fields": dict(_OPERATING_POINT_FIELDS),
        },
        analyses={"description": "analysis names for --analyses and the solve_options flag each switches on", "names": dict(ANALYSES)},
        qualities=list(QUALITIES),
        mesh_densities=list(MESH_DENSITIES),
        run_setup=_setup_schema(),
        thermal={
            "description": "thermal inputs for `coilem thermal --thermal NAME=VALUE` and the Python client's thermal(); "
                           "an outer-rotor motor also uses mount_to_ambient_K_W",
            "inputs": _with_units(ThermalInputs.model_json_schema()),
            "still_air_starter": STILL_AIR_STARTER,
            "cooling": list(COOLING_MODES),
            "insulation_classes": list(INSULATION_CLASSES),
        },
        reference_setups=[setup.to_dict() for setup in REFERENCE_SETUPS],
        documents=DOCUMENT_SCHEMAS,
        exit_codes={str(code): text for code, text in EXIT_CODES.items()},
        error_codes=ERROR_CODES,
        units=UNIT_SUFFIXES,
    )


def _version(args: argparse.Namespace) -> dict[str, Any]:
    from backend.resources import build_identity

    _check_out(args.out)
    return _document(
        "version",
        True,
        build=build_identity(),
        python=platform.python_version(),
        platform={"system": platform.system(), "machine": platform.machine()},
        documents=DOCUMENT_SCHEMAS,
    )


HANDLERS = {"check": _check, "solve": _solve, "thermal": _thermal, "setups": _setups, "schema": _schema, "version": _version}


def _exit_code(error: CoilemError) -> int:
    if isinstance(error, InputError):
        return EXIT_INVALID_INPUT
    if isinstance(error, SolveError):
        return EXIT_CANCELLED if error.error_code == "SOLVER_CANCELLED" else EXIT_SOLVE_FAILED
    if isinstance(error, MainModuleError):
        return EXIT_INTERNAL
    return EXIT_SOLVE_FAILED


def main(argv: Sequence[str]) -> int:
    """Run one command; return its exit code."""

    try:
        args = _parser().parse_args(list(argv))
    except _UsageError as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    command = args.command
    out, compact = getattr(args, "out", None), getattr(args, "compact", False)
    try:
        document = HANDLERS[command](args)
    except _UsageError as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        error: dict[str, Any] = SolveError("The command was cancelled.", error_code="SOLVER_CANCELLED").to_dict()
        code = EXIT_CANCELLED
    except CoilemError as exc:
        error, code = exc.to_dict(), _exit_code(exc)
    except Exception as exc:  # noqa: BLE001 - reported as a document, with the traceback on stderr
        if os.environ.get("COILEM_DEBUG"):
            traceback.print_exc()
        message = f"{type(exc).__name__}: {' '.join(str(exc).split())[:600]}"
        error = {"error_code": "INTERNAL_ERROR", "message": message, "field": None, "suggestion": "Set COILEM_DEBUG=1 for a traceback."}
        code = EXIT_INTERNAL
    else:
        try:
            _write(document, out, compact)
        except OSError as exc:
            print(f"coilem: cannot write {out}: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT
        if out not in (None, "-"):
            _message(args, f"coilem: wrote {out}")
        return EXIT_OK
    print(f"coilem: {error['message']}", file=sys.stderr, flush=True)
    target = out if error.get("error_code") != "OUTPUT_UNWRITABLE" else None
    try:
        _write(_document(command, False, error=error, exit_code=code), target, compact)
    except OSError:
        _write(_document(command, False, error=error, exit_code=code), None, compact)
    return code
