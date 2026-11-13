"""Where a solve spends its time.

Every solve records how long each stage took, in the main process and in the
mesh, solver and field-frame workers. The breakdown is stored with the result
(``solve_metadata.time_breakdown``), shown under Diagnostics in Results and
printed in the report, so two runs of a design can be compared stage by
stage. ``COILEM_SOLVE_PROFILE=1`` also prints the full table to the log and
writes it to ``solve_profile.json`` in the solve's cache folder;
``COILEM_SOLVE_PROFILE=0`` turns recording off.

A solve runs in several processes, some of them started before the solve
(pools are reused), so a stage cannot hand its timings back through the
call that ran it without changing every worker's return value. Instead each
process appends its records to its own file in one spool folder, and the
solve collects the records written since it started. The backend runs one
solve at a time, so the time window identifies the solve. A record is one
short line; a 72-position solve writes about two thousand.

Times are wall-clock seconds inside the stage. Stages that run in parallel
add up to more than the solve's elapsed time; the three steps of the
breakdown (meshing, field solve, packaging) are cut at the moments the last
mesh and the last solve finished, so they add up to the elapsed time.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROFILE_ENV = "COILEM_SOLVE_PROFILE"
PROFILE_SCHEMA = "coilem.solve_profile/v1"
PROFILE_FILENAME = "solve_profile.json"
_SPOOL_DIRNAME = ".solve-profile-spool"
BREAKDOWN_SCHEMA = "coilem.solve_time_breakdown.v1"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_lock = threading.Lock()
_handle: Any = None
_handle_pid: int | None = None
_started_at: float | None = None


def enabled() -> bool:
    """Whether stages are recorded: always, unless ``COILEM_SOLVE_PROFILE`` turns it off."""

    return os.environ.get(PROFILE_ENV, "").strip().lower() not in _FALSE


def verbose() -> bool:
    """Whether the full table also goes to the log and to ``solve_profile.json``."""

    return os.environ.get(PROFILE_ENV, "").strip().lower() in _TRUE


def _spool_dir() -> Path:
    from backend import field_artifacts

    return field_artifacts.solve_cache_root() / _SPOOL_DIRNAME


def _write(entry: dict[str, Any]) -> None:
    global _handle, _handle_pid
    try:
        with _lock:
            if _handle is None or _handle_pid != os.getpid():  # a forked child must not share the file
                folder = _spool_dir()
                folder.mkdir(parents=True, exist_ok=True)
                _handle = (folder / f"{os.getpid()}.jsonl").open("a", encoding="utf-8")
                _handle_pid = os.getpid()
            _handle.write(json.dumps(entry) + "\n")
            # Workers flush every record, because the solving process reads
            # their files. The solving process itself reads its own records
            # only when the solve finishes (_collect flushes them first), and
            # a flush per record cost several milliseconds on its threads.
            if _started_at is None:
                _handle.flush()
    except Exception:  # profiling must never break a solve
        return


def _flush_own_records() -> None:
    try:
        with _lock:
            if _handle is not None and _handle_pid == os.getpid():
                _handle.flush()
    except Exception:  # profiling must never break a solve
        return


def _close_own_records() -> None:
    global _handle, _handle_pid
    try:
        with _lock:
            handle, _handle = _handle, None
            _handle_pid = None
            if handle is not None:
                handle.close()
    except Exception:  # profiling must never break a solve
        return


def record(stage: str, seconds: float, **detail: Any) -> None:
    """Record ``seconds`` spent in ``stage``, ending now."""

    if not enabled():
        return
    entry: dict[str, Any] = {"t": time.time(), "stage": stage, "s": float(seconds)}
    if detail:
        entry["detail"] = detail
    _write(entry)


@contextmanager
def span(stage: str, **detail: Any) -> Iterator[None]:
    """Time the enclosed block as one occurrence of ``stage``."""

    if not enabled():
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        record(stage, time.perf_counter() - started, **detail)


def mark(event: str) -> None:
    """Note that ``event`` happened now, for the timeline."""

    if enabled():
        _write({"t": time.time(), "event": event})


def begin() -> None:
    """Start a solve's profile. Call once, in the process that runs the solve."""

    global _started_at
    if not enabled():
        return
    _started_at = time.time()


