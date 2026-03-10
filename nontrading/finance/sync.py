"""Finance truth-layer sync helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nontrading.finance.config import FinanceSettings
from nontrading.finance.main import _read_rows
from nontrading.finance.models import FinanceAccount, FinancePosition, FinanceTransaction
from nontrading.finance.store import FinanceStore


@dataclass(frozen=True)
class SyncFinanceResult:
    bundle_counts: dict[str, dict[str, int]]
    snapshot: Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_bank_csv(path: Path, store: FinanceStore) -> dict[str, int]:
    transactions = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"accounts": 0, "transactions": 0}
    last = rows[-1]
    account_key = path.stem
    store.upsert_account(
        FinanceAccount(
            account_key=account_key,
            name=str(last.get("Account Name") or path.stem.title()),
            institution=str(last.get("Institution") or ""),
            account_type=str(last.get("Account Type") or "bank"),
            available_cash_usd=float(last.get("Balance", 0.0) or 0.0),
            current_balance_usd=float(last.get("Balance", 0.0) or 0.0),
            source_type="bank_csv",
            source_ref=str(path),
        )
    )
    for index, row in enumerate(rows):
        store.upsert_transaction(
            FinanceTransaction(
                transaction_key=f"{path.stem}-{index}",
                transaction_id=f"{path.stem}-{index}",
                account_key=account_key,
                posted_at=str(row.get("Date") or ""),
                merchant=str(row.get("Description") or ""),
                description=str(row.get("Description") or ""),
                amount_usd=float(row.get("Amount", 0.0) or 0.0),
                category="",
                source="bank_csv",
            )
        )
        transactions += 1
    return {"accounts": 1, "transactions": transactions}


def _parse_card_ofx(path: Path, store: FinanceStore) -> dict[str, int]:
    rows = _read_rows(path)
    account_key = "card"
    text = path.read_text(encoding="utf-8", errors="ignore")
    balance = 0.0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("<BALAMT>"):
            balance = float(line.split(">", 1)[1])
            break
    store.upsert_account(
        FinanceAccount(
            account_key=account_key,
            name="Amex Card",
            institution="Amex",
            account_type="card",
            available_cash_usd=0.0,
            current_balance_usd=balance,
            source_type="ofx",
            source_ref=str(path),
        )
    )
    for row in rows:
        posted = str(row.get("posted_at") or "2026-03-05T12:00:00+00:00")
        if len(posted) == 8 and posted.isdigit():
            posted = f"{posted[:4]}-{posted[4:6]}-{posted[6:8]}T12:00:00+00:00"
        store.upsert_transaction(
            FinanceTransaction(
                transaction_key=str(row.get("transaction_key") or "card-0"),
                transaction_id=str(row.get("transaction_key") or "card-0"),
                account_key=account_key,
                posted_at=posted,
                merchant=str(row.get("merchant") or ""),
                description=str(row.get("description") or ""),
                amount_usd=float(row.get("amount_usd", 0.0) or 0.0),
                source="ofx",
            )
        )
    return {"accounts": 1, "transactions": len(rows)}


def _parse_brokerage_positions(path: Path, store: FinanceStore) -> dict[str, int]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"accounts": 0, "positions": 0}
    first = rows[0]
    account_key = str(first.get("account_id") or path.stem)
    available_cash = float(first.get("cash_balance", 0.0) or 0.0)
    store.upsert_account(
        FinanceAccount(
            account_key=account_key,
            name=str(first.get("account_name") or "Brokerage"),
            institution=str(first.get("institution") or ""),
            account_type=str(first.get("account_type") or "brokerage"),
            available_cash_usd=available_cash,
            current_balance_usd=available_cash,
            source_type="brokerage_csv",
            source_ref=str(path),
        )
    )
    positions = 0
    for index, row in enumerate(rows):
        if str(row.get("asset_class") or "").lower() == "cash":
            continue
        store.upsert_position(
            FinancePosition(
                account_key=account_key,
                position_key=f"{account_key}-{index}",
                external_id=f"{account_key}-{index}",
                symbol=str(row.get("symbol") or ""),
                name=str(row.get("name") or row.get("symbol") or ""),
                asset_class=str(row.get("asset_class") or "equity"),
                asset_type=str(row.get("asset_class") or "equity"),
                quantity=float(row.get("quantity", 0.0) or 0.0),
                cost_basis_usd=float(row.get("cost_basis", 0.0) or 0.0),
                market_value_usd=float(row.get("market_value", 0.0) or 0.0),
                liquidity_tier="liquid",
                source_type="brokerage_csv",
                source_ref=str(path),
            )
        )
        positions += 1
    return {"accounts": 1, "positions": positions}


def _parse_startup_equity(path: Path, store: FinanceStore) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    positions = payload.get("positions", [])
    total_value = round(sum(float(item.get("estimated_value_usd", 0.0) or 0.0) for item in positions), 2)
    account_key = "startup-equity"
    store.upsert_account(
        FinanceAccount(
            account_key=account_key,
            name=str(payload.get("account_name") or "Startup Equity"),
            institution=str(payload.get("institution") or ""),
            account_type="equity",
            liquidity_tier="illiquid",
            available_cash_usd=0.0,
            current_balance_usd=total_value,
            source_type="startup_equity_json",
            source_ref=str(path),
        )
    )
    for index, row in enumerate(positions):
        store.upsert_position(
            FinancePosition(
                account_key=account_key,
                position_key=f"startup-{index}",
                external_id=f"startup-{index}",
                symbol=str(row.get("symbol") or row.get("company") or ""),
                name=str(row.get("company") or row.get("symbol") or ""),
                asset_class="startup_equity",
                asset_type="startup_equity",
                quantity=float(row.get("shares", 0.0) or 0.0),
                cost_basis_usd=float(row.get("cost_basis_usd", 0.0) or 0.0),
                market_value_usd=float(row.get("estimated_value_usd", 0.0) or 0.0),
                liquidity_tier="illiquid",
                source_type="startup_equity_json",
                source_ref=str(path),
            )
        )
    return {"accounts": 1, "positions": len(positions)}


def _parse_runtime_truth(path: Path, repo_root: Path, store: FinanceStore) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    wallet = payload.get("polymarket_wallet", {})
    capital = payload.get("capital", {})
    store.upsert_account(
        FinanceAccount(
            account_key="polymarket",
            name="Polymarket",
            institution="Polymarket",
            account_type="trading",
            available_cash_usd=float(wallet.get("free_collateral_usd", 0.0) or 0.0),
            current_balance_usd=float(wallet.get("total_wallet_value_usd", 0.0) or 0.0),
            source_type="runtime_truth",
            source_ref=str(path),
        )
    )
    sources = capital.get("sources", [])
    kalshi_amount = 0.0
    for source in sources:
        if str(source.get("account") or "").lower() == "kalshi":
            kalshi_amount = float(source.get("amount_usd", 0.0) or 0.0)
            break
    if kalshi_amount:
        store.upsert_account(
            FinanceAccount(
                account_key="kalshi",
                name="Kalshi",
                institution="Kalshi",
                account_type="trading",
                available_cash_usd=kalshi_amount,
                current_balance_usd=kalshi_amount,
                source_type="runtime_truth",
                source_ref=str(path),
            )
        )
    store.upsert_position(
        FinancePosition(
            account_key="polymarket",
            position_key="polymarket-open-positions",
            external_id="polymarket-open-positions",
            symbol="POLY-OPEN",
            name="Polymarket Open Positions",
            asset_class="trading_position",
            asset_type="trading_position",
            quantity=float(wallet.get("open_positions_count", 0.0) or 0.0),
            market_value_usd=float(wallet.get("positions_current_value_usd", 0.0) or 0.0),
            liquidity_tier="liquid",
            source_type="runtime_truth",
            source_ref=str(path),
        )
    )
    realized_pnl = float(payload.get("runtime", {}).get("polymarket_closed_positions_realized_pnl_usd", 0.0) or 0.0)
    if realized_pnl:
        store.upsert_transaction(
            FinanceTransaction(
                transaction_key="runtime-closed-pnl",
                transaction_id="runtime-closed-pnl",
                account_key="polymarket",
                posted_at=str(payload.get("runtime", {}).get("polymarket_wallet_checked_at") or payload.get("generated_at")),
                merchant="Polymarket Realized PnL",
                description="Closed positions realized PnL",
                amount_usd=realized_pnl,
                source="runtime_truth",
                direction="deposit",
            )
        )
    return {"accounts": 2 if kalshi_amount else 1, "positions": 1, "transactions": 1 if realized_pnl else 0}


def sync_finance_truth(
    store: FinanceStore,
    settings: FinanceSettings,
    *,
    repo_root: str | Path,
    report_path: str | Path | None = None,
) -> SyncFinanceResult:
    repo_root = Path(repo_root)
    report_path = Path(report_path) if report_path is not None else repo_root / "reports" / "finance" / "latest.json"
    bundle_counts = {
        "bank_imports": {"accounts": 0, "transactions": 0},
        "brokerage_positions": {"accounts": 0, "positions": 0},
        "startup_equity": {"accounts": 0, "positions": 0},
        "trading_runtime": {"accounts": 0, "positions": 0, "transactions": 0},
    }
    gaps: list[dict[str, str]] = []

    settings.ensure_paths()
    for name, value in {
        "autonomy_mode": settings.autonomy_mode,
        "single_action_cap_usd": settings.single_action_cap_usd,
        "monthly_new_commitment_cap_usd": settings.monthly_new_commitment_cap_usd,
        "min_cash_reserve_months": settings.min_cash_reserve_months,
        "equity_treatment": settings.equity_treatment,
        "whitelist_json": settings.whitelist_json,
    }.items():
        store.set_budget_policy(name, value)

    bank_dir = settings.imports_dir / "bank"
    if bank_dir.exists():
        for csv_path in sorted(bank_dir.glob("*.csv")):
            result = _parse_bank_csv(csv_path, store)
            bundle_counts["bank_imports"]["accounts"] += result["accounts"]
            bundle_counts["bank_imports"]["transactions"] += result["transactions"]
        for ofx_path in sorted(bank_dir.glob("*.ofx")):
            result = _parse_card_ofx(ofx_path, store)
            bundle_counts["bank_imports"]["accounts"] += result["accounts"]
            bundle_counts["bank_imports"]["transactions"] += result["transactions"]
    else:
        gaps.append({"gap_key": "missing_bank_import_dir", "detail": str(bank_dir)})

    positions_path = settings.imports_dir / "brokerage" / "positions.csv"
    if positions_path.exists():
        result = _parse_brokerage_positions(positions_path, store)
        bundle_counts["brokerage_positions"]["accounts"] += result["accounts"]
        bundle_counts["brokerage_positions"]["positions"] += result["positions"]
    else:
        gaps.append({"gap_key": "missing_positions_path", "detail": str(positions_path)})

    equity_path = settings.imports_dir / "startup_equity.json"
    if equity_path.exists():
        result = _parse_startup_equity(equity_path, store)
        bundle_counts["startup_equity"]["accounts"] += result["accounts"]
        bundle_counts["startup_equity"]["positions"] += result["positions"]
    else:
        gaps.append({"gap_key": "missing_startup_equity_snapshot", "detail": str(equity_path)})

    runtime_truth_path = repo_root / "reports" / "runtime_truth_latest.json"
    if runtime_truth_path.exists():
        result = _parse_runtime_truth(runtime_truth_path, repo_root, store)
        for key, value in result.items():
            bundle_counts["trading_runtime"][key] += value
    else:
        gaps.append({"gap_key": "missing_runtime_truth", "detail": str(runtime_truth_path)})

    snapshot = store.build_snapshot(settings=settings)
    snapshot.summary["gaps"] = gaps
    report = {
        "schema_version": "finance_control_plane.truth.v1",
        "generated_at": None,
        "bundle_counts": bundle_counts,
        "snapshot": snapshot.summary,
    }
    _write_json(report_path, report)
    store.record_snapshot("sync_truth", report["schema_version"], report)
    return SyncFinanceResult(bundle_counts=bundle_counts, snapshot=snapshot)
