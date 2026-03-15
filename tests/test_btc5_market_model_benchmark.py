from __future__ import annotations

from datetime import datetime
from pathlib import Path

from benchmarks.btc5_market.v1.benchmark import (
    BENCHMARK_VERSION,
    IMMUTABLE_RUNNER_PATHS,
    SIMULATOR_LOSS_FORMULA,
    freeze_benchmark_from_rows,
    run_benchmark,
    verify_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_rows(count: int = 320) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start_ts = 1_773_057_000
    for index in range(count):
        direction = "DOWN" if index % 3 else "UP"
        session_name = "open_et" if index % 4 < 2 else "late_et"
        price_bucket = "0.49_to_0.51" if index % 5 else "lt_0.49"
        delta_bucket = "le_0.00005" if index % 2 else "gt_0.00010"
        live_fill = (index % 6) not in {0, 5}
        positive_regime = direction == "DOWN" and session_name == "open_et"
        pnl_usd = 0.0
        trade_size_usd = 10.0 if live_fill else 0.0
        if live_fill:
            pnl_usd = 1.2 if positive_regime else -0.9
        rows.append(
            {
                "id": index + 1,
                "window_start_ts": start_ts + (index * 300),
                "slug": f"btc-window-{index:04d}",
                "direction": direction,
                "delta": 0.00012 if direction == "UP" else -0.00008,
                "abs_delta": 0.00012 if direction == "UP" else 0.00008,
                "order_price": 0.50 if price_bucket == "0.49_to_0.51" else 0.48,
                "price_bucket": price_bucket,
                "delta_bucket": delta_bucket,
                "trade_size_usd": trade_size_usd,
                "won": bool(positive_regime),
                "pnl_usd": pnl_usd,
                "realized_pnl_usd": pnl_usd,
                "order_status": "live_filled" if live_fill else "skip_price_outside_guardrails",
                "et_hour": 9 if session_name == "open_et" else 16,
                "session_name": session_name,
                "best_bid": 0.49,
                "best_ask": 0.51,
                "open_price": 84_000.0,
                "current_price": 84_012.0,
                "edge_tier": "high" if positive_regime else "medium",
                "session_policy_name": session_name,
                "effective_stage": 1,
                "loss_cluster_suppressed": 0,
                "source": "synthetic",
            }
        )
    return rows


def test_run_benchmark_is_deterministic_on_frozen_manifest(tmp_path: Path) -> None:
    manifest = freeze_benchmark_from_rows(_synthetic_rows(), benchmark_dir=tmp_path / "benchmarks")
    checks = verify_manifest(manifest)

    packet_one = run_benchmark(tmp_path / "benchmarks" / "manifest.json", candidate_path=ROOT / "btc5_market_model_candidate.py")
    packet_two = run_benchmark(tmp_path / "benchmarks" / "manifest.json", candidate_path=ROOT / "btc5_market_model_candidate.py")

    assert checks[0]["rows"] == 320
    assert manifest["version"] == BENCHMARK_VERSION
    assert manifest["objective"]["formula"] == SIMULATOR_LOSS_FORMULA
    assert manifest["immutable_runner_paths"] == list(IMMUTABLE_RUNNER_PATHS)
    epoch_started = datetime.fromisoformat(manifest["epoch"]["epoch_started_at_utc"].replace("Z", "+00:00"))
    epoch_expires = datetime.fromisoformat(manifest["epoch"]["epoch_expires_at_utc"].replace("Z", "+00:00"))
    assert (epoch_expires - epoch_started).total_seconds() == 24 * 3600
    assert packet_one["epoch"]["benchmark_rows"] == 288
    assert packet_one["benchmark_version"] == BENCHMARK_VERSION
    assert packet_one["dataset"]["warmup_rows"] == 32
    assert packet_one["metrics"]["simulator_loss"] == packet_two["metrics"]["simulator_loss"]
    assert packet_one["metrics"]["p95_drawdown_mae_pct"] == packet_two["metrics"]["p95_drawdown_mae_pct"]
    assert packet_one["candidate_model_name"] == "empirical_backoff_v1"
    assert "best_bid" in packet_one["dataset"]["feature_fields"]
