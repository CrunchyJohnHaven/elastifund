#!/usr/bin/env python3
"""Maker-velocity blitz contracts and deterministic routing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketSnapshot:
    market_id: str
    question: str
    yes_price: float
    no_price: float
    resolution_hours: float
    spread: float
    liquidity_usd: float
    toxicity: float
    venue: str = "polymarket"
    timestamp: str = ""


@dataclass(frozen=True)
class WalletConsensusSignal:
    market_id: str
    direction: str
    edge: float
    fill_prob: float
    velocity_multiplier: float
    wallet_confidence: float
    toxicity_penalty: float
    source: str = "wallet_flow"
    timestamp: str = ""


@dataclass(frozen=True)
class QuoteIntent:
    market_id: str
    side: str
    price: float
    notional_usd: float
    post_only: bool
    level: int
    replace_after_seconds: int
    source_score: float
    generated_at: str


@dataclass(frozen=True)
class FillEvent:
    market_id: str
    side: str
    price: float
    notional_usd: float
    maker: bool
    timestamp: str


@dataclass(frozen=True)
class InventoryState:
    cash_usd: float
    reserved_cash_usd: float
    deployed_usd: float
    positions_usd: dict[str, float]
    updated_at: str


@dataclass(frozen=True)
class RiskEvent:
    event_type: str
    level: str
    triggered: bool
    reason: str
    cooldown_seconds: int
    timestamp: str


@dataclass(frozen=True)
class BlitzLaunchDecision:
    launch_go: bool
    checks: dict[str, bool]
    blocked_reasons: tuple[str, ...]
    source_of_truth: dict[str, str]


def compute_signal_score(
    *,
    edge: float,
    fill_prob: float,
    velocity_multiplier: float,
    wallet_confidence: float,
    toxicity_penalty: float,
) -> float:
    """Deterministic rank function for maker-velocity opportunities."""
    return (
        float(edge)
        * float(fill_prob)
        * float(velocity_multiplier)
        * float(wallet_confidence)
        * float(toxicity_penalty)
    )


def rank_wallet_signals(signals: list[WalletConsensusSignal]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for signal in signals:
        score = compute_signal_score(
            edge=signal.edge,
            fill_prob=signal.fill_prob,
            velocity_multiplier=signal.velocity_multiplier,
            wallet_confidence=signal.wallet_confidence,
            toxicity_penalty=signal.toxicity_penalty,
        )
        row = asdict(signal)
        row["score"] = score
        ranked.append(row)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def allocate_hour0_notional(
    *,
    bankroll_usd: float,
    ranked_signals: list[dict[str, Any]],
    reserve_pct: float = 0.05,
    per_market_cap_pct: float = 0.20,
) -> dict[str, float]:
    """Allocate notional with a fixed reserve and market-level concentration caps."""
    bankroll = max(0.0, float(bankroll_usd))
    if bankroll <= 0.0 or not ranked_signals:
        return {}

    reserve = bankroll * max(0.0, min(1.0, reserve_pct))
    deployable = max(0.0, bankroll - reserve)
    per_market_cap = bankroll * max(0.0, min(1.0, per_market_cap_pct))
    positive = [row for row in ranked_signals if _safe_float(row.get("score")) > 0.0]
    if not positive:
        return {}

    total_score = sum(_safe_float(row.get("score")) for row in positive)
    if total_score <= 0.0:
        return {}

    allocations: dict[str, float] = {}
    for row in positive:
        market_id = _safe_str(row.get("market_id")).strip()
        if not market_id:
            continue
        weight = _safe_float(row.get("score")) / total_score
        allocation = min(deployable * weight, per_market_cap)
        if allocation > 0:
            allocations[market_id] = allocation

    capped_total = sum(allocations.values())
    leftover = max(0.0, deployable - capped_total)
    if leftover <= 0.0:
        return allocations

    under_cap = [row for row in positive if allocations.get(_safe_str(row.get("market_id")), 0.0) < per_market_cap]
    under_cap_total = sum(_safe_float(row.get("score")) for row in under_cap)
    if under_cap_total <= 0.0:
        return allocations

    for row in under_cap:
        market_id = _safe_str(row.get("market_id")).strip()
        if not market_id:
            continue
        score = _safe_float(row.get("score"))
        additional = leftover * (score / under_cap_total)
        room = max(0.0, per_market_cap - allocations.get(market_id, 0.0))
        allocations[market_id] = allocations.get(market_id, 0.0) + min(room, additional)

    return allocations


def build_laddered_quote_intents(
    *,
    allocations_usd: dict[str, float],
    ranked_signals: list[dict[str, Any]],
    market_snapshots: dict[str, MarketSnapshot],
    levels: int = 3,
) -> list[QuoteIntent]:
    """Build post-only quote intents with 3-level ladders and 10-20s refresh."""
    by_market: dict[str, dict[str, Any]] = {}
    for row in ranked_signals:
        market_id = _safe_str(row.get("market_id")).strip()
        if market_id and market_id not in by_market:
            by_market[market_id] = row

    intents: list[QuoteIntent] = []
    levels_count = max(1, int(levels))
    for market_id, allocation in allocations_usd.items():
        if allocation <= 0.0:
            continue
        signal = by_market.get(market_id)
        snapshot = market_snapshots.get(market_id)
        if signal is None or snapshot is None:
            continue
        direction = _safe_str(signal.get("direction")).strip().lower()
        side = "buy_no" if "no" in direction else "buy_yes"
        ref_price = snapshot.no_price if side == "buy_no" else snapshot.yes_price
        score = _safe_float(signal.get("score"))
        per_level = allocation / float(levels_count)
        for idx in range(levels_count):
            price = max(0.01, min(0.99, ref_price - (0.01 * idx)))
            replace_seconds = min(20, 10 + (5 * idx))
            intents.append(
                QuoteIntent(
                    market_id=market_id,
                    side=side,
                    price=round(price, 4),
                    notional_usd=round(per_level, 6),
                    post_only=True,
                    level=idx + 1,
                    replace_after_seconds=replace_seconds,
                    source_score=score,
                    generated_at=_iso_now(),
                )
            )
    return intents


def evaluate_blitz_launch_ready(
    *,
    remote_cycle_status: dict[str, Any] | None,
    remote_service_status: dict[str, Any] | None,
    jj_state: dict[str, Any] | None,
    now: datetime | None = None,
) -> BlitzLaunchDecision:
    """Return machine-evaluable launch checks for maker-velocity blitz mode."""
    cycle = remote_cycle_status if isinstance(remote_cycle_status, dict) else {}
    service = remote_service_status if isinstance(remote_service_status, dict) else {}
    state = jj_state if isinstance(jj_state, dict) else {}
    checks: dict[str, bool] = {}
    blocked: list[str] = []
    source_of_truth = {
        "service_status": "reports/remote_cycle_status.json",
        "fallback_service_status": "reports/remote_service_status.json",
        "fallback_runtime": "jj_state.json",
    }

    wallet_ready = bool((cycle.get("wallet_flow") or {}).get("ready"))
    checks["wallet_ready"] = wallet_ready
    if not wallet_ready:
        blocked.append("wallet_not_ready")

    root_passing = _safe_str((cycle.get("root_tests") or {}).get("status")).lower() == "passing"
    checks["root_tests_passing"] = root_passing
    if not root_passing:
        blocked.append("root_tests_not_passing")

    fast_flow_ready = bool((cycle.get("launch") or {}).get("fast_flow_restart_ready"))
    checks["fast_flow_restart_ready"] = fast_flow_ready
    if not fast_flow_ready:
        blocked.append("fast_flow_not_ready")

    cadence = cycle.get("data_cadence") if isinstance(cycle.get("data_cadence"), dict) else {}
    stale_flag = bool(cadence.get("stale"))
    checks["fresh_pull_required"] = not stale_flag
    if stale_flag:
        blocked.append("fresh_pull_required")

    cycle_service_status = _safe_str((cycle.get("service") or {}).get("status")).strip().lower()
    service_status = _safe_str(service.get("status")).strip().lower()
    if not cycle_service_status:
        cycle_service_status = service_status or _safe_str(state.get("service_status")).strip().lower()
    checks["service_status_known"] = cycle_service_status in {"running", "stopped", "active", "inactive"}
    if not checks["service_status_known"]:
        blocked.append("service_status_unknown")

    if service_status and cycle_service_status and service_status not in {cycle_service_status, "active", "inactive"}:
        checks["service_conflict_reconciled"] = False
        blocked.append("service_status_conflict")
    else:
        checks["service_conflict_reconciled"] = True

    runtime_truth = cycle.get("runtime_truth") if isinstance(cycle.get("runtime_truth"), dict) else {}
    drift_detected = bool(runtime_truth.get("drift_detected"))
    checks["drift_cleared"] = not drift_detected
    if drift_detected:
        blocked.append("runtime_drift_detected")

    checks["capital_available"] = _safe_float(state.get("bankroll"), 0.0) > 0.0
    if not checks["capital_available"]:
        blocked.append("no_polymarket_capital")

    launch_go = all(checks.values())
    return BlitzLaunchDecision(
        launch_go=launch_go,
        checks=checks,
        blocked_reasons=tuple(dict.fromkeys(blocked)),
        source_of_truth=source_of_truth,
    )


def contract_schemas() -> dict[str, dict[str, Any]]:
    """JSON-schema-like contracts used by the maker-velocity LLM playbook."""
    return {
        "MarketSnapshot": {
            "required": [
                "market_id",
                "question",
                "yes_price",
                "no_price",
                "resolution_hours",
                "spread",
                "liquidity_usd",
                "toxicity",
            ]
        },
        "WalletConsensusSignal": {
            "required": [
                "market_id",
                "direction",
                "edge",
                "fill_prob",
                "velocity_multiplier",
                "wallet_confidence",
                "toxicity_penalty",
            ]
        },
        "QuoteIntent": {
            "required": [
                "market_id",
                "side",
                "price",
                "notional_usd",
                "post_only",
                "level",
                "replace_after_seconds",
                "source_score",
            ]
        },
        "FillEvent": {"required": ["market_id", "side", "price", "notional_usd", "maker", "timestamp"]},
        "InventoryState": {
            "required": ["cash_usd", "reserved_cash_usd", "deployed_usd", "positions_usd", "updated_at"]
        },
        "RiskEvent": {
            "required": ["event_type", "level", "triggered", "reason", "cooldown_seconds", "timestamp"]
        },
    }


def validate_contract_payload(contract_name: str, payload: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    schema = contract_schemas().get(contract_name)
    if schema is None:
        return False, (f"unknown_contract:{contract_name}",)
    missing = [field for field in schema["required"] if field not in payload]
    if missing:
        return False, tuple(f"missing:{field}" for field in missing)
    return True, tuple()


def deployment_kpis(*, bankroll_usd: float, inventory: InventoryState, fill_events: list[FillEvent]) -> dict[str, float]:
    bankroll = max(0.0, bankroll_usd)
    deployed_pct = 0.0 if bankroll <= 0 else (inventory.deployed_usd / bankroll) * 100.0
    maker_fills = [event for event in fill_events if event.maker]
    total_fills = len(fill_events)
    maker_fill_rate = 0.0 if total_fills == 0 else len(maker_fills) / total_fills
    return {
        "deployment_pct": round(deployed_pct, 4),
        "fill_count": float(total_fills),
        "maker_fill_rate": round(maker_fill_rate, 6),
        "inventory_skew_usd": round(abs(sum(inventory.positions_usd.values())), 6),
    }

