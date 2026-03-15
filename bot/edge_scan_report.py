#!/usr/bin/env python3
"""Generate the Instance #1 edge-scan handoff artifact."""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.execution_readiness import build_fast_flow_restart_report
from bot.runtime_profile import load_runtime_profile


REPORTS_DIR = REPO_ROOT / "reports"
RECENT_TRADES_LIMIT = 1000
MAX_RECENT_MARKETS = 60
TOP_MARKETS_FOR_VPIN = 10
INSTANCE_VERSION = "2.8.0"
CURRENT_THRESHOLDS = {"yes": 0.15, "no": 0.05}
AGGRESSIVE_THRESHOLDS = {"yes": 0.08, "no": 0.03}
WIDE_OPEN_THRESHOLDS = {"yes": 0.05, "no": 0.02}
AGGRESSIVE_MIN_CATEGORY_PRIORITY = 0
WIDE_OPEN_MIN_CATEGORY_PRIORITY = 0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _load_json_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _lazy_market_classifier() -> tuple[Any, float, float]:
    from bot.jj_live import PLATT_A, PLATT_B, classify_market_category

    return classify_market_category, float(PLATT_A), float(PLATT_B)


def _parse_outcome_prices(payload: dict[str, Any]) -> tuple[float, float]:
    raw = payload.get("outcomePrices")
    values: list[Any]
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            values = []
    elif isinstance(raw, list):
        values = raw
    else:
        values = []

    if len(values) >= 2:
        yes_price = _safe_float(values[0], 0.5)
        no_price = _safe_float(values[1], max(0.0, 1.0 - yes_price))
        return max(0.0, min(1.0, yes_price)), max(0.0, min(1.0, no_price))

    yes_price = _safe_float(payload.get("bestAsk"), 0.5)
    return max(0.0, min(1.0, yes_price)), max(0.0, min(1.0, 1.0 - yes_price))


def inverse_platt_probability(calibrated_prob: float, a: float, b: float) -> float:
    calibrated = max(0.01, min(0.99, float(calibrated_prob)))
    if abs(calibrated - 0.5) < 1e-9:
        return 0.5
    if calibrated < 0.5:
        return 1.0 - inverse_platt_probability(1.0 - calibrated, a, b)
    if abs(a) < 1e-9:
        return calibrated
    logit_output = math.log(calibrated / (1.0 - calibrated))
    logit_input = (logit_output - b) / a
    raw = 1.0 / (1.0 + math.exp(-logit_input))
    return max(0.001, min(0.999, raw))


def _required_llm_probabilities(
    *,
    yes_price: float,
    thresholds: dict[str, float],
    a: float,
    b: float,
) -> dict[str, float | None]:
    no_price = max(0.0, min(1.0, 1.0 - yes_price))
    yes_target = yes_price + float(thresholds["yes"])
    no_target = no_price + float(thresholds["no"])
    return {
        "required_calibrated_prob_yes": yes_target if yes_target <= 0.99 else None,
        "required_calibrated_prob_no": no_target if no_target <= 0.99 else None,
        "required_llm_prob_yes": (
            inverse_platt_probability(yes_target, a, b) if yes_target <= 0.99 else None
        ),
        "required_llm_prob_no": (
            inverse_platt_probability(no_target, a, b) if no_target <= 0.99 else None
        ),
        "in_price_window": bool(yes_target <= 0.99 or no_target <= 0.99),
    }


