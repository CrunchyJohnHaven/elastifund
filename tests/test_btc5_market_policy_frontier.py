from __future__ import annotations

from pathlib import Path

from scripts import btc5_market_policy_frontier as frontier


def test_build_frontier_report_ranks_market_backed_candidates(monkeypatch, tmp_path: Path) -> None:
    cycle_payload = {
        "generated_at": "2026-03-11T23:17:08+00:00",
        "active_runtime_package": {
            "profile": {"name": "current_live_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.5, "down_max_buy_price": 0.51},
            "session_policy": [],
        },
        "selected_active_runtime_package": {
            "profile": {"name": "current_live_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.5, "down_max_buy_price": 0.51},
            "session_policy": [],
        },
        "selected_best_runtime_package": {
            "profile": {"name": "policy-beta", "max_abs_delta": 0.0001, "up_max_buy_price": 0.51, "down_max_buy_price": 0.5},
            "session_policy": [],
        },
        "package_ranking": {
            "ranked_packages": [
                {
                    "runtime_package": {
                        "profile": {"name": "policy-alpha", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
                        "session_policy": [],
                    }
                },
                {
                    "runtime_package": {
                        "profile": {"name": "policy-beta", "max_abs_delta": 0.0001, "up_max_buy_price": 0.51, "down_max_buy_price": 0.5},
                        "session_policy": [],
                    }
                },
            ]
        },
    }

    losses = {
        "current_live_profile": -52000.0,
        "policy-alpha": -56000.0,
        "policy-beta": -54000.0,
    }

    def fake_evaluate(runtime_package, *, handoff_path, market_latest_path):
        profile_name = runtime_package["profile"]["name"]
        return {
            "evaluation_source": "market_champion_replay",
            "market_model_version": "7:market-hash",
            "simulator_champion_id": 7,
            "market_epoch_id": "epoch-1",
            "fold_results": [
                {"fold_id": "fold_1", "policy_loss": losses[profile_name] + 100.0},
                {"fold_id": "fold_2", "policy_loss": losses[profile_name] - 100.0},
            ],
            "confidence_summary": {
                "fold_count": 2,
                "mean_fold_policy_loss": losses[profile_name],
            },
            "policy_benchmark": {
                "policy_loss": losses[profile_name],
                "median_30d_return_pct": 1000.0,
                "p05_30d_return_pct": 900.0,
                "fill_retention_ratio": 1.0,
            },
        }

    monkeypatch.setattr(frontier, "evaluate_runtime_package_against_market", fake_evaluate)
    monkeypatch.setattr(
        frontier,
        "load_market_policy_handoff",
        lambda **_: {"market_model_version": "7:market-hash"},
    )

    payload = frontier.build_frontier_report(
        cycle_payload=cycle_payload,
        market_policy_handoff=tmp_path / "handoff.json",
        market_latest_json=tmp_path / "market_latest.json",
    )

    assert payload["incumbent_policy_id"] == "current_live_profile"
    assert payload["selected_policy_id"] == "policy-beta"
    assert payload["best_market_policy_id"] == "policy-alpha"
    assert payload["loss_improvement_vs_incumbent"] == 4000.0
    assert payload["selected_loss_gap_vs_best"] == 2000.0
    assert payload["beats_incumbent_by_keep_epsilon"] is True
    assert payload["current_market_model_version"] == "7:market-hash"
    assert payload["selection_recommendation"]["policy_id"] == "policy-alpha"
    assert payload["ranked_policies"][0]["fold_win_rate_vs_incumbent"] == 1.0
    assert payload["ranked_policies"][0]["confidence_method"] == "bootstrap_mean_fold_loss_improvement_v1"
    assert [item["policy_id"] for item in payload["ranked_policies"]] == [
        "policy-alpha",
        "policy-beta",
        "current_live_profile",
    ]


def test_build_frontier_report_filters_stale_market_model_versions(monkeypatch, tmp_path: Path) -> None:
    cycle_payload = {
        "generated_at": "2026-03-11T23:17:08+00:00",
        "active_runtime_package": {
            "profile": {"name": "current_live_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.5, "down_max_buy_price": 0.51},
            "session_policy": [],
        },
        "package_ranking": {
            "ranked_packages": [
                {
                    "runtime_package": {
                        "profile": {"name": "current_live_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.5, "down_max_buy_price": 0.51},
                        "session_policy": [],
                    }
                },
                {
                    "runtime_package": {
                        "profile": {"name": "stale-policy", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
                        "session_policy": [],
                    }
                },
            ]
        },
    }

    def fake_evaluate(runtime_package, *, handoff_path, market_latest_path):
        profile_name = runtime_package["profile"]["name"]
        return {
            "evaluation_source": "market_champion_replay",
            "market_model_version": "7:market-hash" if profile_name == "current_live_profile" else "6:old-market-hash",
            "simulator_champion_id": 7,
            "market_epoch_id": "epoch-1",
            "fold_results": [
                {"fold_id": "fold_1", "policy_loss": -52000.0 if profile_name == "current_live_profile" else -56000.0},
            ],
            "policy_benchmark": {
                "policy_loss": -52000.0 if profile_name == "current_live_profile" else -56000.0,
                "median_30d_return_pct": 1000.0,
                "p05_30d_return_pct": 900.0,
                "fill_retention_ratio": 1.0,
            },
        }

    monkeypatch.setattr(frontier, "evaluate_runtime_package_against_market", fake_evaluate)
    monkeypatch.setattr(
        frontier,
        "load_market_policy_handoff",
        lambda **_: {"market_model_version": "7:market-hash"},
    )

    payload = frontier.build_frontier_report(
        cycle_payload=cycle_payload,
        market_policy_handoff=tmp_path / "handoff.json",
        market_latest_json=tmp_path / "market_latest.json",
    )

    assert [item["policy_id"] for item in payload["ranked_policies"]] == ["current_live_profile"]
    assert [item["policy_id"] for item in payload["stale_ranked_policies"]] == ["stale-policy"]
