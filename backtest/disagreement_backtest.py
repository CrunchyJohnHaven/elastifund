#!/usr/bin/env python3
"""Replay disagreement-aware Kelly sizing on cached ensemble history.

This intentionally uses only cached multi-model ensemble outputs. If the cache
does not contain enough multi-model estimates for the 532-market dataset, the
script reports that coverage gap instead of inventing disagreement values.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.llm_ensemble import kelly_fraction_from_stddev

DATA_DIR = Path(__file__).resolve().parent / "data"
REPORT_DIR = ROOT / "reports"
MARKETS_PATH = DATA_DIR / "historical_markets_532.json"
ENSEMBLE_CACHE_PATH = DATA_DIR / "ensemble_cache.json"
RESULTS_PATH = DATA_DIR / "disagreement_backtest.json"
REPORT_PATH = REPORT_DIR / "stream6_disagreement_backtest.md"

STARTING_CAPITAL = float(os.environ.get("JJ_STREAM6_BACKTEST_CAPITAL", "75.0"))
ENTRY_PRICE = float(os.environ.get("JJ_STREAM6_ENTRY_PRICE", "0.50"))
EDGE_THRESHOLD = float(os.environ.get("JJ_STREAM6_EDGE_THRESHOLD", "0.05"))
MAX_POSITION_USD = float(os.environ.get("JJ_STREAM6_MAX_POSITION_USD", "10.0"))
BASE_KELLY = float(os.environ.get("JJ_STREAM6_BASE_KELLY", "0.25"))
MIN_SAMPLE_SIZE = int(os.environ.get("JJ_STREAM6_MIN_SAMPLE", "50"))
WINNER_FEE = 0.02


def _cache_key(question: str) -> str:
    return hashlib.sha256(f"ensemble:{question}".encode()).hexdigest()[:16]


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _quarter_kelly_size(probability: float, direction: str, bankroll: float, kelly_fraction: float) -> float:
    if bankroll <= 0:
        return 0.0

    payout = 1.0 - WINNER_FEE
    if direction == "buy_yes":
        p_win = probability
        cost = ENTRY_PRICE
    else:
        p_win = 1.0 - probability
        cost = 1.0 - ENTRY_PRICE

    if cost <= 0 or cost >= payout:
        return 0.0

    odds = (payout - cost) / cost
    if odds <= 0:
        return 0.0

    kelly = (p_win * odds - (1.0 - p_win)) / odds
    kelly = max(0.0, kelly)
    size = min(MAX_POSITION_USD, bankroll * max(0.0, kelly_fraction) * kelly)
    return round(size, 2) if size >= 0.50 else 0.0


def _resolve_trade(direction: str, size_usd: float, actual_outcome: str) -> tuple[bool, float]:
    if direction == "buy_yes":
        if actual_outcome == "YES_WON":
            shares = size_usd / ENTRY_PRICE
            return True, shares * (1.0 - WINNER_FEE) - size_usd
        return False, -size_usd

    no_price = 1.0 - ENTRY_PRICE
    if actual_outcome == "NO_WON":
        shares = size_usd / no_price
        return True, shares * (1.0 - WINNER_FEE) - size_usd
    return False, -size_usd


def _build_trade_rows(markets: list[dict], ensemble_cache: dict) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    coverage = {
        "requested_markets": len(markets),
        "ensemble_cache_hits": 0,
        "multi_model_cache_hits": 0,
        "tradeable_multi_model_markets": 0,
        "single_model_cache_hits": 0,
        "missing_cache": 0,
    }

    for market in markets:
        cached = ensemble_cache.get(_cache_key(market["question"]))
        if not cached:
            coverage["missing_cache"] += 1
            continue

        coverage["ensemble_cache_hits"] += 1
        n_models = int(cached.get("n_models", 0) or 0)
        individual = cached.get("individual", []) or []
        if n_models < 2 or len(individual) < 2:
            coverage["single_model_cache_hits"] += 1
            continue

        coverage["multi_model_cache_hits"] += 1
        probability = float(cached.get("probability", 0.5))
        edge = probability - ENTRY_PRICE
        if abs(edge) < EDGE_THRESHOLD:
            continue

        coverage["tradeable_multi_model_markets"] += 1
        rows.append(
            {
                "question": market["question"],
                "actual_outcome": market["actual_outcome"],
                "probability": probability,
                "direction": "buy_yes" if edge > 0 else "buy_no",
                "stddev": float(cached.get("stdev", 0.0) or 0.0),
                "n_models": n_models,
            }
        )

    return rows, coverage


def _simulate(rows: list[dict], *, disagreement_adjusted: bool) -> dict:
    bankroll = STARTING_CAPITAL
    peak = bankroll
    wins = 0
    pnls: list[float] = []
    sizes: list[float] = []

    for row in rows:
        if disagreement_adjusted:
            kelly_fraction = min(BASE_KELLY, kelly_fraction_from_stddev(row["stddev"]))
        else:
            kelly_fraction = BASE_KELLY

        size_usd = _quarter_kelly_size(
            probability=row["probability"],
            direction=row["direction"],
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
        )
        if size_usd <= 0:
            continue

        won, pnl = _resolve_trade(row["direction"], size_usd, row["actual_outcome"])
        bankroll = max(0.0, bankroll + pnl)
        peak = max(peak, bankroll)
        if won:
            wins += 1
        pnls.append(pnl)
        sizes.append(size_usd)

    drawdown = 0.0 if peak <= 0 else max(0.0, (peak - bankroll) / peak)
    returns = [pnl / size for pnl, size in zip(pnls, sizes) if size > 0]
    sharpe = 0.0
    if len(returns) > 1:
        std = statistics.pstdev(returns)
        if std > 0:
            sharpe = statistics.mean(returns) / std

    label = "disagreement_adjusted" if disagreement_adjusted else "flat_quarter_kelly"
    trade_count = len(sizes)
    return {
        "strategy": label,
        "trade_count": trade_count,
        "final_bankroll": round(bankroll, 2),
        "total_pnl": round(sum(pnls), 2),
        "win_rate": round(wins / trade_count * 100, 1) if trade_count else 0.0,
        "avg_size": round(statistics.mean(sizes), 2) if sizes else 0.0,
        "max_drawdown_pct": round(drawdown * 100, 1),
        "sharpe": round(sharpe, 3),
    }


def _write_report(results: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    coverage = results["coverage"]
    comparison = results.get("comparison", {})
    status = results["status"]
    lines = [
        "# Stream 6 Disagreement Backtest",
        "",
        f"- Status: **{status}**",
        f"- Requested dataset: {coverage['requested_markets']} markets (`historical_markets_532.json`)",
        f"- Ensemble cache hits: {coverage['ensemble_cache_hits']}",
        f"- Multi-model cache hits: {coverage['multi_model_cache_hits']}",
        f"- Tradeable multi-model markets: {coverage['tradeable_multi_model_markets']}",
        f"- Single-model-only cache hits: {coverage['single_model_cache_hits']}",
        "",
    ]
    if comparison:
        flat = comparison["flat_quarter_kelly"]
        adjusted = comparison["disagreement_adjusted"]
        lines.extend(
            [
                "| Metric | Flat Quarter-Kelly | Disagreement Adjusted |",
                "|---|---:|---:|",
                f"| Trades | {flat['trade_count']} | {adjusted['trade_count']} |",
                f"| Final bankroll | ${flat['final_bankroll']:.2f} | ${adjusted['final_bankroll']:.2f} |",
                f"| Total P&L | ${flat['total_pnl']:.2f} | ${adjusted['total_pnl']:.2f} |",
                f"| Win rate | {flat['win_rate']:.1f}% | {adjusted['win_rate']:.1f}% |",
                f"| Avg size | ${flat['avg_size']:.2f} | ${adjusted['avg_size']:.2f} |",
                f"| Max drawdown | {flat['max_drawdown_pct']:.1f}% | {adjusted['max_drawdown_pct']:.1f}% |",
                "",
            ]
        )
    if results.get("notes"):
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in results["notes"])
    REPORT_PATH.write_text("\n".join(lines) + "\n")


def main() -> int:
    markets = _load_json(MARKETS_PATH)["markets"]
    ensemble_cache = _load_json(ENSEMBLE_CACHE_PATH)

    rows, coverage = _build_trade_rows(markets, ensemble_cache)
    notes = []
    comparison = {}
    status = "ok"

    if coverage["tradeable_multi_model_markets"] < MIN_SAMPLE_SIZE:
        status = "insufficient_disagreement_history"
        notes.append(
            f"Need at least {MIN_SAMPLE_SIZE} multi-model cached markets for a credible replay; "
            f"found {coverage['tradeable_multi_model_markets']}."
        )
    if coverage["multi_model_cache_hits"] == 0:
        notes.append("Current ensemble cache contains only single-model results, so disagreement sizing cannot be validated offline.")

    if rows:
        comparison = {
            "flat_quarter_kelly": _simulate(rows, disagreement_adjusted=False),
            "disagreement_adjusted": _simulate(rows, disagreement_adjusted=True),
        }
        if comparison["disagreement_adjusted"]["final_bankroll"] > comparison["flat_quarter_kelly"]["final_bankroll"]:
            notes.append("Disagreement-adjusted sizing outperformed on available cached sample.")
        elif comparison["disagreement_adjusted"]["final_bankroll"] < comparison["flat_quarter_kelly"]["final_bankroll"]:
            notes.append("Disagreement-adjusted sizing underperformed on available cached sample.")
        else:
            notes.append("Available cached sample produced no bankroll difference between the two sizing rules.")
    else:
        notes.append("No tradeable multi-model rows were available after applying the edge filter.")

    results = {
        "status": status,
        "starting_capital": STARTING_CAPITAL,
        "entry_price": ENTRY_PRICE,
        "edge_threshold": EDGE_THRESHOLD,
        "base_kelly": BASE_KELLY,
        "coverage": coverage,
        "comparison": comparison,
        "notes": notes,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n")
    _write_report(results)

    print(json.dumps(results, indent=2))
    print(f"\nSaved JSON to {RESULTS_PATH}")
    print(f"Saved report to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
