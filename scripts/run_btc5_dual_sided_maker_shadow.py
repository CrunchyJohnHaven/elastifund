#!/usr/bin/env python3
"""Build a BTC 5-minute dual-sided maker shadow plan from the live market registry."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.maker_velocity_blitz import (  # noqa: E402
    MarketSnapshot,
    allocate_dual_sided_spread_notional,
    build_dual_sided_spread_intents,
    rank_dual_sided_spread_markets,
    validate_contract_payload,
)

DEFAULT_REGISTRY_PATH = ROOT / "reports" / "market_registry" / "latest.json"
DEFAULT_RUNTIME_TRUTH_PATH = ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_FINANCE_PATH = ROOT / "reports" / "finance" / "latest.json"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "autoresearch" / "maker_shadow"
DEFAULT_PARALLEL_OUTPUT = ROOT / "reports" / "parallel" / "instance04_dual_sided_maker_shadow_plan.json"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DEFAULT_CAP_SENSITIVITY = (0.97, 0.98, 0.99, 1.0)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _write_markdown(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _quote_levels(book: dict[str, Any] | None, side: str) -> list[dict[str, float]]:
    levels = book.get(side) if isinstance(book, dict) else []
    if not isinstance(levels, list):
        return []
    normalized: list[dict[str, float]] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        price = _safe_float(level.get("price"), None)
        size = _safe_float(level.get("size"), None)
        if price is None or size is None or price <= 0.0 or size <= 0.0:
            continue
        normalized.append({"price": float(price), "size": float(size)})
    return normalized


def _extract_best_quote(book: dict[str, Any] | None) -> dict[str, float | None]:
    bids = _quote_levels(book, "bids")
    asks = _quote_levels(book, "asks")
    best_bid_level = max(bids, key=lambda level: level["price"], default=None)
    best_ask_level = min(asks, key=lambda level: level["price"], default=None)
    return {
        "best_bid": best_bid_level["price"] if best_bid_level else None,
        "best_bid_size": best_bid_level["size"] if best_bid_level else None,
        "best_ask": best_ask_level["price"] if best_ask_level else None,
        "best_ask_size": best_ask_level["size"] if best_ask_level else None,
    }


def _sum_top_levels_usd(book: dict[str, Any] | None, *, levels: int = 5) -> float:
    total = 0.0
    for side in ("bids", "asks"):
        for level in _quote_levels(book, side)[:levels]:
            total += float(level["price"]) * float(level["size"])
    return round(total, 6)


def _fetch_book(token_id: str, *, timeout_seconds: float = 10.0) -> dict[str, Any] | None:
    response = requests.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return payload if isinstance(payload, dict) else None


def _build_market_snapshot(
    row: dict[str, Any],
    *,
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
) -> dict[str, Any]:
    yes_quote = _extract_best_quote(yes_book)
    no_quote = _extract_best_quote(no_book)
    yes_bid = _safe_float(yes_quote.get("best_bid"), None)
    no_bid = _safe_float(no_quote.get("best_bid"), None)
    yes_ask = _safe_float(yes_quote.get("best_ask"), None)
    no_ask = _safe_float(no_quote.get("best_ask"), None)
    liquidity_estimate = round(
        _sum_top_levels_usd(yes_book) + _sum_top_levels_usd(no_book),
        6,
    )
    side_spreads = [
        float(ask) - float(bid)
        for bid, ask in ((yes_bid, yes_ask), (no_bid, no_ask))
        if bid is not None and ask is not None
    ]
    max_side_spread = max(side_spreads) if side_spreads else None
    combined_bid_cost = (float(yes_bid) + float(no_bid)) if yes_bid is not None and no_bid is not None else None
    combined_ask_cost = (float(yes_ask) + float(no_ask)) if yes_ask is not None and no_ask is not None else None
    toxicity = 1.0
    if max_side_spread is not None:
        toxicity = min(1.0, max(0.0, max_side_spread / 0.25))
    snapshot = MarketSnapshot(
        market_id=str(row.get("market_id") or "").strip(),
        question=str(row.get("question") or "").strip(),
        yes_price=float(yes_bid or 0.0),
        no_price=float(no_bid or 0.0),
        resolution_hours=max(0.1, float(row.get("timeframe_minutes") or 5.0) / 60.0),
        spread=float(max_side_spread or 0.0),
        liquidity_usd=float(max(liquidity_estimate, 0.0)),
        toxicity=float(toxicity),
        venue="polymarket",
        timestamp=str(row.get("quote_fetched_at") or ""),
    )
    return {
        "market_snapshot": asdict(snapshot),
        "market_id": snapshot.market_id,
        "question": snapshot.question,
        "yes_best_bid": yes_bid,
        "yes_best_ask": yes_ask,
        "yes_best_bid_size": yes_quote.get("best_bid_size"),
        "yes_best_ask_size": yes_quote.get("best_ask_size"),
        "no_best_bid": no_bid,
        "no_best_ask": no_ask,
        "no_best_bid_size": no_quote.get("best_bid_size"),
        "no_best_ask_size": no_quote.get("best_ask_size"),
        "combined_bid_cost": round(float(combined_bid_cost), 6) if combined_bid_cost is not None else None,
        "combined_ask_cost": round(float(combined_ask_cost), 6) if combined_ask_cost is not None else None,
        "max_side_spread": round(float(max_side_spread), 6) if max_side_spread is not None else None,
        "liquidity_estimate_usd": liquidity_estimate,
        "toxicity_estimate": round(float(toxicity), 6),
    }


def _build_cap_sensitivity(
    *,
    market_snapshots: list[MarketSnapshot],
    caps: tuple[float, ...],
    max_toxicity: float,
    min_liquidity_usd: float,
    max_spread: float,
) -> list[dict[str, Any]]:
    sensitivity: list[dict[str, Any]] = []
    for cap in caps:
        ranked = rank_dual_sided_spread_markets(
            market_snapshots,
            combined_cost_cap=cap,
            max_toxicity=max_toxicity,
            min_liquidity_usd=min_liquidity_usd,
            max_spread=max_spread,
        )
        top = ranked[0] if ranked else {}
        sensitivity.append(
            {
                "combined_cost_cap": round(float(cap), 6),
                "ranked_candidate_count": len(ranked),
                "top_combined_cost": round(float(_safe_float(top.get("combined_cost"), 0.0) or 0.0), 6)
                if ranked
                else None,
                "top_score": round(float(_safe_float(top.get("score"), 0.0) or 0.0), 6) if ranked else 0.0,
                "one_next_cycle_action": "run_dual_sided_maker_shadow_loop" if ranked else "wait_for_tighter_books_or_more_liquidity",
            }
        )
    return sensitivity


def build_shadow_payload(
    *,
    registry_payload: dict[str, Any],
    runtime_truth: dict[str, Any],
    finance_latest: dict[str, Any],
    bankroll_usd: float,
    combined_cost_cap: float,
    max_toxicity: float,
    min_liquidity_usd: float,
    max_spread: float,
    reserve_pct: float,
    per_market_floor_usd: float,
    per_market_cap_usd: float,
    max_markets: int,
    timeout_seconds: int,
    book_fetcher: Any | None = None,
) -> dict[str, Any]:
    if book_fetcher is None:
        book_fetcher = _fetch_book
    rows = registry_payload.get("registry") if isinstance(registry_payload, dict) else []
    eligible_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("eligible") is True
        and str(row.get("asset") or "").lower() == "btc"
        and str(row.get("timeframe") or "").lower() == "5m"
        and row.get("yes_token_id")
        and row.get("no_token_id")
    ]
    snapshots: list[dict[str, Any]] = []
    block_reasons: list[str] = []

    for row in eligible_rows:
        try:
            yes_book = book_fetcher(str(row.get("yes_token_id")))
            no_book = book_fetcher(str(row.get("no_token_id")))
        except Exception as exc:
            snapshots.append(
                {
                    "market_id": row.get("market_id"),
                    "question": row.get("question"),
                    "error": f"book_fetch_failed:{exc}",
                }
            )
            continue
        snapshots.append(
            _build_market_snapshot(
                row,
                yes_book=yes_book,
                no_book=no_book,
            )
        )

    market_snapshots = [
        MarketSnapshot(**row["market_snapshot"])
        for row in snapshots
        if isinstance(row.get("market_snapshot"), dict)
    ]
    ranked = rank_dual_sided_spread_markets(
        market_snapshots,
        combined_cost_cap=combined_cost_cap,
        max_toxicity=max_toxicity,
        min_liquidity_usd=min_liquidity_usd,
        max_spread=max_spread,
    )
    allocations = allocate_dual_sided_spread_notional(
        bankroll_usd=bankroll_usd,
        ranked_candidates=ranked,
        reserve_pct=reserve_pct,
        per_market_floor_usd=per_market_floor_usd,
        per_market_cap_usd=per_market_cap_usd,
        max_markets=max_markets,
    )
    intents = build_dual_sided_spread_intents(
        allocations_usd=allocations,
        ranked_candidates=ranked,
        timeout_seconds=timeout_seconds,
        wallet_confirmation_mode="overlay_only",
    )
    intent_payloads = [asdict(intent) for intent in intents]
    invalid_intents = []
    for idx, payload in enumerate(intent_payloads):
        valid, reasons = validate_contract_payload("DualSidedSpreadIntent", payload)
        if not valid:
            invalid_intents.append({"index": idx, "reasons": list(reasons)})

    combined_bid_costs = [row.get("combined_bid_cost") for row in snapshots if row.get("combined_bid_cost") is not None]
    spreads = [row.get("max_side_spread") for row in snapshots if row.get("max_side_spread") is not None]
    cap_sensitivity = _build_cap_sensitivity(
        market_snapshots=market_snapshots,
        caps=DEFAULT_CAP_SENSITIVITY,
        max_toxicity=max_toxicity,
        min_liquidity_usd=min_liquidity_usd,
        max_spread=max_spread,
    )
    if not snapshots:
        block_reasons.append("no_btc_5m_registry_rows")
    if snapshots and not ranked:
        block_reasons.append("no_shadow_candidates_with_combined_cost_edge")
    if spreads and min(spreads) > max_spread:
        block_reasons.append("books_too_wide_for_live_capture")
    if combined_bid_costs and min(combined_bid_costs) >= combined_cost_cap:
        block_reasons.append("combined_bid_cost_above_cap")

    top_candidate = ranked[0] if ranked else {}
    top_locked_edge = _safe_float(top_candidate.get("locked_edge"), 0.0) or 0.0
    top_score = _safe_float(top_candidate.get("score"), 0.0) or 0.0
    finance_gate_pass = bool(finance_latest.get("finance_gate_pass"))
    payload = {
        "generated_at": _utc_now().isoformat(),
        "strategy_family": "dual_sided_maker_spread_capture",
        "mode": "shadow_only",
        "source_registry_path": "reports/market_registry/latest.json",
        "bankroll_usd": round(float(bankroll_usd), 6),
        "combined_cost_cap": round(float(combined_cost_cap), 6),
        "max_toxicity": round(float(max_toxicity), 6),
        "min_liquidity_usd": round(float(min_liquidity_usd), 6),
        "max_spread": round(float(max_spread), 6),
        "reserve_pct": round(float(reserve_pct), 6),
        "timeout_seconds": int(timeout_seconds),
        "finance_gate_pass": finance_gate_pass,
        "runtime_launch_posture": runtime_truth.get("launch_posture"),
        "runtime_execution_mode": runtime_truth.get("execution_mode"),
        "eligible_market_count": len(eligible_rows),
        "snapshot_count": len(snapshots),
        "markets": snapshots,
        "ranked_candidate_count": len(ranked),
        "ranked_candidates": ranked,
        "combined_cost_cap_sensitivity": cap_sensitivity,
        "allocations_usd": allocations,
        "spread_intents": intent_payloads,
        "all_spread_intents_valid": len(invalid_intents) == 0,
        "invalid_spread_intents": invalid_intents,
        "candidate_delta_arr_bps": round(top_locked_edge * 10_000.0, 4),
        "expected_improvement_velocity_delta": round(top_score, 6),
        "arr_confidence_score": 0.35 if ranked else 0.1,
        "block_reasons": block_reasons,
        "one_next_cycle_action": (
            "run_dual_sided_maker_shadow_loop"
            if ranked and finance_gate_pass
            else "wait_for_tighter_books_or_more_liquidity"
        ),
    }
    return payload


def render_shadow_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# BTC5 Dual-Sided Maker Shadow",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- strategy_family: {payload.get('strategy_family')}",
        f"- bankroll_usd: {payload.get('bankroll_usd')}",
        f"- eligible_market_count: {payload.get('eligible_market_count')}",
        f"- ranked_candidate_count: {payload.get('ranked_candidate_count')}",
        f"- finance_gate_pass: {payload.get('finance_gate_pass')}",
        f"- candidate_delta_arr_bps: {payload.get('candidate_delta_arr_bps')}",
        f"- expected_improvement_velocity_delta: {payload.get('expected_improvement_velocity_delta')}",
        f"- arr_confidence_score: {payload.get('arr_confidence_score')}",
    ]
    block_reasons = list(payload.get("block_reasons") or [])
    lines.append(f"- block_reasons: {', '.join(block_reasons) if block_reasons else 'none'}")
    lines.append(f"- one_next_cycle_action: {payload.get('one_next_cycle_action')}")
    ranked = payload.get("ranked_candidates") or []
    if ranked:
        lines.extend(["", "## Top Candidates"])
        for row in ranked[:5]:
            lines.append(
                "- "
                f"{row.get('market_id')} | locked_edge={row.get('locked_edge')} | "
                f"combined_cost={row.get('combined_cost')} | score={row.get('score')}"
            )
    cap_sensitivity = payload.get("combined_cost_cap_sensitivity") or []
    if cap_sensitivity:
        lines.extend(["", "## Cap Sensitivity"])
        for row in cap_sensitivity:
            lines.append(
                "- "
                f"cap={row.get('combined_cost_cap')} | "
                f"ranked_candidate_count={row.get('ranked_candidate_count')} | "
                f"top_combined_cost={row.get('top_combined_cost')} | "
                f"top_score={row.get('top_score')} | "
                f"action={row.get('one_next_cycle_action')}"
            )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build BTC 5-minute dual-sided maker shadow plan.")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--runtime-truth-path", default=str(DEFAULT_RUNTIME_TRUTH_PATH))
    parser.add_argument("--finance-path", default=str(DEFAULT_FINANCE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--parallel-output", default=str(DEFAULT_PARALLEL_OUTPUT))
    parser.add_argument("--bankroll-usd", type=float, default=247.0)
    parser.add_argument("--combined-cost-cap", type=float, default=0.97)
    parser.add_argument("--max-toxicity", type=float, default=0.35)
    parser.add_argument("--min-liquidity-usd", type=float, default=200.0)
    parser.add_argument("--max-spread", type=float, default=0.25)
    parser.add_argument("--reserve-pct", type=float, default=0.20)
    parser.add_argument("--per-market-floor-usd", type=float, default=5.0)
    parser.add_argument("--per-market-cap-usd", type=float, default=10.0)
    parser.add_argument("--max-markets", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry_payload = _load_json(Path(args.registry_path), {})
    runtime_truth = _load_json(Path(args.runtime_truth_path), {})
    finance_latest = _load_json(Path(args.finance_path), {})
    payload = build_shadow_payload(
        registry_payload=registry_payload,
        runtime_truth=runtime_truth,
        finance_latest=finance_latest,
        bankroll_usd=float(args.bankroll_usd),
        combined_cost_cap=float(args.combined_cost_cap),
        max_toxicity=float(args.max_toxicity),
        min_liquidity_usd=float(args.min_liquidity_usd),
        max_spread=float(args.max_spread),
        reserve_pct=float(args.reserve_pct),
        per_market_floor_usd=float(args.per_market_floor_usd),
        per_market_cap_usd=float(args.per_market_cap_usd),
        max_markets=int(args.max_markets),
        timeout_seconds=int(args.timeout_seconds),
    )
    output_dir = Path(args.output_dir).expanduser().resolve()
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"
    _write_json(latest_json, payload)
    _write_markdown(latest_md, render_shadow_markdown(payload))
    _write_json(Path(args.parallel_output).expanduser().resolve(), payload)
    print(latest_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
