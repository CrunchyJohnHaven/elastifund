"""A-6 monitor orchestration: discovery + pricing + opportunity detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from infra.clob_ws import BestBidAskStore
from signals.sum_violation.sum_discovery import A6PriceSnapshotter, GammaEventDiscovery
from strategies.a6_sum_violation import A6Opportunity, A6SignalEngine, EventWatch


@dataclass(frozen=True)
class A6MonitorSnapshot:
    watch_count: int
    quotes_updated: int
    opportunities: tuple[A6Opportunity, ...]


class A6Monitor:
    """Refresh the A-6 universe and compute execution-aware opportunities."""

    def __init__(
        self,
        *,
        discovery: GammaEventDiscovery | None = None,
        snapshotter: A6PriceSnapshotter | None = None,
        signal_engine: A6SignalEngine | None = None,
        quote_store: BestBidAskStore | None = None,
    ) -> None:
        self.discovery = discovery or GammaEventDiscovery()
        self.snapshotter = snapshotter or A6PriceSnapshotter()
        self.signal_engine = signal_engine or A6SignalEngine()
        self.quote_store = quote_store or BestBidAskStore()
        self._watchlist: dict[str, EventWatch] = {}

    @property
    def watchlist(self) -> dict[str, EventWatch]:
        return dict(self._watchlist)

    def refresh_watchlist(self) -> list[EventWatch]:
        watches = self.discovery.build_watchlist()
        self._watchlist = {watch.event_id: watch for watch in watches}
        return watches

    def refresh_quotes(self, watches: Sequence[EventWatch] | None = None) -> int:
        active = list(watches) if watches is not None else list(self._watchlist.values())
        return self.snapshotter.refresh_store(active, self.quote_store)

    def scan(self, watches: Sequence[EventWatch] | None = None) -> A6MonitorSnapshot:
        active = list(watches) if watches is not None else self.refresh_watchlist()
        quotes_updated = self.refresh_quotes(active)
        opportunities: list[A6Opportunity] = []
        for watch in active:
            opp = self.signal_engine.evaluate_event(watch, self.quote_store)
            if opp is not None:
                opportunities.append(opp)
        opportunities.sort(key=lambda item: item.maker_sum_bid)
        return A6MonitorSnapshot(
            watch_count=len(active),
            quotes_updated=quotes_updated,
            opportunities=tuple(opportunities),
        )
