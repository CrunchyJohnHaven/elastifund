#!/usr/bin/env python3
"""Operator utility for maker-velocity blitz launch checks and artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.maker_velocity_blitz import (  # noqa: E402
    MarketSnapshot,
    WalletConsensusSignal,
    allocate_hour0_notional,
    allocate_dual_sided_spread_notional,
    build_dual_sided_spread_intents,
    build_laddered_quote_intents,
    contract_schemas,
    evaluate_blitz_launch_ready,
    rank_dual_sided_spread_markets,
    rank_wallet_signals,
    validate_contract_payload,
)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _market_from_payload(payload: dict[str, Any]) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=str(payload.get("market_id") or payload.get("id") or "").strip(),
        question=str(payload.get("question") or payload.get("title") or "").strip(),
        yes_price=float(payload.get("yes_price") or payload.get("yesPrice") or 0.5),
        no_price=float(payload.get("no_price") or payload.get("noPrice") or 0.5),
        resolution_hours=float(payload.get("resolution_hours") or 1.0),
        spread=float(payload.get("spread") or 0.02),
        liquidity_usd=float(payload.get("liquidity_usd") or payload.get("liquidity") or 0.0),
        toxicity=float(payload.get("toxicity") or 0.0),
        venue=str(payload.get("venue") or "polymarket"),
        timestamp=str(payload.get("timestamp") or ""),
    )


def _signal_from_payload(payload: dict[str, Any]) -> WalletConsensusSignal:
    return WalletConsensusSignal(
        market_id=str(payload.get("market_id") or "").strip(),
        direction=str(payload.get("direction") or "buy_yes"),
        edge=float(payload.get("edge") or 0.0),
        fill_prob=float(payload.get("fill_prob") or payload.get("fill_probability") or 0.0),
        velocity_multiplier=float(payload.get("velocity_multiplier") or 1.0),
        wallet_confidence=float(payload.get("wallet_confidence") or payload.get("confidence") or 0.0),
        toxicity_penalty=float(payload.get("toxicity_penalty") or 1.0),
        source=str(payload.get("source") or "wallet_flow"),
        timestamp=str(payload.get("timestamp") or ""),
    )


def _cmd_launch_check(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    payload = evaluate_blitz_launch_ready(
        remote_cycle_status=_load_json(repo_root / "reports" / "remote_cycle_status.json", {}),
        remote_service_status=_load_json(repo_root / "reports" / "remote_service_status.json", {}),
        jj_state=_load_json(repo_root / "jj_state.json", {}),
    )
    out = {
        "launch_go": payload.launch_go,
        "checks": payload.checks,
        "blocked_reasons": list(payload.blocked_reasons),
        "source_of_truth": payload.source_of_truth,
    }
    if args.output:
        _write_json(Path(args.output).expanduser().resolve(), out)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if payload.launch_go else 2


def _cmd_emit_contracts(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    _write_json(output, {"contracts": contract_schemas()})
    print(output)
    return 0


def _cmd_build_hour0_plan(args: argparse.Namespace) -> int:
    signals_payload = _load_json(Path(args.signals_json).expanduser().resolve(), [])
    markets_payload = _load_json(Path(args.markets_json).expanduser().resolve(), [])
    if not isinstance(signals_payload, list) or not isinstance(markets_payload, list):
        raise SystemExit("signals_json and markets_json must be JSON arrays")

    signals = [_signal_from_payload(row) for row in signals_payload if isinstance(row, dict)]
    ranked = rank_wallet_signals(signals)
    markets = {
        market.market_id: market
        for market in (_market_from_payload(row) for row in markets_payload if isinstance(row, dict))
        if market.market_id
    }
    allocations = allocate_hour0_notional(
        bankroll_usd=float(args.bankroll_usd),
        ranked_signals=ranked,
    )
    intents = build_laddered_quote_intents(
        allocations_usd=allocations,
        ranked_signals=ranked,
        market_snapshots=markets,
        levels=3,
    )
    quote_payloads = [asdict(intent) for intent in intents]
    invalid_quotes = []
    for idx, quote in enumerate(quote_payloads):
        valid, reasons = validate_contract_payload("QuoteIntent", quote)
        if not valid:
            invalid_quotes.append({"index": idx, "reasons": list(reasons)})

    summary = {
        "bankroll_usd": float(args.bankroll_usd),
        "reserve_pct": 0.05,
        "deploy_target_usd": round(float(args.bankroll_usd) * 0.95, 6),
        "ranked_signal_count": len(ranked),
        "allocations_usd": allocations,
        "quote_intents": quote_payloads,
        "all_quotes_valid": len(invalid_quotes) == 0,
        "invalid_quotes": invalid_quotes,
    }
    output = Path(args.output).expanduser().resolve()
    _write_json(output, summary)
    print(output)
    return 0


def _cmd_build_dual_sided_shadow_plan(args: argparse.Namespace) -> int:
    markets_payload = _load_json(Path(args.markets_json).expanduser().resolve(), [])
    if not isinstance(markets_payload, list):
        raise SystemExit("markets_json must be a JSON array")

    markets = [_market_from_payload(row) for row in markets_payload if isinstance(row, dict)]
    ranked = rank_dual_sided_spread_markets(
        markets,
        combined_cost_cap=float(args.combined_cost_cap),
        max_toxicity=float(args.max_toxicity),
        min_liquidity_usd=float(args.min_liquidity_usd),
        max_spread=float(args.max_spread),
    )
    allocations = allocate_dual_sided_spread_notional(
        bankroll_usd=float(args.bankroll_usd),
        ranked_candidates=ranked,
        reserve_pct=float(args.reserve_pct),
        per_market_floor_usd=float(args.per_market_floor_usd),
        per_market_cap_usd=float(args.per_market_cap_usd),
        max_markets=int(args.max_markets),
    )
    intents = build_dual_sided_spread_intents(
        allocations_usd=allocations,
        ranked_candidates=ranked,
        timeout_seconds=int(args.timeout_seconds),
        wallet_confirmation_mode=str(args.wallet_confirmation_mode),
    )
    intent_payloads = [asdict(intent) for intent in intents]
    invalid_intents = []
    for idx, payload in enumerate(intent_payloads):
        valid, reasons = validate_contract_payload("DualSidedSpreadIntent", payload)
        if not valid:
            invalid_intents.append({"index": idx, "reasons": list(reasons)})

    summary = {
        "bankroll_usd": float(args.bankroll_usd),
        "strategy_family": "dual_sided_maker_spread_capture",
        "maker_only": True,
        "wallet_confirmation_mode": str(args.wallet_confirmation_mode),
        "combined_cost_cap": float(args.combined_cost_cap),
        "timeout_seconds": int(args.timeout_seconds),
        "ranked_candidate_count": len(ranked),
        "ranked_candidates": ranked,
        "allocations_usd": allocations,
        "spread_intents": intent_payloads,
        "all_spread_intents_valid": len(invalid_intents) == 0,
        "invalid_spread_intents": invalid_intents,
    }
    output = Path(args.output).expanduser().resolve()
    _write_json(output, summary)
    print(output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maker velocity blitz operator tooling.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    launch = subparsers.add_parser("launch-check", help="Evaluate machine launch gates from runtime artifacts.")
    launch.add_argument("--repo-root", default=str(ROOT), help="Repository root.")
    launch.add_argument(
        "--output",
        default=str(ROOT / "reports" / "maker_velocity_launch_gate.json"),
        help="Optional output path for launch check JSON.",
    )
    launch.set_defaults(func=_cmd_launch_check)

    contracts = subparsers.add_parser("emit-contracts", help="Write contract schema artifact.")
    contracts.add_argument(
        "--output",
        default=str(ROOT / "reports" / "maker_velocity_contracts.json"),
        help="Output JSON path.",
    )
    contracts.set_defaults(func=_cmd_emit_contracts)

    hour0 = subparsers.add_parser("build-hour0-plan", help="Create allocation and quote intents from signal snapshots.")
    hour0.add_argument("--signals-json", required=True, help="JSON array of WalletConsensusSignal-like rows.")
    hour0.add_argument("--markets-json", required=True, help="JSON array of MarketSnapshot-like rows.")
    hour0.add_argument("--bankroll-usd", type=float, required=True, help="Current bankroll for allocation.")
    hour0.add_argument(
        "--output",
        default=str(ROOT / "reports" / "maker_velocity_hour0_plan.json"),
        help="Output JSON path for hour-0 plan.",
    )
    hour0.set_defaults(func=_cmd_build_hour0_plan)

    spread = subparsers.add_parser(
        "build-dual-sided-shadow-plan",
        help="Create a maker-only dual-sided spread-capture shadow plan from market snapshots.",
    )
    spread.add_argument("--markets-json", required=True, help="JSON array of MarketSnapshot-like rows.")
    spread.add_argument("--bankroll-usd", type=float, required=True, help="Current bankroll for allocation.")
    spread.add_argument("--combined-cost-cap", type=float, default=0.97, help="Max YES+NO combined cost.")
    spread.add_argument("--max-toxicity", type=float, default=0.35, help="Maximum toxicity allowed.")
    spread.add_argument("--min-liquidity-usd", type=float, default=250.0, help="Minimum market liquidity.")
    spread.add_argument("--max-spread", type=float, default=0.08, help="Maximum spread allowed.")
    spread.add_argument("--reserve-pct", type=float, default=0.20, help="Cash reserve percentage.")
    spread.add_argument("--per-market-floor-usd", type=float, default=5.0, help="Minimum notional per market.")
    spread.add_argument("--per-market-cap-usd", type=float, default=10.0, help="Maximum notional per market.")
    spread.add_argument("--max-markets", type=int, default=8, help="Maximum concurrent markets.")
    spread.add_argument("--timeout-seconds", type=int, default=120, help="Hedge timeout / scratch window.")
    spread.add_argument(
        "--wallet-confirmation-mode",
        default="overlay_only",
        help="Wallet-flow usage mode. Defaults to overlay_only.",
    )
    spread.add_argument(
        "--output",
        default=str(ROOT / "reports" / "maker_velocity_dual_sided_shadow_plan.json"),
        help="Output JSON path for dual-sided maker shadow plan.",
    )
    spread.set_defaults(func=_cmd_build_dual_sided_shadow_plan)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
