"""Startup equity snapshot connector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nontrading.finance.models import FinanceAccount, FinanceGap, FinanceImportBundle, FinancePosition, money, utc_now


def _coerce_positions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("positions", "holdings", "equity"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def load_startup_equity_bundle(snapshot_path: str | Path, *, observed_at: str | None = None) -> FinanceImportBundle:
    path = Path(snapshot_path)
    observed = observed_at or utc_now()
    if not path.exists():
        return FinanceImportBundle(
            source_name="startup_equity",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "startup_equity",
                    "missing_startup_equity_snapshot",
                    "Startup equity snapshot JSON does not exist.",
                    source_ref=str(path),
                ),
            ),
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    positions_payload = _coerce_positions(payload)
    if not positions_payload:
        return FinanceImportBundle(
            source_name="startup_equity",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "startup_equity",
                    "empty_startup_equity_snapshot",
                    "Startup equity snapshot JSON contained no positions.",
                    source_ref=str(path),
                ),
            ),
        )

    account_name = "Startup Equity"
    institution = "Private Equity"
    if isinstance(payload, dict):
        account_name = str(payload.get("account_name") or account_name)
        institution = str(payload.get("institution") or institution)

    account = FinanceAccount(
        external_id=path.stem,
        name=account_name,
        institution=institution,
        account_type="equity",
        liquidity_tier="illiquid",
        available_cash_usd=0.0,
        current_balance_usd=0.0,
        source_type="startup_equity_snapshot",
        source_ref=str(path),
        metadata={"file_name": path.name},
    )
    positions: list[FinancePosition] = []
    total_value = 0.0
    for index, item in enumerate(positions_payload):
        company_name = str(item.get("company") or item.get("company_name") or item.get("name") or "Startup Equity").strip()
        symbol = str(item.get("symbol") or company_name[:8]).strip().upper()
        shares = money(item.get("shares") or item.get("quantity") or item.get("vested_shares") or 0.0)
        market_value = money(
            item.get("estimated_value_usd")
            or item.get("fair_value_usd")
            or item.get("market_value_usd")
            or item.get("value_usd")
            or 0.0
        )
        cost_basis = money(item.get("cost_basis_usd") or item.get("strike_cost_usd") or 0.0)
        positions.append(
            FinancePosition(
                account_key=account.account_key,
                external_id=f"{path.stem}:{symbol}:{index + 1}",
                symbol=symbol,
                name=company_name,
                asset_class="startup_equity",
                quantity=shares,
                cost_basis_usd=cost_basis,
                market_value_usd=market_value,
                liquidity_tier="illiquid",
                source_type="startup_equity_snapshot",
                source_ref=str(path),
                captured_at=str(item.get("as_of") or item.get("captured_at") or observed),
                metadata={
                    "vesting_status": item.get("vesting_status"),
                    "notes": item.get("notes"),
                },
            )
        )
        total_value += market_value

    account = FinanceAccount(
        account_key=account.account_key,
        external_id=account.external_id,
        name=account.name,
        institution=account.institution,
        account_type=account.account_type,
        currency=account.currency,
        liquidity_tier=account.liquidity_tier,
        status=account.status,
        available_cash_usd=0.0,
        current_balance_usd=total_value,
        source_type=account.source_type,
        source_ref=account.source_ref,
        metadata=dict(account.metadata),
    )
    return FinanceImportBundle(
        source_name="startup_equity",
        observed_at=observed,
        accounts=(account,),
        positions=tuple(positions),
        metadata={"snapshot_path": str(path)},
    )
