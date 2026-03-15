"""HFT Shadow Validator for maker-only Chainlink/Binance basis experiments.

This module is intentionally network-free and deterministic. It focuses on the
core algorithmic logic needed for shadow validation:

- signal generation in the final candle window
- tie-band convexity handling (UP wins on exact tie)
- strict trade-through maker fill simulation
- maker vs taker EV accounting with the crypto polynomial fee model
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Iterable, Literal

Side = Literal["UP", "DOWN"]
Resolution = Literal["UP", "DOWN", "TIE"]
Verdict = Literal["GO", "NO_GO", "INSUFFICIENT_DATA"]


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
    would_win_if_filled: bool | None
    theoretical_maker_pnl: float
    theoretical_edge_vs_taker: float
    post_fill_edge_vs_taker: float
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


@dataclass(frozen=True)
class Re1ShadowThresholds:
    """Current RE1 keep/kill contract for 72-hour shadow validation."""

    min_signal_count: int = 30
    min_fill_rate: float = 0.15
    min_post_fill_edge_usd: float = 0.0
    min_theoretical_edge_usd: float = 0.0


@dataclass(frozen=True)
class FillProbabilityAssumptions:
    """Explicit assumptions used to interpret maker fill probability."""

    strict_trade_through: bool = True
    max_wait_seconds: float = 60.0
    prior_fill_probability: float = 0.15
    model: str = "strict_trade_through_v1"


@dataclass(frozen=True)
class Re1ShadowReport:
    """Standalone artifact contract for RE1 Chainlink maker-only shadow runs."""

    schema_version: str
    generated_at_utc: str
    run_started_ms: int
    run_ended_ms: int
    requested_shadow_hours: float
    evaluated_cases: int
    signal_count: int
    posted_count: int
    filled_count: int
    maker_fill_rate: float
    maker_fill_probability_assumptions: dict[str, float | str | bool]
    realized_vs_theoretical_edge: dict[str, float]
    tie_band_breakdown: dict[str, dict[str, float]]
    barrier_breakdown: dict[str, dict[str, float]]
    re1_thresholds: dict[str, float | int]
    verdict: Verdict
    verdict_reason: str
    promotion_policy: str

    def to_dict(self) -> dict:
        return asdict(self)


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
                would_win_if_filled=None,
                theoretical_maker_pnl=0.0,
                theoretical_edge_vs_taker=0.0,
                post_fill_edge_vs_taker=0.0,
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

        would_win = self._is_win(intent.side, case.resolution)
        taker_win = would_win
        taker_shares = case.stake_usd / taker_entry
        taker_gross = taker_shares * (1.0 - taker_entry) if taker_win else -case.stake_usd
        taker_net = taker_gross - self.taker_fee(case.stake_usd, taker_entry)
        theoretical_shares = case.stake_usd / intent.limit_price
        theoretical_maker_pnl = (
            theoretical_shares * (1.0 - intent.limit_price) if would_win else -case.stake_usd
        )
        theoretical_edge_vs_taker = theoretical_maker_pnl - taker_net

        if not filled:
            return ShadowTradeResult(
                posted=True,
                filled=False,
                win=False,
                side=intent.side,
                entry_price=float(intent.limit_price),
                maker_pnl=0.0,
                taker_pnl=float(taker_net),
                would_win_if_filled=would_win,
                theoretical_maker_pnl=float(theoretical_maker_pnl),
                theoretical_edge_vs_taker=float(theoretical_edge_vs_taker),
                post_fill_edge_vs_taker=float(0.0 - taker_net),
                confidence=float(intent.confidence),
                fill_timestamp_ms=None,
            )

        win = would_win
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
            would_win_if_filled=would_win,
            theoretical_maker_pnl=float(theoretical_maker_pnl),
            theoretical_edge_vs_taker=float(theoretical_edge_vs_taker),
            post_fill_edge_vs_taker=float(maker_gross - taker_net),
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

    def _in_tie_band(self, snapshot: MarketSnapshot) -> bool:
        tie_band = max(0.0, self.tie_band_bps) / 10_000.0
        if tie_band <= 0.0:
            return False
        return self.move_pct(snapshot.candle_open_price, snapshot.binance_price) <= tie_band

    @staticmethod
    def _bucket_metrics(rows: list[dict]) -> dict[str, float]:
        posted_rows = [r for r in rows if r["result"].posted]
        posted = len(posted_rows)
        filled = sum(1 for r in posted_rows if r["result"].filled)
        wins = sum(1 for r in posted_rows if r["result"].filled and r["result"].win)
        fill_rate = (filled / posted) if posted else 0.0
        win_rate = (wins / filled) if filled else 0.0
        theoretical_edge = (
            sum(r["result"].theoretical_edge_vs_taker for r in posted_rows) / posted
            if posted
            else 0.0
        )
        post_fill_edge = (
            sum(r["result"].post_fill_edge_vs_taker for r in posted_rows) / posted
            if posted
            else 0.0
        )
        return {
            "signals": float(posted),
            "fills": float(filled),
            "fill_rate": float(fill_rate),
            "win_rate": float(win_rate),
            "theoretical_edge_per_signal_usd": float(theoretical_edge),
            "post_fill_edge_per_signal_usd": float(post_fill_edge),
        }

    @staticmethod
    def _verdict_for_report(
        signal_count: int,
        fill_rate: float,
        post_fill_edge_usd: float,
        theoretical_edge_usd: float,
        thresholds: Re1ShadowThresholds,
    ) -> tuple[Verdict, str]:
        if signal_count < thresholds.min_signal_count:
            return (
                "INSUFFICIENT_DATA",
                (
                    f"Need >= {thresholds.min_signal_count} signals, observed {signal_count}. "
                    "Keep RE1 in shadow mode."
                ),
            )
        if fill_rate < thresholds.min_fill_rate:
            return (
                "NO_GO",
                (
                    f"Maker fill rate {fill_rate:.3f} below threshold "
                    f"{thresholds.min_fill_rate:.3f}."
                ),
            )
        if post_fill_edge_usd < thresholds.min_post_fill_edge_usd:
            return (
                "NO_GO",
                (
                    f"Post-fill edge {post_fill_edge_usd:.4f} USD/signal below threshold "
                    f"{thresholds.min_post_fill_edge_usd:.4f}."
                ),
            )
        if theoretical_edge_usd < thresholds.min_theoretical_edge_usd:
            return (
                "NO_GO",
                (
                    f"Theoretical edge {theoretical_edge_usd:.4f} USD/signal below threshold "
                    f"{thresholds.min_theoretical_edge_usd:.4f}."
                ),
            )
        return ("GO", "RE1 shadow thresholds met; eligible for keep/kill review only.")

    def build_re1_shadow_report(
        self,
        cases: Iterable[ShadowCase],
        *,
        run_started_ms: int | None = None,
        run_ended_ms: int | None = None,
        requested_shadow_hours: float = 72.0,
        thresholds: Re1ShadowThresholds | None = None,
        fill_assumptions: FillProbabilityAssumptions | None = None,
    ) -> Re1ShadowReport:
        rows = []
        for case in cases:
            result = self.evaluate_case(case)
            rows.append(
                {
                    "case": case,
                    "result": result,
                    "in_tie_band": self._in_tie_band(case.snapshot),
                }
            )

        thresholds = thresholds or Re1ShadowThresholds()
        fill_assumptions = fill_assumptions or FillProbabilityAssumptions()

        posted_rows = [r for r in rows if r["result"].posted]
        posted_count = len(posted_rows)
        filled_count = sum(1 for r in posted_rows if r["result"].filled)
        fill_rate = (filled_count / posted_count) if posted_count else 0.0

        theoretical_edge_per_signal = (
            sum(r["result"].theoretical_edge_vs_taker for r in posted_rows) / posted_count
            if posted_count
            else 0.0
        )
        post_fill_edge_per_signal = (
            sum(r["result"].post_fill_edge_vs_taker for r in posted_rows) / posted_count
            if posted_count
            else 0.0
        )

        verdict, reason = self._verdict_for_report(
            signal_count=posted_count,
            fill_rate=fill_rate,
            post_fill_edge_usd=post_fill_edge_per_signal,
            theoretical_edge_usd=theoretical_edge_per_signal,
            thresholds=thresholds,
        )

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        end_ms = run_ended_ms if run_ended_ms is not None else now_ms
        start_ms = run_started_ms if run_started_ms is not None else int(
            end_ms - requested_shadow_hours * 3600 * 1000
        )
        tie_band_rows = [r for r in posted_rows if r["in_tie_band"]]
        non_tie_rows = [r for r in posted_rows if not r["in_tie_band"]]

        return Re1ShadowReport(
            schema_version="re1.shadow.v1",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            run_started_ms=int(start_ms),
            run_ended_ms=int(end_ms),
            requested_shadow_hours=float(requested_shadow_hours),
            evaluated_cases=len(rows),
            signal_count=posted_count,
            posted_count=posted_count,
            filled_count=filled_count,
            maker_fill_rate=float(fill_rate),
            maker_fill_probability_assumptions={
                "strict_trade_through": fill_assumptions.strict_trade_through,
                "max_wait_seconds": float(fill_assumptions.max_wait_seconds),
                "prior_fill_probability": float(fill_assumptions.prior_fill_probability),
                "model": fill_assumptions.model,
            },
            realized_vs_theoretical_edge={
                "theoretical_edge_per_signal_usd": float(theoretical_edge_per_signal),
                "post_fill_edge_per_signal_usd": float(post_fill_edge_per_signal),
                "fill_shortfall_edge_per_signal_usd": float(
                    theoretical_edge_per_signal - post_fill_edge_per_signal
                ),
                "theoretical_edge_total_usd": float(
                    sum(r["result"].theoretical_edge_vs_taker for r in posted_rows)
                ),
                "post_fill_edge_total_usd": float(
                    sum(r["result"].post_fill_edge_vs_taker for r in posted_rows)
                ),
            },
            tie_band_breakdown={
                "in_tie_band": self._bucket_metrics(tie_band_rows),
                "outside_tie_band": self._bucket_metrics(non_tie_rows),
            },
            barrier_breakdown={
                "up_barrier": self._bucket_metrics(
                    [r for r in posted_rows if r["result"].side == "UP"]
                ),
                "down_barrier": self._bucket_metrics(
                    [r for r in posted_rows if r["result"].side == "DOWN"]
                ),
            },
            re1_thresholds=asdict(thresholds),
            verdict=verdict,
            verdict_reason=reason,
            promotion_policy="shadow_only_do_not_promote_live",
        )

    def write_re1_shadow_report(self, path: str | Path, report: Re1ShadowReport) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
        return output_path
