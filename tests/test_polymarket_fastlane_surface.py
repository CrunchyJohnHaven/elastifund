from __future__ import annotations

from bot.polymarket_fastlane_surface import _diagnose_empty_surface, _priority_label


def test_priority_label_prefers_btc_and_eth_intraday_order() -> None:
    assert _priority_label("Bitcoin Up or Down - Mar 09, 1:15PM ET (15m)") == (0, "btc_15m")
    assert _priority_label("Bitcoin Up or Down - Mar 09, 1:05PM ET (5m)") == (1, "btc_5m")
    assert _priority_label("Bitcoin Up or Down - March 9, 7:45AM-7:50AM ET") == (1, "btc_5m")
    assert _priority_label("Bitcoin Up or Down - March 9, 7:45AM-8:00AM ET") == (0, "btc_15m")
    assert _priority_label("Bitcoin price at 8PM UTC (4h)") == (2, "btc_4h")
    assert _priority_label("Ethereum Up or Down - next 1h") == (3, "eth_intraday")


def test_diagnose_empty_surface_flags_broken_pipeline_states() -> None:
    assert _diagnose_empty_surface(
        scanner_ok=False,
        filter_ok=True,
        join_ok=True,
        reject_reason_counts={},
    ) == ("broken_pipeline", "scanner")
    assert _diagnose_empty_surface(
        scanner_ok=True,
        filter_ok=False,
        join_ok=True,
        reject_reason_counts={},
    ) == ("broken_pipeline", "filter")
    assert _diagnose_empty_surface(
        scanner_ok=True,
        filter_ok=True,
        join_ok=False,
        reject_reason_counts={},
    ) == ("broken_pipeline", "join")


def test_diagnose_empty_surface_reports_dominant_not_tradeable_reason() -> None:
    state, reason = _diagnose_empty_surface(
        scanner_ok=True,
        filter_ok=True,
        join_ok=True,
        reject_reason_counts={
            "category_gating": 2,
            "data_quality_loss": 4,
            "wallet_sparsity": 1,
            "toxicity": 0,
            "expectancy_failure": 3,
        },
    )
    assert state == "genuinely_not_tradeable"
    assert reason == "data_quality_loss"
