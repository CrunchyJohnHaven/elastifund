#!/usr/bin/env python3
"""
CanonicalEventKey — Cross-Venue Event Identity Mapping
=======================================================
Maps "same event" across Polymarket, Kalshi, and Alpaca to a shared
identity. This enables:
  - Cross-venue parity detection (same event, different prices)
  - Correlation tracking (positions on correlated events across venues)
  - Settlement rule divergence alerts

A CanonicalEventKey is:
  hash(underlying_source + settlement_rule + time_window + entity)

Examples:
  - "BTC price at 2026-03-24 12:00 UTC" maps to the same key whether
    it's a Polymarket 5-min candle or a Kalshi hourly contract
  - "Will it rain in NYC tomorrow?" maps weather contracts across venues
  - "Fed rate decision March 2026" maps across rate prediction contracts

This is NOT a full arbitrage engine. It's the mapping layer that enables
the cross-venue parity niche to function correctly.

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    ALPACA = "alpaca"


class SettlementSource(str, Enum):
    """Known settlement data sources."""
    BINANCE = "binance"           # BTC/ETH price
    COINBASE = "coinbase"         # Crypto prices
    NOAA = "noaa"                 # Weather
    BLS = "bls"                   # Economic data
    FED = "federal_reserve"       # Rate decisions
    AP = "associated_press"       # Election results
    OFFICIAL = "official_result"  # Government/official outcomes
    CUSTOM = "custom"             # Venue-specific rules


@dataclass
class CanonicalEventKey:
    """
    Cross-venue event identity.

    Two contracts on different venues map to the same event if they share:
    - The same underlying source of truth
    - The same settlement rule (or semantically equivalent)
    - Overlapping time windows
    - The same entity/subject
    """
    underlying_source: SettlementSource
    settlement_rule: str          # Normalized rule description
    time_window_start: str        # ISO timestamp
    time_window_end: str          # ISO timestamp
    entity: str                   # Subject (e.g., "BTC", "NYC", "Fed")
    geography: str = ""           # Optional geographic scope

    @property
    def key(self) -> str:
        """Deterministic hash for cross-venue matching."""
        parts = [
            self.underlying_source.value,
            self.settlement_rule.lower().strip(),
            self.time_window_start,
            self.time_window_end,
            self.entity.lower().strip(),
            self.geography.lower().strip(),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "source": self.underlying_source.value,
            "rule": self.settlement_rule,
            "window": f"{self.time_window_start} to {self.time_window_end}",
            "entity": self.entity,
            "geography": self.geography,
        }


@dataclass
class VenueContract:
    """A specific contract on a specific venue."""
    venue: Venue
    contract_id: str
    canonical_key: str            # Links to CanonicalEventKey.key
    title: str
    yes_price: float = 0.5
    no_price: float = 0.5
    volume: float = 0.0
    liquidity: float = 0.0
    fee_regime: str = "standard"  # standard, crypto, sports, etc.
    settlement_semantics: str = ""  # Venue-specific settlement notes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossVenuePair:
    """Two contracts on different venues for the same event."""
    canonical_key: str
    contracts: list[VenueContract] = field(default_factory=list)

    @property
    def price_divergence(self) -> float:
        """Absolute price difference between venues (YES side)."""
        if len(self.contracts) < 2:
            return 0.0
        prices = [c.yes_price for c in self.contracts]
        return max(prices) - min(prices)

    @property
    def has_parity_opportunity(self) -> bool:
        """True if price divergence exceeds minimum threshold."""
        return self.price_divergence > 0.03  # 3 cents minimum

    def fee_adjusted_edge(self) -> float:
        """Edge after accounting for fees on both venues."""
        if len(self.contracts) < 2:
            return 0.0

        # Sort by price: buy cheap, sell expensive
        sorted_c = sorted(self.contracts, key=lambda c: c.yes_price)
        cheap = sorted_c[0]
        expensive = sorted_c[-1]

        gross_edge = expensive.yes_price - cheap.yes_price

        # Estimate fees (conservative)
        fee_rates = {"standard": 0.0, "crypto": 0.025, "sports": 0.007}
        fee_cheap = cheap.yes_price * (1 - cheap.yes_price) * fee_rates.get(cheap.fee_regime, 0.02)
        fee_expensive = expensive.yes_price * (1 - expensive.yes_price) * fee_rates.get(expensive.fee_regime, 0.02)

        return gross_edge - fee_cheap - fee_expensive


# ---------------------------------------------------------------------------
# Event key extraction from market data
# ---------------------------------------------------------------------------

class EventKeyExtractor:
    """
    Heuristic extraction of CanonicalEventKeys from market titles and metadata.

    This is inherently fuzzy. We use pattern matching and known templates
    to map venue-specific contract descriptions to canonical keys.
    """

    # Known BTC 5-min candle pattern
    _BTC_PATTERN = re.compile(
        r"(?:will\s+)?(?:the\s+)?(?:price\s+of\s+)?(?:btc|bitcoin)\s+"
        r"(?:go\s+)?(?:up|down|increase|decrease)",
        re.IGNORECASE,
    )

    # Weather pattern
    _WEATHER_PATTERN = re.compile(
        r"(?:will\s+it\s+)?(?:rain|snow|temperature|weather|high|low)\s+"
        r"(?:in|at|for)\s+(\w+(?:\s+\w+)?)",
        re.IGNORECASE,
    )

    # Fed/economic pattern
    _FED_PATTERN = re.compile(
        r"(?:fed|federal\s+reserve|interest\s+rate|cpi|inflation|gdp|jobs)",
        re.IGNORECASE,
    )

    def extract(self, title: str, metadata: dict) -> Optional[CanonicalEventKey]:
        """Attempt to extract a canonical key from market title and metadata."""
        title_lower = title.lower().strip()

        # BTC candle markets
        if self._BTC_PATTERN.search(title_lower):
            return self._extract_btc_candle(title, metadata)

        # Weather markets
        match = self._WEATHER_PATTERN.search(title_lower)
        if match:
            return self._extract_weather(title, metadata, match.group(1))

        # Fed/economic markets
        if self._FED_PATTERN.search(title_lower):
            return self._extract_economic(title, metadata)

        return None

    def _extract_btc_candle(self, title: str, metadata: dict) -> CanonicalEventKey:
        end_date = metadata.get("end_date", "")
        return CanonicalEventKey(
            underlying_source=SettlementSource.BINANCE,
            settlement_rule="btc_spot_price_direction",
            time_window_start=metadata.get("start_date", ""),
            time_window_end=end_date,
            entity="BTC",
        )

    def _extract_weather(self, title: str, metadata: dict, location: str) -> CanonicalEventKey:
        return CanonicalEventKey(
            underlying_source=SettlementSource.NOAA,
            settlement_rule="weather_observation",
            time_window_start=metadata.get("start_date", ""),
            time_window_end=metadata.get("end_date", ""),
            entity="weather",
            geography=location.strip(),
        )

    def _extract_economic(self, title: str, metadata: dict) -> CanonicalEventKey:
        return CanonicalEventKey(
            underlying_source=SettlementSource.FED,
            settlement_rule="economic_indicator",
            time_window_start=metadata.get("start_date", ""),
            time_window_end=metadata.get("end_date", ""),
            entity="economic",
        )


# ---------------------------------------------------------------------------
# Cross-venue mapping registry
# ---------------------------------------------------------------------------

class CrossVenueRegistry:
    """
    Maintains the mapping between venue-specific contracts and canonical events.
    Detects cross-venue parity opportunities.
    """

    def __init__(self):
        self._contracts: dict[str, list[VenueContract]] = {}  # canonical_key -> contracts
        self._extractor = EventKeyExtractor()

    def register_contract(self, contract: VenueContract) -> None:
        """Register a venue contract under its canonical key."""
        key = contract.canonical_key
        if key not in self._contracts:
            self._contracts[key] = []

        # Avoid duplicates
        existing_ids = {c.contract_id for c in self._contracts[key]}
        if contract.contract_id not in existing_ids:
            self._contracts[key].append(contract)

    def find_pairs(self, min_divergence: float = 0.03) -> list[CrossVenuePair]:
        """Find all cross-venue pairs with sufficient price divergence."""
        pairs = []
        for key, contracts in self._contracts.items():
            # Need at least 2 venues
            venues = {c.venue for c in contracts}
            if len(venues) < 2:
                continue

            pair = CrossVenuePair(canonical_key=key, contracts=contracts)
            if pair.price_divergence >= min_divergence:
                pairs.append(pair)

        return sorted(pairs, key=lambda p: p.price_divergence, reverse=True)

    def get_correlated_positions(self, canonical_key: str) -> list[VenueContract]:
        """Get all contracts across venues for a given event."""
        return self._contracts.get(canonical_key, [])

    def summary(self) -> dict[str, Any]:
        """Summary of cross-venue mapping state."""
        total_contracts = sum(len(v) for v in self._contracts.values())
        multi_venue = sum(
            1 for contracts in self._contracts.values()
            if len({c.venue for c in contracts}) > 1
        )
        return {
            "total_canonical_events": len(self._contracts),
            "total_contracts": total_contracts,
            "multi_venue_events": multi_venue,
            "parity_opportunities": len(self.find_pairs()),
        }
