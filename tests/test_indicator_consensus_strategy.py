import unittest

from src.strategies.indicator_consensus import IndicatorConsensusStrategy


def _indicator_row(
    condition_id: str,
    *,
    ts: int,
    yes_price: float,
    direction: str = "up",
    vol_ratio: float = 1.1,
) -> dict[str, float | int | str]:
    sign = 1.0 if direction == "up" else -1.0
    return {
        "condition_id": condition_id,
        "timeframe": "15m",
        "timestamp_ts": ts,
        "yes_price": yes_price,
        "no_price": 1.0 - yes_price,
        "vol_ratio_30m_2h": vol_ratio,
        "ma_gap_15m": 0.010 * sign,
        "ma_gap_30m": 0.008 * sign,
        "ema_gap_15m": 0.011 * sign,
        "momentum_15m": 0.009 * sign,
        "momentum_30m": 0.008 * sign,
        "macd_hist": 0.004 * sign,
        "rsi_14": 35.0 if direction == "up" else 65.0,
        "bollinger_zscore_20": -1.2 if direction == "up" else 1.2,
        "trade_flow_imbalance": 0.30 * sign,
        "book_imbalance": 0.18 * sign,
        "time_remaining_sec": 480,
        "trade_count_60s": 24,
    }


class TestIndicatorConsensusStrategy(unittest.TestCase):
    def test_strategy_keeps_only_top_k_edges_per_timestamp(self) -> None:
        strategy = IndicatorConsensusStrategy(top_k_per_timestamp=3)
        timestamp = 1_700_100_000
        features = [
            _indicator_row("bull_a", ts=timestamp, yes_price=0.30),
            _indicator_row("bull_b", ts=timestamp, yes_price=0.34),
            _indicator_row("bull_c", ts=timestamp, yes_price=0.39),
            _indicator_row("bull_d", ts=timestamp, yes_price=0.46),
        ]

        signals = strategy.generate_signals([], [], [], features)
        condition_ids = {signal.condition_id for signal in signals}

        self.assertEqual(len(signals), 3)
        self.assertNotIn("bull_d", condition_ids)
        self.assertTrue(all(signal.side == "YES" for signal in signals))
        self.assertTrue(all(signal.metadata["indicator_consensus"] >= 0.72 for signal in signals))

    def test_strategy_skips_high_noise_and_can_emit_no_signals(self) -> None:
        strategy = IndicatorConsensusStrategy()
        features = [
            _indicator_row("too_noisy", ts=1_700_200_000, yes_price=0.78, direction="down", vol_ratio=2.2),
            _indicator_row("clean_down", ts=1_700_200_300, yes_price=0.74, direction="down", vol_ratio=1.0),
        ]

        signals = strategy.generate_signals([], [], [], features)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].condition_id, "clean_down")
        self.assertEqual(signals[0].side, "NO")


if __name__ == "__main__":
    unittest.main()
