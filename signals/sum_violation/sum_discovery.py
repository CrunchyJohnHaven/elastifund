"""A-6 event discovery and batched pricing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from infra.clob_ws import BestBidAskStore
from signals.sum_violation.sum_state import A6QuarantineCache
from strategies.a6_sum_violation import A6WatchlistBuilder, EventWatch


GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
CLOB_PRICES_URL = "https://clob.polymarket.com/prices"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
MAX_PRICE_BATCH_TOKENS = 500


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_level(levels: Sequence[Any], *, side: str) -> tuple[float | None, float | None]:
    priced_levels: list[tuple[float, float | None]] = []
    for level in levels:
        if isinstance(level, Mapping):
            price = _safe_float(level.get("price"))
            size = _safe_float(level.get("size"))
        elif isinstance(level, Sequence) and not isinstance(level, (str, bytes, bytearray)) and level:
            price = _safe_float(level[0])
            size = _safe_float(level[1]) if len(level) > 1 else None
        else:
            price = None
            size = None
        if price is None:
            continue
        if 0.0 <= price <= 1.0:
            priced_levels.append((price, size))
    if not priced_levels:
        return None, None
    best = max(priced_levels, key=lambda item: item[0]) if side == "bid" else min(priced_levels, key=lambda item: item[0])
    return best


def _extract_book_quotes(
    payload: Mapping[str, Any],
) -> tuple[float | None, float | None, float | None, float | None]:
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    bid, bid_size = _best_level(bids, side="bid")
    ask, ask_size = _best_level(asks, side="ask")
    return bid, ask, bid_size, ask_size


def _normalize_prices_response(payload: Any, side: str) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = []
        for token_id, raw in payload.items():
            if isinstance(raw, Mapping):
                price = (
                    _safe_float(raw.get(side))
                    or _safe_float(raw.get("price"))
                    or _safe_float(raw.get("value"))
                )
            else:
                price = _safe_float(raw)
            if price is not None:
                out[str(token_id)] = price
        return out
    else:
        return out

    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        token_id = str(raw.get("token_id") or raw.get("asset_id") or raw.get("id") or "").strip()
        price = (
            _safe_float(raw.get(side))
            or _safe_float(raw.get("price"))
            or _safe_float(raw.get("value"))
        )
        if token_id and price is not None:
            out[token_id] = price
    return out


class GammaEventDiscovery:
    """Gamma `/events` discovery with safe A-6 watchlist building."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 12.0,
        page_size: int = 100,
        max_pages: int = 20,
        watchlist_builder: A6WatchlistBuilder | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.page_size = max(1, min(100, int(page_size)))
        self.max_pages = max(1, int(max_pages))
        self.watchlist_builder = watchlist_builder or A6WatchlistBuilder()

    def fetch_active_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for page in range(self.max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": self.page_size,
                "offset": page * self.page_size,
            }
            resp = self.session.get(GAMMA_EVENTS_URL, params=params, timeout=self.timeout_seconds)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            events.extend([dict(row) for row in batch if isinstance(row, Mapping)])
            if len(batch) < self.page_size:
                break
        return events

    def build_watchlist(self, raw_events: Sequence[Mapping[str, Any]] | None = None) -> list[EventWatch]:
        events = list(raw_events) if raw_events is not None else self.fetch_active_events()
        return self.watchlist_builder.build_watchlist(events)


class A6PriceSnapshotter:
    """Prefer batched `/prices`; fallback to `/book` and quarantine on 404s."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 12.0,
        quarantine: A6QuarantineCache | None = None,
        use_book_fallback: bool = True,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.quarantine = quarantine or A6QuarantineCache()
        self.use_book_fallback = bool(use_book_fallback)

    def refresh_store(self, watches: Sequence[EventWatch], store: BestBidAskStore) -> int:
        return self.refresh_store_for_tokens(
            self._token_ids_for_watches(watches, include_no_tokens=False),
            store,
        )

    def refresh_store_for_tokens(self, token_ids: Sequence[str], store: BestBidAskStore) -> int:
        token_ids = sorted(
            {
                str(token_id).strip()
                for token_id in token_ids
                if str(token_id).strip() and not self.quarantine.is_quarantined(str(token_id).strip())
            }
        )
        if not token_ids:
            return 0

        asks = self._fetch_prices(token_ids, side="SELL")
        bids = self._fetch_prices(token_ids, side="BUY")
        updated = 0

        for token_id in token_ids:
            best_ask = asks.get(token_id)
            best_bid = bids.get(token_id)
            if self.use_book_fallback and (best_bid is None or best_ask is None):
                book_bid, book_ask, book_bid_size, book_ask_size = self._fetch_book_fallback(token_id)
                if book_bid is not None:
                    best_bid = book_bid
                if book_ask is not None:
                    best_ask = book_ask
            else:
                book_bid_size = None
                book_ask_size = None

            if best_bid is None or best_ask is None:
                continue

            store.update(
                token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                best_bid_size=book_bid_size,
                best_ask_size=book_ask_size,
            )
            self.quarantine.mark_success(token_id)
            updated += 1

        return updated

    @staticmethod
    def _token_ids_for_watches(
        watches: Sequence[EventWatch],
        *,
        include_no_tokens: bool,
    ) -> list[str]:
        token_ids: list[str] = []
        for watch in watches:
            for leg in watch.legs:
                if leg.yes_token_id:
                    token_ids.append(leg.yes_token_id)
                if include_no_tokens and leg.no_token_id:
                    token_ids.append(leg.no_token_id)
        return token_ids

    def refresh_store_with_no_tokens(self, watches: Sequence[EventWatch], store: BestBidAskStore) -> int:
        return self.refresh_store_for_tokens(
            self._token_ids_for_watches(watches, include_no_tokens=True),
            store,
        )

    def _fetch_prices(self, token_ids: Sequence[str], *, side: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for idx in range(0, len(token_ids), MAX_PRICE_BATCH_TOKENS):
            chunk = token_ids[idx : idx + MAX_PRICE_BATCH_TOKENS]
            body = [{"token_id": token_id, "side": side} for token_id in chunk]
            resp = self.session.post(CLOB_PRICES_URL, json=body, timeout=self.timeout_seconds)
            resp.raise_for_status()
            out.update(_normalize_prices_response(resp.json(), side))
        return out

    def _fetch_book_fallback(
        self,
        token_id: str,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        resp = self.session.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=self.timeout_seconds)
        if resp.status_code == 404:
            self.quarantine.mark_failure(token_id, reason="book_404", status_code=404)
            return None, None, None, None
        resp.raise_for_status()
        bid, ask, bid_size, ask_size = _extract_book_quotes(resp.json())
        if bid is None or ask is None:
            self.quarantine.mark_failure(token_id, reason="book_missing_quotes", status_code=resp.status_code)
            return None, None, None, None
        return bid, ask, bid_size, ask_size


def ensure_quarantine_file(path: str | Path = Path("data") / "a6_quarantine_tokens.json") -> Path:
    target = Path(path)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"records": {}}, indent=2, sort_keys=True), encoding="utf-8")
    return target
