from __future__ import annotations

import json
from pathlib import Path

from scripts.run_btc5_dual_sided_maker_shadow import (
    _extract_best_quote,
    build_shadow_payload,
    main,
)


def test_extract_best_quote_uses_best_prices_not_first_levels() -> None:
    quote = _extract_best_quote(
        {
            "bids": [
                {"price": "0.01", "size": "10"},
                {"price": "0.48", "size": "5"},
                {"price": "0.50", "size": "2"},
            ],
            "asks": [
                {"price": "0.99", "size": "10"},
                {"price": "0.51", "size": "4"},
                {"price": "0.60", "size": "5"},
            ],
        }
    )
    assert quote["best_bid"] == 0.5
    assert quote["best_bid_size"] == 2.0
    assert quote["best_ask"] == 0.51
    assert quote["best_ask_size"] == 4.0


def test_build_shadow_payload_blocks_when_combined_bid_cost_has_no_edge() -> None:
    registry_payload = {
        "registry": [
            {
                "eligible": True,
                "asset": "btc",
                "timeframe": "5m",
                "market_id": "m1",
                "question": "BTC 5m",
                "yes_token_id": "yes",
                "no_token_id": "no",
                "timeframe_minutes": 5,
                "quote_fetched_at": "2026-03-12T14:00:00+00:00",
            }
        ]
    }
    book_map = {
        "yes": {
            "bids": [{"price": "0.50", "size": "10"}],
            "asks": [{"price": "0.51", "size": "10"}],
        },
        "no": {
            "bids": [{"price": "0.50", "size": "10"}],
            "asks": [{"price": "0.51", "size": "10"}],
        },
    }
    payload = build_shadow_payload(
        registry_payload=registry_payload,
        runtime_truth={"launch_posture": "clear", "execution_mode": "live"},
        finance_latest={"finance_gate_pass": True},
        bankroll_usd=247.0,
        combined_cost_cap=0.97,
        max_toxicity=0.35,
        min_liquidity_usd=10.0,
        max_spread=0.25,
        reserve_pct=0.20,
        per_market_floor_usd=5.0,
        per_market_cap_usd=10.0,
        max_markets=6,
        timeout_seconds=120,
        book_fetcher=lambda token_id: book_map[token_id],
    )
    assert payload["ranked_candidate_count"] == 0
    assert "combined_bid_cost_above_cap" in payload["block_reasons"]
    assert payload["one_next_cycle_action"] == "wait_for_tighter_books_or_more_liquidity"
    sensitivity = payload["combined_cost_cap_sensitivity"]
    assert sensitivity[0]["combined_cost_cap"] == 0.97
    assert sensitivity[0]["ranked_candidate_count"] == 0
    assert sensitivity[2]["combined_cost_cap"] == 0.99
    assert sensitivity[2]["ranked_candidate_count"] == 0


def test_main_writes_shadow_payload_from_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    runtime_truth_path = tmp_path / "runtime_truth.json"
    finance_path = tmp_path / "finance.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry": [
                    {
                        "eligible": True,
                        "asset": "btc",
                        "timeframe": "5m",
                        "market_id": "m1",
                        "question": "BTC 5m",
                        "yes_token_id": "yes",
                        "no_token_id": "no",
                        "timeframe_minutes": 5,
                        "quote_fetched_at": "2026-03-12T14:00:00+00:00",
                    }
                ]
            }
        )
    )
    runtime_truth_path.write_text(json.dumps({"launch_posture": "clear", "execution_mode": "live"}))
    finance_path.write_text(json.dumps({"finance_gate_pass": True}))

    import scripts.run_btc5_dual_sided_maker_shadow as runner

    book_map = {
        "yes": {
            "bids": [{"price": "0.47", "size": "20"}],
            "asks": [{"price": "0.48", "size": "20"}],
        },
        "no": {
            "bids": [{"price": "0.48", "size": "20"}],
            "asks": [{"price": "0.49", "size": "20"}],
        },
    }
    runner._fetch_book = lambda token_id, timeout_seconds=10.0: book_map[token_id]

    output_dir = tmp_path / "out"
    parallel_output = tmp_path / "parallel.json"
    rc = main(
        [
            "--registry-path",
            str(registry_path),
            "--runtime-truth-path",
            str(runtime_truth_path),
            "--finance-path",
            str(finance_path),
            "--output-dir",
            str(output_dir),
            "--parallel-output",
            str(parallel_output),
            "--min-liquidity-usd",
            "10",
        ]
    )
    assert rc == 0
    payload = json.loads((output_dir / "latest.json").read_text())
    assert payload["ranked_candidate_count"] == 1
    assert payload["ranked_candidates"][0]["combined_cost"] == 0.95
    assert payload["spread_intents"][0]["maker_only"] is True
    assert payload["combined_cost_cap_sensitivity"][0]["ranked_candidate_count"] == 1
    assert parallel_output.exists()


def test_cap_sensitivity_shows_when_wider_caps_unlock_candidates() -> None:
    registry_payload = {
        "registry": [
            {
                "eligible": True,
                "asset": "btc",
                "timeframe": "5m",
                "market_id": "m1",
                "question": "BTC 5m",
                "yes_token_id": "yes",
                "no_token_id": "no",
                "timeframe_minutes": 5,
                "quote_fetched_at": "2026-03-12T14:00:00+00:00",
            }
        ]
    }
    book_map = {
        "yes": {
            "bids": [{"price": "0.50", "size": "10"}],
            "asks": [{"price": "0.51", "size": "10"}],
        },
        "no": {
            "bids": [{"price": "0.49", "size": "10"}],
            "asks": [{"price": "0.50", "size": "10"}],
        },
    }
    payload = build_shadow_payload(
        registry_payload=registry_payload,
        runtime_truth={"launch_posture": "clear", "execution_mode": "live"},
        finance_latest={"finance_gate_pass": True},
        bankroll_usd=247.0,
        combined_cost_cap=0.97,
        max_toxicity=0.35,
        min_liquidity_usd=10.0,
        max_spread=0.25,
        reserve_pct=0.20,
        per_market_floor_usd=5.0,
        per_market_cap_usd=10.0,
        max_markets=6,
        timeout_seconds=120,
        book_fetcher=lambda token_id: book_map[token_id],
    )
    sensitivity = {row["combined_cost_cap"]: row["ranked_candidate_count"] for row in payload["combined_cost_cap_sensitivity"]}
    assert sensitivity[0.97] == 0
    assert sensitivity[0.98] == 0
    assert sensitivity[0.99] == 1
    assert sensitivity[1.0] == 1
