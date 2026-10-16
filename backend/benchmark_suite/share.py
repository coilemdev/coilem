"""A shareable benchmark report: Markdown and JSON with every local path removed (#71).

The full report under ``report/`` keeps request files, fixtures and
measurements for audit. This one is meant to be pasted into an issue or a
chat: it names the installation, platform, verdicts and record match, and
nothing about the machine beyond its operating system and Python. It is
checked by the publication check's path rules before it is written.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from backend import __version__
from backend.benchmark_suite import PHASE_LABELS
from backend.benchmark_suite.contract import CHECKOUT, ROOT
from backend.benchmark_suite.record import TOLERANCES, VALUE_LABELS, gate_statuses, gated_values
from backend.local_paths import contains_local_path, redact_local_paths
from backend.resources import build_identity

SHARE_SCHEMA = "coilem.benchmark_share/v1"
SHARE_DIR = "share"
SHARE_NAME = "coilem-benchmark"


def tolerance_text():
    parts = []
    for name, (relative, floor) in TOLERANCES.items():
        label, unit = VALUE_LABELS[name]
        parts.append(f"{label} within {relative * 100:g}% (at least {floor:g} {unit})")
    return "verdicts and gate statuses identical; " + ", ".join(parts)


def _duration(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min {seconds} s"


def _case(row, comparison):
    case = {
        "id": row["id"],
        "phase": row["phase"],
        "status": row["status"],
        "gates": gate_statuses(row["evaluation"]),
        "values": gated_values(row),
    }
    for key in ("reason", "errors"):
        if row["evaluation"].get(key):
            case[key] = row["evaluation"][key]
    if row["id"] in comparison.get("cases", {}):
        case["record"] = comparison["cases"][row["id"]]
    return case


def share_payload(summary, comparison, *, selection):
    run = summary["run"]
    identity = run["identity"]
    started, completed = run.get("started_at"), run.get("completed_at")
    elapsed = (datetime.fromisoformat(completed) - datetime.fromisoformat(started)).total_seconds() if started and completed else None
    return {
        "schema": SHARE_SCHEMA,
        "coilem": {"version": __version__, **build_identity(), "commit": identity["commit"], "modified": identity.get("dirty")},
        "platform": {
            "key": comparison["platform"],
            "system": identity["platform"],
            "machine": identity["machine"],
            "python": identity["python"],
            "dependencies": identity["dependencies"],
        },
        "run": {
            "status": run["status"],
            "outcome": summary["status"],
            "counts": summary["counts"],
            "selection": selection,
            "started_at": started,
            "completed_at": completed,
            "elapsed_s": elapsed,
            "harness_version": identity["harness_version"],
            "protocol_version": identity["protocol_version"],
            "suite_sha256": run["selection"]["spec_sha256"],
            "reference_bundle_sha256": run["selection"]["bundle_sha256"],
            "source_sha256": identity["source_sha256"],
            "binary_sha256": identity["binary_sha256"],
        },
        "record_match": {key: value for key, value in comparison.items() if key != "cases"},
        "match_policy": tolerance_text(),
        "cases": [_case(row, comparison) for row in summary["rows"]],
    }


def match_sentence(comparison):
    status = comparison["status"]
    if status == "NO_RECORD":
        return f"No published record exists for {comparison['platform']}, so this run was not matched against one."
    record = comparison["record"]
    origin = f"the published {record['platform']} record (measured at {record['measured_commit'][:7]})"
    if comparison["cross_platform"]:
        origin += f", the closest to {comparison['platform']}, which has no record of its own"
    if status == "NOT_COMPARABLE":
        return (
            f"Not comparable with {origin}: {len(comparison['physics']['differs'])} physics source(s) differ from the "
            "ones it measured, so differences are expected."
        )
    verb = "Matches" if status == "MATCH" else "Differs from"
    return f"{verb} {origin}: {comparison['matched']} of {comparison['compared']} cases match."


def markdown(payload):
    run, coilem, platform = payload["run"], payload["coilem"], payload["platform"]
    match = payload["record_match"]
    selection = run["selection"]
    scope = "quick subset" if selection.get("quick") else "full suite"
    phases = ", ".join(f"{phase} ({PHASE_LABELS[phase]})" for phase in selection["phases"])
    commit = coilem.get("application_commit") or coilem["commit"]
    lines = [
        f"# coilEM benchmark: {run['outcome']}",
        "",
        f"coilEM {coilem['version']} ({coilem['installation']}, commit `{str(commit)[:12]}`) on **{platform['key']}** "
        f"({platform['system']}, Python {platform['python']}).",
        f"Ran {len(payload['cases'])} cases, {scope}, phases {phases}"
        + (f", in {_duration(run['elapsed_s'])}." if run["elapsed_s"] is not None else "."),
        "",
        f"## Record match: {match['status']}",
        "",
        match_sentence({**match, "cases": {}}),
    ]
    physics = match.get("physics")
    if physics:
        lines.append(
            f"Physics sources: **{physics['status']}**, {physics['files']} files compared"
            + (f"; differ: {', '.join(physics['differs'])}" if physics["differs"] else "")
            + (f"; not checkable in this installation: {len(physics['unverified'])}" if physics["unverified"] else "")
            + "."
        )
    lines += [f"Match policy: {payload['match_policy']}.", "", "## Cases", ""]
    lines += ["| Phase | Case | Verdict | Record | Notes |", "| --- | --- | --- | --- | --- |"]
    for case in payload["cases"]:
        record = case.get("record")
        verdict = "—" if record is None else "match" if record["match"] else "differs"
        notes = "; ".join(record["differences"]) if record and record["differences"] else case.get("reason") or ""
        if case.get("errors"):
            notes = "; ".join(str(error) for error in case["errors"] if error)
        lines.append(f"| {case['phase']} | `{case['id']}` | {case['status']} | {verdict} | {notes.replace('|', '/')} |")
    lines += [
        "",
        "## Run",
        "",
        f"- Harness {run['harness_version']}, protocol {run['protocol_version']}; suite SHA-256 `{run['suite_sha256'][:12]}`, "
        f"reference bundle `{str(run['reference_bundle_sha256'])[:12]}`.",
        f"- Source SHA-256 `{run['source_sha256'][:12]}`, Magneto2D binary `{run['binary_sha256'][:12]}`.",
        f"- Dependencies: {', '.join(f'{name} {version}' for name, version in sorted(platform['dependencies'].items()))}.",
        "",
        "Reproduce with `coilem benchmark" + (" --quick" if selection.get("quick") else "")
        + "".join(f" --phase {phase}" for phase in selection["phases"] if len(selection["phases"]) < len(PHASE_LABELS))
        + "`. The full JSON is beside this file.",
    ]
    return "\n".join(lines) + "\n"


def _redacted(value, known):
    if isinstance(value, str):
        return redact_local_paths(value, known)
    if isinstance(value, list):
        return [_redacted(item, known) for item in value]
    if isinstance(value, dict):
        return {key: _redacted(item, known) for key, item in value.items()}
    return value


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


def write_share_report(output, summary, comparison, *, selection, known_paths=()):
    """Write ``share/coilem-benchmark.{md,json}`` and return the Markdown path."""

    known = [str(output), str(Path(output).resolve()), str(Path.home()), str(ROOT), sys.executable, str(Path.cwd()), *known_paths]
    if CHECKOUT is not None:
        known.append(str(CHECKOUT))
    payload = _redacted(share_payload(summary, comparison, selection=selection), known)
    text = markdown(payload)
    if any(contains_local_path(item) for item in (text, *_strings(payload))):
        raise ValueError("The shareable report still names a local path")
    directory = Path(output) / SHARE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{SHARE_NAME}.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (directory / f"{SHARE_NAME}.md").write_text(text, encoding="utf-8", newline="\n")
    return directory / f"{SHARE_NAME}.md"
