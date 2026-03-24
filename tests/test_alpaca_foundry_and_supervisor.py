from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.lane_supervisor import run_supervisor  # noqa: E402
from bot.thesis_foundry import build_thesis_candidates  # noqa: E402


def test_foundry_includes_alpaca_lane(tmp_path: Path) -> None:
    alpaca_lane = tmp_path / "alpaca_lane.json"
    alpaca_lane.write_text(
        json.dumps(
            {
                "artifact": "alpaca_crypto_lane",
                "generated_at": "2026-03-23T00:00:00Z",
                "candidate_rows": [
                    {
                        "symbol": "BTC/USD",
                        "variant_id": "btcusd_momo_1",
                        "side": "buy",
                        "rank_score": 0.021,
                        "expected_edge_bps": 120.0,
                        "prob_positive": 0.71,
                        "recommended_notional_usd": 25.0,
                        "hold_bars": 15,
                        "stop_loss_bps": 70.0,
                        "take_profit_bps": 150.0,
                        "last_price": 90000.0,
                        "execution_mode": "paper",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_thesis_candidates(
        weather_shadow_path=tmp_path / "missing_weather.json",
        alpaca_lane_path=alpaca_lane,
        btc5_autoresearch_path=tmp_path / "missing_btc5.json",
        now=datetime(2026, 3, 23, tzinfo=timezone.utc),
    )

    lanes = {row["lane"] for row in payload["candidates"]}
    assert "alpaca" in lanes
    thesis = next(row for row in payload["candidates"] if row["lane"] == "alpaca")
    assert thesis["ticker"] == "BTC/USD"
    assert thesis["execution_mode"] == "paper"


def test_supervisor_routes_alpaca_candidates(tmp_path: Path) -> None:
    thesis_path = tmp_path / "thesis_candidates.json"
    thesis_path.write_text(
        json.dumps(
            {
                "artifact": "thesis_candidates.v1",
                "generated_at": "2026-03-23T00:00:00Z",
                "candidates": [
                    {
                        "thesis_id": "alpaca:BTC/USD:btcusd_momo_1",
                        "lane": "alpaca",
                        "venue": "alpaca",
                        "ticker": "BTC/USD",
                        "side": "buy",
                        "execution_mode": "paper",
                        "rank_score": 0.025,
                        "spread_adjusted_edge": 0.012,
                        "expected_edge_bps": 120.0,
                        "prob_positive": 0.70,
                        "recommended_notional_usd": 25.0,
                        "variant_id": "btcusd_momo_1",
                        "hold_bars": 15,
                        "stop_loss_bps": 70.0,
                        "take_profit_bps": 150.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    queue_path = tmp_path / "alpaca_queue.jsonl"
    output_path = tmp_path / "supervisor.json"

    payload = run_supervisor(
        thesis_path=thesis_path,
        output_path=output_path,
        alpaca_queue_path=queue_path,
        route_weather=False,
        route_alpaca=True,
    )

    assert payload["alpaca_candidates_routed"] == 1
    queued = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert queued
    assert queued[0]["ticker"] == "BTC/USD"
    assert queued[0]["variant_id"] == "btcusd_momo_1"
