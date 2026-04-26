from __future__ import annotations

import scripts.run_btc5_micro_edge_paper_search as micro


def test_parse_candidate_id_extracts_profile() -> None:
    candidate = micro._parse_candidate(
        "btc5:policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.50"
    )
    assert candidate is not None
    assert candidate.session_name == "open_et"
    assert candidate.max_abs_delta == 0.00015
    assert candidate.up_max_buy_price == 0.51
    assert candidate.down_max_buy_price == 0.50


def test_evaluate_candidate_blocks_known_loss_cluster() -> None:
    candidate = micro.CandidateProfile(
        session_name="open_et",
        max_abs_delta=0.00005,
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
    )
    rows = [
        {
            "window_start_ts": 1773997500,
            "direction": "UP",
            "order_price": 0.48,
            "delta": 0.00003,
            "session_name": "open_et",
            "price_bucket": "lt_0.49",
            "delta_bucket": "le_0.00005",
            "filled": 1,
            "order_status": "live_filled",
            "trade_size_usd": 5.0,
            "pnl_usd": 2.25,
        },
        {
            "window_start_ts": 1773997800,
            "direction": "UP",
            "order_price": 0.48,
            "delta": 0.00003,
            "session_name": "open_et",
            "price_bucket": "lt_0.49",
            "delta_bucket": "le_0.00005",
            "filled": 1,
            "order_status": "live_filled",
            "trade_size_usd": 5.0,
            "pnl_usd": 1.25,
        },
    ]
    result = micro._evaluate_candidate(candidate, rows, min_filled=2)
    assert result["filled_rows"] == 2
    assert result["loss_cluster_hits"] == 2
    assert result["recommendation"] == "cluster_blocked"


def test_evaluate_candidate_accepts_positive_non_cluster_candidate() -> None:
    candidate = micro.CandidateProfile(
        session_name="hour_et_11",
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
    )
    rows = [
        {
            "window_start_ts": 1774005000,
            "direction": "DOWN",
            "order_price": 0.49,
            "delta": 0.00012,
            "session_name": "hour_et_11",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "0.00010_to_0.00015",
            "filled": 1,
            "order_status": "live_filled",
            "trade_size_usd": 5.0,
            "pnl_usd": 4.2,
        },
        {
            "window_start_ts": 1774005300,
            "direction": "DOWN",
            "order_price": 0.49,
            "delta": 0.00011,
            "session_name": "hour_et_11",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "0.00010_to_0.00015",
            "filled": 1,
            "order_status": "live_filled",
            "trade_size_usd": 5.0,
            "pnl_usd": 1.8,
        },
    ]
    result = micro._evaluate_candidate(candidate, rows, min_filled=2)
    assert result["filled_rows"] == 2
    assert result["loss_cluster_hits"] == 0
    assert result["pnl_usd"] == 6.0
    assert result["recommendation"] == "paper_candidate"


def test_evaluate_candidate_marks_inactive_recent_regime_for_strong_historical_seed() -> None:
    candidate = micro.CandidateProfile(
        session_name="open_et",
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
        historical_ranking_score=97.1641,
        historical_validation_rows=130,
        evidence_band="validated",
        deployment_class="validated_btc5_live_candidate",
    )
    rows = [
        {
            "window_start_ts": 1773997500,
            "direction": "UP",
            "order_price": 0.48,
            "delta": 0.00030,
            "session_name": "open_et",
            "filled": 0,
            "order_status": "skip_probe_confirmation_mismatch",
            "trade_size_usd": 0.0,
            "pnl_usd": 0.0,
        },
        {
            "window_start_ts": 1773997800,
            "direction": "DOWN",
            "order_price": 0.49,
            "delta": 0.00028,
            "session_name": "open_et",
            "filled": 0,
            "order_status": "skip_delta_too_large",
            "trade_size_usd": 0.0,
            "pnl_usd": 0.0,
        },
    ]
    result = micro._evaluate_candidate(candidate, rows, min_filled=2)
    assert result["session_rows"] == 2
    assert result["delta_eligible_rows"] == 0
    assert result["historical_validation_rows"] == 130
    assert result["recommendation"] == "inactive_recent_regime"


def test_evaluate_candidate_marks_single_positive_fill_as_watch_candidate() -> None:
    candidate = micro.CandidateProfile(
        session_name="hour_et_15",
        max_abs_delta=0.00110,
        up_max_buy_price=0.51,
        down_max_buy_price=0.47,
        source="recent_profitable_local",
        historical_validation_rows=1,
    )
    rows = [
        {
            "window_start_ts": 1774292700,
            "direction": "DOWN",
            "order_price": 0.47,
            "delta": -0.0010683333,
            "session_name": "hour_et_15",
            "price_bucket": "lt_0.49",
            "delta_bucket": "gt_0.00015",
            "filled": 1,
            "order_status": "live_filled",
            "trade_size_usd": 7.7973,
            "pnl_usd": 8.7927,
        }
    ]
    result = micro._evaluate_candidate(candidate, rows, min_filled=2)
    assert result["filled_rows"] == 1
    assert result["pnl_usd"] == 8.7927
    assert result["recommendation"] == "watch_candidate"
