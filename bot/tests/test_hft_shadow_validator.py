import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hft_shadow_validator import (
    HFTShadowValidator,
    MarketSnapshot,
    TradePrint,
    ShadowCase,
    MakerIntent,
)


def _snapshot(**kwargs) -> MarketSnapshot:
    base = dict(
        condition_id="m1",
        timestamp_ms=1_000_000,
        binance_price=100.6,
        chainlink_price=100.2,
        candle_open_price=100.0,
        yes_bid=0.57,
        yes_ask=0.59,
        no_bid=0.41,
        no_ask=0.43,
        seconds_to_close=30.0,
        book_imbalance=0.4,
    )
    base.update(kwargs)
    return MarketSnapshot(**base)


class TestSignalLogic:
    def test_tie_resolves_up_bias(self):
        assert HFTShadowValidator.implied_side(100.0, 100.0) == "UP"

    def test_window_gating_blocks_outside_final_window(self):
        v = HFTShadowValidator()
        snap = _snapshot(seconds_to_close=95.0)
        assert v.propose_intent(snap) is None

    def test_move_and_divergence_thresholds_gate_signal(self):
        v = HFTShadowValidator(min_move_pct=0.002, min_divergence_pct=0.001)
        snap = _snapshot(binance_price=100.05, chainlink_price=100.04)
        assert v.propose_intent(snap) is None

    def test_strong_signal_produces_intent(self):
        v = HFTShadowValidator(min_confidence=0.2)
        intent = v.propose_intent(_snapshot())
        assert intent is not None
        assert intent.side == "UP"
        assert 0.01 <= intent.limit_price <= 0.99

    def test_higher_divergence_increases_confidence(self):
        v = HFTShadowValidator(min_confidence=0.0)
        low = _snapshot(chainlink_price=100.45)
        high = _snapshot(chainlink_price=99.8)

        _, conf_low, _, _ = v.confidence_score(low)
        _, conf_high, _, _ = v.confidence_score(high)
        assert conf_high > conf_low


class TestMakerFillModel:
    def test_strict_trade_through_requires_price_below_limit(self):
        intent = MakerIntent(
            condition_id="m1",
            timestamp_ms=1_000,
            side="UP",
            limit_price=0.58,
            confidence=0.7,
            move_pct=0.004,
            divergence_pct=0.003,
        )
        trades = [
            TradePrint(timestamp_ms=1_500, price=0.58, outcome_side="UP"),
            TradePrint(timestamp_ms=1_700, price=0.579, outcome_side="UP"),
        ]
        filled, ts = HFTShadowValidator.simulate_maker_fill(intent, trades, strict_trade_through=True)
        assert filled
        assert ts == 1_700

    def test_non_strict_allows_touch_fill(self):
        intent = MakerIntent(
            condition_id="m1",
            timestamp_ms=1_000,
            side="UP",
            limit_price=0.58,
            confidence=0.7,
            move_pct=0.004,
            divergence_pct=0.003,
        )
        trades = [TradePrint(timestamp_ms=1_500, price=0.58, outcome_side="UP")]
        strict, _ = HFTShadowValidator.simulate_maker_fill(intent, trades, strict_trade_through=True)
        loose, _ = HFTShadowValidator.simulate_maker_fill(intent, trades, strict_trade_through=False)
        assert not strict
        assert loose

    def test_wrong_outcome_side_does_not_fill(self):
        intent = MakerIntent(
            condition_id="m1",
            timestamp_ms=1_000,
            side="DOWN",
            limit_price=0.42,
            confidence=0.7,
            move_pct=0.004,
            divergence_pct=0.003,
        )
        trades = [TradePrint(timestamp_ms=1_500, price=0.40, outcome_side="UP")]
        filled, _ = HFTShadowValidator.simulate_maker_fill(intent, trades)
        assert not filled


class TestPnLAndFees:
    def test_crypto_fee_formula_peak_near_1_56pct_at_half_price(self):
        v = HFTShadowValidator()
        fee = v.taker_fee(1.0, 0.5)
        assert abs(fee - 0.015625) < 1e-9

    def test_tie_resolution_counts_as_up_win(self):
        v = HFTShadowValidator(min_confidence=0.2)
        case = ShadowCase(
            snapshot=_snapshot(binance_price=100.0, chainlink_price=99.7),
            trades=[TradePrint(timestamp_ms=1_000_500, price=0.57, outcome_side="UP")],
            resolution="TIE",
            stake_usd=5.0,
            max_wait_seconds=60.0,
        )
        result = v.evaluate_case(case)
        assert result.posted
        assert result.filled
        assert result.side == "UP"
        assert result.win
        assert result.maker_pnl > 0

    def test_unfilled_trade_has_zero_maker_pnl(self):
        v = HFTShadowValidator(min_confidence=0.2)
        case = ShadowCase(
            snapshot=_snapshot(),
            trades=[],
            resolution="UP",
            stake_usd=5.0,
        )
        result = v.evaluate_case(case)
        assert result.posted
        assert not result.filled
        assert result.maker_pnl == 0.0


class TestBatchMetrics:
    def test_batch_qualifies_when_fill_rate_and_ev_are_positive(self):
        v = HFTShadowValidator(min_confidence=0.2)

        cases = [
            ShadowCase(
                snapshot=_snapshot(condition_id="a", timestamp_ms=1_000_000, binance_price=100.7, chainlink_price=100.2),
                trades=[TradePrint(timestamp_ms=1_000_300, price=0.57, outcome_side="UP")],
                resolution="UP",
            ),
            ShadowCase(
                snapshot=_snapshot(condition_id="b", timestamp_ms=2_000_000, binance_price=100.65, chainlink_price=100.1),
                trades=[TradePrint(timestamp_ms=2_000_400, price=0.56, outcome_side="UP")],
                resolution="UP",
            ),
            ShadowCase(
                snapshot=_snapshot(condition_id="c", timestamp_ms=3_000_000, binance_price=100.61, chainlink_price=100.2),
                trades=[],
                resolution="UP",
            ),
        ]

        metrics = v.evaluate_batch(cases, min_fill_rate=0.15)

        assert metrics.posted == 3
        assert metrics.filled == 2
        assert math.isclose(metrics.fill_rate, 2 / 3, rel_tol=1e-9)
        assert metrics.ev_maker > 0
        assert metrics.qualifies

    def test_batch_fails_when_fill_rate_too_low(self):
        v = HFTShadowValidator(min_confidence=0.2)
        cases = [
            ShadowCase(
                snapshot=_snapshot(condition_id="a", timestamp_ms=1_000_000),
                trades=[],
                resolution="UP",
            ),
            ShadowCase(
                snapshot=_snapshot(condition_id="b", timestamp_ms=2_000_000),
                trades=[],
                resolution="UP",
            ),
        ]

        metrics = v.evaluate_batch(cases, min_fill_rate=0.15)
        assert metrics.posted == 2
        assert metrics.filled == 0
        assert not metrics.qualifies
