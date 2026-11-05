"""Opt-in local-only routes for the frozen FEMM LRK reference."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.experimental import outrunner_runtime as runtime
from backend.experimental import outrunner_visuals as visuals
from backend.experimental.outrunner_project import OutrunnerProject, OutrunnerRunRequest

router = APIRouter(prefix="/experimental/outrunner", tags=["experimental-outrunner"])


def guard() -> None:
    if not runtime.enabled():
        raise HTTPException(404, "The local outrunner experiment is disabled")


@router.post("/mesh-preview")
async def mesh_preview(project: OutrunnerProject):
    guard()
    path = await asyncio.to_thread(visuals.mesh_preview_path, project)
    return FileResponse(path, media_type="application/json", headers={"Content-Encoding": "gzip", "Cache-Control": "no-store"})


@router.post("/estimate")
async def estimate(request: OutrunnerRunRequest):
    guard()
    return await asyncio.to_thread(runtime.estimate, request)


@router.get("/runs/{run_id}/frames")
async def frames(run_id: str):
    guard()
    try:
        return {"frames": await asyncio.to_thread(visuals.completed_frames, run_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/prepare-playback")
async def prepare_playback(run_id: str):
    guard()
    try:
        return await asyncio.to_thread(visuals.prepare_playback, run_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/runs/{run_id}/frames/{index}")
async def frame(run_id: str, index: int):
    guard()
    try:
        return await asyncio.to_thread(visuals.prepare_frame, run_id, index)
    except (ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/runs/{run_id}/frames/{index}/layers/{layer}.webp")
async def frame_layer(run_id: str, index: int, layer: str):
    guard()
    try:
        path = await asyncio.to_thread(visuals.frame_layer_path, run_id, index, layer)
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})
    except (ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/runs/{run_id}/frames/{index}/numerical")
async def numerical_frame(run_id: str, index: int):
    guard()
    try:
        await asyncio.to_thread(visuals.prepare_frame, run_id, index)
        return FileResponse(visuals.frame_folder(run_id, index)/"numerical.json.gz", media_type="application/json",
                            headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600"})
    except (ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/preview")
async def preview(project: OutrunnerProject):
    guard()
    return await asyncio.to_thread(runtime.preview, project)


@router.post("/runs")
async def start(request: OutrunnerRunRequest):
    guard()
    try:
        return runtime.start(request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/runs/{run_id}")
async def status(run_id: str):
    guard()
    try:
        return runtime.status(run_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str):
    guard()
    try:
        return runtime.cancel(run_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/resume")
async def resume(run_id: str, request: OutrunnerRunRequest):
    guard()
    try:
        return runtime.start(request, run_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
