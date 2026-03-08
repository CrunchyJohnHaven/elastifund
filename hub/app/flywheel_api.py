from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any, Iterator

from fastapi import APIRouter, Query

from data_layer import crud, database


router = APIRouter(tags=["flywheel"])


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


@router.get("/api/v1/flywheel/tasks")
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
            {
                "id": row.id,
                "cycle_id": row.cycle_id,
                "strategy_version_id": row.strategy_version_id,
                "finding_id": row.finding_id,
                "action": row.action,
                "title": row.title,
                "details": row.details,
                "priority": row.priority,
                "status": row.status,
                "lane": row.lane,
                "environment": row.environment,
                "source_kind": row.source_kind,
                "source_ref": row.source_ref,
                "metadata": row.metadata_json or {},
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    return {"total": len(items), "items": items}


@router.get("/api/v1/flywheel/findings")
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
            {
                "id": row.id,
                "finding_key": row.finding_key,
                "cycle_id": row.cycle_id,
                "strategy_version_id": row.strategy_version_id,
                "lane": row.lane,
                "environment": row.environment,
                "source_kind": row.source_kind,
                "finding_type": row.finding_type,
                "title": row.title,
                "summary": row.summary,
                "lesson": row.lesson,
                "evidence": row.evidence or {},
                "priority": row.priority,
                "confidence": row.confidence,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    return {"total": len(items), "items": items}
