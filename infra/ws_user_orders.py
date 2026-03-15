"""Threaded wrapper around the CLOB user websocket."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time
from typing import Any, Mapping, Sequence

from infra.clob_ws import ClobUserWebSocketClient, UserOrderEvent


class UserOrderStore:
    """In-memory order event registry with periodic JSON snapshots."""

    def __init__(
        self,
        *,
        snapshot_path: str | Path = Path("data") / "ws_user_orders.json",
        max_events: int = 5000,
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_events = max(10, int(max_events))
        self._latest: dict[str, UserOrderEvent] = {}
        self._events: deque[UserOrderEvent] = deque(maxlen=self.max_events)
        self._lock = threading.Lock()
        self.load_snapshot()

    def apply(self, event: UserOrderEvent) -> None:
        with self._lock:
            self._latest[event.order_id] = event
            self._events.append(event)

    def latest(self, order_id: str) -> UserOrderEvent | None:
        with self._lock:
            return self._latest.get(str(order_id))

    def recent(self, limit: int = 100) -> list[UserOrderEvent]:
        with self._lock:
            return list(self._events)[-max(1, int(limit)) :]

    def write_snapshot(self) -> None:
        with self._lock:
            payload = {
                "updated_ts": time.time(),
                "events": [asdict(event) for event in self._events],
            }
        self.snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        raw_events = payload.get("events", [])
        if not isinstance(raw_events, list):
            return

        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            try:
                self.apply(
                    UserOrderEvent(
                        event_type=str(raw.get("event_type") or "user_event"),
                        order_id=str(raw["order_id"]),
                        market_id=str(raw.get("market_id") or "").strip() or None,
                        token_id=str(raw.get("token_id") or "").strip() or None,
                        status=str(raw.get("status") or "").strip() or None,
                        filled_size=float(raw.get("filled_size") or 0.0),
                        price=float(raw["price"]) if raw.get("price") is not None else None,
                        updated_ts=float(raw.get("updated_ts") or time.time()),
                        raw=dict(raw.get("raw") or {}),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue


class ThreadedUserOrderStream:
    """Background-thread wrapper for live order/fill updates."""

    def __init__(
        self,
        *,
        market_ids: Sequence[str],
        auth: Mapping[str, Any] | None = None,
        store: UserOrderStore | None = None,
    ) -> None:
        self.market_ids = [str(market_id).strip() for market_id in market_ids if str(market_id).strip()]
        self.auth = dict(auth or {})
        self.store = store or UserOrderStore()
        self._thread: threading.Thread | None = None
        self._client: ClobUserWebSocketClient | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="clob-user-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._client is not None:
            self._client.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._client = None
        self.store.write_snapshot()

    def replace_market_ids(self, market_ids: Sequence[str]) -> None:
        new_ids = [str(market_id).strip() for market_id in market_ids if str(market_id).strip()]
        if new_ids == self.market_ids:
            return
        self.market_ids = new_ids
        self.stop()
        self.start()

    def latest(self, order_id: str) -> UserOrderEvent | None:
        return self.store.latest(order_id)

    def _thread_main(self) -> None:  # pragma: no cover - thread wrapper
        asyncio.run(self._async_main())

    async def _async_main(self) -> None:  # pragma: no cover - thread wrapper
        self._client = ClobUserWebSocketClient(
            market_ids=self.market_ids,
            auth=self.auth,
            event_hook=self.store.apply,
        )
        await self._client.run_forever()
