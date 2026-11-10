"""Small column formatter for backend console logs."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TextIO

_TIME_WIDTH = 23
# 7 fits "WARNING" / "CRITICAL"; was 5 which truncated WARNING → WARNI in logs.
_LEVEL_WIDTH = 7
_SOURCE_WIDTH = 14
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:access_token|id_token|refresh_token|token|code|authorization)=)[^&\s]+")
_INLINE_PAYLOAD_RE = re.compile(r'(?i)(["\']?(?:config|input_payload|motor_config)["\']?\s*[:=]\s*)\{.*\}')
_SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "id_token",
    "refresh_token",
    "token",
    "jwt",
    "password",
    "secret",
    "client_secret",
    "invite_code",
}
_EMAIL_KEYS = {"email", "user_email"}
_MOTOR_PAYLOAD_KEYS = {"config", "input_payload", "motor_config", "request_body", "body"}


def _timestamp_from_seconds(seconds: float | None = None) -> str:
    dt = datetime.fromtimestamp(seconds) if seconds is not None else datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def sanitize_log_message(message: object) -> str:
    """Return a privacy-safe string for logs.

    Cloud beta support logs must not carry bearer tokens, email addresses, or
    full motor configs. Structured values keep a tiny topology/pole/slot
    summary where useful and redact the rest.
    """

    sanitized = _sanitize_value(message)
    if isinstance(sanitized, str):
        return sanitized
    try:
        return json.dumps(sanitized, default=str, sort_keys=True)
    except TypeError:
        return _sanitize_text(str(sanitized))


def sanitize_log_value(value: object) -> object:
    """Return a structured privacy-safe value for telemetry/log sinks."""

    return _sanitize_value(value)


def format_log_event(source: str, message: object, *, level: str = "INFO", created: float | None = None) -> str:
    """Format one event as timestamp | level | source | message."""
    normalized_source = str(source or "APP").upper().replace(" ", "_")
    normalized_level = str(level or "INFO").upper()
    lines = sanitize_log_message(message).splitlines() or [""]
    first_prefix = (
        f"{_timestamp_from_seconds(created):<{_TIME_WIDTH}} | "
        f"{normalized_level:<{_LEVEL_WIDTH}.{_LEVEL_WIDTH}} | "
        f"{normalized_source:<{_SOURCE_WIDTH}.{_SOURCE_WIDTH}} | "
    )
    continuation_prefix = (
        f"{'':<{_TIME_WIDTH}} | "
        f"{'':<{_LEVEL_WIDTH}} | "
        f"{'':<{_SOURCE_WIDTH}} | "
    )
    return "\n".join(
        (first_prefix if index == 0 else continuation_prefix) + line
        for index, line in enumerate(lines)
    )


# Optional taps that observe sanitized log events (e.g. per-job diagnostics
# capture). Empty by default so there is no overhead unless a capture session
# registers one. Each tap receives (source, level, sanitized_message, created).
_LOG_TAPS: list["LogTap"] = []

try:  # pragma: no cover - typing only
    from typing import Protocol

    class LogTap(Protocol):
        def __call__(self, source: str, level: str, message: str, created: float) -> None: ...
except Exception:  # pragma: no cover
    LogTap = object  # type: ignore[assignment,misc]


def register_log_tap(tap: "LogTap") -> None:
    if tap not in _LOG_TAPS:
        _LOG_TAPS.append(tap)


def unregister_log_tap(tap: "LogTap") -> None:
    try:
        _LOG_TAPS.remove(tap)
    except ValueError:
        pass


def _emit_to_taps(source: str, level: str, sanitized_message: str, created: float) -> None:
    if not _LOG_TAPS:
        return
    for tap in list(_LOG_TAPS):
        try:
            tap(source, level, sanitized_message, created)
        except Exception:
            # A tap must never break logging.
            pass


def log_event(
    source: str,
    message: object,
    *,
    level: str = "INFO",
    stream: TextIO | None = None,
) -> None:
    sanitized = sanitize_log_message(message)
    normalized_source = str(source or "APP").upper().replace(" ", "_")
    normalized_level = str(level or "INFO").upper()
    print(
        format_log_event(normalized_source, sanitized, level=normalized_level),
        file=stream or sys.stdout,
        flush=True,
    )
    _emit_to_taps(normalized_source, normalized_level, sanitized, time.time())


def _sanitize_value(value: object, key: str | None = None) -> object:
    key_name = str(key or "").lower()
    if key_name in _SENSITIVE_KEYS:
        return "[redacted]"
    if key_name in _EMAIL_KEYS:
        return "[redacted-email]" if value else value
    if key_name in _MOTOR_PAYLOAD_KEYS and isinstance(value, Mapping):
        return _summarize_motor_payload(value)
    if isinstance(value, Mapping):
        return {str(item_key): _sanitize_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bytes):
        return f"[redacted-bytes:{len(value)}]"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if key_name in _MOTOR_PAYLOAD_KEYS:
            return f"[redacted-list:{len(value)}]"
        return [_sanitize_value(item) for item in value]
    return value


def _sanitize_text(value: str) -> str:
    sanitized = _BEARER_RE.sub("Bearer [redacted]", value)
    sanitized = _JWT_RE.sub("[redacted-jwt]", sanitized)
    sanitized = _EMAIL_RE.sub("[redacted-email]", sanitized)
    sanitized = _QUERY_SECRET_RE.sub(r"\1[redacted]", sanitized)
    sanitized = _INLINE_PAYLOAD_RE.sub(r"\1{[redacted-motor-payload]}", sanitized)
    return sanitized


def _summarize_motor_payload(value: Mapping[str, object]) -> dict[str, object]:
    payload = value.get("config")
    if not isinstance(payload, Mapping):
        payload = value
    stator = payload.get("stator") if isinstance(payload, Mapping) else None
    rotor = payload.get("rotor") if isinstance(payload, Mapping) else None
    return {
        "redacted": "motor-payload",
        "kind": value.get("kind") if isinstance(value.get("kind"), str) else None,
        "solver": value.get("solver") if isinstance(value.get("solver"), str) else None,
        "topology": payload.get("topology") if isinstance(payload, Mapping) else None,
        "poles": rotor.get("pole_count") if isinstance(rotor, Mapping) else None,
        "slots": stator.get("slot_count") if isinstance(stator, Mapping) else None,
    }


# Sub-tags that all belong to the FEMM domain. When tagged_log sees one of
# these, it routes to the FEMM source column and embeds the original tag at
# the start of the message so you can still grep for "[SOLVE_TRACE]" etc.
# This keeps the SOURCE column coarse-grained ("which subsystem?") while
# preserving the fine-grained category in the message.
_FEMM_SUBTAGS: frozenset[str] = frozenset({
    "GEOM",
    "LABEL",
    "SOLVE_TRACE",
    "MAT",
    "SLOT",
    "FLUX",
    "FLUX-DIAG",
    "FEMM-AIRGAP",
    "FD-DECOMP",
    "THD",
    "VIEW",
    "MESH",
    # FEMM-specific tags emitted via logger.info/warning rather than tagged_log.
    "CACHE",
    "DEBUG",
})


def tagged_log(*args: object, level: str = "INFO", **_kwargs: object) -> None:
    """Drop-in replacement for ``print()`` calls that emit ``[TAG] message``.

    Routes the message through the column formatter so it ends up looking like
    ``2026-05-07 15:39:42.734 | INFO  | TAG            | message``, matching
    the rest of the backend log. Unknown kwargs (e.g. ``file=sys.stderr`` or
    ``flush=True`` — common on the legacy print() calls) are accepted and
    ignored so the swap is mechanical.

    Tag remapping: tags listed in ``_FEMM_SUBTAGS`` (GEOM, LABEL, SOLVE_TRACE,
    MAT, SLOT, FLUX, FLUX-DIAG, FEMM-AIRGAP, FD-DECOMP, THD, VIEW, MESH) all
    log under the ``FEMM`` source column with the original tag preserved as
    a ``[TAG]`` prefix in the message body. This keeps the SOURCE column at
    a stable, coarse granularity ("FEMM solver activity") so logs are easier
    to filter by subsystem, while keeping the fine-grained category visible
    inline.

    If the joined message doesn't start with ``[TAG]``, it's logged under
    the generic ``APP`` source.
    """
    prefixed = " ".join(str(a) for a in args)
    if prefixed.startswith("[") and "] " in prefixed:
        tag, _, message = prefixed[1:].partition("] ")
        if tag in _FEMM_SUBTAGS:
            log_event("FEMM", f"[{tag}] {message}", level=level)
        else:
            log_event(tag, message, level=level)
    else:
        log_event("APP", prefixed, level=level)


class ColumnLogFormatter(logging.Formatter):
    """Logging formatter shared by uvicorn and backend loggers.

    Recognises the `[TAG] message` convention used throughout the backend:
    when a `logger.info("[TAG] ...")` call lands here, the tag is lifted into
    the SOURCE column (with FEMM-subtag remapping applied) so all of the
    backend's bracket-prefixed lines line up consistently — both the print
    style (via ``tagged_log``) and the logging style (via ``logger.*``).
    """

    def format(self, record: logging.LogRecord) -> str:
        message = self._message(record)
        source, message = self._extract_tag(record, message)
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return format_log_event(source, message, level=record.levelname, created=record.created)

    @classmethod
    def _extract_tag(cls, record: logging.LogRecord, message: str) -> tuple[str, str]:
        # If the formatted message starts with a [TAG] literal we treat that
        # as the canonical source — same convention as ``tagged_log``. This
        # is what makes ``logger.warning("[THD] Insufficient data...")`` end
        # up under SOURCE=FEMM with the [THD] preserved in the message.
        if message.startswith("[") and "] " in message:
            tag, _, rest = message[1:].partition("] ")
            if tag in _FEMM_SUBTAGS:
                return "FEMM", f"[{tag}] {rest}"
            if tag:
                return tag, rest
        return cls._source(record), message

    @staticmethod
    def _source(record: logging.LogRecord) -> str:
        if record.name == "uvicorn.access":
            return "HTTP"
        if record.name.startswith("uvicorn"):
            return "UVICORN"
        return record.name.rsplit(".", 1)[-1] or "APP"

    @staticmethod
    def _message(record: logging.LogRecord) -> str:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) >= 5:
            try:
                client_addr, method, path, _http_version, status_code = record.args[:5]
                return f"{str(method):<7} {str(status_code):<3} {path}  client={client_addr}"
            except Exception:
                return record.getMessage()
        return record.getMessage()


def configure_backend_logging() -> None:
    """Install the column formatter on uvicorn handlers and the root logger.

    Routes:
    * `uvicorn`, `uvicorn.error`, `uvicorn.access` — pre-existing handlers
      get the formatter swapped in (uvicorn installs its own handlers up
      front; we just rebrand the formatter).
    * Root logger — gets a fresh `StreamHandler` with the formatter so any
      backend module that calls `logging.getLogger(__name__).info("[TAG]...")`
      ends up in the same column-formatted stream as `tagged_log` callers.

    Idempotent: re-running the function won't double up the root handler.
    """
    formatter = ColumnLogFormatter()
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            handler.setFormatter(formatter)

    # Root handler — make sure backend module loggers (`backend.femm_solver`,
    # `backend.femm_postprocess`, ...) flow through the same formatter rather
    # than Python's default `LEVEL:name:message` shape.
    root = logging.getLogger()
    if not any(getattr(h, "_openem_column_handler", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        # Tag the handler so we can detect a re-install on a hot reload.
        handler._openem_column_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    # Python's root-logger default is WARNING, which would filter out the INFO
    # lines we want to see (e.g. [MAT] / [CACHE] / [DEBUG] from femm_solver).
    # Lower it to INFO unless someone has explicitly set a more verbose level
    # (DEBUG) for diagnostics.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
