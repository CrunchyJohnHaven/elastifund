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
    build_laddered_quote_intents,
    contract_schemas,
    evaluate_blitz_launch_ready,
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
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

