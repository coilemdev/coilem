"""Exceptions raised by the coilEM Python client."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError


class CoilemError(Exception):
    """Base class for every error the client raises.

    Every error has an ``error_code``, and :meth:`to_dict` gives the same
    fields in JSON form: ``error_code``, ``message``, ``field`` and
    ``suggestion`` (None when not known), plus ``problems`` for input errors.
    """

    error_code: str = "COILEM_ERROR"
    field: str | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": self.error_code,
            "message": str(self),
            "field": self.field,
            "suggestion": self.suggestion,
        }
        problems = getattr(self, "problems", None)
        if problems:
            payload["problems"] = [{"field": field, "message": message} for field, message in problems]
        return payload


class InputError(CoilemError, ValueError):
    """A motor, operating point, run setup or solve setting is not accepted.

    ``field`` is the dotted path of the input at fault, such as
    ``"stator.slot_count"`` or ``"operating_point.current_A"``, or ``None``
    when the problem involves several inputs. ``problems`` lists every
    ``(field, message)`` pair found, first one first. ``error_code`` is
    ``INVALID_INPUT`` unless a more specific code applies, for example
    ``SETUP_NOT_FOUND``, ``SETUP_INCOMPATIBLE`` or ``DESIGN_FILE_UNREADABLE``.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        suggestion: str | None = None,
        problems: list[tuple[str | None, str]] | None = None,
        error_code: str = "INVALID_INPUT",
    ) -> None:
        super().__init__(message)
        self.field = field
        self.suggestion = suggestion
        self.problems = problems if problems is not None else [(field, message)]
        self.error_code = error_code


class SolveError(CoilemError, RuntimeError):
    """A solve was accepted but did not finish.

    ``error_code`` is the product's code for the failure, for example
    ``SOLVER_FAILED``, ``NONLINEAR_CONVERGENCE_FAILED``, ``GMSH_UNAVAILABLE``,
    ``SOLVE_TIMEOUT`` or ``SERVER_UNREACHABLE``. The original exception, when
    there is one, is chained as ``__cause__``.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "SOLVER_FAILED",
        field: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field = field
        self.suggestion = suggestion


class MainModuleError(CoilemError, RuntimeError):
    """The calling program cannot be re-imported by the solver's worker processes.

    On Windows (and wherever Python starts processes with ``spawn`` or
    ``forkserver``) every worker imports the program's main file again. Code
    that calls :func:`solve` must therefore live under
    ``if __name__ == "__main__":`` in a saved ``.py`` file.
    """

    error_code = "MAIN_GUARD_REQUIRED"
    suggestion = 'Call solve() from under `if __name__ == "__main__":` in a saved .py file, or use the `coilem solve` command.'


def _location(loc: tuple[Any, ...], prefix: str | None) -> str | None:
    parts = [str(part) for part in loc]
    if prefix:
        parts.insert(0, prefix)
    return ".".join(parts) or None


def _shown_input(value: Any) -> str:
    if isinstance(value, (bool, int, float)) or value is None:
        return f" (got {value!r})"
    if isinstance(value, str) and len(value) <= 40:
        return f" (got {value!r})"
    return ""


def input_error_from_validation(
    exc: ValidationError,
    *,
    prefix: str | None = None,
    rename: dict[str, str] | None = None,
) -> InputError:
    """Turn a pydantic ``ValidationError`` into an :class:`InputError`.

    ``prefix`` is the section the model sits in (``"stator"``), and
    ``rename`` maps request field names onto the names the caller used.
    """

    problems: list[tuple[str | None, str]] = []
    for error in exc.errors(include_url=False, include_context=False):
        loc = tuple(error["loc"])
        if rename and loc and str(loc[0]) in rename:
            loc = (rename[str(loc[0])], *loc[1:])
        field = _location(loc, prefix)
        message = str(error["msg"]).removeprefix("Value error, ").removeprefix("Assertion failed, ")
        if error.get("type") not in {"value_error", "assertion_error"}:
            message += _shown_input(error.get("input"))
        problems.append((field, message))
    if not problems:  # pragma: no cover - pydantic always reports one
        problems.append((prefix, str(exc)))
    lines = [f"{field}: {message}" if field else message for field, message in problems]
    text = lines[0] if len(lines) == 1 else f"{len(lines)} problems: " + "; ".join(lines)
    return InputError(text, field=problems[0][0], problems=problems)
