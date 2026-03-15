from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nontrading.finance.config import FinanceSettings
from nontrading.finance.models import FinanceAccount, FinancePosition
from nontrading.finance.store import FinanceStore
from nontrading.finance.sync import sync_finance_truth


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_bank_and_brokerage_imports(imports_dir: Path) -> None:
    bank_dir = imports_dir / "bank"
    bank_dir.mkdir(parents=True, exist_ok=True)
    (bank_dir / "checking.csv").write_text(
        "\n".join(
            [
                "Date,Description,Amount,Balance,Account Name,Institution,Account Type",
                "2026-03-01,Payroll,2500.00,2500.00,Primary Checking,Chase,bank",
                "2026-03-02,Rent,-1200.00,1300.00,Primary Checking,Chase,bank",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bank_dir / "card.ofx").write_text(
        """
<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <FI>
        <ORG>Amex
      </FI>
    </SONRS>
  </SIGNONMSGSRSV1>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <CCSTMTRS>
        <CURDEF>USD
        <CCACCTFROM>
          <ACCTID>card-1234
        </CCACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT
            <DTPOSTED>20260305120000[-5:EST]
            <TRNAMT>-30.50
            <FITID>txn-card-1
            <NAME>OpenAI
            <MEMO>ChatGPT Plus
          </STMTTRN>
        </BANKTRANLIST>
        <LEDGERBAL>
          <BALAMT>-30.50
        </LEDGERBAL>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>
""".strip()
        + "\n",
        encoding="utf-8",
    )

    brokerage_dir = imports_dir / "brokerage"
    brokerage_dir.mkdir(parents=True, exist_ok=True)
    (brokerage_dir / "positions.csv").write_text(
        "\n".join(
            [
                "account_name,institution,account_id,account_type,symbol,name,asset_class,quantity,market_value,cost_basis,cash_balance,as_of",
                "Taxable Brokerage,Schwab,schwab-1,brokerage,VTI,Vanguard Total Stock Market,equity,10,2500.00,2300.00,400.00,2026-03-08T10:00:00+00:00",
                "Taxable Brokerage,Schwab,schwab-1,brokerage,CASH,USD Sweep,cash,1,400.00,400.00,400.00,2026-03-08T10:00:00+00:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        imports_dir / "startup_equity.json",
        {
            "account_name": "Startup Equity",
            "institution": "Private Equity",
            "positions": [
                {
                    "company": "Acme Labs",
                    "symbol": "ACME",
                    "shares": 1000,
                    "estimated_value_usd": 5000.0,
                    "cost_basis_usd": 0.0,
                    "as_of": "2026-03-08T00:00:00+00:00",
                }
            ],
        },
    )


def _seed_runtime_truth(repo_root: Path) -> None:
    _write_json(
        repo_root / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": "2026-03-10T12:00:00+00:00",
            "capital": {
                "polymarket_actual_deployable_usd": 317.096023,
                "polymarket_observed_total_usd": 370.6114,
                "polymarket_positions_current_value_usd": 53.515377,
                "sources": [
                    {"account": "Kalshi", "amount_usd": 100.0, "source": "manual_tracked_balance"}
                ],
            },
            "polymarket_wallet": {
                "checked_at": "2026-03-10T12:00:00+00:00",
                "status": "ok",
                "free_collateral_usd": 317.096023,
                "total_wallet_value_usd": 370.6114,
                "positions_current_value_usd": 53.515377,
                "positions_initial_value_usd": 43.1032,
                "positions_unrealized_pnl_usd": 10.412177,
                "open_positions_count": 7,
                "closed_positions_count": 50,
                "closed_positions_realized_pnl_usd": 278.999,
                "live_orders_count": 0,
                "reserved_order_usd": 0.0,
                "warnings": [],
            },
            "runtime": {
                "polymarket_open_positions": 7,
                "polymarket_closed_positions_realized_pnl_usd": 278.999,
                "polymarket_wallet_checked_at": "2026-03-10T12:00:00+00:00",
            },
        },
    )
    _write_json(
        repo_root / "jj_state.json",
        {
            "bankroll": 247.51,
            "cycles_completed": 565,
        },
    )


def test_sync_finance_truth_ingests_mixed_sources_and_writes_snapshot(tmp_path: Path) -> None:
    imports_dir = tmp_path / "imports"
    _seed_bank_and_brokerage_imports(imports_dir)
    _seed_runtime_truth(tmp_path)

    settings = FinanceSettings(
        db_path=tmp_path / "state" / "jj_finance.db",
        imports_dir=imports_dir,
        whitelist_json="[]",
    )
    store = FinanceStore(settings.db_path)
    report_path = tmp_path / "reports" / "finance" / "latest.json"

    result = sync_finance_truth(store, settings, repo_root=tmp_path, report_path=report_path)

    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "finance_control_plane.truth.v1"

    assert result.bundle_counts["bank_imports"]["transactions"] == 3
    assert result.bundle_counts["brokerage_positions"]["positions"] == 1
    assert result.bundle_counts["startup_equity"]["positions"] == 1
    assert result.bundle_counts["trading_runtime"]["accounts"] == 2

    tables = set()
    with sqlite3.connect(settings.db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {str(row[0]) for row in rows}
    assert {
        "finance_accounts",
        "finance_transactions",
        "finance_positions",
        "finance_recurring_commitments",
        "finance_subscriptions",
        "finance_budget_policies",
        "finance_experiments",
        "finance_action_queue",
        "finance_snapshots",
    }.issubset(tables)

    snapshot = result.snapshot.summary
    assert snapshot["counts"]["accounts"] == 6
    assert snapshot["counts"]["positions"] == 3
    assert snapshot["counts"]["transactions"] == 4
    assert snapshot["counts"]["budget_policies"] == 6
    assert snapshot["totals"]["deployable_cash_usd"] == pytest.approx(2117.096023)
    assert snapshot["totals"]["illiquid_position_value_usd"] == pytest.approx(5000.0)
    assert snapshot["totals"]["total_net_worth_proxy_usd"] == pytest.approx(9640.1114)

    accounts = {account["name"]: account for account in snapshot["accounts"]}
    assert accounts["Polymarket"]["available_cash_usd"] == pytest.approx(317.096023)
    assert accounts["Kalshi"]["current_balance_usd"] == pytest.approx(100.0)
    assert accounts["Startup Equity"]["liquidity_tier"] == "illiquid"

    positions = {position["name"]: position for position in snapshot["positions"]}
    assert positions["Acme Labs"]["liquidity_tier"] == "illiquid"
    assert positions["Polymarket Open Positions"]["market_value_usd"] == pytest.approx(53.515377)


def test_sync_finance_truth_emits_machine_readable_gaps_when_sources_missing(tmp_path: Path) -> None:
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    settings = FinanceSettings(
        db_path=tmp_path / "state" / "jj_finance.db",
        imports_dir=imports_dir,
        whitelist_json="[]",
    )
    store = FinanceStore(settings.db_path)
    report_path = tmp_path / "reports" / "finance" / "latest.json"

    result = sync_finance_truth(store, settings, repo_root=tmp_path, report_path=report_path)

    assert report_path.exists()
    gap_keys = {gap["gap_key"] for gap in result.snapshot.summary["gaps"]}
    assert {
        "missing_bank_import_dir",
        "missing_positions_path",
        "missing_startup_equity_snapshot",
        "missing_runtime_truth",
    }.issubset(gap_keys)
    assert result.snapshot.summary["counts"]["accounts"] == 0
    assert result.snapshot.summary["counts"]["positions"] == 0
    assert result.snapshot.summary["counts"]["transactions"] == 0


def test_illiquid_equity_is_excluded_from_deployable_cash(tmp_path: Path) -> None:
    settings = FinanceSettings(
        db_path=tmp_path / "state" / "jj_finance.db",
        imports_dir=tmp_path / "imports",
        equity_treatment="illiquid_only",
        whitelist_json="[]",
    )
    store = FinanceStore(settings.db_path, settings=settings)
    liquid_account = FinanceAccount(
        external_id="checking-1",
        name="Checking",
        institution="Chase",
        account_type="bank",
        available_cash_usd=100.0,
        current_balance_usd=100.0,
        source_type="pytest",
        source_ref="inline",
    )
    illiquid_account = FinanceAccount(
        external_id="equity-1",
        name="Startup Equity",
        institution="Private Equity",
        account_type="equity",
        liquidity_tier="illiquid",
        available_cash_usd=0.0,
        current_balance_usd=10000.0,
        source_type="pytest",
        source_ref="inline",
    )
    store.upsert_accounts([liquid_account, illiquid_account])
    store.upsert_positions(
        [
            FinancePosition(
                account_key=illiquid_account.account_key,
                external_id="equity-position-1",
                symbol="ACME",
                name="Acme Labs",
                asset_class="startup_equity",
                quantity=1000,
                cost_basis_usd=0.0,
                market_value_usd=10000.0,
                liquidity_tier="illiquid",
                source_type="pytest",
                source_ref="inline",
            )
        ]
    )

    snapshot = store.build_snapshot(settings=settings).summary

    assert snapshot["totals"]["deployable_cash_usd"] == pytest.approx(100.0)
    assert snapshot["totals"]["illiquid_position_value_usd"] == pytest.approx(10000.0)
    assert snapshot["totals"]["total_net_worth_proxy_usd"] == pytest.approx(10100.0)
