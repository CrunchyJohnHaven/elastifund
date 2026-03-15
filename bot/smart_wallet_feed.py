from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import aiohttp

logger = logging.getLogger("SmartWalletFeed")

DEFAULT_TRADES_URL = "https://data-api.polymarket.com/trades"
DEFAULT_CONFIG_PATH = Path("config/smart_wallets.json")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_outcome_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("down", "lower", "no", "bear")):
        return "DOWN"
    if any(token in text for token in ("up", "higher", "yes", "bull")):
        return "UP"
    return ""


def _trade_direction(trade: dict[str, Any]) -> str | None:
    side = str(trade.get("side") or "").strip().upper()
    outcome = _normalize_outcome_label(trade.get("outcome"))
    if not outcome:
        raw_idx = trade.get("outcomeIndex")
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            return None
        outcome = "UP" if idx == 0 else "DOWN"
    if side == "SELL":
        return "DOWN" if outcome == "UP" else "UP"
    return outcome


def load_smart_wallet_addresses(config_path: str | Path = DEFAULT_CONFIG_PATH) -> list[str]:
    path = Path(config_path)
    if not path.exists():
        logger.warning("Smart wallet config missing at %s", path)
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed reading smart wallet config %s: %s", path, exc)
        return []

    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("wallets"), list):
        rows = list(payload.get("wallets") or [])
    else:
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, str):
            wallet = _normalize_wallet(item)
        elif isinstance(item, dict):
            wallet = _normalize_wallet(item.get("address") or item.get("wallet"))
        else:
            wallet = ""
        if not wallet or wallet in seen:
            continue
        seen.add(wallet)
        deduped.append(wallet)
    return deduped


@dataclass(frozen=True)
class WalletConsensus:
    condition_id: str
    window_start_ts: int
    direction: str
    smart_wallet_count: int
    combined_notional_usd: float
    avg_price: float
    trade_count: int
    observed_wallets: tuple[str, ...] = field(default_factory=tuple)
    observed_at_ts: int = 0

    def strong(
        self,
        *,
        min_wallets: int = 3,
        min_notional_usd: float = 200.0,
        min_avg_price: float = 0.90,
    ) -> bool:
        return (
            int(self.smart_wallet_count) >= int(min_wallets)
            and float(self.combined_notional_usd) >= float(min_notional_usd)
            and float(self.avg_price) >= float(min_avg_price)
        )