def _collect(started_at: float) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    _flush_own_records()
    try:
        files = sorted(_spool_dir().glob("*.jsonl"))
    except OSError:
        return entries
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and float(entry.get("t", 0.0)) >= started_at:
                entry["pid"] = path.stem
                entries.append(entry)
        # A file whose every record predates this solve belongs to a worker that is gone.
        if path.stem != str(os.getpid()):
            try:
                if path.stat().st_mtime < started_at:
                    path.unlink()
            except OSError:
                pass
    return entries


def summarize(entries: list[dict[str, Any]], started_at: float, finished_at: float) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    timeline: dict[str, dict[str, float]] = {}
    for entry in entries:
        offset = float(entry["t"]) - started_at
        if "event" in entry:
            item = timeline.setdefault(str(entry["event"]), {"first_s": offset, "last_s": offset, "count": 0})
            item["first_s"] = min(item["first_s"], offset)
            item["last_s"] = max(item["last_s"], offset)
            item["count"] += 1
            continue
        seconds = float(entry.get("s", 0.0))
        stage = stages.setdefault(
            str(entry["stage"]),
            {"count": 0, "total_s": 0.0, "max_s": 0.0, "first_start_s": offset - seconds, "last_end_s": offset, "processes": set()},
        )
        stage["count"] += 1
        stage["total_s"] += seconds
        stage["max_s"] = max(stage["max_s"], seconds)
        stage["first_start_s"] = min(stage["first_start_s"], offset - seconds)
        stage["last_end_s"] = max(stage["last_end_s"], offset)
        stage["processes"].add(entry.get("pid"))
    rows = []
    for name, stage in stages.items():
        rows.append(
            {
                "stage": name,
                "count": stage["count"],
                "total_s": round(stage["total_s"], 3),
                "mean_s": round(stage["total_s"] / stage["count"], 3),
                "max_s": round(stage["max_s"], 3),
                "first_start_s": round(max(0.0, stage["first_start_s"]), 2),
                "last_end_s": round(stage["last_end_s"], 2),
                "processes": len(stage["processes"]),
            }
        )
    rows.sort(key=lambda row: (row["stage"].split(":")[0], -row["total_s"]))
    return {
        "schema": PROFILE_SCHEMA,
        "elapsed_s": round(finished_at - started_at, 2),
        "note": (
            "total_s adds up every occurrence of a stage, across workers running in parallel, "
            "so totals exceed elapsed_s. first_start_s and last_end_s place a stage in the solve."
        ),
        "stages": rows,
        "timeline": {
            name: {"first_s": round(item["first_s"], 2), "last_s": round(item["last_s"], 2), "count": int(item["count"])}
            for name, item in sorted(timeline.items(), key=lambda kv: kv[1]["first_s"])
        },
    }


def format_table(summary: dict[str, Any]) -> str:
    lines = [f"solve profile: {summary['elapsed_s']:.1f} s elapsed"]
    lines.append(f"  {'stage':48s} {'count':>5s} {'total s':>9s} {'mean s':>8s} {'max s':>8s} {'from':>7s} {'to':>7s} {'procs':>5s}")
    for row in summary["stages"]:
        lines.append(
            f"  {row['stage'][:48]:48s} {row['count']:5d} {row['total_s']:9.2f} {row['mean_s']:8.3f} {row['max_s']:8.2f} "
            f"{row['first_start_s']:7.1f} {row['last_end_s']:7.1f} {row['processes']:5d}"
        )
    if summary["timeline"]:
        lines.append("  timeline (seconds from the start of the solve):")
        for name, item in summary["timeline"].items():
            span_text = f"{item['first_s']:.1f}" if item["count"] == 1 else f"{item['first_s']:.1f} .. {item['last_s']:.1f}"
            lines.append(f"    {name:44s} {span_text:>16s}  x{item['count']}")
    return "\n".join(lines)


