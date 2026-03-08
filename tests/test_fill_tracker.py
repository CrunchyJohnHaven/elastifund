import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.fill_tracker import FillTracker


def test_fill_tracker_summary_computes_fill_rate_latency_and_buckets(tmp_path: Path) -> None:
    tracker = FillTracker(
        db_path=tmp_path / "jj_trades.db",
        report_path=tmp_path / "fill_rate_report.md",
    )

    tracker.record_order(
        order_id="ord-1",
        market_id="mkt-1",
        token_id="tok-1",
        question="Will policy pass?",
        category="politics",
        side="BUY",
        direction="buy_yes",
        price=0.45,
        size=10.0,
        size_usd=4.50,
        order_type="maker",
    )
    tracker.record_order(
        order_id="ord-2",
        market_id="mkt-2",
        token_id="tok-2",
        question="Will it rain?",
        category="weather",
        side="BUY",
        direction="buy_no",
        price=0.65,
        size=5.0,
        size_usd=3.25,
        order_type="maker",
    )
    tracker.record_order(
        order_id="ord-3",
        market_id="mkt-3",
        token_id="tok-3",
        question="Will inflation print hot?",
        category="politics",
        side="BUY",
        direction="buy_yes",
        price=0.15,
        size=6.0,
        size_usd=0.90,
        order_type="maker",
    )

    tracker.record_fill(
        order_id="ord-1",
        market_id="mkt-1",
        token_id="tok-1",
        fill_price=0.45,
        fill_size=10.0,
        fill_size_usd=4.50,
        latency_seconds=300.0,
        cumulative_size_matched=10.0,
        status="filled",
    )
    tracker.record_fill(
        order_id="ord-2",
        market_id="mkt-2",
        token_id="tok-2",
        fill_price=0.65,
        fill_size=2.0,
        fill_size_usd=1.30,
        latency_seconds=600.0,
        cumulative_size_matched=2.0,
        status="partially_filled",
    )
    tracker.mark_cancelled("ord-3", reason="stale_order")

    summary = tracker.get_summary(hours=24)

    assert summary["total_orders"] == 3
    assert summary["filled_orders"] == 2
    assert summary["cancelled_orders"] == 1
    assert summary["stale_cancelled"] == 1
    assert round(summary["fill_rate"], 2) == 0.67
    assert summary["median_fill_latency_seconds"] == 450.0

    politics = summary["fill_rate_by_market_category"]["politics"]
    weather = summary["fill_rate_by_market_category"]["weather"]
    assert politics["orders"] == 2
    assert politics["filled"] == 1
    assert weather["orders"] == 1
    assert weather["filled"] == 1

    assert summary["fill_rate_by_price_level"]["0.10-0.19"]["orders"] == 1
    assert summary["fill_rate_by_price_level"]["0.40-0.49"]["filled"] == 1
    assert summary["fill_rate_by_price_level"]["0.60-0.69"]["filled"] == 1

    report_path = tracker.write_report(hours=24)
    assert report_path.exists()
    assert "Fill rate: 66.7%" in report_path.read_text()
    tracker.close()


def test_reconcile_open_orders_cancels_stale_unfilled_orders(tmp_path: Path) -> None:
    tracker = FillTracker(
        db_path=tmp_path / "jj_trades.db",
        report_path=tmp_path / "fill_rate_report.md",
    )
    placed_at = datetime.now(timezone.utc) - timedelta(hours=3)
    tracker.record_order(
        order_id="ord-stale",
        market_id="mkt-stale",
        token_id="tok-stale",
        question="Will this order ever fill?",
        category="unknown",
        side="BUY",
        direction="buy_yes",
        price=0.42,
        size=5.0,
        size_usd=2.10,
        order_type="maker",
        placed_at=placed_at,
    )

    cancelled: list[str] = []

    result = tracker.reconcile_open_orders(
        fetch_order=lambda order_id: {
            "status": "live",
            "original_size": "5.0",
            "size_matched": "0.0",
            "price": "0.42",
        },
        cancel_order=lambda order_id: cancelled.append(order_id) or True,
        max_order_age_hours=2.0,
        now=datetime.now(timezone.utc),
    )

    assert result.orders_checked == 1
    assert result.fills_detected == 0
    assert result.stale_cancelled == 1
    assert result.stale_order_ids == ("ord-stale",)
    assert cancelled == ["ord-stale"]

    status = tracker.conn.execute(
        "SELECT status, cancel_reason FROM orders WHERE order_id = ?",
        ("ord-stale",),
    ).fetchone()
    assert dict(status) == {"status": "cancelled", "cancel_reason": "stale_order"}
    tracker.close()
