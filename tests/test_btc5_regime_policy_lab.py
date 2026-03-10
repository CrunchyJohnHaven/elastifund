from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.btc5_monte_carlo import GuardrailProfile
from scripts.btc5_regime_policy_lab import build_session_filters, build_summary, enrich_rows


ET = ZoneInfo("America/New_York")


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp())


def _row(
    *,
    row_id: int,
    ts: int,
    direction: str,
    order_price: float,
    pnl_usd: float,
    order_status: str = "live_filled",
    delta: float = 0.0001,
) -> dict[str, object]:
    return {
        "id": row_id,
        "window_start_ts": ts,
        "slug": f"btc-updown-5m-{ts}",
        "direction": direction,
        "delta": delta,
        "abs_delta": abs(delta),
        "order_price": order_price,
        "trade_size_usd": 5.0,
        "won": pnl_usd > 0,
        "pnl_usd": pnl_usd,
        "realized_pnl_usd": pnl_usd if order_status == "live_filled" else 0.0,
        "order_status": order_status,
        "updated_at": "2026-03-09T00:00:00+00:00",
    }


def test_build_session_filters_includes_dense_hours() -> None:
    rows = enrich_rows(
        [
            _row(row_id=idx, ts=_ts(2026, 3, 9, 10, idx * 5), direction="DOWN", order_price=0.49, pnl_usd=5.0)
            for idx in range(6)
        ]
    )
    filters = build_session_filters(rows, min_session_rows=4)
    assert ("open_et", (9, 10, 11)) in filters
    assert ("hour_et_10", (10,)) in filters


def test_build_summary_finds_session_override_that_beats_current() -> None:
    rows: list[dict[str, object]] = []
    row_id = 1
    for minute in range(0, 40, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 10, minute),
                direction="DOWN",
                order_price=0.50,
                pnl_usd=-5.0,
            )
        )
        row_id += 1
    for minute in range(40, 60, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 10, minute),
                direction="DOWN",
                order_price=0.49,
                pnl_usd=5.2,
            )
        )
        row_id += 1
    for minute in range(0, 30, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 12, minute),
                direction="DOWN",
                order_price=0.49,
                pnl_usd=5.1,
            )
        )
        row_id += 1

    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=Path("reports/tmp_remote_btc_5min_maker.db"),
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=250,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
        min_replay_fills=6,
        min_session_rows=4,
        max_session_overrides=2,
        top_single_overrides_per_session=2,
        max_composed_candidates=16,
    )

    best = summary["best_policy"]
    assert best is not None
    assert best["policy"]["name"] != "policy_current_live_profile"
    assert best["policy"]["overrides"]
    assert "recommended_session_policy" in summary
    assert isinstance(summary["recommended_session_policy"], list)
    assert summary["recommended_session_policy"]
    runtime_policy = summary["recommended_session_policy"][0]
    assert runtime_policy["name"] == best["policy"]["overrides"][0]["session_name"]
    assert runtime_policy["et_hours"] == best["policy"]["overrides"][0]["et_hours"]
    assert set(runtime_policy).issubset(
        {"name", "et_hours", "min_delta", "max_abs_delta", "up_max_buy_price", "down_max_buy_price", "maker_improve_ticks"}
    )
    assert summary["best_vs_current"]["median_arr_pct_delta"] > 0
    assert summary["best_vs_current"]["replay_pnl_delta_usd"] > 0
    assert summary["best_candidate"]["name"]
    assert "arr_delta_vs_active_pct" in summary
    assert "p05_arr_delta_vs_active_pct" in summary
    assert "validation_live_filled_rows" in summary
    assert "generalization_ratio" in summary
    assert "evidence_band" in summary
    assert "last_improvement_at" in summary
    assert "hours_since_last_improvement" in summary
    assert summary["last_improvement_at"] is None or summary["last_improvement_at"].endswith("Z")
    assert summary["hours_since_last_improvement"] is None or summary["hours_since_last_improvement"] >= 0.0
    stress = summary["capacity_stress_candidates"]
    assert isinstance(stress, list)
    assert stress
    assert {
        "name",
        "session_name",
        "variant",
        "expected_fill_lift",
        "expected_median_pnl_delta_usd",
        "expected_p05_arr_delta_pct",
        "evidence_band",
    }.issubset(stress[0].keys())
    follow_ups = summary["follow_up_candidates"]
    assert isinstance(follow_ups, list)
    assert 1 <= len(follow_ups) <= 5
    assert {
        "name",
        "session_name",
        "et_hours",
        "max_abs_delta",
        "up_max_buy_price",
        "down_max_buy_price",
        "ranking_score",
        "evidence_band",
        "validation_live_filled_rows",
        "generalization_ratio",
        "validation_median_arr_pct",
        "validation_p05_arr_pct",
        "arr_improvement_vs_active_pct",
        "fill_retention_vs_active",
        "execution_realism_score",
        "execution_realism_label",
        "follow_up_families",
    }.issubset(follow_ups[0].keys())
    scores = [candidate["ranking_score"] for candidate in follow_ups]
    assert scores == sorted(scores, reverse=True)
    assert "best_live_followups" in summary
    assert "best_one_sided_followups" in summary
    assert isinstance(summary["best_live_followups"], list)
    assert isinstance(summary["best_one_sided_followups"], list)
    assert "loss_cluster_suppression_candidates" in summary
    assert isinstance(summary["loss_cluster_suppression_candidates"], list)
    assert summary["loss_cluster_suppression_candidates"]
    assert {
        "direction",
        "session_name",
        "price_bucket",
        "delta_bucket",
        "loss_rows",
        "total_loss_usd",
        "suggested_action",
    }.issubset(summary["loss_cluster_suppression_candidates"][0].keys())


def test_build_summary_can_promote_two_session_policy() -> None:
    rows: list[dict[str, object]] = []
    row_id = 1
    for hour in (9, 14):
        for minute in range(0, 30, 5):
            rows.append(
                _row(
                    row_id=row_id,
                    ts=_ts(2026, 3, 9, hour, minute),
                    direction="DOWN",
                    order_price=0.50,
                    pnl_usd=-5.0,
                )
            )
            row_id += 1
        for minute in (30, 35):
            rows.append(
                _row(
                    row_id=row_id,
                    ts=_ts(2026, 3, 9, hour, minute),
                    direction="DOWN",
                    order_price=0.49 if hour == 9 else 0.48,
                    pnl_usd=5.2 if hour == 9 else 5.4,
                )
            )
            row_id += 1
    for minute in range(0, 30, 5):
        rows.append(
            _row(
                row_id=row_id,
                ts=_ts(2026, 3, 9, 12, minute),
                direction="DOWN",
                order_price=0.49,
                pnl_usd=5.1,
            )
        )
        row_id += 1

    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=Path("reports/tmp_remote_btc_5min_maker.db"),
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=250,
        block_size=3,
        loss_limit_usd=10.0,
        seed=11,
        min_replay_fills=8,
        min_session_rows=4,
        max_session_overrides=2,
        top_single_overrides_per_session=2,
        max_composed_candidates=16,
    )

    best = summary["best_policy"]
    assert best is not None
    assert len(best["policy"]["overrides"]) == 2
    assert summary["best_candidate"]["session_count"] == 2
    assert len(summary["recommended_session_policy"]) == 2
    assert summary["best_vs_current"]["replay_pnl_delta_usd"] > 0
    assert summary["input"]["generated_composed_policies"] > 0