def finish(output_dir: Path | None) -> dict[str, Any] | None:
    """Collect this solve's records, log the breakdown and write it to ``output_dir``."""

    global _started_at
    started_at, _started_at = _started_at, None
    try:
        if not enabled() or started_at is None:
            return None
        summary = summarize(_collect(started_at), started_at, time.time())
        if verbose():
            print(format_table(summary), file=sys.stderr, flush=True)
            if output_dir is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / PROFILE_FILENAME).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary
    except Exception:  # profiling must never break a solve
        return None
    finally:
        # Worker pools have joined before the solve returns. Release this
        # process's spool too, so Windows can archive/delete the runtime and
        # the next solve opens a fresh file, possibly under a new data root.
        _close_own_records()


# The stages of each step, in reading order: (recorded stage, label, indent).
# An indented row is part of the row above it.
_STEPS: tuple[tuple[str, str, tuple[str, ...], tuple[tuple[str, str, int], ...]], ...] = (
    (
        "meshing",
        "Meshing",
        ("mesh worker: one group, total",),
        (
            ("mesh worker: build base mesh", "Build a mesh", 0),
            ("mesh: describe the geometry", "Describe the geometry", 1),
            ("mesh: start Gmsh", "Start Gmsh", 1),
            ("mesh: build geometry and size fields", "Hand Gmsh the geometry and element sizes", 1),
            ("mesh: Gmsh generates the mesh", "Gmsh generates the mesh", 1),
            ("mesh: copy triangles out of Gmsh", "Copy the triangles out of Gmsh", 1),
            ("mesh: build the solve mesh record", "Label regions, currents and magnets", 1),
            ("mesh: mesh checks", "Mesh checks", 1),
            ("mesh worker: re-bake cached mesh", "Reuse a cached mesh", 0),
            ("mesh worker: rotate to a matching position", "Rotate a mesh to a matching position", 0),
            ("mesh worker: evidence hashes", "Hash each mesh for the run record", 0),
        ),
    ),
    (
        "field_solve",
        "Field solve",
        ("solve (loaded): one position, total", "solve (noload): one position, total"),
        (
            ("solve: prepare the solver's settings", "Prepare the solver's settings", 0),
            ("solve: write input and mesh files", "Write the solver's input and mesh files", 0),
            ("solve: find the solver executable", "Find the solver", 0),
            ("solve: solver process, start to exit", "Solver process", 0),
            ("solver: start-up, reading mesh, writing report", "Start up, read the mesh, write the report", 1),
            ("solver: matrix assembly", "Assemble the equations", 1),
            ("solver: linear solves", "Solve the equations", 1),
            ("solver: rest of its timed work (fields, torque)", "Step checks, fields, torque and other outputs", 1),
            ("solve: read and parse the report", "Read the solver's report", 0),
            ("solve: record settings and keep the solver's files", "Record settings and keep the solver's files", 0),
        ),
    ),
    (
        "packaging",
        "Packaging results",
        (),
        (
            ("frame worker: read solver reports", "Read the solver reports for a field frame", 0),
            ("frame worker: build frame from reports", "Build a field frame", 0),
            ("frame worker: encode and write frame", "Compress and store a field frame", 0),
            ("frame worker: flux statistics and iron-loss sample", "Flux statistics and iron-loss sample", 0),
            ("result: assemble from reports", "Assemble the result", 0),
        ),
    ),
    (
        "coordination",
        "Coordination",
        (),
        (
            ("main: receive mesh group from worker", "Receive a mesh from its worker", 0),
            ("main: hand mesh group to solves", "Hand a mesh to the solves", 0),
        ),
    ),
)


