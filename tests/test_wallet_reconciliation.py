from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from bot.wallet_reconciliation import (
    PolymarketWalletReconciler,
    build_closed_winners_summary,
    build_open_position_inventory,
    classify_btc_open_positions,
)
from scripts.reconcile_polymarket_wallet import _load_env_defaults, _looks_like_live_wallet_address


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request {url}")
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def _seed_trades(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                market_id TEXT,
                token_id TEXT,
                outcome TEXT,
                pnl REAL,
                resolved_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO trades (id, market_id, token_id, outcome, pnl, resolved_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("open_match", "0xcond1", "0xtoken1", None, None, None),
                ("open_remote_closed", "0xcond2", "0xtoken2", None, None, None),
                ("closed_match", "0xcond3", "0xtoken3", "won", 2.0, "2026-03-11T00:00:00Z"),
                ("open_phantom", "0xcond4", "0xtoken4", None, None, None),
            ],
        )


def test_reconcile_to_sqlite_mirrors_remote_positions_and_scores_drift(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "jj_trades.db"
    report_path = tmp_path / "reports" / "wallet_reconciliation" / "latest.json"
    _seed_trades(db_path)

    reconciler = PolymarketWalletReconciler(session=FakeSession([]))
    summary = reconciler.reconcile_to_sqlite(
        user_address="0xabc",
        db_path=db_path,
        report_path=report_path,
        open_positions=[
            {
                "conditionId": "0xcond1",
                "asset": "0xtoken1",
                "title": "ETH 5m",
                "outcome": "UP",
                "size": 5.0,
            }
        ],
        closed_positions=[
            {
                "conditionId": "0xcond2",
                "asset": "0xtoken2",
                "title": "SOL 5m",
                "outcome": "UP",
                "size": 5.0,
                "realizedPnl": 1.5,
                "transactionHash": "0xhash2",
            },
            {
                "conditionId": "0xcond3",
                "asset": "0xtoken3",
                "title": "XRP 5m",
                "outcome": "DOWN",
                "size": 4.0,
                "realizedPnl": 2.0,
                "transactionHash": "0xhash3",
            },
        ],
    )

    assert summary.open_positions_count == 1
    assert summary.closed_positions_count == 2
    assert summary.matched_local_open_trades == 1
    assert summary.matched_local_closed_trades == 1
    assert summary.remote_closed_local_open_mismatches == 1
    assert summary.phantom_local_open_trade_ids == ["open_phantom"]
    assert summary.snapshot_precision == 1.0
    assert summary.classification_precision == 0.5
    assert summary.status == "drift_detected"
    assert summary.unmatched_open_positions["absolute_delta"] == 2
    assert summary.unmatched_closed_positions["absolute_delta"] == 1
    assert summary.remote_closed_local_open_trade_ids == ["open_remote_closed"]
    assert summary.local_fixes["closed_trades_backfilled"] == 0
    assert summary.local_fixes["phantom_open_trades_deleted"] == 0
    assert summary.recommendation == "purge_phantom_open_trades"
    assert report_path.exists()

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["remote_closed_local_open_mismatches"] == 1
    assert report_payload["status"] == "drift_detected"
    assert report_payload["unmatched_open_positions"]["delta_remote_minus_local"] == -2

    with sqlite3.connect(db_path) as conn:
        open_count = conn.execute("SELECT COUNT(*) FROM wallet_open_positions").fetchone()[0]
        closed_count = conn.execute("SELECT COUNT(*) FROM wallet_closed_positions").fetchone()[0]
        trade_recon_count = conn.execute("SELECT COUNT(*) FROM wallet_trade_reconciliation").fetchone()[0]
    assert open_count == 1
    assert closed_count == 2
    assert trade_recon_count == 4


def test_reconcile_to_sqlite_can_backfill_closed_trades_and_purge_phantoms(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "jj_trades.db"
    _seed_trades(db_path)

    reconciler = PolymarketWalletReconciler(session=FakeSession([]))
    summary = reconciler.reconcile_to_sqlite(
        user_address="0xabc",
        db_path=db_path,
        open_positions=[
            {
                "conditionId": "0xcond1",
                "asset": "0xtoken1",
                "title": "ETH 5m",
                "outcome": "UP",
                "size": 5.0,
            }
        ],
        closed_positions=[
            {
                "conditionId": "0xcond2",
                "asset": "0xtoken2",
                "title": "SOL 5m",
                "outcome": "UP",
                "size": 5.0,
                "realizedPnl": 1.5,
                "transactionHash": "0xhash2",
                "resolvedAt": "2026-03-11T12:00:00Z",
            },
            {
                "conditionId": "0xcond3",
                "asset": "0xtoken3",
                "title": "XRP 5m",
                "outcome": "DOWN",
                "size": 4.0,
                "realizedPnl": 0.0,
                "transactionHash": "0xhash3",
            },
        ],
        apply_local_fixes=True,
        purge_phantom_open_trades=True,
    )

    assert summary.local_fixes["closed_trades_backfilled"] == 1
    assert summary.local_fixes["phantom_open_trades_deleted"] == 1
    assert summary.status == "reconciled"
    assert summary.classification_precision == 1.0
    assert summary.recommendation == "ready_for_launch_gate"

    with sqlite3.connect(db_path) as conn:
        fixed = conn.execute(
            "SELECT outcome, pnl, resolved_at FROM trades WHERE id = 'open_remote_closed'"
        ).fetchone()
        phantom = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE id = 'open_phantom'"
        ).fetchone()[0]

    assert fixed == ("won", 1.5, "2026-03-11T12:00:00Z")
    assert phantom == 0


def test_fetch_positions_retries_after_rate_limit(monkeypatch) -> None:
    session = FakeSession(
        [
            FakeResponse([], status_code=429),
            FakeResponse(
                [
                    {
                        "conditionId": "0xcond1",
                        "asset": "0xtoken1",
                        "title": "BTC 5m",
                        "size": 1.0,
                    }
                ]
            ),
        ]
    )
    reconciler = PolymarketWalletReconciler(session=session)
    monkeypatch.setattr("bot.wallet_reconciliation.time.sleep", lambda *_args, **_kwargs: None)

    rows = reconciler.fetch_open_positions("0xabc")

    assert len(rows) == 1
    assert len(session.calls) == 2


def test_cli_address_validation_rejects_placeholder_values() -> None:
    assert _looks_like_live_wallet_address("0xyourpolymarketwalletaddress") is False
    assert _looks_like_live_wallet_address("0x1234") is False
    assert _looks_like_live_wallet_address("0x" + ("ab" * 20)) is True


def test_cli_env_loader_reads_wallet_address_from_repo_env(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "IGNORED_KEY=value",
                "POLY_SAFE_ADDRESS=0x" + ("ab" * 20),
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("POLY_SAFE_ADDRESS", raising=False)
    monkeypatch.delenv("POLYMARKET_FUNDER", raising=False)

    _load_env_defaults(env_path)

    assert os.environ["POLY_SAFE_ADDRESS"] == "0x" + ("ab" * 20)


def test_open_position_inventory_separates_btc_fast_leaks_and_discretionary_book() -> None:
    open_positions = [
        {
            "conditionId": "0xbtc",
            "asset": "0xbtcasset",
            "title": "Bitcoin Up or Down - March 11, 10:10AM-10:15AM ET",
            "outcome": "Down",
            "size": 25.0,
            "initialValue": 12.0,
            "currentValue": 25.0,
            "endDate": "2026-03-11T14:15:00Z",
            "redeemable": False,
        },
        {
            "conditionId": "0xeth",
            "asset": "0xethasset",
            "title": "Ethereum Up or Down - March 11, 6:10AM-6:15AM ET",
            "outcome": "Down",
            "size": 14.0,
            "initialValue": 7.0,
            "currentValue": 5.5,
            "endDate": "2026-03-11T10:15:00Z",
            "redeemable": False,
        },
        {
            "conditionId": "0xlong",
            "asset": "0xlongasset",
            "title": "Will Harvey Weinstein be sentenced to no prison time?",
            "outcome": "Yes",
            "size": 68.39,
            "initialValue": 28.0399,
            "currentValue": 36.72543,
            "endDate": "2025-12-31",
            "redeemable": False,
        },
    ]

    btc_open_status = classify_btc_open_positions(open_positions)
    inventory = build_open_position_inventory(open_positions, btc_open_status=btc_open_status)

    assert inventory["summary"]["sleeve_counts"]["btc5_intentional"] == 1
    assert inventory["summary"]["sleeve_counts"]["non_btc_fast"] == 1
    assert inventory["summary"]["sleeve_counts"]["long_dated_discretionary"] == 1
    assert inventory["summary"]["policy_counts"]["close_only"] == 1
    assert inventory["summary"]["non_btc_fast_close_only"] is True

    eth_row = next(row for row in inventory["rows"] if row["token_id"] == "0xethasset")
    assert eth_row["sleeve"] == "non_btc_fast"
    assert eth_row["policy_state"] == "close_only"
    assert eth_row["exit_owner"] == "operator"

    long_row = next(row for row in inventory["rows"] if row["token_id"] == "0xlongasset")
    assert long_row["sleeve"] == "long_dated_discretionary"
    assert long_row["policy_state"] == "inventory_only"


def test_closed_winners_summary_orders_by_realized_pnl() -> None:
    winners = build_closed_winners_summary(
        [
            {"conditionId": "0x1", "asset": "0xa", "title": "Market A", "outcome": "Yes", "realizedPnl": 2.0},
            {"conditionId": "0x2", "asset": "0xb", "title": "Market B", "outcome": "No", "realizedPnl": 9.5},
            {"conditionId": "0x3", "asset": "0xc", "title": "Market C", "outcome": "Yes", "realizedPnl": -1.0},
        ],
        limit=2,
    )

    assert [row["title"] for row in winners] == ["Market B", "Market A"]
