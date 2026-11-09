"""Field playback images for saved runs, drawn from the run's own field frames.

A saved run keeps one compact field frame per rotor position but not the six
1536 px playback layers drawn from each, which were more than half of a run.
Those live in a disposable solve-cache folder per run. A solve saves its run
before any image is drawn and then starts drawing them there in the
background (start_drawing); whenever an image is missing (not drawn yet, or
removed by cache pruning) it is drawn from the run's frames when the viewer
asks for it, starting with that frame. A run whose frames retention removed
has no playback to draw.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from backend.field_artifacts import SOLVE_CACHE_DIR_PREFIX, solve_cache_root

if TYPE_CHECKING:
    from backend.solve_workspace import SolveWorkspace

RUN_PLAYBACK_PREFIX = "playback/"
PLAYBACK_MODES = frozenset({"resultant_pm", "resultant", "armature"})
# The compositions each mode draws; one frame's composition plays from these layers.
MODE_COMPOSITIONS = {"resultant_pm": ("resultant", "pm"), "resultant": ("resultant",), "armature": ("armature",)}
_PLAYED_LAYERS = ("base", "{composition}_flux", "{composition}_lines")
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


def playback_mode(relative: str) -> str | None:
    """The playback mode a run-relative image path belongs to, or None if it is not one."""

    parsed = _parse(relative)
    return parsed[0] if parsed is not None else None


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
    from backend.solver._process_pool import tracked_process_pool

    with _JOBS_LOCK:
        futures = _JOBS.get(output_dir)
        if futures is not None and index in futures and not futures[index].done():
            return futures[index]
        frames = _stored_frames(workspace, project_slug, run_id)
        if index >= len(frames):
            raise FileNotFoundError("playback frame not found")
        output_dir.mkdir(parents=True, exist_ok=True)
        executor = _playback_executor(len(frames))
        lifetime = ExitStack()
        try:
            lifetime.enter_context(tracked_process_pool(executor))
            lifetime.enter_context(executor)
            # The requested frame first, then onwards, as playback will ask for them.
            order = sorted(range(len(frames)), key=lambda position: (position - index) % len(frames))
            futures = {
                position: executor.submit(render_stored_playback_frame, position, str(frames[position]), str(output_dir), mode)
                for position in order
            }
            # Keep registration and the executor's process handles until its
            # workers have joined. shutdown(wait=False) drops those handles,
            # leaving application exit unable to stop background renders.
            threading.Thread(target=lifetime.close, name="coilem-playback-shutdown", daemon=True).start()
        except BaseException:
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            finally:
                lifetime.close()
            raise
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


def start_drawing(workspace: SolveWorkspace, project_slug: str, run_id: str, mode: str = "resultant_pm") -> None:
    """Start drawing a just-saved run's playback images in the background, frame 0 first.

    A solve's result no longer waits for these images (about 30 s on a
    72-position outrunner). A viewer request for a frame that is not drawn
    yet waits for that frame's job (playback_image). Never raises: if this
    fails, the images are drawn when the viewer asks for them.
    """

    if mode not in PLAYBACK_MODES:
        return
    try:
        _render_job(workspace, project_slug, run_id, mode, run_playback_dir(project_slug, run_id) / mode, 0)
    except Exception:  # noqa: BLE001 - drawing on demand still works
        return


def drawing_progress(
    workspace: SolveWorkspace, project_slug: str, run_id: str, mode: str, composition: str,
) -> dict[str, int | bool]:
    """How many of a saved run's positions have ``composition``'s playback layers drawn.

    The viewer enables Play once every position is drawn, so playback never
    waits on drawing. When positions are missing and this process has never
    started drawing ``mode`` for the run (the app restarted, or cache pruning
    removed the images), drawing starts here. A job that has finished leaves
    ``drawing`` False even with positions missing, so the viewer stops waiting
    and those frames are drawn on request as before.

    Raises FileNotFoundError for an unknown mode or composition, or a run
    with no field frames to draw from.
    """

    if composition not in MODE_COMPOSITIONS.get(mode, ()):
        raise FileNotFoundError("not a playback composition")
    total = len(_stored_frames(workspace, project_slug, run_id))
    output_dir = run_playback_dir(project_slug, run_id) / mode
    names = {path.name for path in output_dir.iterdir()} if output_dir.is_dir() else set()
    layers = [layer.format(composition=composition) for layer in _PLAYED_LAYERS]
    missing = [
        index for index in range(total)
        if any(f"frame_{index:04d}_{layer}.webp" not in names for layer in layers)
    ]
    with _JOBS_LOCK:
        futures = _JOBS.get(output_dir)
    if missing and futures is None:
        _render_job(workspace, project_slug, run_id, mode, output_dir, missing[0])
        with _JOBS_LOCK:
            futures = _JOBS.get(output_dir)
    drawing = bool(missing) and futures is not None and not all(future.done() for future in futures.values())
    return {"frames_total": total, "frames_drawn": total - len(missing), "drawing": drawing, "ready": not missing}
