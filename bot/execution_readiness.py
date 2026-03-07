#!/usr/bin/env python3
"""Execution-readiness gates for structural arbitrage lanes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
RESTART_WEEKDAY = 0  # Monday
RESTART_START_HOUR = 20
RESTART_START_MINUTE = 0
RESTART_DURATION_MINUTES = 20


def _as_utc_datetime(value: datetime | int | float | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def in_polymarket_restart_window(now: datetime | int | float | None = None) -> bool:
    """Return True during the documented weekly maintenance window.

    Official Polymarket docs currently describe the maintenance window as
    Monday 20:00-20:20 ET for order-related endpoints returning HTTP 425.
    """

    current = _as_utc_datetime(now).astimezone(EASTERN_TZ)
    if current.weekday() != RESTART_WEEKDAY:
        return False
    start_minutes = RESTART_START_HOUR * 60 + RESTART_START_MINUTE
    current_minutes = current.hour * 60 + current.minute
    return start_minutes <= current_minutes < (start_minutes + RESTART_DURATION_MINUTES)


def builder_relayer_available(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return bool(
        source.get("POLY_BUILDER_API_KEY")
        and source.get("POLY_BUILDER_API_SECRET")
        and source.get("POLY_BUILDER_API_PASSPHRASE")
    )


@dataclass(frozen=True)
class FeedHealth:
    healthy: bool
    reasons: tuple[str, ...]
    silence_seconds: float | None = None
    divergence_ticks: float | None = None


def evaluate_feed_health(
    *,
    last_data_ts: float | int | None,
    max_silence_seconds: float,
    now_ts: float | int | None = None,
    book_best_bid: float | None = None,
    book_best_ask: float | None = None,
    price_best_bid: float | None = None,
    price_best_ask: float | None = None,
    midpoint: float | None = None,
    tick_size: float | None = None,
    max_divergence_ticks: float = 1.0,
) -> FeedHealth:
    now_value = float(_as_utc_datetime(now_ts).timestamp())
    silence_seconds = None if last_data_ts is None else max(0.0, now_value - float(last_data_ts))
    reasons: list[str] = []

    if last_data_ts is None:
        reasons.append("feed_missing")
    elif silence_seconds is not None and silence_seconds > float(max_silence_seconds):
        reasons.append("feed_silent")

    divergence_ticks = None
    valid_book = (
        book_best_bid is not None
        and book_best_ask is not None
        and 0.0 <= float(book_best_bid) <= 1.0
        and 0.0 <= float(book_best_ask) <= 1.0
    )
    valid_price = (
        price_best_bid is not None
        and price_best_ask is not None
        and 0.0 <= float(price_best_bid) <= 1.0
        and 0.0 <= float(price_best_ask) <= 1.0
    )
    resolved_midpoint = None
    if midpoint is not None:
        resolved_midpoint = float(midpoint)
    elif valid_price:
        resolved_midpoint = (float(price_best_bid) + float(price_best_ask)) / 2.0

    if valid_book and resolved_midpoint is not None and tick_size is not None and tick_size > 0:
        book_midpoint = (float(book_best_bid) + float(book_best_ask)) / 2.0
        divergence_ticks = abs(book_midpoint - resolved_midpoint) / float(tick_size)
        if divergence_ticks > float(max_divergence_ticks):
            reasons.append("book_price_divergence")

    return FeedHealth(
        healthy=not reasons,
        reasons=tuple(reasons),
        silence_seconds=silence_seconds,
        divergence_ticks=divergence_ticks,
    )


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    status: str
    reasons: tuple[str, ...]
    estimated_one_leg_loss_usd: float


@dataclass(frozen=True)
class ExecutionReadinessInputs:
    feed_healthy: bool
    tick_size_ok: bool
    quote_surface_ok: bool
    estimated_one_leg_loss_usd: float
    max_one_leg_loss_threshold_usd: float
    neg_risk: bool
    neg_risk_flag_configured: bool
    builder_required: bool = False
    builder_available: bool = False
    now: datetime | int | float | None = None


def evaluate_execution_readiness(inputs: ExecutionReadinessInputs) -> ExecutionReadiness:
    reasons: list[str] = []

    if not inputs.feed_healthy:
        reasons.append("feed_unhealthy")
    if not inputs.tick_size_ok:
        reasons.append("tick_size_stale")
    if not inputs.quote_surface_ok:
        reasons.append("quote_surface_incomplete")
    if float(inputs.estimated_one_leg_loss_usd) > float(inputs.max_one_leg_loss_threshold_usd):
        reasons.append("one_leg_loss_exceeds_threshold")
    if in_polymarket_restart_window(inputs.now):
        reasons.append("restart_window_active")
    if inputs.neg_risk and not inputs.neg_risk_flag_configured:
        reasons.append("neg_risk_flag_missing")
    if inputs.builder_required and not inputs.builder_available:
        reasons.append("builder_relayer_unavailable")

    status = "ready" if not reasons else "blocked"
    return ExecutionReadiness(
        ready=not reasons,
        status=status,
        reasons=tuple(reasons),
        estimated_one_leg_loss_usd=float(inputs.estimated_one_leg_loss_usd),
    )
