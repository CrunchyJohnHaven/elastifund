"""Threaded market-channel cache with optional snapshot persistence."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any, Sequence

from infra.clob_ws import BestBidAsk, BestBidAskStore, ThreadedMarketStream


class WsMarketCache:
    """Shared best-bid/ask cache backed by the CLOB market websocket."""

    def __init__(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        snapshot_path: str | Path = Path("data") / "ws_market_cache.json",
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = BestBidAskStore()
        self.asset_ids = [str(asset_id).strip() for asset_id in (asset_ids or []) if str(asset_id).strip()]
        self._stream = ThreadedMarketStream(asset_ids=self.asset_ids, store=self.store)
        self.load_snapshot()

    def start(self) -> None:
        self._stream.replace_asset_ids(self.asset_ids)
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()
        self.write_snapshot()

    def replace_asset_ids(self, asset_ids: Sequence[str]) -> None:
        self.asset_ids = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
        self._stream.replace_asset_ids(self.asset_ids)

    def get(self, token_id: str, *, max_age_seconds: float | None = None) -> BestBidAsk | None:
        quote = self.store.get(token_id)
        if quote is None:
            return None
        if max_age_seconds is not None and (time.time() - quote.updated_ts) > float(max_age_seconds):
            return None
        return quote

    def mark_no_orderbook(self, token_id: str) -> None:
        self.store.mark_no_orderbook(token_id)

    def snapshot(self, token_ids: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
        ids = token_ids if token_ids is not None else self.asset_ids
        raw = self.store.snapshot(ids)
        return {token_id: asdict(quote) for token_id, quote in raw.items()}

    def write_snapshot(self) -> None:
        payload = {
            "updated_ts": time.time(),
            "asset_ids": list(self.asset_ids),
            "quotes": self.snapshot(),
            "no_orderbook": sorted(self.store.tokens_without_orderbook()),
        }
        self.snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        asset_ids = payload.get("asset_ids")
        if isinstance(asset_ids, list):
            self.asset_ids = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]

        quotes = payload.get("quotes", {})
        if isinstance(quotes, dict):
            for token_id, quote in quotes.items():
                if not isinstance(quote, dict):
                    continue
                try:
                    self.store.update(
                        str(token_id),
                        best_bid=float(quote["best_bid"]),
                        best_ask=float(quote["best_ask"]),
                        updated_ts=float(quote.get("updated_ts") or time.time()),
                    )
                except (KeyError, TypeError, ValueError):
                    continue

        no_orderbook = payload.get("no_orderbook", [])
        if isinstance(no_orderbook, list):
            for token_id in no_orderbook:
                self.store.mark_no_orderbook(str(token_id))

