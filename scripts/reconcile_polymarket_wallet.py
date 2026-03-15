#!/usr/bin/env python3
"""Reconcile Polymarket wallet API truth with CSV export + local ledger."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.position_merger import default_user_address
from bot.wallet_reconciliation import (
    PolymarketWalletReconciler,
    apply_wallet_reconciliation_to_runtime_truth,
    build_closed_winners_summary,
    build_open_position_inventory,
    build_capital_attribution_summary,
    classify_btc_open_positions,
    cross_reference_wallet_export,
    load_wallet_export_csv,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    value = dt or _utc_now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_datetime_like(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        if text.isdigit():
            try:
                parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
            except (ValueError, OSError):
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_label(age_hours: float | None) -> str:
    if age_hours is None:
        return "unknown"
    if age_hours <= 6.0:
        return "fresh"
    if age_hours <= 24.0:
        return "aging"
    return "stale"


def _render_open_exposure_markdown(
    *,
    generated_at: str,
    closed_winners: list[dict[str, Any]],
    open_inventory: dict[str, Any],
) -> str:
    lines = [
        "# Open Exposure Triage",
        "",
        f"Generated at `{generated_at}`.",
        "",
        "## Realized Closed Winners",
        "",
        "| title | outcome | realized_pnl_usd |",
        "| --- | --- | ---: |",
    ]
    for row in closed_winners:
        lines.append(
            f"| {row.get('title') or ''} | {row.get('outcome') or ''} | {float(row.get('realized_pnl_usd') or 0.0):.4f} |"
        )

    lines.extend(
        [
            "",
            "## Current Mark-To-Market Open Book",
            "",
            "| sleeve | title | current_value_usd | unrealized_pnl_usd | policy_state | exit_owner | exit_rule |",
            "| --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in open_inventory.get("rows") or []:
        lines.append(
            "| {sleeve} | {title} | {current:.4f} | {pnl:.4f} | {policy} | {owner} | {rule} |".format(
                sleeve=row.get("sleeve") or "",
                title=row.get("title") or "",
                current=float(row.get("current_value_usd") or 0.0),
                pnl=float(row.get("unrealized_pnl_usd") or 0.0),
                policy=row.get("policy_state") or "",
                owner=row.get("exit_owner") or "",
                rule=row.get("exit_rule") or "",
            )
        )
    return "\n".join(lines) + "\n"


def _looks_like_live_wallet_address(value: str) -> bool:
    text = str(value or "").strip().lower()
    if len(text) != 42 or not text.startswith("0x"):
        return False
    return all(ch in "0123456789abcdef" for ch in text[2:])


def _load_env_defaults(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"POLY_SAFE_ADDRESS", "POLYMARKET_FUNDER"} or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _wallet_export_candidates() -> list[Path]:
    candidates: list[Path] = []
    for base in (
        REPO_ROOT,
        REPO_ROOT / "data",
        REPO_ROOT / "reports",
        Path.home() / "Downloads",
    ):
        if not base.exists():
            continue
        for path in base.glob("Polymarket-History-*.csv"):
            candidates.append(path.resolve())
    unique = sorted(set(candidates), key=lambda path: path.stat().st_mtime, reverse=True)
    return unique


def _position_fingerprint(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[str] = []
    token_ids: set[str] = set()
    for row in rows:
        condition_id = _normalize_text(row.get("conditionId") or row.get("condition_id"))
        asset_id = _normalize_text(row.get("asset") or row.get("assetId") or row.get("tokenId"))
        outcome = _normalize_text(row.get("outcome"))
        size = f"{_safe_float(row.get('size'), 0.0):.10f}"
        end_date = _normalize_text(row.get("endDate") or row.get("timestamp"))
        items.append("|".join((condition_id, asset_id, outcome, size, end_date)))
        if asset_id:
            token_ids.add(asset_id)
    payload = "\n".join(sorted(items))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "count": len(rows),
        "fingerprint": digest,
        "token_ids": sorted(token_ids),
    }


def _fetch_consistent_remote_positions(
    reconciler: PolymarketWalletReconciler,
    *,
    user: str,
    max_attempts: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    last_signature: tuple[str, str] | None = None
    last_open: list[dict[str, Any]] = []
    last_closed: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        open_rows = reconciler.fetch_open_positions(user)
        closed_rows = reconciler.fetch_closed_positions(user)
        open_fp = _position_fingerprint(open_rows)
        closed_fp = _position_fingerprint(closed_rows)
        signature = (open_fp["fingerprint"], closed_fp["fingerprint"])
        attempts.append(
            {
                "attempt": attempt,
                "checked_at": _iso(),
                "open_positions": open_fp,
                "closed_positions": closed_fp,
            }
        )
        if signature == last_signature:
            return open_rows, closed_rows, attempts
        last_signature = signature
        last_open = open_rows
        last_closed = closed_rows

    raise RuntimeError(
        json.dumps(
            {
                "reason": "api_inconsistent_after_3_attempts",
                "attempts": attempts,
                "last_open_count": len(last_open),
                "last_closed_count": len(last_closed),
            },
            sort_keys=True,
        )
    )


def _load_runtime_truth(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _wallet_surface_from_runtime_truth(runtime_truth: dict[str, Any]) -> dict[str, float]:
    wallet = runtime_truth.get("polymarket_wallet") if isinstance(runtime_truth.get("polymarket_wallet"), dict) else {}
    capital = runtime_truth.get("capital") if isinstance(runtime_truth.get("capital"), dict) else {}
    free_collateral = _safe_float(
        wallet.get("free_collateral_usd"),
        _safe_float(capital.get("polymarket_actual_deployable_usd"), 0.0),
    )
    reserved = _safe_float(
        wallet.get("reserved_order_usd"),
        _safe_float(capital.get("polymarket_reserved_order_usd"), 0.0),
    )
    wallet_total = _safe_float(
        wallet.get("total_wallet_value_usd"),
        _safe_float(capital.get("polymarket_observed_total_usd"), 0.0),
    )
    return {
        "wallet_value_usd": round(wallet_total, 6),
        "free_collateral_usd": round(free_collateral, 6),
        "reserved_order_usd": round(reserved, 6),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=None, help="Polymarket funder / safe address.")
    parser.add_argument("--db-path", type=Path, default=REPO_ROOT / "data" / "jj_trades.db")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=REPO_ROOT / "reports" / "wallet_reconciliation" / "latest.json",
    )
    parser.add_argument(
        "--debug-path",
        type=Path,
        default=REPO_ROOT / "reports" / "wallet_reconciliation_debug.json",
    )
    parser.add_argument(
        "--runtime-truth-path",
        type=Path,
        default=REPO_ROOT / "reports" / "runtime_truth_latest.json",
    )
    parser.add_argument(
        "--wallet-export-csv",
        type=Path,
        default=None,
        help="Optional explicit wallet export CSV path. Defaults to newest Polymarket-History-*.csv in repo/Downloads.",
    )
    parser.add_argument(
        "--apply-local-fixes",
        action="store_true",
        help="Backfill closed trades in the local ledger using remote wallet truth.",
    )
    parser.add_argument(
        "--purge-phantoms",
        action="store_true",
        help="Delete local open trades that have no remote match and no transaction hash.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _load_env_defaults(REPO_ROOT / ".env")
    user = str(args.user or default_user_address() or "").strip()
    if not user:
        raise SystemExit("wallet address required via --user or POLY_SAFE_ADDRESS/POLYMARKET_FUNDER")
    if not _looks_like_live_wallet_address(user):
        raise SystemExit(
            "wallet address is missing or placeholder; set POLY_SAFE_ADDRESS/POLYMARKET_FUNDER to a live 0x address"
        )

    wallet_export_path = args.wallet_export_csv.resolve() if args.wallet_export_csv else None
    if wallet_export_path is None:
        candidates = _wallet_export_candidates()
        wallet_export_path = candidates[0] if candidates else None
    if wallet_export_path is None:
        wallet_export_summary = {
            "available": False,
            "path": None,
            "latest_timestamp": None,
            "row_count": 0,
            "open_market_keys": [],
            "redeemed_market_keys": [],
        }
    else:
        wallet_export_summary = load_wallet_export_csv(wallet_export_path)

    reconciler = PolymarketWalletReconciler()
    try:
        try:
            open_positions, closed_positions, api_attempts = _fetch_consistent_remote_positions(
                reconciler,
                user=user,
                max_attempts=3,
            )
        except RuntimeError as exc:
            debug_payload = {
                "status": "api_inconsistent",
                "checked_at": _iso(),
                "user_address": user,
                "error": str(exc),
            }
            args.debug_path.parent.mkdir(parents=True, exist_ok=True)
            args.debug_path.write_text(
                json.dumps(debug_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(debug_payload, indent=2, sort_keys=True))
            return 2

        base_summary = reconciler.reconcile_to_sqlite(
            user_address=user,
            db_path=args.db_path.resolve(),
            report_path=None,
            open_positions=open_positions,
            closed_positions=closed_positions,
            apply_local_fixes=bool(args.apply_local_fixes),
            purge_phantom_open_trades=bool(args.purge_phantoms),
        )
    finally:
        reconciler.close()

    runtime_truth = _load_runtime_truth(args.runtime_truth_path.resolve())
    wallet_surface = _wallet_surface_from_runtime_truth(runtime_truth)
    open_current_value = round(
        sum(_safe_float(row.get("currentValue"), 0.0) for row in open_positions),
        6,
    )
    if wallet_surface["wallet_value_usd"] <= 0.0:
        wallet_surface["wallet_value_usd"] = round(
            wallet_surface["free_collateral_usd"] + wallet_surface["reserved_order_usd"] + open_current_value,
            6,
        )
    if wallet_surface["free_collateral_usd"] <= 0.0:
        wallet_surface["free_collateral_usd"] = max(
            0.0,
            round(
                wallet_surface["wallet_value_usd"] - wallet_surface["reserved_order_usd"] - open_current_value,
                6,
            ),
        )

    cross_reference = cross_reference_wallet_export(
        wallet_export_summary=wallet_export_summary,
        open_positions=open_positions,
        closed_positions=closed_positions,
    )
    btc_open_status = classify_btc_open_positions(open_positions, now=_utc_now(), stale_after_hours=24.0)
    open_position_inventory = build_open_position_inventory(
        open_positions,
        btc_open_status=btc_open_status,
    )
    closed_winners = build_closed_winners_summary(closed_positions, limit=10)
    capital_attribution = build_capital_attribution_summary(
        open_positions=open_positions,
        wallet_value_usd=wallet_surface["wallet_value_usd"],
        free_collateral_usd=wallet_surface["free_collateral_usd"],
        reserved_order_usd=wallet_surface["reserved_order_usd"],
    )
    capital_delta_abs = abs(_safe_float(capital_attribution.get("capital_accounting_delta_usd"), 0.0))

    export_latest_ts = _parse_datetime_like(wallet_export_summary.get("latest_timestamp"))
    export_age_hours = None
    if export_latest_ts is not None:
        export_age_hours = round(max(0.0, (_utc_now() - export_latest_ts).total_seconds() / 3600.0), 4)

    stage_gate_blocking_checks: list[str] = []
    if not wallet_export_summary.get("available"):
        stage_gate_blocking_checks.append("wallet_export_missing")
    if export_age_hours is not None and export_age_hours > 24.0:
        stage_gate_blocking_checks.append("wallet_export_stale")
    if int(_safe_float(btc_open_status.get("btc_open_positions_stale"), 0.0) or 0) > 0:
        stage_gate_blocking_checks.append("wallet_export_btc_open_markets_stale_not_zero")
    if capital_delta_abs > 5.0:
        stage_gate_blocking_checks.append("capital_accounting_delta_usd_above_tolerance")

    stage_gate_ready = not stage_gate_blocking_checks
    launch_gate_status = "ready_for_launch_gate" if stage_gate_ready else base_summary.status
    launch_gate_recommendation = "ready_for_launch_gate" if stage_gate_ready else base_summary.recommendation

    wallet_reconciliation_summary = {
        "checked_at": _iso(),
        "user_address": user,
        "status": launch_gate_status,
        "recommendation": launch_gate_recommendation,
        "local_ledger_status": base_summary.status,
        "local_ledger_recommendation": base_summary.recommendation,
        "open_positions_count": base_summary.open_positions_count,
        "closed_positions_count": base_summary.closed_positions_count,
        "matched_remote_open_positions": base_summary.matched_remote_open_positions,
        "matched_remote_closed_positions": base_summary.matched_remote_closed_positions,
        "unmatched_remote_open_positions": base_summary.unmatched_remote_open_positions,
        "unmatched_remote_closed_positions": base_summary.unmatched_remote_closed_positions,
        "local_trade_count": base_summary.local_trade_count,
        "phantom_local_open_trade_ids": list(base_summary.phantom_local_open_trade_ids),
        "remote_closed_local_open_trade_ids": list(base_summary.remote_closed_local_open_trade_ids),
        "wallet_export_path": wallet_export_summary.get("path"),
        "wallet_export_latest_timestamp": wallet_export_summary.get("latest_timestamp"),
        "wallet_export_age_hours": export_age_hours,
        "wallet_export_freshness_label": _freshness_label(export_age_hours),
        "reconciliation_reason": "api_csv_cross_reference",
        "open_inventory_ready": True,
        "btc5_intentional_open_positions": int(
            (open_position_inventory.get("summary") or {}).get("sleeve_counts", {}).get("btc5_intentional", 0)
        ),
        "non_btc_fast_open_positions": int(
            (open_position_inventory.get("summary") or {}).get("sleeve_counts", {}).get("non_btc_fast", 0)
        ),
        "long_dated_discretionary_open_positions": int(
            (open_position_inventory.get("summary") or {}).get("sleeve_counts", {}).get("long_dated_discretionary", 0)
        ),
        "close_only_open_positions": int(
            (open_position_inventory.get("summary") or {}).get("policy_counts", {}).get("close_only", 0)
        ),
        "stage_gate_ready": stage_gate_ready,
        "stage_gate_blocking_checks": stage_gate_blocking_checks,
        "stage_gate_reason": (
            "Wallet/API reconciliation is ready for launch gates."
            if stage_gate_ready
            else "Wallet/API reconciliation still has blocking checks for launch gates."
        ),
    }

    open_position_snapshot = [
        {
            "condition_id": row.get("conditionId"),
            "token_id": row.get("asset"),
            "title": row.get("title"),
            "outcome": row.get("outcome"),
            "size": _safe_float(row.get("size"), 0.0),
            "initial_value_usd": _safe_float(row.get("initialValue"), 0.0),
            "current_value_usd": _safe_float(row.get("currentValue"), 0.0),
            "end_date": row.get("endDate"),
            "redeemable": bool(row.get("redeemable")),
        }
        for row in open_positions
    ]
    closed_position_snapshot = [
        {
            "condition_id": row.get("conditionId"),
            "token_id": row.get("asset"),
            "title": row.get("title"),
            "outcome": row.get("outcome"),
            "realized_pnl_usd": _safe_float(row.get("realizedPnl"), 0.0),
            "end_date": row.get("endDate"),
            "timestamp": row.get("timestamp"),
        }
        for row in closed_positions
    ]
    payload = {
        "status": "ok",
        "generated_at": _iso(),
        "user_address": user,
        "api_attempts": api_attempts,
        "wallet_reconciliation_summary": wallet_reconciliation_summary,
        "cross_reference": cross_reference,
        "btc_open_status": btc_open_status,
        "open_position_inventory": open_position_inventory,
        "closed_winners": closed_winners,
        "capital_attribution": capital_attribution,
        "wallet_export_summary": {
            "available": wallet_export_summary.get("available"),
            "path": wallet_export_summary.get("path"),
            "row_count": wallet_export_summary.get("row_count"),
            "latest_timestamp": wallet_export_summary.get("latest_timestamp"),
            "open_market_keys_count": len(wallet_export_summary.get("open_market_keys") or []),
            "redeemed_market_keys_count": len(wallet_export_summary.get("redeemed_market_keys") or []),
        },
        "open_positions": {
            "count": len(open_position_snapshot),
            "rows": open_position_snapshot,
            "token_ids": sorted(
                {
                    str(item.get("token_id"))
                    for item in open_position_snapshot
                    if str(item.get("token_id") or "").strip()
                }
            ),
        },
        "closed_positions": {
            "count": len(closed_position_snapshot),
            "rows": closed_position_snapshot,
        },
    }

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    exposure_report_path = args.report_path.with_name("open_exposure_inventory.md")
    exposure_report_path.write_text(
        _render_open_exposure_markdown(
            generated_at=payload["generated_at"],
            closed_winners=closed_winners,
            open_inventory=open_position_inventory,
        ),
        encoding="utf-8",
    )
    apply_wallet_reconciliation_to_runtime_truth(
        runtime_truth_path=args.runtime_truth_path.resolve(),
        reconciliation_payload=payload,
    )

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
