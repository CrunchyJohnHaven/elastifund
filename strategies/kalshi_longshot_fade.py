"""Kalshi low-priced YES / buy-NO basket strategy policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from signals.fee_models import FeeEstimate, breakeven_win_probability, kalshi_fee_estimate
from signals.resolution_risk import ResolutionRiskProfile, estimate_resolution_risk
from signals.tail_bins import TailBinSpec, TailPosterior, assign_tail_bin, default_kalshi_longshot_bins, robust_kelly_fraction


@dataclass(frozen=True)
class KalshiLongshotMarket:
    ticker: str
    title: str
    yes_ask: float
    no_ask: float
    yes_bid: float | None = None
    no_bid: float | None = None
    volume: float = 0.0
    open_interest: float = 0.0
    rules_text: str = ""
    settlement_source: str | None = None


@dataclass(frozen=True)
class KalshiLongshotDecision:
    qualifies: bool
    ticker: str
    traded_side: str
    bin_id: str | None
    intended_order_type: str
    entry_price: float
    contracts: int
    fee: FeeEstimate
    breakeven_win_rate: float
    posterior_mean: float | None
    posterior_lower: float | None
    robust_kelly_fraction: float
    resolution_risk: ResolutionRiskProfile
    reasons: tuple[str, ...] = field(default_factory=tuple)


class KalshiLongshotFadeStrategy:
    """Policy object for the first tail-calibration experiment."""

    def __init__(
        self,
        *,
        bins: Iterable[TailBinSpec] | None = None,
        maker: bool = False,
        contracts: int = 10,
        max_total_risk_score: float = 0.25,
        min_volume: float = 0.0,
    ) -> None:
        self.bins = tuple(bins or default_kalshi_longshot_bins())
        self.maker = bool(maker)
        self.contracts = max(1, int(contracts))
        self.max_total_risk_score = float(max_total_risk_score)
        self.min_volume = float(min_volume)

    def evaluate(
        self,
        market: KalshiLongshotMarket,
        *,
        posterior: TailPosterior | None = None,
    ) -> KalshiLongshotDecision:
        bin_spec = assign_tail_bin(yes_price=market.yes_ask, specs=self.bins)
        entry_price = float(market.no_bid if self.maker and market.no_bid is not None else market.no_ask)
        fee = kalshi_fee_estimate(price=entry_price, contracts=self.contracts, maker=self.maker)
        breakeven = breakeven_win_probability(
            entry_price=entry_price,
            fee_dollars=fee.fee_dollars,
            contracts=self.contracts,
        )
        risk = estimate_resolution_risk(
            venue="kalshi",
            rules_text=market.rules_text,
            settlement_source=market.settlement_source,
        )

        reasons: list[str] = []
        if bin_spec is None:
            reasons.append("yes_price_outside_longshot_bins")
        if market.volume < self.min_volume and market.open_interest < self.min_volume:
            reasons.append("insufficient_liquidity")
        if risk.total_risk_score > self.max_total_risk_score:
            reasons.append("resolution_risk_too_high")
        if risk.blockers:
            reasons.extend(risk.blockers)
        if not (0.0 < entry_price < 1.0):
            reasons.append("invalid_entry_price")

        p_mean = posterior.mean if posterior is not None else None
        p_lower = posterior.lower_bound if posterior is not None else None
        size_fraction = robust_kelly_fraction(p_lower=p_lower, entry_price=entry_price) if p_lower is not None else 0.0
        if posterior is not None and p_lower <= breakeven:
            reasons.append("posterior_lower_below_breakeven")

        qualifies = not reasons
        return KalshiLongshotDecision(
            qualifies=qualifies,
            ticker=market.ticker,
            traded_side="NO",
            bin_id=bin_spec.bin_id if bin_spec is not None else None,
            intended_order_type="maker" if self.maker else "taker",
            entry_price=entry_price,
            contracts=self.contracts,
            fee=fee,
            breakeven_win_rate=breakeven,
            posterior_mean=p_mean,
            posterior_lower=p_lower,
            robust_kelly_fraction=size_fraction,
            resolution_risk=risk,
            reasons=tuple(reasons),
        )

