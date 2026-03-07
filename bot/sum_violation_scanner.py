#!/usr/bin/env python3
"""Instance 3 runtime: event-based A-6 sum-violation scanner."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import requests

try:
    from bot.constraint_arb_engine import ConstraintArbEngine, ConstraintViolation
except ImportError:  # pragma: no cover - direct script mode
    from constraint_arb_engine import ConstraintArbEngine, ConstraintViolation  # type: ignore

try:
    from infra.clob_ws import BestBidAskStore, ThreadedMarketStream
    from strategies.a6_sum_violation import A6WatchlistBuilder, parse_clob_token_ids
except ImportError:  # pragma: no cover - direct script mode
    from clob_ws import BestBidAskStore, ThreadedMarketStream  # type: ignore
    from a6_sum_violation import A6WatchlistBuilder, parse_clob_token_ids  # type: ignore


GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_PRICES_URL = "https://clob.polymarket.com/prices"

logger = logging.getLogger("sum_violation_scanner")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_gamma_yes_quotes(raw: Mapping[str, Any]) -> tuple[float | None, float | None]:
    best_bid = _as_float(raw.get("bestBid"), default=-1.0)
    best_ask = _as_float(raw.get("bestAsk"), default=-1.0)
    if 0.0 <= best_bid <= 1.0 and 0.0 <= best_ask <= 1.0:
        return best_bid, best_ask

    prices_raw = raw.get("outcomePrices")
    if isinstance(prices_raw, str):
        try:
            prices_raw = json.loads(prices_raw)
        except json.JSONDecodeError:
            prices_raw = []

    if isinstance(prices_raw, list) and prices_raw:
        yes = _as_float(prices_raw[0], default=-1.0)
        if 0.0 <= yes <= 1.0:
            return yes, yes
    return None, None


@dataclass(frozen=True)
class ScanStats:
    timestamp_ts: int
    events_fetched: int
    candidate_events: int
    candidate_markets: int
    quotes_updated: int
    events_blocked_no_orderbook: int
    violations_found: int
    elapsed_seconds: float


class SumViolationScanner:
    """Gamma event discovery + WebSocket/REST quote scanner for A-6."""

    def __init__(
        self,
        *,
        db_path: str | Path = Path("data") / "constraint_arb.db",
        output_path: str | Path = Path("logs") / "sum_violation_events.jsonl",
        report_path: str | Path = Path("reports") / "constraint_arb_shadow_report.md",
        interval_seconds: int = 60,
        max_pages: int = 20,
        page_size: int = 50,
        max_events: int = 60,
        min_event_markets: int = 3,
        buy_threshold: float = 0.97,
        execute_threshold: float = 0.95,
        unwind_threshold: float = 1.03,
        prefilter_buffer: float = 0.05,
        stale_quote_seconds: int = 45,
        timeout_seconds: float = 12.0,
        use_websocket: bool = True,
        ws_chunk_size: int = 200,
        ws_warmup_seconds: float = 1.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.output_path = Path(output_path)
        self.report_path = Path(report_path)
        self.interval_seconds = max(1, int(interval_seconds))
        self.max_pages = max(1, int(max_pages))
        self.page_size = max(1, min(100, int(page_size)))
        self.max_events = max(1, int(max_events))
        self.min_event_markets = max(3, int(min_event_markets))
        self.buy_threshold = float(buy_threshold)
        self.execute_threshold = float(execute_threshold)
        self.unwind_threshold = float(unwind_threshold)
        self.prefilter_buffer = max(0.0, float(prefilter_buffer))
        self.stale_quote_seconds = max(1, int(stale_quote_seconds))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.use_websocket = bool(use_websocket)
        self.ws_chunk_size = max(1, int(ws_chunk_size))
        self.ws_warmup_seconds = max(0.0, float(ws_warmup_seconds))

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._quote_store = BestBidAskStore()
        self._market_stream: ThreadedMarketStream | None = None
        self._stream_assets: tuple[str, ...] = tuple()
        self._watch_builder = A6WatchlistBuilder(
            min_event_markets=self.min_event_markets,
            max_legs=12,
            exclude_augmented=True,
        )

    def close(self) -> None:
        if self._market_stream is not None:
            self._market_stream.stop()
        self._session.close()

    def fetch_active_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for page in range(self.max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": self.page_size,
                "offset": page * self.page_size,
            }
            resp = self._session.get(f"{GAMMA_API_BASE}/events", params=params, timeout=self.timeout_seconds)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            events.extend([event for event in batch if isinstance(event, dict)])
            if len(batch) < self.page_size:
                break
            time.sleep(0.15)
        return events

    def _select_candidate_events(self, raw_events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        watches = self._watch_builder.build_watchlist(raw_events)
        scored: list[tuple[float, dict[str, Any]]] = []
        for watch in watches:
            approx_sum = 0.0
            for raw_market in watch.raw_event.get("markets", []):
                if not isinstance(raw_market, Mapping):
                    continue
                _, ask = extract_gamma_yes_quotes(raw_market)
                if ask is not None:
                    approx_sum += ask

            if approx_sum > self.buy_threshold + self.prefilter_buffer and approx_sum < self.unwind_threshold - self.prefilter_buffer:
                continue
            scored.append((abs(approx_sum - 1.0), dict(watch.raw_event)))

        scored.sort(key=lambda row: row[0], reverse=True)
        return [event for _, event in scored[: self.max_events]]

    def _ensure_market_stream(self, token_ids: Sequence[str]) -> None:
        asset_ids = tuple(sorted({str(token_id).strip() for token_id in token_ids if str(token_id).strip()}))
        if not self.use_websocket or not asset_ids:
            return
        if self._market_stream is None:
            self._market_stream = ThreadedMarketStream(
                asset_ids=asset_ids,
                store=self._quote_store,
                chunk_size=self.ws_chunk_size,
            )
            self._market_stream.start()
            self._stream_assets = asset_ids
            if self.ws_warmup_seconds > 0:
                time.sleep(self.ws_warmup_seconds)
            return
        if asset_ids != self._stream_assets:
            self._market_stream.replace_asset_ids(asset_ids)
            self._stream_assets = asset_ids
            if self.ws_warmup_seconds > 0:
                time.sleep(self.ws_warmup_seconds)

    def _parse_prices_payload(self, payload: Any, side: str) -> dict[str, float]:
        side_key = str(side).upper()
        out: dict[str, float] = {}
        if isinstance(payload, dict):
            nested = payload.get("prices")
            if nested is not None:
                return self._parse_prices_payload(nested, side)
            for token_id, raw_value in payload.items():
                price: float | None = None
                if isinstance(raw_value, Mapping):
                    price = _as_float(raw_value.get(side_key), default=-1.0)
                else:
                    price = _as_float(raw_value, default=-1.0)
                if price is not None and 0.0 <= price <= 1.0:
                    out[str(token_id)] = float(price)
            return out

        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                token_id = str(item.get("token_id") or item.get("asset_id") or "").strip()
                if not token_id:
                    continue
                price = None
                if isinstance(item.get("prices"), Mapping):
                    price = _as_float(item["prices"].get(side_key), default=-1.0)
                elif isinstance(item.get(side_key), (int, float, str)):
                    price = _as_float(item.get(side_key), default=-1.0)
                elif isinstance(item.get("price"), (int, float, str)):
                    price = _as_float(item.get("price"), default=-1.0)
                if price is not None and 0.0 <= price <= 1.0:
                    out[token_id] = float(price)
        return out

    def _fetch_prices_batch(self, token_ids: Sequence[str], *, side: str) -> tuple[dict[str, float], set[str]]:
        clean_ids = [str(token_id).strip() for token_id in token_ids if str(token_id).strip()]
        if not clean_ids:
            return {}, set()

        try:
            resp = self._session.post(
                CLOB_PRICES_URL,
                json=[{"token_id": token_id, "side": str(side).upper()} for token_id in clean_ids],
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            return {}, set(clean_ids)

        if resp.status_code == 404:
            return {}, set(clean_ids)
        if resp.status_code != 200:
            return {}, set(clean_ids)

        prices = self._parse_prices_payload(resp.json(), side)
        missing = {token_id for token_id in clean_ids if token_id not in prices}
        return prices, missing

    def _fetch_quotes_for_events(
        self,
        candidate_events: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, tuple[float, float]], set[str]]:
        token_to_market: dict[str, str] = {}
        token_to_event: dict[str, str] = {}
        token_ids: list[str] = []
        for raw_event in candidate_events:
            event_id = str(raw_event.get("id") or raw_event.get("event_id") or "").strip()
            markets = raw_event.get("markets")
            if not event_id or not isinstance(markets, list):
                continue
            for raw_market in markets:
                if not isinstance(raw_market, Mapping):
                    continue
                yes_token_id, _ = parse_clob_token_ids(raw_market.get("clobTokenIds"))
                market_id = str(raw_market.get("id") or raw_market.get("market_id") or "").strip()
                if not yes_token_id or not market_id:
                    continue
                token_ids.append(yes_token_id)
                token_to_market[yes_token_id] = market_id
                token_to_event[yes_token_id] = event_id

        self._ensure_market_stream(token_ids)

        quotes: dict[str, tuple[float, float]] = {}
        missing: set[str] = set()
        for token_id in token_ids:
            if self.use_websocket and self._quote_store.is_fresh(token_id, max_age_seconds=self.stale_quote_seconds):
                quote = self._quote_store.get(token_id)
                if quote is not None:
                    quotes[token_to_market[token_id]] = (quote.best_bid, quote.best_ask)
                    continue
            missing.add(token_id)

        if missing:
            bid_prices, missing_buy = self._fetch_prices_batch(sorted(missing), side="BUY")
            ask_prices, missing_sell = self._fetch_prices_batch(sorted(missing), side="SELL")
            missing = missing_buy | missing_sell | {token_id for token_id in missing if token_id not in bid_prices or token_id not in ask_prices}
            for token_id in sorted(set(token_ids) - missing):
                if token_id not in bid_prices or token_id not in ask_prices:
                    continue
                bid = float(bid_prices[token_id])
                ask = float(ask_prices[token_id])
                self._quote_store.update(token_id, best_bid=bid, best_ask=ask, updated_ts=time.time())
                quotes[token_to_market[token_id]] = (bid, ask)

        blocked_event_ids = {token_to_event[token_id] for token_id in missing if token_id in token_to_event}
        for token_id in missing:
            self._quote_store.mark_no_orderbook(token_id)
        return quotes, blocked_event_ids

    @staticmethod
    def _violation_to_record(violation: ConstraintViolation) -> dict[str, Any]:
        record = asdict(violation)
        record["market_ids"] = list(violation.market_ids)
        return record

    def _append_violations(self, violations: Sequence[ConstraintViolation]) -> None:
        if not violations:
            return
        with self.output_path.open("a", encoding="utf-8") as handle:
            for violation in violations:
                handle.write(json.dumps(self._violation_to_record(violation), sort_keys=True) + "\n")

    def scan_once(self) -> ScanStats:
        started = time.time()
        now_ts = int(started)

        raw_events = self.fetch_active_events()
        candidate_events = self._select_candidate_events(raw_events)
        quote_map, blocked_event_ids = self._fetch_quotes_for_events(candidate_events)

        tradable_events = [event for event in candidate_events if str(event.get("id") or event.get("event_id") or "").strip() not in blocked_event_ids]
        selected_markets = self._watch_builder.flatten_markets(tradable_events)

        engine = ConstraintArbEngine(
            db_path=self.db_path,
            buy_threshold=self.buy_threshold,
            execute_threshold=self.execute_threshold,
            unwind_threshold=self.unwind_threshold,
            stale_quote_seconds=self.stale_quote_seconds,
        )
        engine.register_markets(selected_markets)

        for market_id, (bid, ask) in quote_map.items():
            if market_id in {market.get("id") for market in selected_markets}:
                engine.update_quote(market_id=market_id, yes_bid=bid, yes_ask=ask, updated_ts=now_ts)

        violations = engine.scan_sum_violations(now_ts=now_ts)
        self._append_violations(violations)
        engine.db.write_shadow_report(self.report_path, days=14)

        return ScanStats(
            timestamp_ts=now_ts,
            events_fetched=len(raw_events),
            candidate_events=len(candidate_events),
            candidate_markets=len(selected_markets),
            quotes_updated=len(quote_map),
            events_blocked_no_orderbook=len(blocked_event_ids),
            violations_found=len(violations),
            elapsed_seconds=round(time.time() - started, 3),
        )

    def run(self, *, once: bool = False, max_cycles: int | None = None) -> None:
        cycle = 0
        while True:
            cycle += 1
            try:
                stats = self.scan_once()
                logger.info(
                    "sum_scan cycle=%s events=%s candidates=%s selected=%s quotes=%s blocked=%s violations=%s elapsed=%.2fs",
                    cycle,
                    stats.events_fetched,
                    stats.candidate_events,
                    stats.candidate_markets,
                    stats.quotes_updated,
                    stats.events_blocked_no_orderbook,
                    stats.violations_found,
                    stats.elapsed_seconds,
                )
            except Exception:
                logger.exception("sum_scan_failed cycle=%s", cycle)

            if once:
                return
            if max_cycles is not None and cycle >= max_cycles:
                return
            time.sleep(self.interval_seconds)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-outcome sum-violation scanner")
    parser.add_argument("--db-path", default="data/constraint_arb.db")
    parser.add_argument("--output-path", default="logs/sum_violation_events.jsonl")
    parser.add_argument("--report-path", default="reports/constraint_arb_shadow_report.md")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-events", type=int, default=60)
    parser.add_argument("--min-event-markets", type=int, default=3)
    parser.add_argument("--buy-threshold", type=float, default=0.97)
    parser.add_argument("--execute-threshold", type=float, default=0.95)
    parser.add_argument("--unwind-threshold", type=float, default=1.03)
    parser.add_argument("--prefilter-buffer", type=float, default=0.05)
    parser.add_argument("--stale-quote-seconds", type=int, default=45)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--use-websocket", action="store_true")
    parser.add_argument("--disable-websocket", action="store_true")
    parser.add_argument("--ws-chunk-size", type=int, default=200)
    parser.add_argument("--ws-warmup-seconds", type=float, default=1.0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    use_websocket = bool(args.use_websocket or not args.disable_websocket)

    scanner = SumViolationScanner(
        db_path=args.db_path,
        output_path=args.output_path,
        report_path=args.report_path,
        interval_seconds=args.interval_seconds,
        max_pages=args.max_pages,
        page_size=args.page_size,
        max_events=args.max_events,
        min_event_markets=args.min_event_markets,
        buy_threshold=args.buy_threshold,
        execute_threshold=args.execute_threshold,
        unwind_threshold=args.unwind_threshold,
        prefilter_buffer=args.prefilter_buffer,
        stale_quote_seconds=args.stale_quote_seconds,
        timeout_seconds=args.timeout_seconds,
        use_websocket=use_websocket,
        ws_chunk_size=args.ws_chunk_size,
        ws_warmup_seconds=args.ws_warmup_seconds,
    )
    try:
        scanner.run(once=args.once, max_cycles=args.max_cycles)
    finally:
        scanner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
