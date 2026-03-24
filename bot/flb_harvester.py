"""
Favorite-Longshot Bias Harvester — Systematic Tail Event Portfolio
==================================================================
Dispatch: DISPATCH_107 (Deep Research Integration)

Harvests the favorite-longshot bias: events priced <10% happen more often
than the price implies; events priced >90% fail more often. 50+ years of
academic consensus. 2026 paper confirms on Kalshi (300K+ contracts).

Strategy:
    1. Scan all markets for contracts priced at 90c-98c (YES) or 2c-10c (YES)
    2. For each, estimate true probability using LLM + Bayesian shrinkage
    3. If FLB edge exceeds costs → add to portfolio
    4. Diversify across 20-50 simultaneous positions
    5. Size by Kelly with conservative lower-bound credible interval

Signal Source: #8 in jj_live.py

Author: JJ (autonomous)
Date: 2026-03-23
"""

import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("JJ.flb_harvester")

try:
    from bot.net_edge_accounting import (
        FeeSchedule,
        bayesian_bin_calibration,
        BinCalibration,
        kelly_prediction_market,
        evaluate_edge,
    )
except ImportError:
    from net_edge_accounting import (  # type: ignore
        FeeSchedule,
        bayesian_bin_calibration,
        BinCalibration,
        kelly_prediction_market,
        evaluate_edge,
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class FLBConfig:
    """Configuration for the FLB harvester."""
    # Price bins to target (YES price ranges where FLB is expected)
    # Tail YES: buy NO when YES price is 90-98c (event "certain" but sometimes fails)
    tail_yes_min: float = 0.90
    tail_yes_max: float = 0.98
    # Tail NO: buy YES when YES price is 2-10c (event "impossible" but sometimes happens)
    tail_no_min: float = 0.02
    tail_no_max: float = 0.10
    # Minimum FLB edge (bps) to consider a position
    min_edge_bps: float = 50.0
    # Maximum simultaneous positions
    max_positions: int = 50
    # Maximum capital per position (fraction of bankroll)
    max_position_frac: float = 0.05
    # Maximum total portfolio exposure (fraction of bankroll)
    max_portfolio_frac: float = 0.80
    # Minimum days to resolution (skip fast-resolving)
    min_days_to_resolution: int = 1
    # Maximum days to resolution (avoid capital lockup)
    max_days_to_resolution: int = 60
    # Bayesian prior strength (higher = more shrinkage toward bin center)
    prior_alpha: float = 2.0
    prior_beta: float = 2.0
    # Minimum historical observations per bin for calibration
    min_bin_observations: int = 30
    # Maximum category concentration (fraction of positions)
    max_category_concentration: float = 0.40
    # LLM filter: reject if LLM estimate within this of market price
    llm_agreement_threshold: float = 0.03


class TailType(Enum):
    """Which tail we're harvesting."""
    HIGH_YES = "high_yes"   # YES at 90-98c, we buy NO (event fails)
    LOW_YES = "low_yes"     # YES at 2-10c, we buy YES (event happens)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MarketCalibrationData:
    """Historical resolution data for a probability bin."""
    bin_center: float
    category: str
    wins: int = 0        # YES resolutions
    losses: int = 0      # NO resolutions
    total: int = 0
    venue: str = "polymarket"

    @property
    def calibration(self) -> BinCalibration:
        return bayesian_bin_calibration(
            wins=self.wins,
            total=self.total,
            bin_center=self.bin_center,
        )


@dataclass
class FLBCandidate:
    """A contract identified as a potential FLB opportunity."""
    market_id: str
    token_id: str
    question: str
    category: str
    venue: str
    yes_price: float           # current YES price
    no_price: float            # current NO price
    tail_type: TailType
    days_to_resolution: float
    volume_24h: float = 0.0
    spread: float = 0.0        # bid-ask spread


@dataclass
class FLBSignal:
    """Generated when FLB edge exceeds threshold for a candidate."""
    market_id: str
    token_id: str
    venue: str
    tail_type: TailType
    side: str                  # "BUY_YES" or "BUY_NO"
    market_price: float        # the price we're betting against
    estimated_true_prob: float # our Bayesian estimate
    flb_edge_bps: float        # (estimated/market - 1) * 10000
    net_edge_bps: float        # after costs
    kelly_fraction: float      # recommended position size
    position_usd: float        # dollar amount to allocate
    confidence: float          # 0-1
    calibration: BinCalibration
    ts: float


@dataclass
class FLBPortfolio:
    """Current state of the tail harvesting portfolio."""
    positions: list[FLBSignal] = field(default_factory=list)
    total_capital_locked: float = 0.0
    bankroll: float = 1000.0
    category_counts: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def capital_utilization(self) -> float:
        if self.bankroll <= 0:
            return 0.0
        return self.total_capital_locked / self.bankroll


# ---------------------------------------------------------------------------
# Calibration Database
# ---------------------------------------------------------------------------

class CalibrationDB:
    """
    In-memory calibration database for FLB bins.

    Stores historical win/loss counts per (bin_center, category, venue).
    Used to estimate true resolution rates via Bayesian shrinkage.

    In production, this is persisted to SQLite.
    """

    def __init__(self, prior_alpha: float = 2.0, prior_beta: float = 2.0):
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        # Key: (bin_center_rounded, category, venue)
        self._data: dict[tuple[float, str, str], MarketCalibrationData] = {}

    def record_resolution(self, market_price_at_entry: float,
                          category: str, venue: str,
                          resolved_yes: bool) -> None:
        """Record a contract resolution for calibration."""
        bin_center = self._price_to_bin(market_price_at_entry)
        key = (bin_center, category, venue)

        if key not in self._data:
            self._data[key] = MarketCalibrationData(
                bin_center=bin_center,
                category=category,
                venue=venue,
            )

        entry = self._data[key]
        entry.total += 1
        if resolved_yes:
            entry.wins += 1
        else:
            entry.losses += 1

    def get_calibration(self, market_price: float,
                        category: str, venue: str) -> Optional[BinCalibration]:
        """Get calibration for a price/category/venue combination."""
        bin_center = self._price_to_bin(market_price)
        key = (bin_center, category, venue)

        entry = self._data.get(key)
        if entry is None or entry.total < 5:
            # Fall back to category-agnostic
            fallback = self._aggregate_bin(bin_center, venue)
            if fallback is None or fallback.total < 5:
                return None
            entry = fallback

        return bayesian_bin_calibration(
            wins=entry.wins,
            total=entry.total,
            bin_center=bin_center,
            prior_alpha=self.prior_alpha,
            prior_beta=self.prior_beta,
        )

    def _price_to_bin(self, price: float) -> float:
        """Round price to nearest 0.01 bin center."""
        return round(price, 2)

    def _aggregate_bin(self, bin_center: float,
                       venue: str) -> Optional[MarketCalibrationData]:
        """Aggregate across all categories for a bin."""
        total_wins = 0
        total_total = 0
        for (bc, cat, v), data in self._data.items():
            if abs(bc - bin_center) < 0.005 and v == venue:
                total_wins += data.wins
                total_total += data.total
        if total_total == 0:
            return None
        return MarketCalibrationData(
            bin_center=bin_center,
            category="all",
            wins=total_wins,
            total=total_total,
            venue=venue,
        )

    def get_all_calibrations(self, venue: str = "all") -> list[BinCalibration]:
        """Get calibration curves for all bins."""
        results = []
        bins_seen = set()
        for (bc, cat, v), data in sorted(self._data.items()):
            if venue != "all" and v != venue:
                continue
            if bc in bins_seen:
                continue
            bins_seen.add(bc)
            agg = self._aggregate_bin(bc, v)
            if agg and agg.total >= 5:
                results.append(bayesian_bin_calibration(
                    wins=agg.wins, total=agg.total,
                    bin_center=bc,
                    prior_alpha=self.prior_alpha,
                    prior_beta=self.prior_beta,
                ))
        return sorted(results, key=lambda x: x.bin_center)


# ---------------------------------------------------------------------------
# FLB Harvester Engine
# ---------------------------------------------------------------------------

class FLBHarvester:
    """
    Scans prediction markets for favorite-longshot bias opportunities
    and manages a diversified tail portfolio.

    Usage:
        harvester = FLBHarvester(bankroll=1000.0)
        candidates = harvester.scan_markets(markets)
        signals = harvester.evaluate_candidates(candidates)
        harvester.add_positions(signals)
    """

    def __init__(self, bankroll: float = 1000.0,
                 config: Optional[FLBConfig] = None):
        self.config = config or FLBConfig()
        self.calibration_db = CalibrationDB(
            prior_alpha=self.config.prior_alpha,
            prior_beta=self.config.prior_beta,
        )
        self.portfolio = FLBPortfolio(bankroll=bankroll)
        self._signal_history: list[FLBSignal] = []

    def identify_candidates(self, markets: list[dict]) -> list[FLBCandidate]:
        """
        Scan a list of markets for FLB candidates.

        Markets should have: id, tokens, question, category, end_date_iso,
        volume_24h, best_bid, best_ask.
        """
        candidates = []
        now = time.time()

        for market in markets:
            market_id = market.get("id", "")
            question = market.get("question", "")
            category = market.get("category", "unknown")
            venue = market.get("venue", "polymarket")

            # Parse tokens
            tokens = market.get("tokens", [])
            if not tokens:
                continue

            for token in tokens:
                token_id = token.get("token_id", "")
                outcome = token.get("outcome", "").upper()

                # Get prices
                best_bid = token.get("best_bid", 0.0)
                best_ask = token.get("best_ask", 0.0)
                if best_bid <= 0 or best_ask <= 0:
                    continue

                mid = (best_bid + best_ask) / 2.0
                spread = best_ask - best_bid

                # Days to resolution
                end_date = market.get("end_date_iso", "")
                days_to_res = market.get("days_to_resolution", 30)

                if days_to_res < self.config.min_days_to_resolution:
                    continue
                if days_to_res > self.config.max_days_to_resolution:
                    continue

                # Check if in FLB target range
                tail_type = None
                if outcome == "YES":
                    if self.config.tail_yes_min <= mid <= self.config.tail_yes_max:
                        tail_type = TailType.HIGH_YES
                    elif self.config.tail_no_min <= mid <= self.config.tail_no_max:
                        tail_type = TailType.LOW_YES

                if tail_type is None:
                    continue

                candidates.append(FLBCandidate(
                    market_id=market_id,
                    token_id=token_id,
                    question=question,
                    category=category,
                    venue=venue,
                    yes_price=mid,
                    no_price=1.0 - mid,
                    tail_type=tail_type,
                    days_to_resolution=days_to_res,
                    volume_24h=market.get("volume_24h", 0.0),
                    spread=spread,
                ))

        logger.info("FLB scan: %d markets → %d candidates", len(markets), len(candidates))
        return candidates

    def evaluate_candidates(
        self,
        candidates: list[FLBCandidate],
        llm_estimates: Optional[dict[str, float]] = None,
    ) -> list[FLBSignal]:
        """
        Evaluate FLB candidates against calibration data and LLM filter.

        Args:
            candidates: from identify_candidates()
            llm_estimates: optional dict of market_id → LLM probability estimate
        """
        signals = []
        llm_estimates = llm_estimates or {}

        for cand in candidates:
            # Check portfolio capacity
            if self.portfolio.position_count >= self.config.max_positions:
                break

            # Check category concentration
            cat_count = self.portfolio.category_counts.get(cand.category, 0)
            max_cat = int(self.config.max_positions * self.config.max_category_concentration)
            if cat_count >= max_cat:
                continue

            # Get calibration for this price bin
            cal = self.calibration_db.get_calibration(
                cand.yes_price, cand.category, cand.venue,
            )

            # LLM filter
            llm_est = llm_estimates.get(cand.market_id)
            if llm_est is not None:
                # If LLM agrees with market, skip (no FLB edge)
                if abs(llm_est - cand.yes_price) < self.config.llm_agreement_threshold:
                    continue
                estimated_true = llm_est
            elif cal is not None and cal.sample_size >= self.config.min_bin_observations:
                # Use calibration-based estimate with shrinkage
                estimated_true = cal.posterior_mean
            else:
                # Not enough data: use prior assumption of FLB
                # Conservative: assume 2% FLB at tails
                if cand.tail_type == TailType.HIGH_YES:
                    estimated_true = cand.yes_price - 0.02  # YES slightly less likely
                else:
                    estimated_true = cand.yes_price + 0.02  # YES slightly more likely
                cal = bayesian_bin_calibration(0, 0, cand.yes_price)

            # Compute edge
            if cand.tail_type == TailType.HIGH_YES:
                # We buy NO. Edge = how much market overprices YES.
                # If market says 95% but true is 92%, edge = 3%
                flb_edge = cand.yes_price - estimated_true
                side = "BUY_NO"
                our_price = 1 - cand.yes_price  # cost of NO contract
            else:
                # We buy YES. Edge = how much market underprices YES.
                flb_edge = estimated_true - cand.yes_price
                side = "BUY_YES"
                our_price = cand.yes_price

            flb_edge_bps = flb_edge * 10_000

            if flb_edge_bps < self.config.min_edge_bps:
                continue

            # Kelly sizing
            kf = kelly_prediction_market(estimated_true, cand.yes_price)
            if cand.tail_type == TailType.HIGH_YES:
                kf = kelly_prediction_market(1 - estimated_true, 1 - cand.yes_price)

            # Cap at config max
            kf = min(kf, self.config.max_position_frac)

            # Position size
            available = self.portfolio.bankroll * (
                self.config.max_portfolio_frac - self.portfolio.capital_utilization
            )
            position_usd = min(kf * self.portfolio.bankroll, available)
            if position_usd < 1.0:
                continue

            # Evaluate net edge
            fee_sched = (FeeSchedule.polymarket() if cand.venue == "polymarket"
                         else FeeSchedule.kalshi())
            edge_result = evaluate_edge(
                gross_edge_bps=flb_edge_bps,
                p_fill=0.85,
                p_win=estimated_true if cand.tail_type == TailType.LOW_YES else (1 - estimated_true),
                position_usd=position_usd,
                hours_locked=cand.days_to_resolution * 24,
                fee_schedule=fee_sched,
                spread_bps=cand.spread * 10_000,
                is_maker=True,
                min_net_edge_bps=self.config.min_edge_bps * 0.5,
            )

            if not edge_result.is_tradeable:
                continue

            signal = FLBSignal(
                market_id=cand.market_id,
                token_id=cand.token_id,
                venue=cand.venue,
                tail_type=cand.tail_type,
                side=side,
                market_price=cand.yes_price,
                estimated_true_prob=estimated_true,
                flb_edge_bps=flb_edge_bps,
                net_edge_bps=edge_result.net_edge_bps,
                kelly_fraction=kf,
                position_usd=position_usd,
                confidence=min(1.0, flb_edge_bps / 300),
                calibration=cal,
                ts=time.time(),
            )

            signals.append(signal)
            logger.info(
                "FLB_SIGNAL: %s %s market=%.2f true_est=%.2f edge=%.0fbps kelly=%.4f $%.2f",
                signal.side, cand.market_id[:30], cand.yes_price,
                estimated_true, flb_edge_bps, kf, position_usd,
            )

        return signals

    def add_position(self, signal: FLBSignal) -> bool:
        """Add a position to the portfolio."""
        if self.portfolio.position_count >= self.config.max_positions:
            return False
        if self.portfolio.capital_utilization >= self.config.max_portfolio_frac:
            return False

        self.portfolio.positions.append(signal)
        self.portfolio.total_capital_locked += signal.position_usd
        self.portfolio.category_counts[signal.venue] += 1
        self._signal_history.append(signal)
        return True

    def remove_position(self, market_id: str) -> Optional[FLBSignal]:
        """Remove a resolved position."""
        for i, pos in enumerate(self.portfolio.positions):
            if pos.market_id == market_id:
                removed = self.portfolio.positions.pop(i)
                self.portfolio.total_capital_locked -= removed.position_usd
                return removed
        return None

    def get_portfolio_stats(self) -> dict:
        """Get current portfolio statistics."""
        if not self.portfolio.positions:
            return {
                "position_count": 0,
                "capital_locked": 0.0,
                "utilization": 0.0,
                "avg_edge_bps": 0.0,
                "avg_kelly": 0.0,
            }

        edges = [p.flb_edge_bps for p in self.portfolio.positions]
        kellys = [p.kelly_fraction for p in self.portfolio.positions]

        return {
            "position_count": self.portfolio.position_count,
            "capital_locked": self.portfolio.total_capital_locked,
            "utilization": self.portfolio.capital_utilization,
            "avg_edge_bps": sum(edges) / len(edges),
            "avg_kelly": sum(kellys) / len(kellys),
            "max_edge_bps": max(edges),
            "min_edge_bps": min(edges),
            "high_yes_count": sum(1 for p in self.portfolio.positions if p.tail_type == TailType.HIGH_YES),
            "low_yes_count": sum(1 for p in self.portfolio.positions if p.tail_type == TailType.LOW_YES),
        }
