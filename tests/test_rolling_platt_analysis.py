import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.rolling_platt_analysis import (
    ResolvedEstimate,
    evaluate_variant,
    load_resolved_estimates,
    rolling_platt_fit,
)


def _row(idx: int, raw_prob: float, outcome: int, end_date: str) -> ResolvedEstimate:
    return ResolvedEstimate(
        market_id=str(idx),
        question=f"Q{idx}?",
        end_date=end_date,
        raw_prob=raw_prob,
        outcome=outcome,
    )


def test_rolling_platt_fit_short_history_returns_static():
    rows = [_row(i, 0.6, 1, f"2026-01-{i + 1:02d}") for i in range(10)]
    a, b = rolling_platt_fit(rows, window=50, initial_a=0.55, initial_b=-0.40)
    assert a == 0.55
    assert b == -0.40


def test_load_resolved_estimates_joins_markets_and_cache(tmp_path):
    markets_path = tmp_path / "markets.json"
    cache_path = tmp_path / "cache.json"

    question = "Will X happen?"
    markets_path.write_text(
        """
        {
          "markets": [
            {
              "id": "m1",
              "question": "Will X happen?",
              "actual_outcome": "YES_WON",
              "end_date": "2026-03-01T00:00:00Z",
              "volume": 1000,
              "liquidity": 500
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    from backtest.rolling_platt_analysis import question_cache_key

    cache_path.write_text(
        f'{{"{question_cache_key(question)}": {{"probability": 0.73}}}}',
        encoding="utf-8",
    )

    rows = load_resolved_estimates(markets_path, cache_path)
    assert len(rows) == 1
    assert rows[0].raw_prob == 0.73
    assert rows[0].outcome == 1


def test_evaluate_variant_produces_validation_predictions():
    rows = [_row(i, 0.55 + (i % 3) * 0.05, i % 2, f"2026-01-{i + 1:02d}") for i in range(30)]
    result = evaluate_variant(rows, window=None, initial_train=20)
    assert result.n_predictions == 10
    assert 0.0 <= result.brier <= 1.0


def test_rolling_variant_can_beat_bad_static_baseline():
    rows = []
    for i in range(30):
        raw_prob = 0.85 if i % 2 == 0 else 0.90
        rows.append(_row(i, raw_prob, 0, f"2026-02-{i + 1:02d}"))

    static = evaluate_variant(rows, window=None, initial_train=20, static_a=1.0, static_b=0.0)
    rolling = evaluate_variant(rows, window=20, initial_train=20, static_a=1.0, static_b=0.0)
    assert rolling.brier < static.brier
