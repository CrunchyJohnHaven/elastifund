from __future__ import annotations

from scripts.btc5_correlation_lab import (
    build_empirical_bayes_regime_model,
    build_experiment_catalog,
    build_feed_inventory,
)


def test_build_empirical_bayes_regime_model_ranks_positive_and_negative_regimes() -> None:
    rows = [
        {
            "session_name": "open_et",
            "direction": "DOWN",
            "price_bucket": "0.50",
            "delta_bucket": "small",
            "pnl_usd": 10.0,
        },
        {
            "session_name": "open_et",
            "direction": "DOWN",
            "price_bucket": "0.50",
            "delta_bucket": "small",
            "pnl_usd": 8.0,
        },
        {
            "session_name": "late_et",
            "direction": "UP",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "small",
            "pnl_usd": -6.0,
        },
        {
            "session_name": "late_et",
            "direction": "UP",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "small",
            "pnl_usd": -4.0,
        },
    ]

    model = build_empirical_bayes_regime_model(rows, prior_fills=2.0, limit=4)

    assert model["global_avg_pnl_usd"] == 2.0
    assert model["positive_regimes"][0]["fields"] == {
        "session_name": "open_et",
        "direction": "DOWN",
        "price_bucket": "0.50",
        "delta_bucket": "small",
    }
    assert model["positive_regimes"][0]["shrunk_avg_pnl_usd"] == 5.5
    assert model["negative_regimes"][0]["fields"] == {
        "session_name": "late_et",
        "direction": "UP",
        "price_bucket": "0.49_to_0.51",
        "delta_bucket": "small",
    }
    assert model["negative_regimes"][0]["shrunk_avg_pnl_usd"] == -1.5


def test_build_feed_inventory_uses_archive_confirmation_and_local_db(tmp_path) -> None:
    local_db_path = tmp_path / "btc5_correlation_lab_test.sqlite"
    local_db_path.write_text("ready")
    inventory = build_feed_inventory(
        signal_audit={
            "capital_ranking_support": {
                "confirmation_blocking_checks": [
                    "wallet_flow:covered_executed_window_rows 1 < required 2",
                    "lmsr:source_window_rows 0 < required 3",
                    "lmsr:join_key_window_mismatch:probe[1-2]:source[3-4]",
                ]
            }
        },
        confirmation={
            "by_source": {
                "wallet_flow": {
                    "source_window_rows": 0,
                    "covered_executed_window_rows": 0,
                },
                "lmsr": {
                    "source_window_rows": 0,
                    "covered_executed_window_rows": 0,
                },
            }
        },
        confirmation_archive={
            "by_source": {
                "wallet_flow": {
                    "source_window_rows": 4,
                    "covered_executed_window_rows": 1,
                },
                "lmsr": {
                    "source_window_rows": 0,
                    "covered_executed_window_rows": 0,
                },
            }
        },
        local_db_path=local_db_path,
    )

    inventory_by_key = {item["key"]: item for item in inventory}

    assert inventory_by_key["best_bid_ask"]["current_status"] == "ready_with_local_db"
    assert inventory_by_key["decision_tags"]["current_status"] == "ready_with_local_db"
    assert inventory_by_key["wallet_flow_confirmation"]["current_status"] == "partial_data"
    assert "archive has 4 signal windows and 1 covered executed windows" in inventory_by_key["wallet_flow_confirmation"]["notes"]
    assert inventory_by_key["lmsr_confirmation"]["current_status"] == "blocked"
    assert "lmsr:join_key_window_mismatch" in inventory_by_key["lmsr_confirmation"]["notes"]


def test_build_experiment_catalog_preserves_local_db_and_partial_data_statuses() -> None:
    feed_inventory = [
        {"key": "spot_open_delta", "current_status": "ready_now"},
        {"key": "session_time", "current_status": "ready_now"},
        {"key": "price_band", "current_status": "ready_now"},
        {"key": "best_bid_ask", "current_status": "ready_with_local_db"},
        {"key": "decision_tags", "current_status": "ready_with_local_db"},
        {"key": "wallet_flow_confirmation", "current_status": "partial_data"},
        {"key": "lmsr_confirmation", "current_status": "blocked"},
        {"key": "microstructure_gate", "current_status": "blocked"},
        {"key": "volatility_path", "current_status": "needs_persistence_upgrade"},
    ]

    catalog = build_experiment_catalog(feed_inventory)
    catalog_by_key = {item["key"]: item for item in catalog}

    assert catalog_by_key["session_direction_price_delta_sweep"]["status"] == "ready_now"
    assert catalog_by_key["book_quote_geometry"]["status"] == "ready_with_local_db"
    assert catalog_by_key["decision_and_sizing_tag_attribution"]["status"] == "ready_with_local_db"
    assert catalog_by_key["wallet_flow_confirmation_join"]["status"] == "partial_data"
    assert catalog_by_key["lmsr_confirmation_join"]["status"] == "blocked"
    assert catalog_by_key["stateful_sequence_model"]["status"] == "needs_persistence_upgrade"
