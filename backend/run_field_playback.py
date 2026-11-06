"""Field playback images for saved runs, drawn from the run's own field frames.

A saved run keeps one compact field frame per rotor position but not the six
1536 px playback layers drawn from each, which were more than half of a run.
Those live in a disposable solve-cache folder per run: the solve links its own
images there, and once cache pruning has removed them they are drawn again
from the run's frames when the viewer asks for one, starting with that frame.
A run whose frames retention removed has no playback to draw.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING

from backend.field_artifacts import SOLVE_CACHE_DIR_PREFIX, solve_cache_root

if TYPE_CHECKING:
    from backend.solve_workspace import SolveWorkspace

RUN_PLAYBACK_PREFIX = "playback/"
PLAYBACK_MODES = frozenset({"resultant_pm", "resultant", "armature"})
# The viewer waits for its frame; a 48-position run redraws in a few seconds.
RENDER_TIMEOUT_S = 300.0
_IMAGE_NAME = re.compile(r"^frame_(\d{4})_[a-z_]+\.webp$")
_JOBS_LOCK = threading.Lock()
_JOBS: dict[Path, dict[int, Future]] = {}


def run_playback_dir(project_slug: str, run_id: str) -> Path:
    """The disposable solve-cache folder holding one saved run's playback images."""

    return solve_cache_root() / f"{SOLVE_CACHE_DIR_PREFIX}playback-{project_slug}-{run_id}"


def run_playback_relative(mode: str, name: str) -> str | None:
    """The run-relative path a result uses for a playback image, or None if it is not one."""

    if mode not in PLAYBACK_MODES or not _IMAGE_NAME.fullmatch(name):
        return None
    return f"{RUN_PLAYBACK_PREFIX}{mode}/{name}"


def _parse(relative: str) -> tuple[str, str, int] | None:
    if not relative.startswith(RUN_PLAYBACK_PREFIX):
        return None
    parts = relative.removeprefix(RUN_PLAYBACK_PREFIX).split("/")
    if len(parts) != 2 or run_playback_relative(*parts) is None:
        return None
    match = _IMAGE_NAME.fullmatch(parts[1])
    assert match is not None
    return parts[0], parts[1], int(match.group(1))


def is_run_playback_path(relative: str) -> bool:
    return _parse(relative) is not None


def _stored_frames(workspace: SolveWorkspace, project_slug: str, run_id: str) -> list[Path]:
    """The run's field frames in playback order; FileNotFoundError once retention removed them."""

    result = json.loads(workspace.resolve_artifact(project_slug, run_id, "result.json").read_text(encoding="utf-8"))
    playback = result.get("field_playback") if isinstance(result, dict) else None
    snapshots = playback.get("numerical_snapshots") if isinstance(playback, dict) else None
    if not isinstance(snapshots, list) or not snapshots:
        raise FileNotFoundError("this run has no field playback")
    frames: list[Path] = []
    for snapshot in snapshots:
        relative = snapshot.get("relative_path") if isinstance(snapshot, dict) else None
        if not isinstance(relative, str):
            raise FileNotFoundError("this run's field frames are not stored")
        frames.append(workspace.resolve_artifact(project_slug, run_id, relative))
    return frames


def _render_job(workspace: SolveWorkspace, project_slug: str, run_id: str, mode: str, output_dir: Path, index: int) -> Future:
    """The render of ``index``: an unfinished one already queued, or a new job for all frames."""

    from backend.public_field_playback import _playback_executor, render_stored_playback_frame

    with _JOBS_LOCK:
        futures = _JOBS.get(output_dir)
        if futures is not None and index in futures and not futures[index].done():
            return futures[index]
        frames = _stored_frames(workspace, project_slug, run_id)
        if index >= len(frames):
            raise FileNotFoundError("playback frame not found")
        output_dir.mkdir(parents=True, exist_ok=True)
        executor = _playback_executor(len(frames))
        # The requested frame first, then onwards, as playback will ask for them.
        order = sorted(range(len(frames)), key=lambda position: (position - index) % len(frames))
        futures = {
            position: executor.submit(render_stored_playback_frame, position, str(frames[position]), str(output_dir), mode)
            for position in order
        }
        executor.shutdown(wait=False)  # queued frames still render; the workers exit after
        _JOBS[output_dir] = futures
        return futures[index]


def playback_image(workspace: SolveWorkspace, project_slug: str, run_id: str, relative: str) -> Path:
    """A saved run's playback image, drawn again from its field frames when the cache no longer has it.

    Raises FileNotFoundError when the path is not a playback image or the run
    has no frames left to draw it from.
    """

    parsed = _parse(relative)
    if parsed is None:
        raise FileNotFoundError("not a playback image")
    mode, name, index = parsed
    workspace.resolve_run(project_slug, run_id)  # validates both names and that the run exists
    output_dir = run_playback_dir(project_slug, run_id) / mode
    target = output_dir / name
    if target.is_file():
        return target
    _render_job(workspace, project_slug, run_id, mode, output_dir, index).result(timeout=RENDER_TIMEOUT_S)
    if not target.is_file():
        raise FileNotFoundError("playback frame not found")
    return target
