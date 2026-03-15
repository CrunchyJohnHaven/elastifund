from __future__ import annotations

from datetime import datetime
import json

from kalshi.weather_simulator import (
    DecisionSnapshot,
    StationHistory,
    build_decision_snapshots,
    build_default_scenarios,
    classify_strategy,
    load_histories,
    resolve_contract,
    run_scenarios,
)


def test_resolve_contract_supports_range_and_above():
    assert resolve_contract("range", 64.0, 65.0, 64.0) is True
    assert resolve_contract("range", 64.0, 65.0, 66.0) is False
    assert resolve_contract("above", 70.0, None, 70.0) is True
    assert resolve_contract("above", 70.0, None, 69.0) is False


def test_classify_strategy_maps_contract_styles():
    assert classify_strategy(contract_family="above", side="yes", order_probability=0.40, tail_yes_max_price=0.20) == "binary_threshold"
    assert classify_strategy(contract_family="range", side="no", order_probability=0.55, tail_yes_max_price=0.20) == "range_fade"
    assert classify_strategy(contract_family="range", side="yes", order_probability=0.12, tail_yes_max_price=0.20) == "range_tail_yes"
    assert classify_strategy(contract_family="range", side="yes", order_probability=0.33, tail_yes_max_price=0.20) is None


def test_build_decision_snapshots_uses_max_observed_before_cutoff():
    history = StationHistory(
        station_code="NYC",
        city_code="NYC",
        display_name="NYC",
        ticker_prefix="KXHIGHNY",
        hourly_by_day={
            "2026-03-01": [
                (datetime(2026, 3, 1, 17, 0), 65.0),
                (datetime(2026, 3, 1, 19, 0), 66.0),
                (datetime(2026, 3, 1, 21, 0), 69.0),
            ]
        },
        official_high_by_day={"2026-03-01": 70.0},
    )

    snapshots = build_decision_snapshots(history, decision_hour_utc=20)

    assert len(snapshots) == 1
    assert snapshots[0] == DecisionSnapshot(
        station_code="NYC",
        city_code="NYC",
        display_name="NYC",
        ticker_prefix="KXHIGHNY",
        target_date="2026-03-01",
        decision_hour_utc=20,
        observed_max_f=66.0,
        final_high_f=70.0,
    )


def test_run_scenarios_builds_report_from_repo_fixture():
    histories = load_histories()
    scenarios = build_default_scenarios(
        decision_hours_utc=[20],
        market_std_multipliers=[1.15],
        max_signals_per_day=1,
    )

    report = run_scenarios(histories, scenarios)

    assert report["simulation_type"] == "weather_scenario_simulation"
    assert report["recommended_strategy"] in {"range_fade", "range_tail_yes", "binary_threshold"}
    assert set(report["robustness_summary"]) == {"range_fade", "range_tail_yes", "binary_threshold"}
    assert len(report["scenario_summaries"]) == 3
    assert any(item["strategy"] == "binary_threshold" and item["trades"] > 0 for item in report["scenario_summaries"])
    assert set(report["operator_guidance"]) == {
        "recommended_contract_family",
        "rationale",
        "decision_hour_utc",
        "uncertainty_regime",
        "paper_trade_parameters",
        "range_contracts_secondary",
    }
    assert report["operator_guidance"]["range_contracts_secondary"] is True
    assert report["operator_guidance"]["recommended_contract_family"] in {None, "binary_threshold"}


def test_run_scenarios_includes_forecast_archive_and_settlement_matching(tmp_path):
    histories = load_histories()
    scenarios = build_default_scenarios(
        decision_hours_utc=[20],
        market_std_multipliers=[1.15],
        max_signals_per_day=1,
    )
    forecast_archive = tmp_path / "forecast_archive.jsonl"
    forecast_archive.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "captured_at": "2026-03-09T19:00:00+00:00",
                        "city": "NYC",
                        "target_date": "2026-03-10",
                        "high_temp_f": 61.0,
                        "pop_probability": 0.3,
                        "source_period": "Tonight",
                    }
                ),
                json.dumps(
                    {
                        "captured_at": "2026-03-09T20:00:00+00:00",
                        "city": "NYC",
                        "target_date": "2026-03-10",
                        "high_temp_f": 62.0,
                        "pop_probability": 0.35,
                        "source_period": "Overnight",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    decisions_log = tmp_path / "decisions.jsonl"
    decisions_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "market_ticker": "KXHIGHNY-26MAR10-A62",
                        "side": "yes",
                        "execution_mode": "paper",
                        "execution_result": "paper",
                        "order_client_id": "cid-match",
                    }
                ),
                json.dumps(
                    {
                        "market_ticker": "KXHIGHNY-26MAR10-A64",
                        "side": "no",
                        "execution_mode": "paper",
                        "execution_result": "paper",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settlement_log = tmp_path / "settlements.jsonl"
    settlement_log.write_text(
        json.dumps(
            {
                "order_client_id": "cid-match",
                "market_ticker": "KXHIGHNY-26MAR10-A62",
                "side": "yes",
                "result": "yes",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_scenarios(
        histories,
        scenarios,
        forecast_archive_path=forecast_archive,
        decisions_log_path=decisions_log,
        settlement_log_path=settlement_log,
    )

    assert report["forecast_replay"]["snapshot_rows"] == 2
    assert report["forecast_replay"]["city_date_pairs"] == 1
    assert len(report["forecast_replay"]["latest_replayable_snapshots"]) == 1
    assert report["settlement_reconciliation"]["total_executed_decisions"] == 2
    assert report["settlement_reconciliation"]["matched_settlements"] == 1
    assert report["settlement_reconciliation"]["unmatched_settlements"] == 1
