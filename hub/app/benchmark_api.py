from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from inventory.methodology import methodology_payload
from inventory.service import (
    bot_detail_payload,
    list_bots_payload,
    paper_status_payload,
    rankings_payload,
    run_artifacts_payload,
    runs_payload,
)


router = APIRouter(tags=["benchmark"])


@router.get("/api/v1/benchmark/methodology")
def benchmark_methodology() -> dict[str, Any]:
    return methodology_payload()


@router.get("/api/v1/bots")
def list_bots(
    category: str | None = Query(default=None),
    benchmark_status: str | None = Query(default=None),
    maintenance_status: str | None = Query(default=None),
) -> dict[str, Any]:
    return list_bots_payload(
        category=category,
        benchmark_status=benchmark_status,
        maintenance_status=maintenance_status,
    )


@router.get("/api/v1/bots/{bot_id}")
def bot_detail(bot_id: str) -> dict[str, Any]:
    try:
        return bot_detail_payload(bot_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/v1/rankings")
def rankings(
    category: str | None = Query(default=None),
    track: str | None = Query(default=None),
    window: str = Query(default="30d"),
) -> dict[str, Any]:
    return rankings_payload(category=category, track=track, window=window)


@router.get("/api/v1/runs")
def runs(
    bot_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    return runs_payload(bot_id=bot_id, status=status_filter)


@router.get("/api/v1/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict[str, Any]:
    try:
        return run_artifacts_payload(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/v1/paper-status")
def paper_status(bot_id: str | None = Query(default=None)) -> dict[str, Any]:
    return paper_status_payload(bot_id=bot_id)
