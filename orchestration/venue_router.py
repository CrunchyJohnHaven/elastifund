"""Cross-venue routing helpers for opportunity arbitration and shared exposure caps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VenueRouteCandidate:
    """One venue's trade candidate for a logically equivalent opportunity."""

    venue: str
    market_id: str
    opportunity_key: str
    gross_edge: float
    fee_rate: float = 0.0
    fill_probability: float = 1.0
    latency_penalty: float = 0.0
    notional_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def net_edge(self) -> float:
        """Edge after fees, expected fill degradation, and latency risk."""
        gross = float(self.gross_edge)
        fee = max(0.0, float(self.fee_rate))
        fill = min(1.0, max(0.0, float(self.fill_probability)))
        latency = max(0.0, float(self.latency_penalty))
        fill_drag = (1.0 - fill) * max(0.0, gross)
        return gross - fee - fill_drag - latency


@dataclass
class SharedRiskBudget:
    """Rolling exposure caps shared across venues."""

    hourly_cap_usd: float
    daily_cap_usd: float
    hourly_used_usd: float = 0.0
    daily_used_usd: float = 0.0

    @property
    def remaining_hourly_usd(self) -> float:
        return max(0.0, float(self.hourly_cap_usd) - float(self.hourly_used_usd))

    @property
    def remaining_daily_usd(self) -> float:
        return max(0.0, float(self.daily_cap_usd) - float(self.daily_used_usd))

    def can_allocate(self, notional_usd: float) -> tuple[bool, str | None]:
        amount = max(0.0, float(notional_usd))
        if amount > self.remaining_hourly_usd:
            return False, "shared_budget_exhausted_hourly"
        if amount > self.remaining_daily_usd:
            return False, "shared_budget_exhausted_daily"
        return True, None

    def reserve(self, notional_usd: float) -> None:
        amount = max(0.0, float(notional_usd))
        self.hourly_used_usd += amount
        self.daily_used_usd += amount


@dataclass(frozen=True)
class RouteRejection:
    venue: str
    market_id: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteDecision:
    opportunity_key: str
    selected: VenueRouteCandidate | None
    selected_reason: str
    rejections: tuple[RouteRejection, ...] = ()



def route_opportunity(
    candidates: list[VenueRouteCandidate],
    *,
    budget: SharedRiskBudget,
    min_net_edge: float = 0.0,
) -> RouteDecision:
    """Pick the best venue for one opportunity and reserve shared budget if accepted."""
    if not candidates:
        return RouteDecision(opportunity_key="", selected=None, selected_reason="no_candidates")

    deduped: dict[tuple[str, str], VenueRouteCandidate] = {}
    duplicate_rejections: list[RouteRejection] = []
    for candidate in sorted(candidates, key=lambda item: item.net_edge, reverse=True):
        dedupe_key = (candidate.opportunity_key, candidate.venue)
        existing = deduped.get(dedupe_key)
        if existing is None:
            deduped[dedupe_key] = candidate
            continue
        duplicate_rejections.append(
            RouteRejection(
                venue=candidate.venue,
                market_id=candidate.market_id,
                reason="duplicate_opportunity_lower_edge",
                details={
                    "opportunity_key": candidate.opportunity_key,
                    "candidate_net_edge": candidate.net_edge,
                    "kept_market_id": existing.market_id,
                    "kept_venue": existing.venue,
                    "kept_net_edge": existing.net_edge,
                },
            )
        )

    ranked = sorted(deduped.values(), key=lambda item: item.net_edge, reverse=True)
    if not ranked:
        key = candidates[0].opportunity_key
        return RouteDecision(
            opportunity_key=key,
            selected=None,
            selected_reason="all_candidates_deduplicated",
            rejections=tuple(duplicate_rejections),
        )

    key = ranked[0].opportunity_key
    winner = ranked[0]
    rejections = list(duplicate_rejections)

    if winner.net_edge < float(min_net_edge):
        for candidate in ranked:
            rejections.append(
                RouteRejection(
                    venue=candidate.venue,
                    market_id=candidate.market_id,
                    reason="below_min_net_edge",
                    details={
                        "opportunity_key": candidate.opportunity_key,
                        "net_edge": candidate.net_edge,
                        "min_net_edge": float(min_net_edge),
                    },
                )
            )
        return RouteDecision(
            opportunity_key=key,
            selected=None,
            selected_reason="below_min_net_edge",
            rejections=tuple(rejections),
        )

    allowed, block_reason = budget.can_allocate(winner.notional_usd)
    if not allowed:
        for candidate in ranked:
            rejections.append(
                RouteRejection(
                    venue=candidate.venue,
                    market_id=candidate.market_id,
                    reason=block_reason or "shared_budget_blocked",
                    details={
                        "requested_notional_usd": candidate.notional_usd,
                        "remaining_hourly_usd": budget.remaining_hourly_usd,
                        "remaining_daily_usd": budget.remaining_daily_usd,
                    },
                )
            )
        return RouteDecision(
            opportunity_key=key,
            selected=None,
            selected_reason=block_reason or "shared_budget_blocked",
            rejections=tuple(rejections),
        )

    budget.reserve(winner.notional_usd)
    for candidate in ranked[1:]:
        rejections.append(
            RouteRejection(
                venue=candidate.venue,
                market_id=candidate.market_id,
                reason="venue_not_best_net_edge",
                details={
                    "opportunity_key": candidate.opportunity_key,
                    "selected_market_id": winner.market_id,
                    "selected_venue": winner.venue,
                    "selected_net_edge": winner.net_edge,
                    "candidate_net_edge": candidate.net_edge,
                },
            )
        )

    return RouteDecision(
        opportunity_key=key,
        selected=winner,
        selected_reason="best_net_edge_after_costs",
        rejections=tuple(rejections),
    )
