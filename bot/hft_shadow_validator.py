"""HFT Shadow Validator for maker-only Chainlink/Binance basis experiments.

This module is intentionally network-free and deterministic. It focuses on the
core algorithmic logic needed for shadow validation:

- signal generation in the final candle window
- tie-band convexity handling (UP wins on exact tie)
- strict trade-through maker fill simulation
- maker vs taker EV accounting with the crypto polynomial fee model
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Literal

Side = Literal["UP", "DOWN"]
Resolution = Literal["UP", "DOWN", "TIE"]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class MarketSnapshot:
    """Single market state used for a shadow decision."""

    condition_id: str
    timestamp_ms: int
    binance_price: float
    chainlink_price: float
    candle_open_price: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    seconds_to_close: float
    book_imbalance: float = 0.0  # [-1, +1], positive means bullish pressure


@dataclass(frozen=True)
class MakerIntent:
    """Proposed maker order from the validator."""

    condition_id: str
    timestamp_ms: int
    side: Side
    limit_price: float
    confidence: float
    move_pct: float
    divergence_pct: float
    metadata: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TradePrint:
    """Executed market trade used for fill simulation."""

    timestamp_ms: int
    price: float
    outcome_side: Side
    size_usd: float = 0.0


@dataclass(frozen=True)
class ShadowCase:
    """Standalone shadow-validation scenario."""

    snapshot: MarketSnapshot
    trades: list[TradePrint]
    resolution: Resolution
    stake_usd: float = 5.0
    max_wait_seconds: float = 60.0


@dataclass(frozen=True)
class ShadowTradeResult:
    """Outcome of one candidate shadow trade."""

    posted: bool
    filled: bool
    win: bool
    side: Side | None
    entry_price: float | None
    maker_pnl: float
    taker_pnl: float
    confidence: float
    fill_timestamp_ms: int | None


@dataclass(frozen=True)
class BatchMetrics:
    """Aggregate metrics for acceptance gating."""

    posted: int
    filled: int
    wins: int
    fill_rate: float
    win_rate: float
    ev_maker: float
    ev_taker: float
    qualifies: bool


class HFTShadowValidator:
    """Deterministic core for Chainlink barrier shadow testing."""

    def __init__(
        self,
        *,
        min_move_pct: float = 0.0008,
        min_divergence_pct: float = 0.0005,
        min_confidence: float = 0.58,
        decision_window_start_sec: float = 60.0,
        decision_window_end_sec: float = 10.0,
        tie_band_bps: float = 1.0,
        tick_size: float = 0.001,
        crypto_fee_rate: float = 0.25,
        crypto_fee_exponent: float = 2.0,
    ):
        self.min_move_pct = min_move_pct
        self.min_divergence_pct = min_divergence_pct
        self.min_confidence = min_confidence
        self.decision_window_start_sec = decision_window_start_sec
        self.decision_window_end_sec = decision_window_end_sec
        self.tie_band_bps = tie_band_bps
        self.tick_size = tick_size
        self.crypto_fee_rate = crypto_fee_rate
        self.crypto_fee_exponent = crypto_fee_exponent

    @staticmethod
    def implied_side(open_price: float, spot_price: float) -> Side:
        """Direction under ">=" resolution logic (ties resolve UP)."""
        if spot_price >= open_price:
            return "UP"
        return "DOWN"

    @staticmethod
    def move_pct(open_price: float, spot_price: float) -> float:
        if open_price <= 0:
            return 0.0
        return abs(spot_price - open_price) / open_price

    @staticmethod
    def divergence_pct(binance_price: float, chainlink_price: float) -> float:
        denom = max(1e-9, abs(binance_price))
        return abs(binance_price - chainlink_price) / denom

    def in_decision_window(self, seconds_to_close: float) -> bool:
        return self.decision_window_end_sec <= seconds_to_close <= self.decision_window_start_sec

    def _tie_band_bonus(self, snapshot: MarketSnapshot, side: Side) -> float:
        """Small convexity bonus near exact-tie boundary for UP side."""
        band = max(0.0, self.tie_band_bps) / 10_000.0
        if band <= 0:
            return 0.0

        dist = self.move_pct(snapshot.candle_open_price, snapshot.binance_price)
        if dist > band:
            return 0.0

        # Tie-band convexity only helps UP because equality resolves UP.
        if side == "UP":
            return 0.025
        return -0.010

    def confidence_score(self, snapshot: MarketSnapshot) -> tuple[Side, float, float, float]:
        """Return (side, confidence, move_pct, divergence_pct)."""
        side = self.implied_side(snapshot.candle_open_price, snapshot.binance_price)
        move = self.move_pct(snapshot.candle_open_price, snapshot.binance_price)
        div = self.divergence_pct(snapshot.binance_price, snapshot.chainlink_price)

        move_strength = _clamp(move / max(self.min_move_pct, 1e-9), 0.0, 3.0) / 3.0
        div_strength = _clamp(div / max(self.min_divergence_pct, 1e-9), 0.0, 3.0) / 3.0

        window_span = max(1e-6, self.decision_window_start_sec - self.decision_window_end_sec)
        urgency = _clamp((self.decision_window_start_sec - snapshot.seconds_to_close) / window_span, 0.0, 1.0)

        flow = _clamp(snapshot.book_imbalance, -1.0, 1.0)
        flow_alignment = 0.5 + 0.5 * (flow if side == "UP" else -flow)

        conf = (
            0.35 * move_strength
            + 0.35 * div_strength
            + 0.20 * flow_alignment
            + 0.10 * urgency
        )
        conf += self._tie_band_bonus(snapshot, side)
        conf = _clamp(conf, 0.0, 0.99)

        return side, conf, move, div

    def propose_intent(self, snapshot: MarketSnapshot) -> MakerIntent | None:
        """Return a maker order intent or None when gate conditions fail."""
        if not self.in_decision_window(snapshot.seconds_to_close):
            return None

        side, confidence, move, div = self.confidence_score(snapshot)
        tie_band = max(0.0, self.tie_band_bps) / 10_000.0
        in_tie_band = move <= tie_band
        if div < self.min_divergence_pct:
            return None
        if move < self.min_move_pct and not (side == "UP" and in_tie_band):
            return None
        if confidence < self.min_confidence:
            return None

        if side == "UP":
            bid = _clamp(snapshot.yes_bid, 0.01, 0.99)
            ask = _clamp(snapshot.yes_ask, bid, 0.99)
        else:
            bid = _clamp(snapshot.no_bid, 0.01, 0.99)
            ask = _clamp(snapshot.no_ask, bid, 0.99)

        spread = max(0.0, ask - bid)
        aggressiveness = 0.40 + 0.40 * confidence
        target = bid + aggressiveness * spread
        limit_price = _clamp(min(ask - self.tick_size, target), bid, ask)
        limit_price = _clamp(limit_price, 0.01, 0.99)

        return MakerIntent(
            condition_id=snapshot.condition_id,
            timestamp_ms=snapshot.timestamp_ms,
            side=side,
            limit_price=limit_price,
            confidence=confidence,
            move_pct=move,
            divergence_pct=div,
            metadata={
                "seconds_to_close": snapshot.seconds_to_close,
                "book_imbalance": snapshot.book_imbalance,
            },
        )

    @staticmethod
    def simulate_maker_fill(
        intent: MakerIntent,
        trades: Iterable[TradePrint],
        *,
        strict_trade_through: bool = True,
        max_wait_seconds: float = 60.0,
        eps: float = 1e-12,
    ) -> tuple[bool, int | None]:
        """Simulate maker fill using strict trade-through execution logic.

        For passive BUY intents:
        - side UP means buying UP shares; we require UP trades at lower prices.
        - side DOWN means buying DOWN shares; same fill rule on DOWN book.

        strict_trade_through=True requires trades to move *through* our level:
        - fill when trade price < limit (not equal)
        """
        start_ms = intent.timestamp_ms
        end_ms = start_ms + int(max(0.0, max_wait_seconds) * 1000)

        for trade in sorted(trades, key=lambda t: t.timestamp_ms):
            if trade.outcome_side != intent.side:
                continue
            if trade.timestamp_ms < start_ms or trade.timestamp_ms > end_ms:
                continue

            if strict_trade_through:
                if trade.price < intent.limit_price - eps:
                    return True, trade.timestamp_ms
            else:
                if trade.price <= intent.limit_price + eps:
                    return True, trade.timestamp_ms

        return False, None

    def taker_fee(self, stake_usd: float, price: float) -> float:
        """Polymarket crypto polynomial taker fee model.

        fee = stake * fee_rate * (p*(1-p))^exponent
        """
        p = _clamp(price, 0.001, 0.999)
        # fee is charged on contracts; with stake-sized notionals this collapses to
        # stake * fee_rate * (p*(1-p))^exponent.
        return stake_usd * self.crypto_fee_rate * ((p * (1.0 - p)) ** self.crypto_fee_exponent)

    @staticmethod
    def _is_win(side: Side, resolution: Resolution) -> bool:
        if resolution == "TIE":
            return side == "UP"
        if side == "UP":
            return resolution == "UP"
        return resolution == "DOWN"

    def evaluate_case(self, case: ShadowCase) -> ShadowTradeResult:
        intent = self.propose_intent(case.snapshot)
        if intent is None:
            return ShadowTradeResult(
                posted=False,
                filled=False,
                win=False,
                side=None,
                entry_price=None,
                maker_pnl=0.0,
                taker_pnl=0.0,
                confidence=0.0,
                fill_timestamp_ms=None,
            )

        filled, fill_ts = self.simulate_maker_fill(
            intent,
            case.trades,
            strict_trade_through=True,
            max_wait_seconds=case.max_wait_seconds,
        )

        # Taker benchmark assumes immediate aggressive execution at ask.
        taker_entry = case.snapshot.yes_ask if intent.side == "UP" else case.snapshot.no_ask
        taker_entry = _clamp(taker_entry, 0.01, 0.99)

        taker_win = self._is_win(intent.side, case.resolution)
        taker_shares = case.stake_usd / taker_entry
        taker_gross = taker_shares * (1.0 - taker_entry) if taker_win else -case.stake_usd
        taker_net = taker_gross - self.taker_fee(case.stake_usd, taker_entry)

        if not filled:
            return ShadowTradeResult(
                posted=True,
                filled=False,
                win=False,
                side=intent.side,
                entry_price=float(intent.limit_price),
                maker_pnl=0.0,
                taker_pnl=float(taker_net),
                confidence=float(intent.confidence),
                fill_timestamp_ms=None,
            )

        win = self._is_win(intent.side, case.resolution)
        shares = case.stake_usd / intent.limit_price
        maker_gross = shares * (1.0 - intent.limit_price) if win else -case.stake_usd

        return ShadowTradeResult(
            posted=True,
            filled=True,
            win=win,
            side=intent.side,
            entry_price=float(intent.limit_price),
            maker_pnl=float(maker_gross),
            taker_pnl=float(taker_net),
            confidence=float(intent.confidence),
            fill_timestamp_ms=fill_ts,
        )

    def evaluate_batch(
        self,
        cases: Iterable[ShadowCase],
        *,
        min_fill_rate: float = 0.15,
    ) -> BatchMetrics:
        results = [self.evaluate_case(case) for case in cases]

        posted = sum(1 for r in results if r.posted)
        filled = sum(1 for r in results if r.filled)
        wins = sum(1 for r in results if r.filled and r.win)

        fill_rate = (filled / posted) if posted else 0.0
        win_rate = (wins / filled) if filled else 0.0

        maker_samples = [r.maker_pnl for r in results if r.posted]
        taker_samples = [r.taker_pnl for r in results if r.posted]

        ev_maker = (sum(maker_samples) / len(maker_samples)) if maker_samples else 0.0
        ev_taker = (sum(taker_samples) / len(taker_samples)) if taker_samples else 0.0

        qualifies = fill_rate >= min_fill_rate and ev_maker > 0.0

        return BatchMetrics(
            posted=posted,
            filled=filled,
            wins=wins,
            fill_rate=fill_rate,
            win_rate=win_rate,
            ev_maker=ev_maker,
            ev_taker=ev_taker,
            qualifies=qualifies,
        )
