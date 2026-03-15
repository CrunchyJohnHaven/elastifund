"""Connector for existing Polymarket, Kalshi, and runtime truth artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nontrading.finance.models import FinanceAccount, FinanceGap, FinanceImportBundle, FinancePosition, FinanceTransaction, money, utc_now


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def load_trading_runtime_bundle(repo_root: str | Path, *, observed_at: str | None = None) -> FinanceImportBundle:
    root = Path(repo_root)
    observed = observed_at or utc_now()
    runtime_truth_path = root / "reports" / "runtime_truth_latest.json"
    remote_cycle_path = root / "reports" / "remote_cycle_status.json"
    public_snapshot_path = root / "reports" / "public_runtime_snapshot.json"
    jj_state_path = root / "jj_state.json"

    runtime_truth = _load_json(runtime_truth_path)
    remote_cycle = _load_json(remote_cycle_path)
    public_snapshot = _load_json(public_snapshot_path)
    jj_state = _load_json(jj_state_path)

    primary = runtime_truth or remote_cycle or public_snapshot or {}
    if not primary:
        return FinanceImportBundle(
            source_name="trading_runtime",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "trading_runtime",
                    "missing_runtime_truth",
                    "No runtime truth artifacts were available for trading account sync.",
                    source_ref=str(runtime_truth_path),
                ),
            ),
        )

    source_ref = str(runtime_truth_path if runtime_truth else remote_cycle_path if remote_cycle else public_snapshot_path)
    capital = dict(primary.get("capital") or {})
    polymarket_wallet = dict(primary.get("polymarket_wallet") or {})
    runtime = dict(primary.get("runtime") or {})
    generated_at = (
        str(primary.get("generated_at") or polymarket_wallet.get("checked_at") or runtime.get("polymarket_wallet_checked_at") or observed)
    )

    accounts: list[FinanceAccount] = []
    positions: list[FinancePosition] = []
    transactions: list[FinanceTransaction] = []
    gaps: list[FinanceGap] = []

    polymarket_total = money(polymarket_wallet.get("total_wallet_value_usd") or capital.get("polymarket_observed_total_usd") or 0.0)
    polymarket_cash = money(polymarket_wallet.get("free_collateral_usd") or capital.get("polymarket_actual_deployable_usd") or 0.0)
    polymarket_position_value = money(
        polymarket_wallet.get("positions_current_value_usd") or capital.get("polymarket_positions_current_value_usd") or 0.0
    )
    polymarket_account = FinanceAccount(
        external_id="polymarket",
        name="Polymarket",
        institution="Polymarket",
        account_type="trading",
        available_cash_usd=polymarket_cash,
        current_balance_usd=polymarket_total,
        source_type="runtime_artifact",
        source_ref=source_ref,
        last_synced_at=str(polymarket_wallet.get("checked_at") or generated_at),
        metadata={
            "status": polymarket_wallet.get("status"),
            "open_positions_count": polymarket_wallet.get("open_positions_count"),
            "closed_positions_count": polymarket_wallet.get("closed_positions_count"),
            "reserved_order_usd": polymarket_wallet.get("reserved_order_usd"),
            "runtime_source": source_ref,
        },
    )
    accounts.append(polymarket_account)

    open_positions_count = int(
        polymarket_wallet.get("open_positions_count")
        or runtime.get("polymarket_open_positions")
        or 0
    )
    if polymarket_position_value > 0.0 or open_positions_count > 0:
        positions.append(
            FinancePosition(
                account_key=polymarket_account.account_key,
                external_id="polymarket-open-positions",
                symbol="PMKT",
                name="Polymarket Open Positions",
                asset_class="prediction_market",
                quantity=open_positions_count,
                cost_basis_usd=money(polymarket_wallet.get("positions_initial_value_usd") or 0.0),
                market_value_usd=polymarket_position_value,
                liquidity_tier="restricted",
                source_type="runtime_artifact",
                source_ref=source_ref,
                captured_at=str(polymarket_wallet.get("checked_at") or generated_at),
                metadata={
                    "positions_unrealized_pnl_usd": polymarket_wallet.get("positions_unrealized_pnl_usd"),
                    "live_orders_count": polymarket_wallet.get("live_orders_count"),
                },
            )
        )

    realized_pnl = money(
        polymarket_wallet.get("closed_positions_realized_pnl_usd")
        or runtime.get("polymarket_closed_positions_realized_pnl_usd")
        or 0.0
    )
    closed_positions_count = int(polymarket_wallet.get("closed_positions_count") or 0)
    if realized_pnl != 0.0 or closed_positions_count > 0:
        transactions.append(
            FinanceTransaction(
                account_key=polymarket_account.account_key,
                external_id=f"polymarket-closed-batch-{generated_at}",
                posted_at=str(polymarket_wallet.get("checked_at") or generated_at),
                amount_usd=realized_pnl,
                description="Polymarket closed batch realized PnL",
                merchant="Polymarket",
                category="realized_pnl",
                source_type="runtime_artifact",
                source_ref=source_ref,
                merchant_confidence=1.0,
                metadata={
                    "closed_positions_count": closed_positions_count,
                    "warnings": polymarket_wallet.get("warnings") or [],
                },
            )
        )

    capital_sources = capital.get("sources") or []
    kalshi_source = None
    for item in capital_sources:
        if isinstance(item, dict) and str(item.get("account") or "").strip().lower() == "kalshi":
            kalshi_source = item
            break
    if kalshi_source is not None:
        kalshi_balance = money(kalshi_source.get("amount_usd") or 0.0)
        accounts.append(
            FinanceAccount(
                external_id="kalshi",
                name="Kalshi",
                institution="Kalshi",
                account_type="trading",
                available_cash_usd=kalshi_balance,
                current_balance_usd=kalshi_balance,
                source_type="runtime_artifact",
                source_ref=source_ref,
                last_synced_at=generated_at,
                metadata={"capital_source": dict(kalshi_source)},
            )
        )
        gaps.append(
            FinanceGap(
                "trading_runtime",
                "kalshi_runtime_detail_missing",
                "Kalshi truth is currently sourced from tracked runtime capital, not a direct account export.",
                severity="info",
                source_ref=source_ref,
            )
        )
    else:
        tracked_balance = money((public_snapshot or {}).get("capital", {}).get("kalshi_tracked_balance_usd") or 0.0)
        if tracked_balance > 0.0:
            accounts.append(
                FinanceAccount(
                    external_id="kalshi",
                    name="Kalshi",
                    institution="Kalshi",
                    account_type="trading",
                    available_cash_usd=tracked_balance,
                    current_balance_usd=tracked_balance,
                    source_type="runtime_artifact",
                    source_ref=str(public_snapshot_path if public_snapshot else source_ref),
                    last_synced_at=generated_at,
                )
            )
            gaps.append(
                FinanceGap(
                    "trading_runtime",
                    "kalshi_balance_fallback",
                    "Kalshi balance used a public snapshot fallback because capital.sources had no Kalshi entry.",
                    severity="info",
                    source_ref=str(public_snapshot_path),
                )
            )

    if jj_state and "bankroll" in jj_state:
        polymarket_account = FinanceAccount(
            account_key=polymarket_account.account_key,
            external_id=polymarket_account.external_id,
            name=polymarket_account.name,
            institution=polymarket_account.institution,
            account_type=polymarket_account.account_type,
            currency=polymarket_account.currency,
            liquidity_tier=polymarket_account.liquidity_tier,
            status=polymarket_account.status,
            available_cash_usd=polymarket_account.available_cash_usd,
            current_balance_usd=polymarket_account.current_balance_usd,
            source_type=polymarket_account.source_type,
            source_ref=polymarket_account.source_ref,
            last_synced_at=polymarket_account.last_synced_at,
            metadata={
                **dict(polymarket_account.metadata),
                "jj_state_bankroll_usd": jj_state.get("bankroll"),
                "jj_state_cycles_completed": jj_state.get("cycles_completed"),
            },
        )
        accounts[0] = polymarket_account

    return FinanceImportBundle(
        source_name="trading_runtime",
        observed_at=observed,
        accounts=tuple(accounts),
        transactions=tuple(transactions),
        positions=tuple(positions),
        gaps=tuple(gaps),
        metadata={
            "source_ref": source_ref,
            "artifacts_used": [
                str(path)
                for path, payload in (
                    (runtime_truth_path, runtime_truth),
                    (remote_cycle_path, remote_cycle),
                    (public_snapshot_path, public_snapshot),
                    (jj_state_path, jj_state),
                )
                if payload is not None
            ],
        },
    )