class SmartWalletFeed:
    def __init__(
        self,
        smart_wallet_addresses: Sequence[str],
        *,
        poll_interval_sec: float = 15.0,
        observation_window_sec: int = 180,
        request_timeout_sec: float = 10.0,
        trades_url: str = DEFAULT_TRADES_URL,
        session: aiohttp.ClientSession | None = None,
        clock: Callable[[], float] = time.time,
    ):
        normalized = [_normalize_wallet(addr) for addr in smart_wallet_addresses]
        self.smart_wallet_addresses = tuple(addr for addr in normalized if addr)
        self._wallet_set = set(self.smart_wallet_addresses)
        self.poll_interval_sec = max(1.0, float(poll_interval_sec))
        self.observation_window_sec = max(1, int(observation_window_sec))
        self.request_timeout_sec = max(1.0, float(request_timeout_sec))
        self.trades_url = str(trades_url or DEFAULT_TRADES_URL)
        self._clock = clock
        self._session = session
        self._session_owner = session is None
        self._state_lock = asyncio.Lock()
        self._watch_tasks: dict[int, asyncio.Task[None]] = {}
        self._cache: dict[int, WalletConsensus] = {}

    @classmethod
    def from_config(
        cls,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        **kwargs: Any,
    ) -> "SmartWalletFeed":
        wallets = load_smart_wallet_addresses(config_path)
        return cls(wallets, **kwargs)

    def start_background_watch(self, condition_id: str, window_start_ts: int) -> None:
        if not condition_id:
            return
        window_key = int(window_start_ts)
        existing = self._watch_tasks.get(window_key)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            self._observe_window(condition_id=str(condition_id), window_start_ts=window_key),
            name=f"smart-wallet-watch-{window_key}",
        )
        self._watch_tasks[window_key] = task

    async def get_cached_consensus(self, window_start_ts: int) -> WalletConsensus | None:
        window_key = int(window_start_ts)
        async with self._state_lock:
            return self._cache.get(window_key)

    async def wait_for_window(self, window_start_ts: int, timeout_sec: float = 5.0) -> None:
        task = self._watch_tasks.get(int(window_start_ts))
        if task is None:
            return
        await asyncio.wait_for(asyncio.shield(task), timeout=max(0.1, float(timeout_sec)))

    async def close(self) -> None:
        tasks = [task for task in self._watch_tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._watch_tasks.clear()
        if self._session_owner and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _observe_window(self, *, condition_id: str, window_start_ts: int) -> None:
        window_end_ts = int(window_start_ts) + self.observation_window_sec
        window_key = int(window_start_ts)
        try:
            while True:
                trades = await self._fetch_trades_for_condition(condition_id)
                consensus = self._compute_consensus(
                    condition_id=condition_id,
                    window_start_ts=window_key,
                    trades=trades,
                )
                if consensus is not None:
                    async with self._state_lock:
                        current = self._cache.get(window_key)
                        if current is None or self._is_better_consensus(consensus, current):
                            self._cache[window_key] = consensus
                now_ts = int(self._clock())
                if now_ts >= window_end_ts:
                    break
                sleep_for = min(self.poll_interval_sec, max(0.0, window_end_ts - now_ts))
                if sleep_for <= 0:
                    break
                await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Smart wallet watch failed condition=%s window=%s: %s",
                condition_id,
                window_key,
                exc,
            )
        finally:
            self._watch_tasks.pop(window_key, None)

    async def _fetch_trades_for_condition(self, condition_id: str) -> list[dict[str, Any]]:
        if not self._wallet_set:
            return []
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout_sec)
            self._session = aiohttp.ClientSession(timeout=timeout)
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_sec)
        try:
            async with self._session.get(
                self.trades_url,
                params={"conditionId": condition_id, "limit": 200},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Smart wallet trades fetch status=%s condition=%s",
                        resp.status,
                        condition_id,
                    )
                    return []
                payload = await resp.json()
        except Exception as exc:
            logger.warning("Smart wallet trades fetch failed condition=%s: %s", condition_id, exc)
            return []

        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("data", [])
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def _compute_consensus(
        self,
        *,
        condition_id: str,
        window_start_ts: int,
        trades: list[dict[str, Any]],
    ) -> WalletConsensus | None:
        if not trades or not self._wallet_set:
            return None
        window_end_ts = int(window_start_ts) + self.observation_window_sec
        buckets: dict[str, dict[str, Any]] = {
            "UP": {"wallets": set(), "notional": 0.0, "price_notional": 0.0, "trades": 0},
            "DOWN": {"wallets": set(), "notional": 0.0, "price_notional": 0.0, "trades": 0},
        }

        for trade in trades:
            wallet = _normalize_wallet(trade.get("proxyWallet") or trade.get("wallet"))
            if wallet not in self._wallet_set:
                continue
            ts = int(_safe_float(trade.get("timestamp"), 0.0) or 0.0)
            if ts < window_start_ts or ts > window_end_ts:
                continue
            direction = _trade_direction(trade)
            if direction not in {"UP", "DOWN"}:
                continue
            size = _safe_float(trade.get("size"), 0.0) or 0.0
            price = _safe_float(trade.get("price"), 0.0) or 0.0
            if size <= 0 or price <= 0:
                continue
            notional = float(size) * float(price)
            bucket = buckets[direction]
            bucket["wallets"].add(wallet)
            bucket["notional"] += notional
            bucket["price_notional"] += float(price) * notional
            bucket["trades"] += 1

        candidate_direction = max(
            buckets,
            key=lambda key: (
                len(buckets[key]["wallets"]),
                float(buckets[key]["notional"]),
                int(buckets[key]["trades"]),
            ),
        )
        selected = buckets[candidate_direction]
        wallet_count = len(selected["wallets"])
        combined_notional = float(selected["notional"])
        trade_count = int(selected["trades"])
        if wallet_count <= 0 or combined_notional <= 0 or trade_count <= 0:
            return None
        avg_price = float(selected["price_notional"]) / combined_notional
        return WalletConsensus(
            condition_id=str(condition_id),
            window_start_ts=int(window_start_ts),
            direction=candidate_direction,
            smart_wallet_count=wallet_count,
            combined_notional_usd=combined_notional,
            avg_price=avg_price,
            trade_count=trade_count,
            observed_wallets=tuple(sorted(selected["wallets"])),
            observed_at_ts=int(self._clock()),
        )

    @staticmethod
    def _is_better_consensus(candidate: WalletConsensus, current: WalletConsensus) -> bool:
        return (
            int(candidate.smart_wallet_count),
            float(candidate.combined_notional_usd),
            float(candidate.avg_price),
            int(candidate.trade_count),
        ) > (
            int(current.smart_wallet_count),
            float(current.combined_notional_usd),
            float(current.avg_price),
            int(current.trade_count),
        )

