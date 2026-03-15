from __future__ import annotations

from execution.shadow_order_lifecycle import ShadowOrderLifecycle, ShadowOrderState


def test_shadow_order_lifecycle_dedup_ttl_and_markouts() -> None:
    lifecycle = ShadowOrderLifecycle(ttl_seconds=2.0, expected_fill_window_seconds=1.0, markout_windows_seconds=(1, 2))
    first = lifecycle.place_synthetic_order(
        market_id="m1",
        side="buy_yes",
        reference_price=0.50,
        size_usd=5.0,
        expected_fill_probability=0.6,
        now_ts=100.0,
    )
    assert first is not None

    # Duplicate active order on same market+side should be deduped.
    dup = lifecycle.place_synthetic_order(
        market_id="m1",
        side="buy_yes",
        reference_price=0.49,
        size_usd=5.0,
        expected_fill_probability=0.6,
        now_ts=101.0,
    )
    assert dup is None

    markout_updates = lifecycle.record_markouts(now_ts=101.5, market_prices={"m1": 0.52})
    assert markout_updates == 1
    assert "1s" in first.markouts_bps

    expired = lifecycle.expire(now_ts=103.0)
    assert expired == 1
    assert first.state == ShadowOrderState.EXPIRED
    assert first.cancelled_reason == "ttl_expired"

    report = lifecycle.to_report()
    assert report["orders_total"] == 1
    assert report["states"]["expired"] == 1