async def _fetch_recent_trades(
    client: httpx.AsyncClient,
    *,
    limit: int = RECENT_TRADES_LIMIT,
) -> list[dict[str, Any]]:
    response = await client.get(
        "https://data-api.polymarket.com/trades",
        params={"limit": limit},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def _fetch_market_by_condition_id(
    client: httpx.AsyncClient,
    condition_id: str,
) -> dict[str, Any] | None:
    response = await client.get(
        "https://gamma-api.polymarket.com/markets",
        params={"condition_ids": condition_id},
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list) and payload:
        item = payload[0]
        return item if isinstance(item, dict) else None
    return None


async def fetch_recent_open_markets(
    *,
    max_markets: int = MAX_RECENT_MARKETS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    now = _now_utc()
    timeout = httpx.Timeout(15.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        recent_trades = await _fetch_recent_trades(client)
        recent_condition_ids: list[str] = []
        fast_market_titles: set[str] = set()
        for trade in recent_trades:
            title = str(trade.get("title") or "")
            lowered = title.lower()
            if "up or down" in lowered and any(token in lowered for token in ("5m", "15m", "5-minute", "15-minute")):
                fast_market_titles.add(title)
            condition_id = str(trade.get("conditionId") or "").strip()
            if condition_id and condition_id not in recent_condition_ids:
                recent_condition_ids.append(condition_id)
            if len(recent_condition_ids) >= max_markets:
                break

        tasks = [
            _fetch_market_by_condition_id(client, condition_id)
            for condition_id in recent_condition_ids
        ]
        hydrated = [market for market in await asyncio.gather(*tasks) if isinstance(market, dict)]

    open_under_24h: list[dict[str, Any]] = []
    for market in hydrated:
        end_dt = _parse_iso8601(str(market.get("endDate") or ""))
        if end_dt is None:
            continue
        hours = (end_dt - now).total_seconds() / 3600.0
        if hours <= 0.0 or hours > 24.0:
            continue
        if bool(market.get("closed")):
            continue
        if not bool(market.get("acceptingOrders", True)):
            continue
        open_under_24h.append(market)

    return open_under_24h, recent_trades, {
        "recent_trades_fetched": len(recent_trades),
        "recent_market_hydrations": len(hydrated),
        "recent_fast_markets_seen": len(fast_market_titles),
    }


def _priority_for_category(
    category: str,
    category_priorities: dict[str, int],
) -> int:
    return int(category_priorities.get(category, category_priorities.get("unknown", 0)))


def _load_structural_truth() -> dict[str, dict[str, Any]]:
    empirical_snapshot = _load_json_payload(REPORTS_DIR / "arb_empirical_snapshot.json")
    b1_template_audit = _load_json_payload(REPORTS_DIR / "b1_template_audit.json")
    repo_truth = (
        empirical_snapshot.get("repo_truth", {})
        if isinstance(empirical_snapshot.get("repo_truth"), dict)
        else {}
    )
    public_a6 = repo_truth.get("public_a6_audit", {}) if isinstance(repo_truth.get("public_a6_audit"), dict) else {}
    public_b1 = repo_truth.get("public_b1_audit", {}) if isinstance(repo_truth.get("public_b1_audit"), dict) else {}
    live_surface = (
        empirical_snapshot.get("live_surface", {})
        if isinstance(empirical_snapshot.get("live_surface"), dict)
        else {}
    )
    template_pairs = b1_template_audit.get("template_pairs")
    template_pair_count = (
        len(template_pairs)
        if isinstance(template_pairs, list)
        else _safe_int(public_b1.get("deterministic_template_pair_count"))
    )

    return {
        "a6": {
            "allowed_events": _safe_int(public_a6.get("allowed_neg_risk_event_count")),
            "qualified": _safe_int(live_surface.get("qualified_a6_count")),
            "executable": _safe_int(public_a6.get("executable_constructions_below_threshold")),
            "execute_threshold": _safe_float(public_a6.get("execute_threshold"), 0.95),
        },
        "b1": {
            "template_pairs": template_pair_count,
            "allowed_market_sample_size": _safe_int(public_b1.get("allowed_market_sample_size"), 1000),
        },
    }


def summarize_market(
    market: dict[str, Any],
    *,
    now: datetime,
    category_priorities: dict[str, int],
    current_min_priority: int,
    aggressive_min_priority: int,
    wide_open_min_priority: int,
) -> dict[str, Any]:
    classifier, platt_a, platt_b = _lazy_market_classifier()
    question = str(market.get("question") or "")
    category = classifier(question)
    end_dt = _parse_iso8601(str(market.get("endDate") or ""))
    hours = (end_dt - now).total_seconds() / 3600.0 if end_dt is not None else None
    yes_price, no_price = _parse_outcome_prices(market)
    best_bid = _safe_float(market.get("bestBid"), yes_price)
    best_ask = _safe_float(market.get("bestAsk"), yes_price)
    spread = _safe_float(market.get("spread"), max(0.0, best_ask - best_bid))

    current_required = _required_llm_probabilities(
        yes_price=yes_price,
        thresholds=CURRENT_THRESHOLDS,
        a=platt_a,
        b=platt_b,
    )
    aggressive_required = _required_llm_probabilities(
        yes_price=yes_price,
        thresholds=AGGRESSIVE_THRESHOLDS,
        a=platt_a,
        b=platt_b,
    )
    wide_open_required = _required_llm_probabilities(
        yes_price=yes_price,
        thresholds=WIDE_OPEN_THRESHOLDS,
        a=platt_a,
        b=platt_b,
    )

    category_priority = _priority_for_category(category, category_priorities)
    return {
        "id": str(market.get("conditionId") or market.get("id") or ""),
        "question": question,
        "resolution_time": end_dt.isoformat() if end_dt is not None else None,
        "resolution_hours": _round_or_none(hours),
        "yes_price": _round_or_none(yes_price),
        "no_price": _round_or_none(no_price),
        "best_bid": _round_or_none(best_bid),
        "best_ask": _round_or_none(best_ask),
        "spread": _round_or_none(spread),
        "liquidity": _round_or_none(_safe_float(market.get("liquidity") or market.get("liquidityClob"))),
        "volume": _round_or_none(_safe_float(market.get("volume") or market.get("volumeClob"))),
        "category": category,
        "category_priority": category_priority,
        "allowed_current_profile": category_priority >= current_min_priority,
        "allowed_aggressive_profile": category_priority >= aggressive_min_priority,
        "allowed_wide_open_profile": category_priority >= wide_open_min_priority,
        "current_thresholds": {
            key: _round_or_none(value) if isinstance(value, float) else value
            for key, value in current_required.items()
        },
        "aggressive_thresholds": {
            key: _round_or_none(value) if isinstance(value, float) else value
            for key, value in aggressive_required.items()
        },
        "wide_open_thresholds": {
            key: _round_or_none(value) if isinstance(value, float) else value
            for key, value in wide_open_required.items()
        },
    }


def _build_lmsr_inputs(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for market in markets:
        prices = market.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                prices = None
        if not isinstance(prices, list):
            prices = list(_parse_outcome_prices(market))
        payloads.append(
            {
                "condition_id": str(market.get("conditionId") or market.get("id") or ""),
                "question": str(market.get("question") or ""),
                "outcomePrices": prices,
                "bestBid": market.get("bestBid"),
                "bestAsk": market.get("bestAsk"),
                "volume24hr": market.get("volume24hr"),
                "liquidity": market.get("liquidity") or market.get("liquidityClob"),
            }
        )
    return payloads


def _scan_wallet_flow() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from bot.wallet_flow_detector import get_bootstrap_status, get_signals_for_engine

    bootstrap = get_bootstrap_status()
    if not bootstrap.ready:
        return [], {
            "status": "blocked",
            "bootstrap": asdict(bootstrap),
            "signals_found": 0,
        }

    signals = get_signals_for_engine()
    return signals, {
        "status": "active" if signals else "idle",
        "bootstrap": asdict(bootstrap),
        "signals_found": len(signals),
    }


def _scan_lmsr(markets: list[dict[str, Any]], threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from bot.lmsr_engine import LMSREngine

    engine = LMSREngine(entry_threshold=threshold)
    inputs = _build_lmsr_inputs(markets[:15])
    signals = engine.get_signals(inputs)
    return signals, {
        "status": "active" if signals else "idle",
        "signals_found": len(signals),
        "markets_scanned": len(inputs),
    }


def _scan_cross_platform(timeout_seconds: float = 30.0) -> dict[str, Any]:
    from bot.cross_platform_arb import (
        fetch_kalshi_markets,
        match_markets,
        fetch_polymarket_markets,
        get_kalshi_client,
        scan_for_arbs,
    )

    def _runner() -> dict[str, Any]:
        client = get_kalshi_client()
        if not client:
            return {
                "status": "blocked",
                "reason": "kalshi_client_unavailable",
                "credentials_present": False,
                "opportunities": [],
                "opportunities_found": 0,
            }
        poly_markets = asyncio.run(fetch_polymarket_markets(max_pages=2))
        kalshi_markets = fetch_kalshi_markets(client, max_pages=2)
        matches = match_markets(poly_markets, kalshi_markets, threshold=0.70)
        arbs = scan_for_arbs(poly_markets, kalshi_markets)
        return {
            "status": "active" if arbs else "idle",
            "credentials_present": True,
            "polymarket_markets_scanned": len(poly_markets),
            "kalshi_markets_scanned": len(kalshi_markets),
            "matches_found": len(matches),
            "opportunities_found": len(arbs),
            "opportunities": [
                {
                    "direction": arb.direction,
                    "match_score": _round_or_none(arb.match_score),
                    "net_profit_pct": _round_or_none(arb.net_profit_pct),
                    "poly_market_id": str(arb.poly_market.market_id),
                    "poly_title": arb.poly_market.title,
                    "kalshi_market_id": str(arb.kalshi_market.market_id),
                    "kalshi_title": arb.kalshi_market.title,
                    "poly_end_date": arb.poly_market.end_date,
                    "kalshi_end_date": arb.kalshi_market.end_date,
                }
                for arb in arbs[:10]
            ],
        }

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_runner)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return {
            "status": "timeout",
            "reason": f"cross_platform_scan_exceeded_{int(timeout_seconds)}s",
            "credentials_present": True,
            "opportunities": [],
            "opportunities_found": 0,
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _scan_a6(profile_bundle: Any) -> dict[str, Any]:
    from bot.sum_violation_scanner import SumViolationScanner

    scanner = SumViolationScanner(
        use_websocket=False,
        max_pages=3,
        page_size=50,
        max_events=20,
        buy_threshold=float(profile_bundle.profile.combinatorial_thresholds.a6_buy_threshold),
        execute_threshold=0.95,
        unwind_threshold=float(profile_bundle.profile.combinatorial_thresholds.a6_unwind_threshold),
        stale_quote_seconds=int(profile_bundle.profile.combinatorial_thresholds.stale_book_max_age_seconds),
        timeout_seconds=10.0,
    )
    try:
        stats = scanner.scan_once()
        opportunities = list(getattr(scanner, "_latest_opportunities", []))
        return {
            "status": "active" if stats.violations_found else "idle",
            "stats": asdict(stats),
            "candidates": stats.candidate_markets,
            "executable": len(opportunities),
            "opportunities": [
                {
                    "event_id": opp.event_id,
                    "signal_type": opp.signal_type,
                    "theoretical_edge": _round_or_none(opp.theoretical_edge),
                    "sum_yes_ask": _round_or_none(opp.sum_yes_ask),
                    "selected_construction": opp.selected_construction,
                    "readiness_status": opp.readiness_status,
                    "legs": len(opp.legs),
                }
                for opp in opportunities[:10]
            ],
        }
    finally:
        scanner.close()


async def _fetch_condition_trades(
    client: httpx.AsyncClient,
    condition_id: str,
    *,
    limit: int = 250,
) -> list[dict[str, Any]]:
    response = await client.get(
        "https://data-api.polymarket.com/trades",
        params={"conditionId": condition_id, "limit": limit},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def compute_vpin_snapshots(
    market_summaries: list[dict[str, Any]],
    *,
    bucket_size: float,
    window_size: int,
    toxic_threshold: float,
    safe_threshold: float,
) -> list[dict[str, Any]]:
    from bot.vpin_toxicity import VPINManager

    top = sorted(
        market_summaries,
        key=lambda item: (-_safe_float(item.get("liquidity")), _safe_float(item.get("spread"), 1.0)),
    )[:TOP_MARKETS_FOR_VPIN]
    timeout = httpx.Timeout(15.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tapes = await asyncio.gather(
            *[
                _fetch_condition_trades(client, str(item["id"]))
                for item in top
            ],
            return_exceptions=True,
        )

    snapshots: list[dict[str, Any]] = []
    for item, tape in zip(top, tapes):
        if isinstance(tape, Exception):
            snapshots.append(
                {
                    "market_id": item["id"],
                    "question": item["question"],
                    "status": "error",
                    "error": str(tape),
                }
            )
            continue
        manager = VPINManager(
            bucket_size=bucket_size,
            window_size=window_size,
            toxic_threshold=toxic_threshold,
            safe_threshold=safe_threshold,
        )
        ordered = sorted(tape, key=lambda row: _safe_float(row.get("timestamp")))
        for trade in ordered:
            manager.on_trade(
                str(item["id"]),
                price=_safe_float(trade.get("price"), 0.5),
                size=_safe_float(trade.get("size"), 0.0),
                side=str(trade.get("side") or "").lower(),
                timestamp=_safe_float(trade.get("timestamp"), 0.0),
            )
        state = manager._get_or_create_state(str(item["id"]))
        snapshots.append(
            {
                "market_id": item["id"],
                "question": item["question"],
                "trade_count": len(ordered),
                "vpin": _round_or_none(state.vpin),
                "regime": state.regime.value,
                "is_ready": state.is_ready,
                "buckets_filled": state.buckets_filled,
                "toxic": bool(state.is_ready and state.regime.value == "toxic"),
            }
        )
    return snapshots


def _kelly_size_usd(
    *,
    edge: float,
    market_price: float,
    bankroll_usd: float,
    position_cap_usd: float,
    resolution_hours: float | None,
) -> float:
    from bot.lmsr_engine import kelly_fraction

    fast_market = resolution_hours is not None and resolution_hours <= 1.0
    fraction = kelly_fraction(
        ev=edge,
        p_market=max(0.01, min(0.99, market_price)),
        fast_market=bool(fast_market),
        taker_fee=0.0,
    )
    return round(min(position_cap_usd, bankroll_usd * fraction), 4)


def _join_candidates(
    *,
    market_summaries: list[dict[str, Any]],
    wallet_signals: list[dict[str, Any]],
    lmsr_signals: list[dict[str, Any]],
    vpin_snapshots: list[dict[str, Any]],
    bankroll_usd: float,
    position_cap_usd: float,
    current_min_priority: int,
    aggressive_min_priority: int,
    wide_open_min_priority: int,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    by_market_id = {str(item["id"]): item for item in market_summaries}
    vpin_by_market = {str(item["market_id"]): item for item in vpin_snapshots}
    all_signals = [
        *wallet_signals,
        *lmsr_signals,
    ]
    directions_by_market: dict[str, set[str]] = {}
    for signal in all_signals:
        market_id = str(signal.get("market_id") or "")
        directions_by_market.setdefault(market_id, set()).add(str(signal.get("direction") or ""))

    candidates: list[dict[str, Any]] = []
    counts = {"current": 0, "aggressive": 0, "wide_open": 0}
    notes: list[str] = []

    for signal in all_signals:
        market_id = str(signal.get("market_id") or "")
        market = by_market_id.get(market_id)
        if market is None:
            continue
        direction = str(signal.get("direction") or "")
        edge = _safe_float(signal.get("edge"))
        current_threshold = CURRENT_THRESHOLDS["yes"] if direction == "buy_yes" else CURRENT_THRESHOLDS["no"]
        aggressive_threshold = AGGRESSIVE_THRESHOLDS["yes"] if direction == "buy_yes" else AGGRESSIVE_THRESHOLDS["no"]
        wide_open_threshold = WIDE_OPEN_THRESHOLDS["yes"] if direction == "buy_yes" else WIDE_OPEN_THRESHOLDS["no"]
        local_failures: list[str] = []
        if len(directions_by_market.get(market_id, set())) > 1:
            local_failures.append("conflicting_directions")
        vpin_snapshot = vpin_by_market.get(market_id)
        if isinstance(vpin_snapshot, dict) and vpin_snapshot.get("toxic"):
            local_failures.append("toxic_flow")
        category_priority = _safe_int(market.get("category_priority"))
        current_allowed = category_priority >= current_min_priority
        aggressive_allowed = category_priority >= aggressive_min_priority
        wide_open_allowed = category_priority >= wide_open_min_priority
        passes_current = current_allowed and edge >= current_threshold and not local_failures
        passes_aggressive = aggressive_allowed and edge >= aggressive_threshold and not local_failures
        passes_wide_open = wide_open_allowed and edge >= wide_open_threshold and not local_failures
        if passes_current:
            counts["current"] += 1
        if passes_aggressive:
            counts["aggressive"] += 1
        if passes_wide_open:
            counts["wide_open"] += 1
        if "conflicting_directions" in local_failures:
            notes.append(
                f"Conflicting live directions on {market['question']} ({', '.join(sorted(directions_by_market[market_id]))})."
            )
        market_price = _safe_float(market.get("yes_price"), _safe_float(signal.get("market_price"), 0.5))
        candidates.append(
            {
                "id": market_id,
                "title": market["question"],
                "resolution_time": market["resolution_time"],
                "resolution_hours": market["resolution_hours"],
                "category": market["category"],
                "source": signal.get("source"),
                "direction": direction,
                "yes_price": market["yes_price"],
                "edge": _round_or_none(edge),
                "confidence": _round_or_none(_safe_float(signal.get("confidence"))),
                "reasoning": signal.get("reasoning"),
                "current_threshold_pass": passes_current,
                "aggressive_threshold_pass": passes_aggressive,
                "wide_open_threshold_pass": passes_wide_open,
                "kill_rule_status": "pass" if not local_failures else "fail",
                "kill_rule_failures": sorted(set(local_failures)),
                "vpin": vpin_snapshot,
                "recommended_size_usd": _kelly_size_usd(
                    edge=edge,
                    market_price=market_price,
                    bankroll_usd=bankroll_usd,
                    position_cap_usd=position_cap_usd,
                    resolution_hours=_safe_float(market.get("resolution_hours"), None),
                ),
            }
        )

    deduped_notes = sorted(set(notes))
    return candidates, counts, deduped_notes


def _build_capital_snapshot() -> dict[str, Any]:
    jj_state_path = REPO_ROOT / "jj_state.json"
    runtime_snapshot_path = REPORTS_DIR / "public_runtime_snapshot.json"
    jj_state = json.loads(jj_state_path.read_text()) if jj_state_path.exists() else {}
    runtime_snapshot = json.loads(runtime_snapshot_path.read_text()) if runtime_snapshot_path.exists() else {}
    capital = runtime_snapshot.get("capital", {}) if isinstance(runtime_snapshot, dict) else {}
    return {
        "polymarket_bankroll_usd": _safe_float(jj_state.get("bankroll"), _safe_float(capital.get("bankroll_usd"))),
        "deployed_capital_usd": _safe_float(jj_state.get("total_deployed"), _safe_float(capital.get("deployed_capital_usd"))),
        "tracked_capital_usd": _safe_float(capital.get("tracked_capital_usd"), _safe_float(jj_state.get("bankroll"))),
        "undeployed_capital_usd": _safe_float(capital.get("undeployed_capital_usd"), _safe_float(jj_state.get("bankroll"))),
    }


def _recommend_action(
    *,
    restart_gate: dict[str, Any],
    viable_current: int,
    viable_aggressive: int,
    viable_wide_open: int | None = None,
    candidate_notes: list[str],
) -> tuple[str, bool, str]:
    blocked_reasons = [str(reason) for reason in restart_gate.get("blocked_reasons") or []]
    service_status = str(restart_gate.get("service_status") or "unknown")
    if viable_current >= 3 and bool(restart_gate.get("restart_ready")):
        return "restart_current", True, "Current thresholds already surface 3+ locally viable opportunities."
    if viable_aggressive >= 3 and bool(restart_gate.get("restart_ready")):
        return (
            "restart_with_aggressive_thresholds",
            True,
            "Aggressive thresholds surface 3+ locally viable opportunities and the restart gate is clear.",
        )
    if service_status == "running" and blocked_reasons:
        reason = "Service is already running while restart blockers remain unresolved."
        if candidate_notes:
            reason += f" {candidate_notes[0]}"
        return "human_review_required", False, reason
    if viable_wide_open == 0:
        return (
            "recalibrate",
            False,
            "Zero viable markets even at wide-open thresholds (YES=0.05, NO=0.02); Platt parameters may be stale.",
        )
    if candidate_notes:
        return "stay_paused", False, candidate_notes[0]
    if viable_aggressive > viable_current:
        return (
            "stay_paused",
            False,
            "Aggressive thresholds widen the theoretical trade set, but restart blockers still dominate.",
        )
    return "stay_paused", False, "No clean restart recommendation emerged from the current scan."


def generate_edge_scan_report(*, output_path: Path | None = None) -> Path:
    load_dotenv(REPO_ROOT / ".env")
    now = _now_utc()
    profile_bundle = load_runtime_profile()
    restart_gate = build_fast_flow_restart_report(REPO_ROOT)
    capital = _build_capital_snapshot()
    structural_truth = _load_structural_truth()
    bankroll_usd = _safe_float(capital.get("polymarket_bankroll_usd"))
    current_min_priority = int(profile_bundle.profile.market_filters.min_category_priority)
    category_priorities = {
        str(key): int(value)
        for key, value in profile_bundle.profile.market_filters.category_priorities.items()
    }

    markets, recent_trades, market_scan = asyncio.run(fetch_recent_open_markets())
    market_summaries = [
        summarize_market(
            market,
            now=now,
            category_priorities=category_priorities,
            current_min_priority=current_min_priority,
            aggressive_min_priority=AGGRESSIVE_MIN_CATEGORY_PRIORITY,
            wide_open_min_priority=WIDE_OPEN_MIN_CATEGORY_PRIORITY,
        )
        for market in markets
    ]
    market_summaries.sort(
        key=lambda item: (-_safe_float(item.get("liquidity")), _safe_float(item.get("spread"), 1.0))
    )

    wallet_signals, wallet_health = _scan_wallet_flow()
    lmsr_signals, lmsr_health = _scan_lmsr(
        markets,
        threshold=float(profile_bundle.profile.signal_thresholds.lmsr_entry_threshold),
    )
    cross_platform = _scan_cross_platform()
    a6_scan_result = _scan_a6(profile_bundle)
    vpin_snapshots = asyncio.run(
        compute_vpin_snapshots(
            market_summaries,
            bucket_size=float(profile_bundle.profile.microstructure_thresholds.vpin_bucket_size),
            window_size=int(profile_bundle.profile.microstructure_thresholds.vpin_window_size),
            toxic_threshold=float(profile_bundle.profile.microstructure_thresholds.vpin_toxic_threshold),
            safe_threshold=float(profile_bundle.profile.microstructure_thresholds.vpin_safe_threshold),
        )
    )

    candidate_markets, viable_counts, candidate_notes = _join_candidates(
        market_summaries=market_summaries,
        wallet_signals=wallet_signals,
        lmsr_signals=lmsr_signals,
        vpin_snapshots=vpin_snapshots,
        bankroll_usd=bankroll_usd,
        position_cap_usd=float(profile_bundle.profile.risk_limits.max_position_usd),
        current_min_priority=current_min_priority,
        aggressive_min_priority=AGGRESSIVE_MIN_CATEGORY_PRIORITY,
        wide_open_min_priority=WIDE_OPEN_MIN_CATEGORY_PRIORITY,
    )

    recommended_action, restart_recommended, action_reason = _recommend_action(
        restart_gate=restart_gate,
        viable_current=viable_counts["current"],
        viable_aggressive=viable_counts["aggressive"],
        viable_wide_open=viable_counts["wide_open"],
        candidate_notes=candidate_notes,
    )

    payload = {
        "instance": 1,
        "instance_version": INSTANCE_VERSION,
        "purpose": "edge_scan_and_fast_flow_restart_readiness",
        "generated_at": now.isoformat(),
        "runtime_profile": profile_bundle.selected_profile,
        "source_path": profile_bundle.source_path,
        "markets_pulled": len(markets),
        "markets_under_24h": len(market_summaries),
        "markets_in_price_window": {
            "current": sum(1 for item in market_summaries if item["current_thresholds"]["in_price_window"]),
            "aggressive": sum(1 for item in market_summaries if item["aggressive_thresholds"]["in_price_window"]),
            "wide_open": sum(1 for item in market_summaries if item["wide_open_thresholds"]["in_price_window"]),
        },
        "markets_in_allowed_categories": {
            "current": sum(1 for item in market_summaries if item["allowed_current_profile"]),
            "aggressive": sum(1 for item in market_summaries if item["allowed_aggressive_profile"]),
            "wide_open": sum(1 for item in market_summaries if item["allowed_wide_open_profile"]),
        },
        "viable_at_current_thresholds": viable_counts["current"],
        "viable_at_aggressive_thresholds": viable_counts["aggressive"],
        "viable_at_wide_open": viable_counts["wide_open"],
        "threshold_sensitivity": {
            "current": dict(CURRENT_THRESHOLDS),
            "aggressive": dict(AGGRESSIVE_THRESHOLDS),
            "wide_open": dict(WIDE_OPEN_THRESHOLDS),
            "current_min_category_priority": current_min_priority,
            "aggressive_min_category_priority": AGGRESSIVE_MIN_CATEGORY_PRIORITY,
            "wide_open_min_category_priority": WIDE_OPEN_MIN_CATEGORY_PRIORITY,
        },
        "capital_available_usd": bankroll_usd,
        "capital_available": capital,
        "risk_caps": {
            "max_position_usd": float(profile_bundle.profile.risk_limits.max_position_usd),
            "max_daily_loss_usd": float(profile_bundle.profile.risk_limits.max_daily_loss_usd),
            "max_open_positions": int(profile_bundle.profile.risk_limits.max_open_positions),
            "kelly_fraction": float(profile_bundle.profile.risk_limits.kelly_fraction),
            "paper_mode_local": bool(profile_bundle.profile.mode.paper_trading),
        },
        "runtime_truth": restart_gate,
        "market_scan": {
            **market_scan,
            "recent_trade_window": {
                "newest_trade_at": (
                    datetime.fromtimestamp(
                        max(_safe_float(trade.get("timestamp")) for trade in recent_trades),
                        tz=timezone.utc,
                    ).isoformat()
                    if recent_trades
                    else None
                ),
                "oldest_trade_at": (
                    datetime.fromtimestamp(
                        min(_safe_float(trade.get("timestamp")) for trade in recent_trades),
                        tz=timezone.utc,
                    ).isoformat()
                    if recent_trades
                    else None
                ),
            },
        },
        "wallet_flow_status": {
            "ready": bool(wallet_health.get("bootstrap", {}).get("ready")),
            "scored_wallets": _safe_int(wallet_health.get("bootstrap", {}).get("wallet_count")),
            "signals_found": _safe_int(wallet_health.get("signals_found")),
        },
        "a6_scan_result": {
            **structural_truth["a6"],
            "live_scan_candidates": _safe_int(a6_scan_result.get("candidates")),
            "live_scan_executable": _safe_int(a6_scan_result.get("executable")),
        },
        "b1_scan_result": dict(structural_truth["b1"]),
        "cross_platform_arb": {
            "kalshi_markets": _safe_int(cross_platform.get("kalshi_markets_scanned")),
            "matches": _safe_int(cross_platform.get("matches_found")),
            "arb_opportunities": _safe_int(cross_platform.get("opportunities_found")),
            "status": cross_platform.get("status"),
            "reason": cross_platform.get("reason"),
        },
        "lane_health": {
            "wallet_flow": wallet_health,
            "lmsr": lmsr_health,
            "cross_platform_arb": cross_platform,
            "a6": a6_scan_result,
            "vpin": {
                "status": "active" if vpin_snapshots else "idle",
                "tokens_tracked": len(vpin_snapshots),
                "toxic_tokens": [item["market_id"] for item in vpin_snapshots if item.get("toxic")],
                "microstructure": vpin_snapshots,
            },
        },
        "markets": market_summaries[:20],
        "candidate_markets": candidate_markets[:20],
        "recommended_action": recommended_action,
        "restart_recommended": restart_recommended,
        "action_reason": action_reason,
        "notes": [
            "Primary market discovery used recent trade tape hydration because Gamma active-market paging did not surface current fast markets in the first pages.",
            *candidate_notes,
        ],
    }

    if output_path is None:
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        output_path = REPORTS_DIR / f"edge_scan_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Instance #1 edge scan report.")
    parser.add_argument(
        "--output",
        help="Optional explicit output path. Defaults to reports/edge_scan_<timestamp>.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = generate_edge_scan_report(
        output_path=Path(args.output).expanduser().resolve() if args.output else None,
    )
    print(output)


if __name__ == "__main__":
    main()
