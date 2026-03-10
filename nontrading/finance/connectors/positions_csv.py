"""Brokerage and manual positions CSV connector."""

from __future__ import annotations

import csv
from pathlib import Path

from nontrading.finance.models import FinanceAccount, FinanceGap, FinanceImportBundle, FinancePosition, money, utc_now

SYMBOL_COLUMNS = ("symbol", "ticker", "asset", "security")
NAME_COLUMNS = ("name", "description", "security_name")
ACCOUNT_COLUMNS = ("account_name", "account", "account name")
ACCOUNT_ID_COLUMNS = ("account_id", "account_number", "account number")
INSTITUTION_COLUMNS = ("institution", "broker", "custodian")
TYPE_COLUMNS = ("account_type", "type")
ASSET_CLASS_COLUMNS = ("asset_class", "asset type", "security_type")
QUANTITY_COLUMNS = ("quantity", "shares", "units")
MARKET_VALUE_COLUMNS = ("market_value", "market value", "value", "current_value")
COST_BASIS_COLUMNS = ("cost_basis", "cost basis", "cost_basis_total", "book_value")
CASH_COLUMNS = ("cash_balance", "cash", "available_cash")
AS_OF_COLUMNS = ("as_of", "captured_at", "date", "valuation_date")
CURRENT_BALANCE_COLUMNS = ("account_value", "total_account_value", "current_balance")


def _canonical_row(row: dict[str, str]) -> dict[str, str]:
    return {str(key or "").strip().lower(): str(value or "").strip() for key, value in row.items()}


def _field(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = row.get(alias)
        if value:
            return value
    return ""


def load_positions_csv_bundle(import_path: str | Path, *, observed_at: str | None = None) -> FinanceImportBundle:
    root = Path(import_path)
    observed = observed_at or utc_now()
    if not root.exists():
        return FinanceImportBundle(
            source_name="brokerage_positions",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "brokerage_positions",
                    "missing_positions_path",
                    "Brokerage positions import path does not exist.",
                    source_ref=str(root),
                ),
            ),
        )

    files = [root] if root.is_file() else sorted(path for path in root.rglob("*.csv") if path.is_file())
    if not files:
        return FinanceImportBundle(
            source_name="brokerage_positions",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "brokerage_positions",
                    "no_positions_csv_files",
                    "No brokerage positions CSV files were found.",
                    source_ref=str(root),
                ),
            ),
        )

    account_state: dict[str, dict[str, object]] = {}
    positions: list[FinancePosition] = []
    gaps: list[FinanceGap] = []
    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                gaps.append(
                    FinanceGap(
                        "brokerage_positions",
                        "missing_positions_header",
                        "Positions CSV file is missing headers.",
                        source_ref=str(path),
                    )
                )
                continue
            for index, raw_row in enumerate(reader):
                row = _canonical_row(raw_row)
                account_name = _field(row, ACCOUNT_COLUMNS) or path.stem.replace("_", " ").title()
                institution = _field(row, INSTITUTION_COLUMNS) or path.parent.name.replace("_", " ").title()
                account_id = _field(row, ACCOUNT_ID_COLUMNS) or f"{path.stem}-{account_name}"
                account_type = _field(row, TYPE_COLUMNS) or "brokerage"
                account = FinanceAccount(
                    external_id=account_id,
                    name=account_name,
                    institution=institution,
                    account_type=account_type,
                    source_type="positions_csv",
                    source_ref=str(path),
                    metadata={"file_name": path.name},
                )
                state = account_state.setdefault(
                    account.account_key,
                    {
                        "account": account,
                        "cash_total": 0.0,
                        "position_total": 0.0,
                        "current_balance": None,
                    },
                )
                account_value = _field(row, CURRENT_BALANCE_COLUMNS)
                if account_value:
                    state["current_balance"] = money(account_value)

                cash_value = _field(row, CASH_COLUMNS)
                if cash_value:
                    state["cash_total"] = money(cash_value)

                asset_class = (_field(row, ASSET_CLASS_COLUMNS) or "equity").lower()
                symbol = _field(row, SYMBOL_COLUMNS)
                name = _field(row, NAME_COLUMNS) or symbol
                market_value = _field(row, MARKET_VALUE_COLUMNS)
                quantity = _field(row, QUANTITY_COLUMNS) or 0.0
                cost_basis = _field(row, COST_BASIS_COLUMNS) or 0.0
                if asset_class in {"cash", "cash_equivalent"} or symbol.upper() in {"CASH", "USD"}:
                    state["cash_total"] = money(market_value or cash_value or state["cash_total"])
                    continue
                if not market_value or not name:
                    gaps.append(
                        FinanceGap(
                            "brokerage_positions",
                            "positions_row_missing_required_fields",
                            f"Skipped positions row {index + 1}: missing market value or name.",
                            source_ref=str(path),
                            metadata={"row_index": index + 1},
                        )
                    )
                    continue
                position = FinancePosition(
                    account_key=account.account_key,
                    external_id=f"{account_id}:{symbol or name}:{index + 1}",
                    symbol=symbol,
                    name=name,
                    asset_class=asset_class,
                    quantity=money(quantity),
                    cost_basis_usd=money(cost_basis),
                    market_value_usd=money(market_value),
                    liquidity_tier="liquid",
                    source_type="positions_csv",
                    source_ref=str(path),
                    captured_at=_field(row, AS_OF_COLUMNS) or observed,
                    metadata={"raw_row": row},
                )
                positions.append(position)
                state["position_total"] = float(state["position_total"]) + position.market_value_usd

    accounts: list[FinanceAccount] = []
    for state in account_state.values():
        account = state["account"]
        cash_total = money(state["cash_total"])
        position_total = money(state["position_total"])
        current_balance = state["current_balance"]
        if current_balance is None:
            current_balance = cash_total + position_total
        accounts.append(
            FinanceAccount(
                account_key=account.account_key,
                external_id=account.external_id,
                name=account.name,
                institution=account.institution,
                account_type=account.account_type,
                currency=account.currency,
                liquidity_tier=account.liquidity_tier,
                status=account.status,
                available_cash_usd=cash_total,
                current_balance_usd=current_balance,
                source_type=account.source_type,
                source_ref=account.source_ref,
                metadata=dict(account.metadata),
            )
        )

    return FinanceImportBundle(
        source_name="brokerage_positions",
        observed_at=observed,
        accounts=tuple(accounts),
        positions=tuple(positions),
        gaps=tuple(gaps),
        metadata={"import_root": str(root), "files": [str(path) for path in files]},
    )
