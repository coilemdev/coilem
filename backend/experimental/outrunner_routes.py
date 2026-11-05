"""Opt-in local-only routes for the frozen FEMM LRK reference."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from backend.experimental import outrunner_runtime as runtime
from backend.experimental.outrunner_project import OutrunnerProject, OutrunnerRunRequest

router = APIRouter(prefix="/experimental/outrunner", tags=["experimental-outrunner"])


def guard() -> None:
    if not runtime.enabled():
        raise HTTPException(404, "The local outrunner experiment is disabled")


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
