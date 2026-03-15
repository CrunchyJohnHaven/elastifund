#!/usr/bin/env python3
"""Execute a selected neg-risk basket arb opportunity (paper-first)."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.negrisk_arb_scanner import NegRiskOpportunity, scan_to_report
from bot.polymarket_clob import build_authenticated_clob_client

logger = logging.getLogger("execute_negrisk_arb")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        clean_key = key.strip()
        clean_value = value.strip().strip('"').strip("'")
        os.environ.setdefault(clean_key, clean_value)


def _maker_price(*, bid: float | None, ask: float | None, tick_size: float = 0.01) -> float:
    tick = max(0.001, float(tick_size))
    if bid is None and ask is None:
        raise ValueError("both bid and ask are missing")
    if bid is None:
        return round(max(tick, min(0.99, float(ask) - tick)), 4)
    if ask is None:
        return round(max(tick, min(0.99, float(bid))), 4)
    bid_f = float(bid)
    ask_f = float(ask)
    if ask_f <= bid_f + tick:
        return round(max(tick, min(0.99, bid_f)), 4)
    return round(max(tick, min(0.99, min(ask_f - tick, bid_f + tick))), 4)


@dataclass(frozen=True)
class PlannedLegOrder:
    event_id: str
    strategy: str
    outcome: str
    market_id: str
    condition_id: str
    token_id: str
    side: str
    limit_price: float
    shares: float
    notional_usd: float


def _candidate_opportunities(
    report_payload: dict[str, Any],
    *,
    event_id: str | None,
) -> list[NegRiskOpportunity]:
    opportunities_raw = report_payload.get("opportunities")
    if not isinstance(opportunities_raw, list) or not opportunities_raw:
        raise RuntimeError("no opportunities available in scan report")
    candidates = opportunities_raw
    if event_id:
        candidates = [
            row
            for row in opportunities_raw
            if str(row.get("event_id")) == event_id or str(row.get("event_slug")) == event_id
        ]
        if not candidates:
            raise RuntimeError(f"event_id '{event_id}' not found in current opportunities")
    parsed: list[NegRiskOpportunity] = []
    for selected in candidates:
        parsed.append(
            NegRiskOpportunity(
                event_id=str(selected.get("event_id") or ""),
                event_slug=str(selected.get("event_slug") or ""),
                event_title=str(selected.get("event_title") or ""),
                strategy=str(selected.get("strategy") or ""),
                outcomes_count=int(selected.get("outcomes_count") or 0),
                volume24hr_usd=float(selected.get("volume24hr_usd") or 0.0),
                sum_yes_ask=float(selected.get("sum_yes_ask") or 0.0),
                sum_no_ask=float(selected.get("sum_no_ask") or 0.0),
                deviation=float(selected.get("deviation") or 0.0),
                required_capital_usd=float(selected.get("required_capital_usd") or 0.0),
                payout_usd=float(selected.get("payout_usd") or 0.0),
                expected_profit_usd=float(selected.get("expected_profit_usd") or 0.0),
                profit_per_capital=float(selected.get("profit_per_capital") or 0.0),
                profit_per_capital_day=(
                    float(selected["profit_per_capital_day"])
                    if selected.get("profit_per_capital_day") is not None
                    else None
                ),
                resolution_hours=(
                    float(selected["resolution_hours"])
                    if selected.get("resolution_hours") is not None
                    else None
                ),
                resolution_time_utc=(
                    str(selected.get("resolution_time_utc"))
                    if selected.get("resolution_time_utc") is not None
                    else None
                ),
                legs=tuple(),
            )
        )
    return parsed


def _build_plan(
    report_payload: dict[str, Any],
    selected: NegRiskOpportunity,
    *,
    max_position_usd: float,
    min_order_shares: float,
) -> list[PlannedLegOrder]:
    opportunities_raw = report_payload.get("opportunities")
    if not isinstance(opportunities_raw, list):
        raise RuntimeError("invalid opportunities payload")
    raw = next((row for row in opportunities_raw if str(row.get("event_id")) == selected.event_id), None)
    if not isinstance(raw, dict):
        raise RuntimeError("selected event details not found in report")
    legs_raw = raw.get("legs")
    if not isinstance(legs_raw, list) or not legs_raw:
        raise RuntimeError("selected event has no leg data")

    per_leg_budget = max_position_usd / len(legs_raw)
    plan: list[PlannedLegOrder] = []
    strategy = selected.strategy
    if strategy not in {"buy_all_yes", "buy_all_no"}:
        raise RuntimeError(f"unsupported strategy: {strategy}")

    for leg in legs_raw:
        if not isinstance(leg, dict):
            continue
        outcome = str(leg.get("outcome") or leg.get("market_id") or "").strip()
        market_id = str(leg.get("market_id") or "").strip()
        condition_id = str(leg.get("condition_id") or market_id).strip()
        if strategy == "buy_all_no":
            token_id = str(leg.get("no_token_id") or "").strip()
            bid = _safe_float(leg.get("no_bid"), default=-1.0)
            ask = _safe_float(leg.get("no_ask"), default=-1.0)
        else:
            token_id = str(leg.get("yes_token_id") or "").strip()
            bid = _safe_float(leg.get("yes_bid"), default=-1.0)
            ask = _safe_float(leg.get("yes_ask"), default=-1.0)
        bid_value = bid if 0.0 <= bid <= 1.0 else None
        ask_value = ask if 0.0 <= ask <= 1.0 else None
        if not token_id:
            raise RuntimeError(f"missing token id for leg '{outcome}'")
        price = _maker_price(bid=bid_value, ask=ask_value)
        shares = round(per_leg_budget / price, 2) if price > 0 else 0.0
        if shares + 1e-9 < min_order_shares:
            raise RuntimeError(
                f"insufficient budget for leg '{outcome}': "
                f"{per_leg_budget:.2f} USD allows {shares:.2f} shares < minimum {min_order_shares:.2f}"
            )
        notional = round(shares * price, 6)
        plan.append(
            PlannedLegOrder(
                event_id=selected.event_id,
                strategy=strategy,
                outcome=outcome,
                market_id=market_id,
                condition_id=condition_id,
                token_id=token_id,
                side="BUY",
                limit_price=price,
                shares=shares,
                notional_usd=notional,
            )
        )
    return plan


def _live_execute(
    *,
    orders: Sequence[PlannedLegOrder],
    signature_type: int,
    fill_timeout_seconds: float,
    poll_interval_seconds: float,
    report_path: Path,
) -> dict[str, Any]:
    private_key = (
        os.environ.get("POLY_PRIVATE_KEY")
        or os.environ.get("POLYMARKET_PK")
        or os.environ.get("PRIVATE_KEY")
        or ""
    ).strip()
    safe_address = (
        os.environ.get("POLY_SAFE_ADDRESS")
        or os.environ.get("POLYMARKET_FUNDER")
        or os.environ.get("POLY_PROXY_WALLET")
        or ""
    ).strip()
    if not private_key or not safe_address:
        raise RuntimeError("missing POLY private key or safe address in environment")

    # py_clob_client imports are intentionally local so paper mode works without it.
    from py_clob_client.clob_types import OrderArgs, OrderType

    clob_client, selected_sig_type, sig_probe = build_authenticated_clob_client(
        private_key=private_key,
        safe_address=safe_address,
        configured_signature_type=signature_type,
        logger=logger,
        log_prefix="negrisk_arb",
    )

    placements: list[dict[str, Any]] = []
    for order in orders:
        order_args = OrderArgs(
            token_id=order.token_id,
            price=order.limit_price,
            size=order.shares,
            side=order.side,
        )
        signed = clob_client.create_order(order_args)
        response = clob_client.post_order(
            signed,
            OrderType.GTC,
            post_only=True,
            neg_risk=True,
        )
        order_id = ""
        if isinstance(response, dict):
            order_id = str(response.get("orderID") or response.get("id") or "").strip()
        placements.append(
            {
                "order": asdict(order),
                "order_id": order_id,
                "response": response if isinstance(response, dict) else {"raw": str(response)},
            }
        )

    start_ts = time.time()
    deadline = start_ts + max(1.0, fill_timeout_seconds)
    any_partial_fill = False
    fill_snapshot: dict[str, dict[str, Any]] = {}

    while time.time() < deadline:
        all_filled = True
        for placement in placements:
            order_id = placement.get("order_id") or ""
            if not order_id:
                all_filled = False
                continue
            try:
                payload = clob_client.get_order(order_id)
            except Exception as exc:  # pragma: no cover - network/venue path
                fill_snapshot[order_id] = {"error": str(exc)}
                all_filled = False
                continue

            original = _safe_float(
                payload.get("original_size", payload.get("size", 0.0)),
                default=0.0,
            )
            matched = _safe_float(payload.get("size_matched"), default=0.0)
            remaining = max(0.0, original - matched)
            if matched > 0:
                any_partial_fill = True
            if remaining > 1e-6:
                all_filled = False
            fill_snapshot[order_id] = {
                "status": str(payload.get("status", "")).lower(),
                "original_size": original,
                "size_matched": matched,
                "remaining": remaining,
            }

        if all_filled:
            break
        time.sleep(max(0.5, poll_interval_seconds))

    cancellations: list[dict[str, Any]] = []
    unfilled_order_ids: list[str] = []
    for placement in placements:
        order_id = str(placement.get("order_id") or "").strip()
        if not order_id:
            continue
        snap = fill_snapshot.get(order_id, {})
        if _safe_float(snap.get("remaining"), default=0.0) > 1e-6:
            unfilled_order_ids.append(order_id)

    if any_partial_fill and unfilled_order_ids:
        logger.warning(
            "partial basket fill detected: cancelling %s unfilled legs",
            len(unfilled_order_ids),
        )
        for order_id in unfilled_order_ids:
            try:
                cancel_resp = clob_client.cancel(order_id)
                cancellations.append({"order_id": order_id, "response": cancel_resp, "success": True})
            except Exception as exc:  # pragma: no cover - network/venue path
                cancellations.append({"order_id": order_id, "error": str(exc), "success": False})

    execution_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "signature_type_selected": selected_sig_type,
        "signature_probe": sig_probe,
        "placements": placements,
        "fills": fill_snapshot,
        "any_partial_fill": any_partial_fill,
        "cancellations": cancellations,
        "fill_timeout_seconds": fill_timeout_seconds,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(execution_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return execution_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute neg-risk basket arbitrage")
    parser.add_argument("--event-id", default=None, help="Target event id (or slug). Defaults to top opportunity.")
    parser.add_argument("--scan-report-path", default="reports/negrisk_opportunities.json")
    parser.add_argument("--execution-report-path", default=None)
    parser.add_argument("--max-position-usd", type=float, default=None)
    parser.add_argument("--min-order-shares", type=float, default=5.0)
    parser.add_argument("--signature-type", type=int, default=1)
    parser.add_argument("--fill-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--live", action="store_true", help="Submit live orders. Default is paper mode.")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _load_env_file(".env")

    max_position_usd = args.max_position_usd
    if max_position_usd is None:
        max_position_usd = _safe_float(os.environ.get("JJ_MAX_POSITION_USD"), default=10.0)
    if max_position_usd <= 0:
        raise RuntimeError("max-position-usd must be positive")

    scan_report_path = Path(args.scan_report_path)
    report_payload = scan_to_report(
        output_path=scan_report_path,
        min_overround_sum=1.02,
        max_underround_sum=0.98,
        min_deviation=0.03,
        min_volume24hr_usd=500.0,
        min_outcomes=2,
    )
    min_order_shares = max(0.01, float(args.min_order_shares))
    selected: NegRiskOpportunity | None = None
    plan: list[PlannedLegOrder] | None = None
    candidate_errors: list[str] = []
    for candidate in _candidate_opportunities(report_payload, event_id=args.event_id):
        try:
            proposed = _build_plan(
                report_payload,
                candidate,
                max_position_usd=max_position_usd,
                min_order_shares=min_order_shares,
            )
        except RuntimeError as exc:
            candidate_errors.append(f"{candidate.event_id}: {exc}")
            continue
        selected = candidate
        plan = proposed
        break
    if selected is None or plan is None:
        raise RuntimeError(
            "no feasible opportunity for current budget/min-order settings: "
            + "; ".join(candidate_errors[:5])
        )
    plan_notional = round(sum(row.notional_usd for row in plan), 6)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    execution_report_path = (
        Path(args.execution_report_path)
        if args.execution_report_path
        else Path("reports") / f"negrisk_execution_{timestamp}.json"
    )

    paper_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "paper",
        "selected_event": {
            "event_id": selected.event_id,
            "event_slug": selected.event_slug,
            "event_title": selected.event_title,
            "strategy": selected.strategy,
            "expected_profit_usd_per_basket": selected.expected_profit_usd,
            "required_capital_usd_per_basket": selected.required_capital_usd,
        },
        "position_budget_usd": max_position_usd,
        "planned_notional_usd": plan_notional,
        "planned_orders": [asdict(row) for row in plan],
    }

    if not args.live:
        execution_report_path.parent.mkdir(parents=True, exist_ok=True)
        execution_report_path.write_text(
            json.dumps(paper_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "paper mode only: event=%s planned_legs=%s report=%s",
            selected.event_id,
            len(plan),
            execution_report_path,
        )
        return 0

    live_report = _live_execute(
        orders=plan,
        signature_type=int(args.signature_type),
        fill_timeout_seconds=float(args.fill_timeout_seconds),
        poll_interval_seconds=float(args.poll_interval_seconds),
        report_path=execution_report_path,
    )
    logger.info(
        "live execution complete: placements=%s cancellations=%s report=%s",
        len(live_report.get("placements", [])),
        len(live_report.get("cancellations", [])),
        execution_report_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
