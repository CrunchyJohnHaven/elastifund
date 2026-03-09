from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.btc5_hypothesis_lab import (
    HypothesisSpec,
    build_hypothesis_specs,
    evaluate_hypothesis_walk_forward,
    priced_rows,
    summarize_hypothesis_history,
)


ET_ZONE = ZoneInfo("America/New_York")


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base = datetime(2026, 3, 1, 10, 0, tzinfo=ET_ZONE)
    row_id = 1
    for day in range(15):
        down_dt = (base + timedelta(days=day)).astimezone(timezone.utc)
        up_dt = (base + timedelta(days=day, hours=2)).astimezone(timezone.utc)
        rows.append(
            {
                "id": row_id,
                "window_start_ts": int(down_dt.timestamp()),
                "slug": f"btc-updown-5m-{row_id}",
                "direction": "DOWN",
                "delta": -0.00008,
                "abs_delta": 0.00008,
                "order_price": 0.48,
                "trade_size_usd": 5.0,
                "won": True,
                "pnl_usd": 5.2,
                "realized_pnl_usd": 5.2,
                "order_status": "live_filled",
                "updated_at": down_dt.isoformat(),
            }
        )
        row_id += 1
        rows.append(
            {
                "id": row_id,
                "window_start_ts": int(up_dt.timestamp()),
                "slug": f"btc-updown-5m-{row_id}",
                "direction": "UP",
                "delta": 0.00011,
                "abs_delta": 0.00011,
                "order_price": 0.50,
                "trade_size_usd": 5.0,
                "won": False,
                "pnl_usd": -5.0,
                "realized_pnl_usd": -5.0,
                "order_status": "live_filled",
                "updated_at": up_dt.isoformat(),
            }
        )
        row_id += 1
    rows.append(
        {
            "id": row_id,
            "window_start_ts": int((base + timedelta(days=20)).astimezone(timezone.utc).timestamp()),
            "slug": f"btc-updown-5m-{row_id}",
            "direction": "UP",
            "delta": 0.00020,
            "abs_delta": 0.00020,
            "order_price": None,
            "trade_size_usd": 0.0,
            "won": False,
            "pnl_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "order_status": "skip_price_outside_guardrails",
            "updated_at": (base + timedelta(days=20)).astimezone(timezone.utc).isoformat(),
        }
    )
    return rows


def test_priced_rows_filters_unpriced_observations() -> None:
    rows = priced_rows(_synthetic_rows())
    assert len(rows) == 30
    assert all(row["priced_observation"] for row in rows)


def test_build_hypothesis_specs_includes_hour_specific_variants() -> None:
    rows = priced_rows(_synthetic_rows())
    specs = build_hypothesis_specs(rows, min_rows_per_hour=4)
    names = {spec.name for spec in specs}
    assert any("hour_et_10" in name for name in names)
    assert any("down" in name for name in names)


def test_summarize_hypothesis_history_matches_directional_hour_edge() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="down_hour_10",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.49,
        et_hours=(10,),
        session_name="hour_et_10",
    )
    history = summarize_hypothesis_history(rows, spec)
    assert history["replay_live_filled_rows"] == 15
    assert history["replay_live_filled_pnl_usd"] > 70.0


def test_evaluate_hypothesis_walk_forward_finds_persistent_edge() -> None:
    rows = priced_rows(_synthetic_rows())
    spec = HypothesisSpec(
        name="down_hour_10",
        direction="DOWN",
        max_abs_delta=0.00010,
        up_max_buy_price=None,
        down_max_buy_price=0.49,
        et_hours=(10,),
        session_name="hour_et_10",
    )
    result = evaluate_hypothesis_walk_forward(
        rows,
        spec,
        paths=100,
        block_size=2,
        loss_limit_usd=10.0,
        seed=7,
        min_train_rows=8,
        min_validate_rows=4,
        min_train_fills=2,
        min_validate_fills=1,
    )
    assert result is not None
    assert result["summary"]["splits_evaluated"] >= 2
    assert result["summary"]["validation_replay_pnl_usd"] > 0.0
    assert result["summary"]["validation_median_arr_pct"] > 0.0
