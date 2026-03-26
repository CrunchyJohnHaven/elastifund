from __future__ import annotations
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel


class FillRecord(BaseModel):
    id: Optional[int] = None
    market_id: Optional[str] = None
    direction: Optional[str] = None
    order_status: Optional[str] = None
    resolved_side: Optional[str] = None
    decision_ts: Optional[int] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    pnl: Optional[float] = None
    raw: Optional[dict[str, Any]] = None


class MutationEvent(BaseModel):
    type: str  # e.g. "mutation.applied", "mutation.killed"
    mutation_id: Optional[str] = None
    parameter: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    timestamp: str = ""
    payload: Optional[dict[str, Any]] = None


class SafetyEvent(BaseModel):
    type: str  # e.g. "safety.kill", "safety.circuit_break"
    strategy: Optional[str] = None
    reason: Optional[str] = None
    timestamp: str = ""
    payload: Optional[dict[str, Any]] = None


class HealthSnapshot(BaseModel):
    timestamp: Optional[str] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    daily_pnl: Optional[float] = None
    total_pnl: Optional[float] = None
    fill_count: Optional[int] = None
    active_direction: Optional[str] = None
    kelly_fraction: Optional[float] = None
    raw: Optional[dict[str, Any]] = None


class CohortReport(BaseModel):
    cohort_start_ts: Optional[int] = None
    cohort_start_dt: Optional[str] = None
    fill_count: Optional[int] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    pnl: Optional[float] = None
    status: Optional[str] = None  # PASS, FAIL, COLLECTING
    raw: Optional[dict[str, Any]] = None


class VPSStatus(BaseModel):
    jj_live: str = "unknown"
    btc_5min_maker: str = "unknown"
    last_check: Optional[str] = None
    error: Optional[str] = None


class DeployStatus(BaseModel):
    exit_code: int = -1
    profile: str = ""
    stdout: str = ""
    stderr: str = ""
    success: bool = False
    timestamp: str = ""


class Hypothesis(BaseModel):
    id: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # EXPLORING, VALIDATING, REJECTED, PROMOTED
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    fill_count: Optional[int] = None
    created_at: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class HypothesisResult(BaseModel):
    hypothesis_id: str
    status: str
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    fill_count: Optional[int] = None
    verdict: Optional[str] = None  # CONTINUE, PROMOTE, KILL
    timestamp: str = ""


class SchedulerJobStatus(BaseModel):
    id: str
    next_run: Optional[str] = None
    trigger: str = ""


class WebSocketEvent(BaseModel):
    type: str
    payload: Optional[Any] = None
    timestamp: str = ""
