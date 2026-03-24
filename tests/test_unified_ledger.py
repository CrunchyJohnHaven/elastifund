"""Tests for unified trade ledger."""
import os
import tempfile
import pytest
from bot.unified_ledger import UnifiedLedger, TradeRecord, OrderStatus


@pytest.fixture
def ledger(tmp_path):
    db_path = str(tmp_path / "test_ledger.db")
    return UnifiedLedger(db_path=db_path)


def test_record_and_retrieve_trade(ledger):
    trade = TradeRecord(
        trade_id="test-001",
        instance_id="btc5_maker",
        market_id="mkt-123",
        token_id="tok-456",
        direction="DOWN",
        side="BUY",
        order_price=0.52,
        order_size=10.0,
        order_status="placed",
        strategy_name="btc5_maker",
    )
    ledger.record_trade(trade)
    trades = ledger.get_trades(instance_id="btc5_maker")
    assert len(trades) == 1
    assert trades[0]["direction"] == "DOWN"
    assert trades[0]["order_price"] == 0.52


def test_record_fill_updates_trade(ledger):
    trade = TradeRecord(
        trade_id="test-002",
        instance_id="btc5_maker",
        market_id="mkt-123",
        token_id="tok-456",
        order_size=10.0,
        order_status="placed",
    )
    ledger.record_trade(trade)
    ledger.record_fill("test-002", "order-abc", 0.51, 5.0, "2026-03-24T12:00:00Z")

    trades = ledger.get_trades()
    assert trades[0]["order_status"] == "partially_filled"
    assert trades[0]["fill_size"] == 5.0

    ledger.record_fill("test-002", "order-abc", 0.52, 5.0, "2026-03-24T12:00:01Z")
    trades = ledger.get_trades()
    assert trades[0]["order_status"] == "filled"
    assert trades[0]["fill_size"] == 10.0


def test_skip_logging(ledger):
    ledger.record_skip("btc5_maker", "skip_delta_too_large", delta_value=0.0180)
    ledger.record_skip("btc5_maker", "skip_tod_suppressed", skip_detail="Hour 2 ET")
    ledger.record_skip("btc5_maker", "skip_delta_too_large", delta_value=0.0200)

    stats = ledger.get_skip_stats("btc5_maker", hours=1)
    assert stats["skip_delta_too_large"] == 2
    assert stats["skip_tod_suppressed"] == 1


def test_pnl_summary(ledger):
    for i, outcome in enumerate(["WIN", "WIN", "LOSS"]):
        trade = TradeRecord(
            trade_id=f"pnl-{i}",
            instance_id="btc5_maker",
            market_id=f"mkt-{i}",
            token_id=f"tok-{i}",
            order_status="filled",
            resolution_outcome=outcome,
            realized_pnl=10.0 if outcome == "WIN" else -5.0,
            fees_paid=0.0,
        )
        ledger.record_trade(trade)

    summary = ledger.get_pnl_summary("btc5_maker")
    assert summary["wins"] == 2
    assert summary["losses"] == 1
    assert summary["win_rate"] == pytest.approx(0.6667, abs=0.01)
    assert summary["total_realized_pnl"] == 15.0


def test_fingerprint_dedup(ledger):
    trade = TradeRecord(
        trade_id="dedup-001",
        instance_id="btc5_maker",
        market_id="mkt-123",
        token_id="tok-456",
    )
    fp = trade.compute_fingerprint()
    assert len(fp) == 16
    # Same inputs = same fingerprint
    trade2 = TradeRecord(
        trade_id="dedup-001",
        instance_id="btc5_maker",
        market_id="mkt-123",
        token_id="tok-456",
    )
    assert trade2.compute_fingerprint() == fp


def test_reconcile_from_wallet(ledger):
    # Pre-existing trade
    trade = TradeRecord(
        trade_id="existing-001",
        instance_id="btc5_maker",
        market_id="btc-5min",
        token_id="tok-match",
        condition_id="cond-match",
    )
    ledger.record_trade(trade)

    wallet_positions = [
        {"condition_id": "cond-match", "token_id": "tok-match", "size": "10", "avgPrice": "0.52"},
        {"condition_id": "cond-new", "token_id": "tok-new", "size": "5", "avgPrice": "0.48", "market_slug": "some-market"},
    ]
    result = ledger.reconcile_from_wallet(wallet_positions)
    assert result["matched"] == 1
    assert result["backfilled"] == 1

    all_trades = ledger.get_trades()
    assert len(all_trades) == 2
