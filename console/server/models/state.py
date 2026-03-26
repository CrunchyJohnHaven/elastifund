from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel
from .events import (
    HealthSnapshot,
    CohortReport,
    VPSStatus,
    Hypothesis,
    SchedulerJobStatus,
)


class SystemSnapshot(BaseModel):
    health: Optional[dict[str, Any]] = None
    cohort: Optional[dict[str, Any]] = None
    filter_economics: Optional[dict[str, Any]] = None
    runtime_contract: Optional[dict[str, Any]] = None
    cohort_contract: Optional[dict[str, Any]] = None
    active_mutation: Optional[dict[str, Any]] = None
    vps_status: Optional[dict[str, Any]] = None
    autoresearch_results: Optional[list[dict[str, Any]]] = None
    scheduler_jobs: Optional[list[dict[str, Any]]] = None
    recent_fills: Optional[list[dict[str, Any]]] = None
    fill_count: Optional[int] = None
    snapshot_ts: Optional[str] = None
