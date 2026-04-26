from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any, Iterator

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from data_layer import crud, database


router = APIRouter(tags=["flywheel"])


class FlywheelTaskRecord(BaseModel):
    task_id: int
    id: int
    cycle_id: int | None
    strategy_version_id: int | None
    finding_id: int | None
    action: str
    title: str
    details: str | None
    priority: int
    task_status: str
    status: str
    lane: str | None
    environment: str | None
    source_kind: str | None
    source_ref: str | None
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    task_metadata: dict[str, Any] = Field(default_factory=dict)


class FlywheelTaskListResponse(BaseModel):
    total: int
    tasks: list[FlywheelTaskRecord]
    items: list[FlywheelTaskRecord]


class FlywheelFindingRecord(BaseModel):
    finding_id: int
    id: int
    finding_key: str
    cycle_id: int | None
    strategy_version_id: int | None
    lane: str | None
    environment: str | None
    source_kind: str | None
    finding_type: str
    title: str
    summary: str | None
    lesson: str | None
    priority: int
    confidence: float | None
    finding_status: str
    status: str
    created_at: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class FlywheelFindingListResponse(BaseModel):
    total: int
    findings: list[FlywheelFindingRecord]
    items: list[FlywheelFindingRecord]


def _control_db_url() -> str:
    return os.environ.get("ELASTIFUND_CONTROL_DB_URL", "sqlite:///data/flywheel_control.db")


@contextmanager
def _session_scope() -> Iterator[Any]:
    database.reset_engine()
    engine = database.get_engine(_control_db_url())
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        database.reset_engine()


@router.get("/api/v1/flywheel/tasks", response_model=FlywheelTaskListResponse)
def list_flywheel_tasks(
    lane: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    status_filter: str | None = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    with _session_scope() as session:
        rows = crud.list_flywheel_tasks(
            session,
            lane=lane,
            environment=environment,
            source_kind=source_kind,
            status=status_filter,
            limit=limit,
        )
        items = [
            FlywheelTaskRecord(
                task_id=row.id,
                id=row.id,
                cycle_id=row.cycle_id,
                strategy_version_id=row.strategy_version_id,
                finding_id=row.finding_id,
                action=row.action,
                title=row.title,
                details=row.details,
                priority=row.priority,
                task_status=row.status,
                status=row.status,
                lane=row.lane,
                environment=row.environment,
                source_kind=row.source_kind,
                source_ref=row.source_ref,
                metadata=row.metadata_json or {},
                task_metadata=row.metadata_json or {},
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    return FlywheelTaskListResponse(total=len(items), tasks=items, items=items)


@router.get("/api/v1/flywheel/findings", response_model=FlywheelFindingListResponse)
def list_flywheel_findings(
    lane: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    status_filter: str | None = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    with _session_scope() as session:
        rows = crud.list_flywheel_findings(
            session,
            lane=lane,
            environment=environment,
            source_kind=source_kind,
            status=status_filter,
            limit=limit,
        )
        items = [
            FlywheelFindingRecord(
                finding_id=row.id,
                id=row.id,
                finding_key=row.finding_key,
                cycle_id=row.cycle_id,
                strategy_version_id=row.strategy_version_id,
                lane=row.lane,
                environment=row.environment,
                source_kind=row.source_kind,
                finding_type=row.finding_type,
                title=row.title,
                summary=row.summary,
                lesson=row.lesson,
                evidence=row.evidence or {},
                priority=row.priority,
                confidence=row.confidence,
                finding_status=row.status,
                status=row.status,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    return FlywheelFindingListResponse(total=len(items), findings=items, items=items)