def breakdown(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored, displayed form of a profile: three steps that add up, each with its parts."""

    if not summary or not summary.get("stages"):
        return None
    stages = {row["stage"]: row for row in summary["stages"]}
    timeline = summary.get("timeline") or {}
    elapsed = float(summary["elapsed_s"])

    def last(event: str) -> float | None:
        item = timeline.get(event)
        return float(item["last_s"]) if item else None

    def count(event: str) -> int:
        item = timeline.get(event)
        return int(item["count"]) if item else 0

    steps: list[dict[str, Any]] = []
    for key, label, total_stages, rows in _STEPS:
        parts = [
            {
                "label": part_label,
                "indent": indent,
                "count": stages[name]["count"],
                "total_s": stages[name]["total_s"],
                "mean_s": stages[name]["mean_s"],
                "max_s": stages[name]["max_s"],
            }
            for name, part_label, indent in rows
            if name in stages
        ]
        if not parts:
            continue
        totals = [stages[name]["total_s"] for name in total_stages if name in stages]
        work = sum(totals) if totals else sum(part["total_s"] for part in parts if part["indent"] == 0)
        present = [stages[name] for name, _label, _indent in rows if name in stages]
        steps.append(
            {
                "key": key,
                "label": label,
                "work_s": round(work, 2),
                "started_s": round(min(row["first_start_s"] for row in present), 1),
                "ended_s": round(max(row["last_end_s"] for row in present), 1),
                "parts": parts,
            }
        )

    # Cut the elapsed time where the last mesh arrived and the last solve finished.
    mesh_end, solve_end = last("mesh group ready"), last("solve finished")
    elapsed_steps: list[dict[str, Any]] = []
    if solve_end is not None:
        mesh_end = min(mesh_end if mesh_end is not None else 0.0, solve_end)
        elapsed_steps = [
            {"key": "meshing", "label": "Meshing", "detail": "until the last mesh was ready", "seconds": round(mesh_end, 1)},
            {
                "key": "field_solve",
                "label": "Field solve",
                "detail": "from then until the last position was solved",
                "seconds": round(solve_end - mesh_end, 1),
            },
            {
                "key": "packaging",
                "label": "Packaging results",
                "detail": "field frames and the result, after the last solve",
                "seconds": round(max(0.0, elapsed - solve_end), 1),
            },
        ]
    built = stages.get("mesh worker: build base mesh", {}).get("count", 0)
    rotated = stages.get("mesh worker: rotate to a matching position", {}).get("count", 0)
    return {
        "schema_version": BREAKDOWN_SCHEMA,
        "elapsed_s": round(elapsed, 1),
        "elapsed_steps": elapsed_steps,
        "steps": steps,
        "counts": {
            "meshes_built": int(built),
            "meshes_rotated": int(rotated),
            "solves": count("solve finished"),
            "field_frames": count("frame finished"),
        },
    }


def format_seconds(seconds: float) -> str:
    """Seconds as a short figure: 0.043 s, 1.35 s, 12.8 s, 155 s, 21 min."""

    value = max(0.0, float(seconds))
    if value >= 6000:
        return f"{round(value / 60)} min"
    if value >= 100:
        return f"{round(value)} s"
    if value >= 10:
        return f"{value:.1f} s"
    if value >= 1:
        return f"{value:.2f} s"
    return f"{value:.3f} s"


def report_rows(value: Any) -> tuple[list[tuple[str, str]], list[tuple[str, list[tuple[str, str]]]]]:
    """A stored breakdown as report rows: the summary, then each step's stages.

    Returns empty lists for a run that recorded no breakdown or one in a
    layout this version does not know.
    """

    if not isinstance(value, dict) or value.get("schema_version") != BREAKDOWN_SCHEMA:
        return [], []
    elapsed = float(value.get("elapsed_s") or 0.0)
    summary = [("Elapsed", format_seconds(elapsed))]
    for step in value.get("elapsed_steps") or []:
        share = f" ({round(100 * step['seconds'] / elapsed)}%)" if elapsed > 0 else ""
        summary.append((step["label"], f"{format_seconds(step['seconds'])}{share}, {step['detail']}"))
    counts = value.get("counts") or {}
    if counts.get("meshes_built") or counts.get("meshes_rotated"):
        rotated = f", {counts['meshes_rotated']} rotated from them" if counts.get("meshes_rotated") else ""
        summary.append(("Meshes", f"{counts.get('meshes_built', 0)} generated{rotated}"))
    if counts.get("solves"):
        summary.append(("Field solves", str(counts["solves"])))
    if counts.get("field_frames"):
        summary.append(("Field frames", str(counts["field_frames"])))
    steps = []
    for step in value.get("steps") or []:
        rows = [
            (
                ("– " if part["indent"] else "") + part["label"],
                f"{format_seconds(part['total_s'])} in total; run {part['count']} times, "
                f"{format_seconds(part['mean_s'])} each on average, slowest {format_seconds(part['max_s'])}",
            )
            for part in step.get("parts") or []
        ]
        if rows:
            steps.append((f"{step['label']}: {format_seconds(step['work_s'])} of work across workers", rows))
    return summary, steps
