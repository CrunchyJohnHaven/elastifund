#!/usr/bin/env python3
"""Instance #2 Polymarket fast-lane candidate surface generator."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

# Allow direct execution via `python3 bot/polymarket_fastlane_surface.py`.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.edge_scan_report import (
    REPO_ROOT,
    REPORTS_DIR,
    _safe_float,
    _safe_int,
    _parse_iso8601,
    _parse_outcome_prices,
    fetch_recent_open_markets,
)
from bot.lmsr_engine import LMSREngine
from bot.runtime_profile import load_runtime_profile
from bot.vpin_toxicity import VPINManager
from bot.wallet_flow_detector import get_bootstrap_status, get_signals_for_engine

INSTANCE_VERSION = "2.0.0"
TRADES_API = "https://data-api.polymarket.com/trades"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _priority_label(question: str) -> tuple[int, str]:
    q = (question or "").lower()
    is_btc = "bitcoin" in q or "btc" in q
    is_eth = "ethereum" in q or "eth" in q
    interval_minutes = _infer_interval_minutes(question)

    if is_btc and any(token in q for token in ("15m", "15-minute", "15 minute")):
        return 0, "btc_15m"
    if is_btc and any(token in q for token in ("5m", "5-minute", "5 minute")):
        return 1, "btc_5m"
    if is_btc and interval_minutes == 15:
        return 0, "btc_15m"
    if is_btc and interval_minutes == 5:
        return 1, "btc_5m"
    if is_btc and any(token in q for token in ("4h", "4-hour", "4 hour")):
        return 2, "btc_4h"

    eth_intraday_tokens = ("5m", "15m", "30m", "1h", "2h", "3h", "4h", "intraday", "hour")
    if is_eth and any(token in q for token in eth_intraday_tokens):
        return 3, "eth_intraday"

    return 4, "other"


def _infer_interval_minutes(question: str) -> int | None:
    title = str(question or "")
    match = re.search(
        r"(\d{1,2}):(\d{2})\s*(am|pm)\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)",
        title,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    def _to_minutes(hour_text: str, minute_text: str, ampm: str) -> int:
        hour = int(hour_text) % 12
        if ampm.lower() == "pm":
            hour += 12
        minute = int(minute_text)
        return (hour * 60) + minute

    start = _to_minutes(match.group(1), match.group(2), match.group(3))
    end = _to_minutes(match.group(4), match.group(5), match.group(6))
    if end < start:
        end += 24 * 60
    diff = end - start
    return diff if diff > 0 else None


def _horizon_label(resolution_hours: float | None) -> str:
    if resolution_hours is None:
        return "unknown"
    if resolution_hours <= 3.0:
        return "3h"
    if resolution_hours <= 24.0:
        return "24h"
    return ">24h"


def _safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if den == 0:
        return default
    return num / den


def _compute_ofi_from_tape(trades: list[dict[str, Any]]) -> float:
    buy = 0.0
    sell = 0.0
    for trade in trades:
        size = _safe_float(trade.get("size"), 0.0)
        side = str(trade.get("side") or "").lower()
        if side == "buy":
            buy += size
        elif side == "sell":
            sell += size
    total = buy + sell
    return max(-1.0, min(1.0, _safe_ratio(buy - sell, total, 0.0)))


def _expected_fill_probability(
    *,
    spread: float,
    liquidity: float,
    vpin: float | None,
    resolution_hours: float | None,
) -> float:
    spread_penalty = min(1.0, max(0.0, spread) * 3.0)
    liquidity_boost = min(1.0, math.log10(max(1.0, liquidity + 1.0)) / 4.0)
    vpin_penalty = 0.0
    if vpin is not None:
        vpin_penalty = max(0.0, min(1.0, (vpin - 0.5) * 1.6))
    speed_boost = 0.0
    if isinstance(resolution_hours, (int, float)) and resolution_hours > 0:
        speed_boost = min(0.25, 0.25 / max(1.0, float(resolution_hours)))

    raw = 0.35 + (0.45 * liquidity_boost) + speed_boost - (0.30 * spread_penalty) - (0.25 * vpin_penalty)
    return round(max(0.01, min(0.99, raw)), 4)


def _route_score(
    *,
    fee_adjusted_edge: float,
    fill_probability: float,
    wallet_consensus_score: float,
    toxicity_state: str,
    quality_penalty: float,
) -> float:
    toxicity_multiplier = 0.5 if toxicity_state == "toxic" else 1.0
    raw = fee_adjusted_edge * fill_probability * (0.5 + wallet_consensus_score) * toxicity_multiplier
    return round(raw * quality_penalty, 6)


def _diagnose_empty_surface(
    *,
    scanner_ok: bool,
    filter_ok: bool,
    join_ok: bool,
    reject_reason_counts: dict[str, int],
) -> tuple[str, str]:
    if not scanner_ok:
        return "broken_pipeline", "scanner"
    if not filter_ok:
        return "broken_pipeline", "filter"
    if not join_ok:
        return "broken_pipeline", "join"

    ordered = [
        "category_gating",
        "data_quality_loss",
        "wallet_sparsity",
        "toxicity",
        "expectancy_failure",
    ]
    top_reason = "expectancy_failure"
    top_count = -1
    for reason in ordered:
        count = int(reject_reason_counts.get(reason, 0))
        if count > top_count:
            top_reason = reason
            top_count = count
    return "genuinely_not_tradeable", top_reason


async def _fetch_condition_trades(client: httpx.AsyncClient, condition_id: str, limit: int = 300) -> list[dict[str, Any]]:
    response = await client.get(TRADES_API, params={"conditionId": condition_id, "limit": limit})
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _load_wallet_signals() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bootstrap = get_bootstrap_status()
    if not bootstrap.ready:
        return [], {"status": "blocked", "bootstrap": asdict(bootstrap), "signals_found": 0}
    signals = get_signals_for_engine()
    return signals, {"status": "active" if signals else "idle", "bootstrap": asdict(bootstrap), "signals_found": len(signals)}


def _load_lmsr_signals(markets: list[dict[str, Any]], entry_threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for market in markets:
        yes_price, _ = _parse_outcome_prices(market)
        inputs.append(
            {
                "condition_id": str(market.get("conditionId") or market.get("id") or ""),
                "question": str(market.get("question") or ""),
                "outcomePrices": [yes_price, 1.0 - yes_price],
                "bestBid": market.get("bestBid"),
                "bestAsk": market.get("bestAsk"),
                "volume24hr": market.get("volume24hr"),
                "liquidity": market.get("liquidity") or market.get("liquidityClob"),
            }
        )

    engine = LMSREngine(entry_threshold=entry_threshold)
    signals = engine.get_signals(inputs)
    return signals, {"status": "active" if signals else "idle", "signals_found": len(signals), "markets_scanned": len(inputs)}


def _build_market_records(
    *,
    markets: list[dict[str, Any]],
    wallet_signals: list[dict[str, Any]],
    lmsr_signals: list[dict[str, Any]],
    trade_tapes: dict[str, list[dict[str, Any]]],
    vpin_state: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    wallet_by_market = {str(item.get("market_id") or ""): item for item in wallet_signals}
    lmsr_by_market = {str(item.get("market_id") or ""): item for item in lmsr_signals}

    records: list[dict[str, Any]] = []
    reject_reason_counts = {
        "category_gating": 0,
        "data_quality_loss": 0,
        "wallet_sparsity": 0,
        "toxicity": 0,
        "expectancy_failure": 0,
    }

    for market in markets:
        market_id = str(market.get("conditionId") or market.get("id") or "")
        question = str(market.get("question") or "")
        if not market_id:
            continue

        end_dt = _parse_iso8601(str(market.get("endDate") or ""))
        resolution_hours = None
        if end_dt is not None:
            resolution_hours = (end_dt - _now_utc()).total_seconds() / 3600.0

        yes_price, no_price = _parse_outcome_prices(market)
        best_bid = _safe_float(market.get("bestBid"), yes_price)
        best_ask = _safe_float(market.get("bestAsk"), yes_price)
        spread = max(0.0, _safe_float(market.get("spread"), best_ask - best_bid))
        liquidity = _safe_float(market.get("liquidity") or market.get("liquidityClob"), 0.0)
        volume = _safe_float(market.get("volume") or market.get("volumeClob"), 0.0)

        priority_rank, priority_label = _priority_label(question)
        horizon = _horizon_label(resolution_hours)
        wallet_signal = wallet_by_market.get(market_id)
        lmsr_signal = lmsr_by_market.get(market_id)
        vpin_snapshot = vpin_state.get(market_id, {})
        tape = trade_tapes.get(market_id, [])
        trade_count = len(tape)

        wallet_conf = _safe_float((wallet_signal or {}).get("confidence"), 0.0)
        wallet_count_hint = _safe_float((wallet_signal or {}).get("reasoning", "").count("wallet"), 0.0)
        wallet_consensus_score = round(min(1.0, wallet_conf + (0.02 * wallet_count_hint)), 4)

        lmsr_gap = _safe_float((lmsr_signal or {}).get("edge"), 0.0)
        vpin = vpin_snapshot.get("vpin") if isinstance(vpin_snapshot.get("vpin"), (int, float)) else None
        toxicity_state = "unknown"
        if isinstance(vpin_snapshot, dict) and vpin_snapshot:
            toxicity_state = str(vpin_snapshot.get("regime") or "unknown")
        ofi = _compute_ofi_from_tape(tape)

        expected_fill_probability = _expected_fill_probability(
            spread=spread,
            liquidity=liquidity,
            vpin=_safe_float(vpin, 0.5) if vpin is not None else None,
            resolution_hours=resolution_hours,
        )

        maker_fee = 0.0
        fee_adjusted_edge = round(max(-1.0, min(1.0, lmsr_gap + (wallet_consensus_score * 0.08) - maker_fee)), 6)

        data_quality_flags: list[str] = []
        if trade_count == 0:
            data_quality_flags.append("no_trade_tape")
        if vpin is None:
            data_quality_flags.append("vpin_not_ready")
        if liquidity <= 0.0:
            data_quality_flags.append("no_liquidity")
        if spread <= 0.0:
            data_quality_flags.append("spread_missing_or_zero")

        quality_penalty = 1.0 - min(0.6, 0.15 * len(data_quality_flags))
        route_score = _route_score(
            fee_adjusted_edge=fee_adjusted_edge,
            fill_probability=expected_fill_probability,
            wallet_consensus_score=wallet_consensus_score,
            toxicity_state=toxicity_state,
            quality_penalty=quality_penalty,
        )

        reject_reason: str | None = None
        if priority_rank > 3:
            reject_reason = "category_gating"
        elif data_quality_flags:
            reject_reason = "data_quality_loss"
        elif toxicity_state == "toxic":
            reject_reason = "toxicity"
        elif wallet_consensus_score < 0.45:
            reject_reason = "wallet_sparsity"
        elif fee_adjusted_edge <= 0.0 or route_score <= 0.0:
            reject_reason = "expectancy_failure"

        if reject_reason is not None:
            reject_reason_counts[reject_reason] = reject_reason_counts.get(reject_reason, 0) + 1

        record = {
            "market_id": market_id,
            "title": question,
            "priority_lane": priority_label,
            "priority_rank": priority_rank,
            "horizon": horizon,
            "resolution_time": end_dt.isoformat() if end_dt else None,
            "resolution_hours": round(resolution_hours, 4) if isinstance(resolution_hours, (int, float)) else None,
            "best_yes": round(yes_price, 4),
            "best_no": round(no_price, 4),
            "spread": round(spread, 4),
            "visible_depth_proxy": round(liquidity, 4),
            "visible_volume_proxy": round(volume, 4),
            "wallet_consensus_score": wallet_consensus_score,
            "top_wallet_convergence_time": _safe_int((wallet_signal or {}).get("signal_age_seconds"), 0),
            "lmsr_gap": round(lmsr_gap, 6),
            "vpin": round(_safe_float(vpin), 6) if vpin is not None else None,
            "ofi": round(ofi, 6),
            "toxicity_state": toxicity_state,
            "expected_maker_fill_probability": expected_fill_probability,
            "fee_adjusted_expected_edge": fee_adjusted_edge,
            "route_score": route_score,
            "reject_reason": reject_reason,
            "data_quality_flags": data_quality_flags,
        }
        records.append(record)

    records.sort(key=lambda item: (item["priority_rank"], -_safe_float(item.get("route_score"), 0.0)))
    return records, reject_reason_counts


def _render_markdown(
    *,
    now: datetime,
    json_path: Path,
    total_markets: int,
    filtered_markets: int,
    candidates: list[dict[str, Any]],
    reject_reason_counts: dict[str, int],
    scanner_ok: bool,
    filter_ok: bool,
    join_ok: bool,
    wallet_health: dict[str, Any],
    lmsr_health: dict[str, Any],
) -> str:
    candidate_count = sum(1 for item in candidates if item.get("reject_reason") is None)
    surface_state, surface_reason = _diagnose_empty_surface(
        scanner_ok=scanner_ok,
        filter_ok=filter_ok,
        join_ok=join_ok,
        reject_reason_counts=reject_reason_counts,
    )

    lines = [
        "# Polymarket Fast-Lane Scan",
        "",
        f"- generated_at: {now.isoformat()}",
        f"- candidates_json: {json_path}",
        f"- total_markets_scanned: {total_markets}",
        f"- markets_after_priority_horizon_filter: {filtered_markets}",
        f"- routeable_candidates: {candidate_count}",
        f"- wallet_flow_status: {wallet_health.get('status')}",
        f"- lmsr_status: {lmsr_health.get('status')}",
        f"- scanner_ok: {scanner_ok}",
        f"- filter_ok: {filter_ok}",
        f"- join_ok: {join_ok}",
        "",
        "## Reject Reasons",
        "",
    ]
    for reason in ("category_gating", "data_quality_loss", "wallet_sparsity", "toxicity", "expectancy_failure"):
        lines.append(f"- {reason}: {int(reject_reason_counts.get(reason, 0))}")

    lines.extend(["", "## Diagnostic Split", ""])
    if candidate_count == 0:
        lines.append(f"- empty_surface_classification: {surface_state}")
        lines.append(f"- empty_surface_primary_reason: {surface_reason}")
        if surface_state == "broken_pipeline":
            lines.append("- interpretation: scanner/filter/join path is degraded and needs repair before risk decisions.")
        else:
            lines.append("- interpretation: scanner is healthy, but the current surface is genuinely not tradeable under safe constraints.")
    else:
        lines.append("- empty_surface_classification: not_empty")
        lines.append("- empty_surface_primary_reason: n/a")

    top_rows = [item for item in candidates if item.get("reject_reason") is None][:10]
    lines.extend(["", "## Top Routeable Candidates", ""])
    if not top_rows:
        lines.append("- none")
    for row in top_rows:
        lines.append(
            "- "
            f"{row['title'][:90]} | lane={row['priority_lane']} | horizon={row['horizon']} | "
            f"route_score={row['route_score']:.6f} | edge={row['fee_adjusted_expected_edge']:.4f} | "
            f"fill_prob={row['expected_maker_fill_probability']:.4f}"
        )

    return "\n".join(lines) + "\n"


def generate_polymarket_fastlane_surface(*, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    load_dotenv(REPO_ROOT / ".env")
    now = _now_utc()
    profile_bundle = load_runtime_profile()

    markets_under_24h, _recent_trades, _scan_health = asyncio.run(fetch_recent_open_markets(max_markets=120))

    prioritized = []
    for market in markets_under_24h:
        end_dt = _parse_iso8601(str(market.get("endDate") or ""))
        if end_dt is None:
            continue
        resolution_hours = (end_dt - now).total_seconds() / 3600.0
        if resolution_hours <= 0.0 or resolution_hours > 24.0:
            continue
        rank, _label = _priority_label(str(market.get("question") or ""))
        if rank > 3:
            continue
        prioritized.append(market)

    wallet_signals, wallet_health = _load_wallet_signals()
    lmsr_signals, lmsr_health = _load_lmsr_signals(
        prioritized,
        entry_threshold=float(profile_bundle.profile.signal_thresholds.lmsr_entry_threshold),
    )

    vpin_manager = VPINManager(
        bucket_size=float(profile_bundle.profile.microstructure_thresholds.vpin_bucket_size),
        window_size=int(profile_bundle.profile.microstructure_thresholds.vpin_window_size),
        toxic_threshold=float(profile_bundle.profile.microstructure_thresholds.vpin_toxic_threshold),
        safe_threshold=float(profile_bundle.profile.microstructure_thresholds.vpin_safe_threshold),
    )

    trade_tapes: dict[str, list[dict[str, Any]]] = {}
    vpin_state: dict[str, dict[str, Any]] = {}

    if prioritized:
        timeout = httpx.Timeout(20.0, connect=15.0)
        async def _collect() -> None:
            async with httpx.AsyncClient(timeout=timeout) as client:
                tasks = []
                for market in prioritized:
                    market_id = str(market.get("conditionId") or market.get("id") or "")
                    tasks.append(_fetch_condition_trades(client, market_id, limit=300))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for market, tape in zip(prioritized, results):
                    market_id = str(market.get("conditionId") or market.get("id") or "")
                    if isinstance(tape, Exception):
                        trade_tapes[market_id] = []
                        continue
                    ordered = sorted(tape, key=lambda row: _safe_float(row.get("timestamp"), 0.0))
                    trade_tapes[market_id] = ordered
                    for trade in ordered:
                        vpin_manager.on_trade(
                            market_id,
                            price=_safe_float(trade.get("price"), 0.5),
                            size=_safe_float(trade.get("size"), 0.0),
                            side=str(trade.get("side") or "").lower(),
                            timestamp=_safe_float(trade.get("timestamp"), 0.0),
                        )
                    state = vpin_manager._get_or_create_state(market_id)
                    vpin_state[market_id] = {
                        "vpin": state.vpin,
                        "regime": state.regime.value,
                        "is_ready": state.is_ready,
                        "buckets_filled": state.buckets_filled,
                    }

        asyncio.run(_collect())

    records, reject_reason_counts = _build_market_records(
        markets=prioritized,
        wallet_signals=wallet_signals,
        lmsr_signals=lmsr_signals,
        trade_tapes=trade_tapes,
        vpin_state=vpin_state,
    )
    join_ok = len(records) == len(prioritized) if prioritized else False

    routeable = [item for item in records if item.get("reject_reason") is None]

    scanner_ok = len(markets_under_24h) > 0
    filter_ok = len(prioritized) > 0

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"poly_fastlane_candidates_{stamp}.json"
    md_path = output_dir / f"poly_fastlane_scan_{stamp}.md"

    payload = {
        "instance": 2,
        "instance_version": INSTANCE_VERSION,
        "generated_at": now.isoformat(),
        "universe": {
            "total_markets_scanned": len(markets_under_24h),
            "markets_after_priority_horizon_filter": len(prioritized),
            "priority_order": ["btc_15m", "btc_5m", "btc_4h", "eth_intraday"],
            "horizons": ["3h", "24h"],
        },
        "lane_health": {
            "wallet_flow": wallet_health,
            "lmsr": lmsr_health,
            "scanner_ok": scanner_ok,
            "filter_ok": filter_ok,
            "join_ok": join_ok,
        },
        "candidate_count": len(routeable),
        "reject_reason_counts": reject_reason_counts,
        "candidates": records,
    }

    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    md_path.write_text(
        _render_markdown(
            now=now,
            json_path=json_path,
            total_markets=len(markets_under_24h),
            filtered_markets=len(prioritized),
            candidates=records,
            reject_reason_counts=reject_reason_counts,
            scanner_ok=scanner_ok,
            filter_ok=filter_ok,
            join_ok=join_ok,
            wallet_health=wallet_health,
            lmsr_health=lmsr_health,
        )
    )

    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Polymarket fast-lane candidate surface.")
    parser.add_argument("--output-dir", default=str(REPORTS_DIR), help="Directory for output artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = generate_polymarket_fastlane_surface(output_dir=output_dir)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
