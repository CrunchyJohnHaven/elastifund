#!/usr/bin/env python3
"""
Whale Tracker — Signal Source for JJ
=====================================
Tracks "smart money" wallets on Polymarket by monitoring on-chain trade
activity. Detects anomalous trading patterns (fresh wallets making large bets,
concentrated positions, pre-resolution timing) and generates copy-trade signals
when multiple tracked wallets agree on a direction.

Architecture:
  WalletProfile  — scoring record per wallet (freshness, concentration, win rate)
  WhaleAlert     — fired when a single trade looks anomalous
  ConsensusSignal — fired when N wallets agree on the same market/direction

Data source: https://gamma-api.polymarket.com/trades
  ?market=<conditionId>&limit=N

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

logger = logging.getLogger("JJ.whale_tracker")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FRESHNESS_HALF_LIFE_SECONDS: float = 3 * 24 * 3600.0   # 3-day half-life
FRESHNESS_WINDOW_HOURS_DEFAULT: float = 168.0            # 7 days = "fresh"
NICHE_MARKET_VOLUME_THRESHOLD: float = 50_000.0          # < $50k → niche
LARGE_SINGLE_TRADE_USD: float = 20_000.0                 # single trade alert
SUSPICIOUS_SIZE_USD: float = 5_000.0                     # freshness + conc. gate
SUSPICIOUS_FRESHNESS: float = 0.7
SUSPICIOUS_CONCENTRATION: float = 0.8
MIN_CONSENSUS_WALLETS: int = 3                           # require at least 3
KELLY_BANKROLL_DEFAULT: float = 400.0                    # rough bankroll estimate
MAX_RECOMMENDED_USD: float = 50.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WalletProfile:
    address: str
    first_seen: float = 0.0              # Unix timestamp of first trade
    total_trades: int = 0
    total_volume_usd: float = 0.0
    win_rate: float = 0.0                # Fraction of resolved trades that were profitable
    avg_trade_size_usd: float = 0.0
    markets_traded: int = 0              # Unique markets
    concentration_score: float = 0.0    # 0-1, how concentrated in few markets
    freshness_score: float = 0.0        # 0-1, how "new" the wallet is
    profitability_score: float = 0.0    # Composite score
    is_suspicious: bool = False
    tags: list[str] = field(default_factory=list)
    # Internal bookkeeping (not part of public API)
    _markets: list[str] = field(default_factory=list, repr=False)
    _resolved_wins: int = 0
    _resolved_total: int = 0
    _trust_score: float = 0.5           # For manually-added wallets
    _label: str = ""


@dataclass
class WhaleAlert:
    wallet: str
    market_id: str
    market_question: str
    side: str                      # "YES" or "NO"
    size_usd: float
    price: float
    timestamp: float
    anomaly_score: float           # 0-1
    anomaly_reasons: list[str]


@dataclass
class ConsensusSignal:
    market_id: str
    market_question: str
    direction: str                 # "YES" or "NO"
    agreeing_wallets: int
    total_tracked: int
    consensus_pct: float
    avg_size_usd: float
    total_volume_usd: float
    confidence: float
    signal_time: float
    recommended_size_usd: float


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class WhaleTracker:
    """Tracks whale wallets and generates copy-trade signals."""

    def __init__(
        self,
        min_trade_size_usd: float = 1000.0,
        freshness_window_hours: float = FRESHNESS_WINDOW_HOURS_DEFAULT,
        anomaly_threshold: float = 0.6,
        consensus_threshold: float = 0.7,
        max_tracked_wallets: int = 200,
        api_base: str = "https://gamma-api.polymarket.com",
        _now_fn: Any = None,     # Injection point for tests
    ) -> None:
        self.min_trade_size_usd = min_trade_size_usd
        self.freshness_window_hours = freshness_window_hours
        self.anomaly_threshold = anomaly_threshold
        self.consensus_threshold = consensus_threshold
        self.max_tracked_wallets = max_tracked_wallets
        self.api_base = api_base

        self.wallet_profiles: dict[str, WalletProfile] = {}
        self.alerts: list[WhaleAlert] = []
        self.trade_history: list[dict] = []

        # {market_id: {wallet: {"side": str, "size_usd": float, "question": str}}}
        self._market_positions: dict[str, dict[str, dict]] = {}

        # Signal history for diagnostics
        self._signals_emitted: int = 0
        self._trades_ingested: int = 0

        # Overridable clock (for deterministic tests)
        self._now: Any = _now_fn if _now_fn is not None else time.time

    # ------------------------------------------------------------------
    # Wallet scoring
    # ------------------------------------------------------------------

    def score_wallet(self, address: str, trades: list[dict]) -> WalletProfile:
        """Score a wallet based on its trading history.

        Scoring components:
        1. Freshness: wallet age < 7 days = 1.0, decays exponentially (half-life 3 days)
        2. Concentration: trades in fewer unique markets = higher score
        3. Size: larger average trade = higher score (log scale)
        4. Win rate: higher = better (requires resolved trade data)
        5. Timing: trades placed within 24h of favorable resolution = higher

        is_suspicious = True if:
        - freshness > 0.7 AND single-market concentration > 0.8 AND size > $5000
        - OR any single trade > $20000 on a niche market (< $50k daily volume)
        """
        now = self._now()

        if not trades:
            profile = WalletProfile(address=address)
            profile.freshness_score = 1.0   # No history → treat as new
            return profile

        timestamps = [float(t.get("timestamp", now)) for t in trades]
        first_seen = min(timestamps)

        # Unique markets
        market_ids: list[str] = []
        for t in trades:
            mid = str(t.get("market_id", t.get("conditionId", "")))
            if mid:
                market_ids.append(mid)
        unique_markets = len(set(market_ids))

        # USD values
        usd_values: list[float] = []
        for t in trades:
            size = float(t.get("size", 0.0))
            price = float(t.get("price", 0.0))
            usd_values.append(size * price)

        total_volume = sum(usd_values)
        avg_size = total_volume / len(trades) if trades else 0.0

        # Win rate from resolved trades
        resolved_wins_count = 0
        resolved_total_count = 0
        for t in trades:
            if "_resolved_win" in t:
                resolved_total_count += 1
                if t["_resolved_win"]:
                    resolved_wins_count += 1

        win_rate = resolved_wins_count / resolved_total_count if resolved_total_count > 0 else 0.5

        # --- Component scores ---

        # 1. Freshness: exponential decay from first_seen
        wallet_age_seconds = max(0.0, now - first_seen)
        freshness_score = math.exp(
            -math.log(2) * wallet_age_seconds / FRESHNESS_HALF_LIFE_SECONDS
        )
        freshness_score = max(0.0, min(1.0, freshness_score))

        # 2. Concentration: 1 market = 1.0, spreads down as markets grow
        #    score = 1 / sqrt(unique_markets)
        concentration_score = 1.0 / math.sqrt(max(1, unique_markets))
        concentration_score = max(0.0, min(1.0, concentration_score))

        # 3. Size score: log-scale normalised to ~$10k → 1.0
        if avg_size > 0:
            size_score = min(1.0, math.log1p(avg_size) / math.log1p(10_000.0))
        else:
            size_score = 0.0

        # 4. Timing: fraction of trades placed within 24h of any resolution hint
        #    We approximate: if market_id appears only once → likely niche/pre-resolution
        market_id_counts: dict[str, int] = {}
        for mid in market_ids:
            market_id_counts[mid] = market_id_counts.get(mid, 0) + 1
        timing_score = 0.0
        if market_ids:
            single_market_trades = sum(
                1 for mid in market_ids if market_id_counts[mid] == 1
            )
            timing_score = single_market_trades / len(market_ids)

        # Profitability composite
        profitability_score = (
            0.35 * win_rate
            + 0.25 * size_score
            + 0.20 * freshness_score
            + 0.20 * (1.0 - concentration_score)  # diversity bonus
        )
        profitability_score = max(0.0, min(1.0, profitability_score))

        # Suspicious flag
        is_suspicious = False
        tags: list[str] = []

        if freshness_score > SUSPICIOUS_FRESHNESS:
            tags.append("fresh_wallet")
        if concentration_score > SUSPICIOUS_CONCENTRATION:
            tags.append("high_concentration")
        if avg_size > SUSPICIOUS_SIZE_USD:
            tags.append("large_size")

        # Rule 1: fresh + concentrated + large
        if (
            freshness_score > SUSPICIOUS_FRESHNESS
            and concentration_score > SUSPICIOUS_CONCENTRATION
            and avg_size > SUSPICIOUS_SIZE_USD
        ):
            is_suspicious = True

        # Rule 2: any single trade > $20k
        if any(v > LARGE_SINGLE_TRADE_USD for v in usd_values):
            is_suspicious = True
            tags.append("mega_trade")

        profile = WalletProfile(
            address=address,
            first_seen=first_seen,
            total_trades=len(trades),
            total_volume_usd=total_volume,
            win_rate=win_rate,
            avg_trade_size_usd=avg_size,
            markets_traded=unique_markets,
            concentration_score=concentration_score,
            freshness_score=freshness_score,
            profitability_score=profitability_score,
            is_suspicious=is_suspicious,
            tags=list(set(tags)),
        )
        profile._markets = list(set(market_ids))
        profile._resolved_wins = resolved_wins_count
        profile._resolved_total = resolved_total_count

        return profile

    # ------------------------------------------------------------------
    # Trade ingestion
    # ------------------------------------------------------------------

    def ingest_trade(self, trade: dict) -> Optional[WhaleAlert]:
        """Process a single trade from the Polymarket feed.

        trade format:
            maker_address, taker_address, market_id, market_question,
            side ("BUY"/"SELL"), outcome ("YES"/"NO"), price, size, timestamp

        Returns WhaleAlert if anomaly_score > threshold, else None.
        """
        size = float(trade.get("size", 0.0))
        price = float(trade.get("price", 0.0))
        size_usd = size * price

        if size_usd < self.min_trade_size_usd:
            logger.debug(
                "Trade below min_trade_size_usd: %.2f < %.2f",
                size_usd,
                self.min_trade_size_usd,
            )
            return None

        wallet = str(trade.get("taker_address", trade.get("maker_address", "")))
        market_id = str(trade.get("market_id", ""))
        market_question = str(trade.get("market_question", ""))
        outcome = str(trade.get("outcome", "YES")).upper()
        side = str(trade.get("side", "BUY")).upper()
        ts = float(trade.get("timestamp", self._now()))

        # Determine effective direction
        if side == "SELL":
            direction = "NO" if outcome == "YES" else "YES"
        else:
            direction = outcome  # YES or NO directly

        # Update or create wallet profile
        if wallet not in self.wallet_profiles:
            profile = self.score_wallet(wallet, [trade])
        else:
            profile = self.wallet_profiles[wallet]
            # Incremental update
            n = profile.total_trades
            profile.total_trades += 1
            profile.total_volume_usd += size_usd
            profile.avg_trade_size_usd = profile.total_volume_usd / profile.total_trades
            if market_id and market_id not in profile._markets:
                profile._markets.append(market_id)
                profile.markets_traded = len(profile._markets)
                profile.concentration_score = 1.0 / math.sqrt(max(1, profile.markets_traded))

        self.wallet_profiles[wallet] = profile

        # Cap tracked wallets (evict least profitable)
        if len(self.wallet_profiles) > self.max_tracked_wallets:
            self._evict_least_profitable()

        # Update market positions
        if market_id:
            if market_id not in self._market_positions:
                self._market_positions[market_id] = {}
            self._market_positions[market_id][wallet] = {
                "side": direction,
                "size_usd": size_usd,
                "question": market_question,
            }

        self.trade_history.append(trade)
        self._trades_ingested += 1

        # Compute anomaly
        anomaly_score, reasons = self.compute_anomaly_score(profile, trade)

        if anomaly_score >= self.anomaly_threshold:
            alert = WhaleAlert(
                wallet=wallet,
                market_id=market_id,
                market_question=market_question,
                side=direction,
                size_usd=size_usd,
                price=price,
                timestamp=ts,
                anomaly_score=anomaly_score,
                anomaly_reasons=reasons,
            )
            self.alerts.append(alert)
            logger.info(
                "WhaleAlert wallet=%s market=%s side=%s size=%.2f score=%.3f reasons=%s",
                wallet[:10],
                market_id[:10],
                direction,
                size_usd,
                anomaly_score,
                reasons,
            )
            return alert

        return None

    # ------------------------------------------------------------------
    # Anomaly scoring
    # ------------------------------------------------------------------

    def compute_anomaly_score(
        self, wallet: WalletProfile, trade: dict
    ) -> tuple[float, list[str]]:
        """Compute how anomalous a trade is.

        Factors (weighted sum):
        - Fresh wallet making large trade:      weight 0.30
        - Trade size >> wallet average:         weight 0.20
        - Single-market concentration:          weight 0.20
        - Niche market (low volume):            weight 0.15
        - Time proximity to expected resolution:weight 0.15

        Returns (score, reasons_list)
        """
        reasons: list[str] = []

        size = float(trade.get("size", 0.0))
        price = float(trade.get("price", 0.0))
        size_usd = size * price
        market_daily_volume = float(trade.get("market_daily_volume", 0.0))

        # Component 1: freshness × large trade
        freshness_component = wallet.freshness_score
        if freshness_component > 0.5 and size_usd > self.min_trade_size_usd * 2:
            reasons.append("fresh_wallet_large_trade")
        freshness_component = max(0.0, min(1.0, freshness_component))

        # Component 2: size relative to wallet average
        if wallet.avg_trade_size_usd > 0:
            ratio = size_usd / wallet.avg_trade_size_usd
            size_rel_component = min(1.0, math.log1p(max(0.0, ratio - 1.0)) / math.log1p(9.0))
            if ratio > 3.0:
                reasons.append("size_spike")
        else:
            # First trade → no history → treat as unusual
            size_rel_component = 0.5

        # Component 3: concentration
        concentration_component = wallet.concentration_score
        if concentration_component > SUSPICIOUS_CONCENTRATION:
            reasons.append("concentrated_position")

        # Component 4: niche market
        if 0 < market_daily_volume < NICHE_MARKET_VOLUME_THRESHOLD:
            niche_component = 1.0 - (market_daily_volume / NICHE_MARKET_VOLUME_THRESHOLD)
            if size_usd > LARGE_SINGLE_TRADE_USD:
                reasons.append("large_trade_niche_market")
        elif market_daily_volume == 0:
            niche_component = 0.5  # Unknown volume → moderate signal
        else:
            niche_component = 0.0

        # Component 5: time proximity to resolution
        resolution_ts = float(trade.get("expected_resolution_ts", 0.0))
        now = self._now()
        if resolution_ts > now:
            hours_to_resolution = (resolution_ts - now) / 3600.0
            if hours_to_resolution < 24:
                resolution_proximity = max(0.0, 1.0 - hours_to_resolution / 24.0)
                if resolution_proximity > 0.5:
                    reasons.append("pre_resolution_timing")
            else:
                resolution_proximity = 0.0
        else:
            resolution_proximity = 0.0

        score = (
            0.30 * freshness_component
            + 0.20 * size_rel_component
            + 0.20 * concentration_component
            + 0.15 * niche_component
            + 0.15 * resolution_proximity
        )
        score = max(0.0, min(1.0, score))

        return score, reasons

    # ------------------------------------------------------------------
    # Consensus signals
    # ------------------------------------------------------------------

    def get_consensus_signals(self) -> list[ConsensusSignal]:
        """Analyse all tracked wallets to find markets with consensus.

        For each market with 3+ tracked wallets having positions:
        1. Count wallets on YES vs NO.
        2. If consensus_pct > threshold → generate signal.
        3. Recommended size = min(bankroll * kelly, $50).

        Returns signals sorted by confidence descending.
        """
        signals: list[ConsensusSignal] = []
        now = self._now()

        for market_id, positions in self._market_positions.items():
            if len(positions) < MIN_CONSENSUS_WALLETS:
                continue

            yes_wallets: list[dict] = []
            no_wallets: list[dict] = []
            question = ""

            for wallet_addr, pos in positions.items():
                question = pos.get("question", question)
                if pos["side"] == "YES":
                    yes_wallets.append(pos)
                else:
                    no_wallets.append(pos)

            total = len(positions)
            yes_count = len(yes_wallets)
            no_count = len(no_wallets)

            if yes_count >= no_count:
                direction = "YES"
                agreeing = yes_wallets
                agreeing_count = yes_count
            else:
                direction = "NO"
                agreeing = no_wallets
                agreeing_count = no_count

            consensus_pct = agreeing_count / total
            if consensus_pct < self.consensus_threshold:
                continue

            total_vol = sum(p["size_usd"] for p in agreeing)
            avg_size = total_vol / agreeing_count if agreeing_count else 0.0

            # Confidence: consensus_pct × average profitability of agreeing wallets
            prof_scores = []
            for wallet_addr, pos in positions.items():
                if pos["side"] == direction:
                    profile = self.wallet_profiles.get(wallet_addr)
                    if profile:
                        prof_scores.append(profile.profitability_score)
            avg_profitability = sum(prof_scores) / len(prof_scores) if prof_scores else 0.5

            confidence = min(1.0, consensus_pct * avg_profitability * (agreeing_count / MIN_CONSENSUS_WALLETS))

            # Kelly-adjusted size: use crude edge estimate = consensus_pct - 0.5
            edge = max(0.0, consensus_pct - 0.5)
            kelly_fraction = edge / max(0.01, (1.0 - consensus_pct))  # simplified Kelly
            recommended = min(MAX_RECOMMENDED_USD, KELLY_BANKROLL_DEFAULT * kelly_fraction * 0.25)
            recommended = max(0.0, recommended)

            sig = ConsensusSignal(
                market_id=market_id,
                market_question=question,
                direction=direction,
                agreeing_wallets=agreeing_count,
                total_tracked=total,
                consensus_pct=consensus_pct,
                avg_size_usd=avg_size,
                total_volume_usd=total_vol,
                confidence=confidence,
                signal_time=now,
                recommended_size_usd=recommended,
            )
            signals.append(sig)
            self._signals_emitted += 1
            logger.info(
                "ConsensusSignal market=%s direction=%s wallets=%d/%d pct=%.2f conf=%.3f",
                market_id[:12],
                direction,
                agreeing_count,
                total,
                consensus_pct,
                confidence,
            )

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    # ------------------------------------------------------------------
    # Manual wallet management
    # ------------------------------------------------------------------

    def add_known_wallet(
        self,
        address: str,
        label: str = "",
        trust_score: float = 0.5,
    ) -> None:
        """Manually add a wallet to track (e.g., known profitable traders)."""
        if address not in self.wallet_profiles:
            profile = WalletProfile(address=address)
            self.wallet_profiles[address] = profile
        profile = self.wallet_profiles[address]
        profile._label = label
        profile._trust_score = trust_score
        logger.debug("add_known_wallet address=%s label=%s trust=%.2f", address[:10], label, trust_score)

    def get_top_wallets(self, k: int = 20) -> list[WalletProfile]:
        """Return the top-k most profitable tracked wallets."""
        profiles = list(self.wallet_profiles.values())
        profiles.sort(key=lambda p: p.profitability_score, reverse=True)
        return profiles[:k]

    # ------------------------------------------------------------------
    # Market activity
    # ------------------------------------------------------------------

    def get_market_whale_activity(self, market_id: str) -> dict:
        """Summarise whale activity for a specific market."""
        positions = self._market_positions.get(market_id, {})
        relevant_alerts = [a for a in self.alerts if a.market_id == market_id]

        yes_vol = sum(p["size_usd"] for p in positions.values() if p["side"] == "YES")
        no_vol = sum(p["size_usd"] for p in positions.values() if p["side"] == "NO")
        total_vol = yes_vol + no_vol
        dominant_side = "YES" if yes_vol >= no_vol else "NO"

        return {
            "total_whale_volume": total_vol,
            "yes_volume": yes_vol,
            "no_volume": no_vol,
            "dominant_side": dominant_side,
            "num_whales": len(positions),
            "alerts": [
                {
                    "wallet": a.wallet,
                    "side": a.side,
                    "size_usd": a.size_usd,
                    "anomaly_score": a.anomaly_score,
                    "reasons": a.anomaly_reasons,
                }
                for a in relevant_alerts
            ],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def export_watchlist(self) -> list[dict]:
        """Export all tracked wallets as serialisable dicts."""
        result = []
        for addr, profile in self.wallet_profiles.items():
            d = asdict(profile)
            # Remove private fields (leading _) that asdict includes
            d = {k: v for k, v in d.items() if not k.startswith("_")}
            result.append(d)
        return result

    def import_watchlist(self, wallets: list[dict]) -> int:
        """Import a list of wallet profile dicts. Returns count imported."""
        imported = 0
        for w in wallets:
            address = w.get("address", "")
            if not address:
                continue
            profile = WalletProfile(
                address=address,
                first_seen=float(w.get("first_seen", 0.0)),
                total_trades=int(w.get("total_trades", 0)),
                total_volume_usd=float(w.get("total_volume_usd", 0.0)),
                win_rate=float(w.get("win_rate", 0.0)),
                avg_trade_size_usd=float(w.get("avg_trade_size_usd", 0.0)),
                markets_traded=int(w.get("markets_traded", 0)),
                concentration_score=float(w.get("concentration_score", 0.0)),
                freshness_score=float(w.get("freshness_score", 0.0)),
                profitability_score=float(w.get("profitability_score", 0.0)),
                is_suspicious=bool(w.get("is_suspicious", False)),
                tags=list(w.get("tags", [])),
            )
            self.wallet_profiles[address] = profile
            imported += 1
        logger.debug("import_watchlist: imported %d wallets", imported)
        return imported

    # ------------------------------------------------------------------
    # Async API fetch
    # ------------------------------------------------------------------

    async def fetch_recent_trades(
        self,
        market_id: Optional[str] = None,
        limit: int = 100,
        _injected: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Fetch recent trades from the Polymarket Gamma API.

        GET /trades?market={market_id}&limit={limit}

        For testing, pass _injected to bypass network call.
        """
        if _injected is not None:
            return _injected

        if httpx is None:
            raise RuntimeError("httpx is required for live API calls")

        params: dict[str, Any] = {"limit": limit}
        if market_id:
            params["market"] = market_id

        url = f"{self.api_base}/trades"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("data", [])
        except Exception as exc:
            logger.warning("fetch_recent_trades failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict:
        """Return tracker stats."""
        suspicious_count = sum(
            1 for p in self.wallet_profiles.values() if p.is_suspicious
        )
        top_profile = self.get_top_wallets(k=1)
        top_wallet = top_profile[0].address if top_profile else None

        return {
            "wallets_tracked": len(self.wallet_profiles),
            "alerts_generated": len(self.alerts),
            "signals_emitted": self._signals_emitted,
            "trades_ingested": self._trades_ingested,
            "suspicious_wallets": suspicious_count,
            "markets_with_positions": len(self._market_positions),
            "top_wallet_by_profitability": top_wallet,
            "min_trade_size_usd": self.min_trade_size_usd,
            "anomaly_threshold": self.anomaly_threshold,
            "consensus_threshold": self.consensus_threshold,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_least_profitable(self) -> None:
        """Remove the least profitable wallet when cap is exceeded."""
        if not self.wallet_profiles:
            return
        worst = min(self.wallet_profiles, key=lambda a: self.wallet_profiles[a].profitability_score)
        logger.debug("Evicting wallet %s (profitability=%.3f)", worst[:10], self.wallet_profiles[worst].profitability_score)
        del self.wallet_profiles[worst]
