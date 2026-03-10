#!/usr/bin/env python3
"""Instance 3 runtime: event-based A-6 sum-violation scanner."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

import requests

try:
    from bot.constraint_arb_engine import ConstraintArbEngine, ConstraintViolation
except ImportError:  # pragma: no cover - direct script mode
    from constraint_arb_engine import ConstraintArbEngine, ConstraintViolation  # type: ignore

try:
    from bot.a6_sum_scanner import A6ScannerConfig, A6SumScanner
except ImportError:  # pragma: no cover - direct script mode
    try:
        from a6_sum_scanner import A6ScannerConfig, A6SumScanner  # type: ignore
    except ImportError:
        A6ScannerConfig = None  # type: ignore
        A6SumScanner = None  # type: ignore

try:
    from infra.clob_ws import BestBidAskStore, ThreadedMarketStream
    from strategies.a6_sum_violation import A6WatchlistBuilder, parse_clob_token_ids
except ImportError:  # pragma: no cover - direct script mode
    from clob_ws import BestBidAskStore, ThreadedMarketStream  # type: ignore
    from a6_sum_violation import A6WatchlistBuilder, parse_clob_token_ids  # type: ignore


GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_PRICES_URL = "https://clob.polymarket.com/prices"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"

logger = logging.getLogger("sum_violation_scanner")

_DATE_OR_NUMERIC_RE = re.compile(
    r"\b(?:"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"20\d{2}|\d{1,2}/\d{1,2}|\d+(?:\.\d+)?%?"
    r")\b",
    flags=re.IGNORECASE,
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _norm_text(text: str) -> str:
    value = text.lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _question_skeleton(question: str) -> str:
    skeleton = _DATE_OR_NUMERIC_RE.sub("<value>", question.lower())
    skeleton = re.sub(r"[^a-z<>\s]", " ", skeleton)
    return re.sub(r"\s+", " ", skeleton).strip()


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
    measurement_records: int = 0
    measurement_executable_records: int = 0


@dataclass(frozen=True)
class SumViolationLeg:
    market_id: str
    event_id: str
    question: str
    outcome: str
    category: str
    yes_token_id: str | None
    no_token_id: str | None
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_depth_usd: float
    no_depth_usd: float
    resolution_hours: float | None
    tick_size: float
    raw_market: dict[str, Any]


@dataclass(frozen=True)
class SumViolationOpportunity:
    violation_id: str
    event_id: str
    event_key: str
    event_title: str
    market_ids: tuple[str, ...]
    outcomes: tuple[str, ...]
    legs: tuple[SumViolationLeg, ...]
    threshold: float
    sum_yes_bid: float | None
    sum_yes_ask: float | None
    sum_no_bid: float | None
    sum_no_ask: float | None
    trade_side: str
    violation_amount: float
    gross_profit_per_basket: float
    gross_profit_per_dollar: float
    execution_cost: float
    payout_per_basket: float
    can_trade_fifty_cents_per_leg: bool


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
        measurement_only: bool = False,
        measurement_artifact_path: str | Path | None = None,
        enable_order_routing: bool = False,
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
        self.measurement_only = bool(measurement_only)
        self.enable_order_routing = bool(enable_order_routing)
        if self.measurement_only and self.enable_order_routing:
            raise ValueError("measurement_only mode forbids order routing")
        self.measurement_artifact_path = (
            Path(measurement_artifact_path) if measurement_artifact_path is not None else None
        )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.measurement_artifact_path is not None:
            self.measurement_artifact_path.parent.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._quote_store = BestBidAskStore()
        self._market_stream: ThreadedMarketStream | None = None
        self._stream_assets: tuple[str, ...] = tuple()
        self._watch_builder = A6WatchlistBuilder(
            min_event_markets=self.min_event_markets,
            max_legs=12,
            exclude_augmented=True,
        )
        self._latest_opportunities: list = []
        self._latest_measurement_capture: dict[str, Any] | None = None
        self._measurement_event_state: dict[str, str] = {}
        self._measurement_last_scan_ts: int | None = None

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

    def fetch_active_markets(self) -> list[dict[str, Any]]:
        """Fetch all active Gamma markets for market-based sum scanning."""
        markets: list[dict[str, Any]] = []
        for page in range(self.max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": self.page_size,
                "offset": page * self.page_size,
            }
            resp = self._session.get(f"{GAMMA_API_BASE}/markets", params=params, timeout=self.timeout_seconds)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            markets.extend([market for market in batch if isinstance(market, dict)])
            if len(batch) < self.page_size:
                break
            time.sleep(0.15)
        return markets

    @staticmethod
    def _market_event_id(raw_market: Mapping[str, Any]) -> str:
        direct = str(
            raw_market.get("event_id")
            or raw_market.get("eventId")
            or raw_market.get("parentEventId")
            or raw_market.get("parentEventID")
            or ""
        ).strip()
        if direct:
            return direct
        events = raw_market.get("events")
        if isinstance(events, list):
            for raw_event in events:
                if isinstance(raw_event, Mapping):
                    event_id = str(raw_event.get("id") or raw_event.get("event_id") or "").strip()
                    if event_id:
                        return event_id
        return ""

    @staticmethod
    def _market_event_title(raw_market: Mapping[str, Any]) -> str:
        direct = str(
            raw_market.get("event_title")
            or raw_market.get("eventTitle")
            or raw_market.get("groupTitle")
            or ""
        ).strip()
        if direct:
            return direct
        events = raw_market.get("events")
        if isinstance(events, list):
            for raw_event in events:
                if isinstance(raw_event, Mapping):
                    title = str(raw_event.get("title") or raw_event.get("slug") or "").strip()
                    if title:
                        return title
        return str(raw_market.get("question") or raw_market.get("title") or raw_market.get("id") or "").strip()

    @staticmethod
    def _market_outcome(raw_market: Mapping[str, Any]) -> str:
        return str(
            raw_market.get("groupItemTitle")
            or raw_market.get("outcome")
            or raw_market.get("outcomeName")
            or raw_market.get("title")
            or raw_market.get("id")
            or ""
        ).strip()

    @staticmethod
    def _market_tick_size(raw_market: Mapping[str, Any]) -> float:
        return max(0.001, _as_float(raw_market.get("orderPriceMinTickSize"), 0.01))

    @staticmethod
    def _market_category(raw_market: Mapping[str, Any]) -> str:
        return str(
            raw_market.get("eventCategory")
            or raw_market.get("category")
            or raw_market.get("tag")
            or "unknown"
        ).strip() or "unknown"

    @staticmethod
    def _estimate_resolution_hours(raw_market: Mapping[str, Any]) -> float | None:
        end_date_str = raw_market.get("endDate") or raw_market.get("end_date_iso")
        if not end_date_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                end_dt = datetime.strptime(str(end_date_str), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
            if hours > 0:
                return hours
        return None

    def group_market_siblings(self, raw_markets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        seen_outcomes: dict[str, set[str]] = {}
        for raw_market in raw_markets:
            if not isinstance(raw_market, Mapping):
                continue
            if _as_bool(raw_market.get("closed")):
                continue
            if raw_market.get("active") is False:
                continue
            question = str(raw_market.get("question") or raw_market.get("title") or "").strip()
            if not question:
                continue
            event_id = self._market_event_id(raw_market)
            event_key = event_id or _question_skeleton(question) or _norm_text(question) or question.lower()
            outcome = self._market_outcome(raw_market)
            outcome_key = _norm_text(outcome) or str(raw_market.get("id") or "").strip()
            if not outcome_key:
                continue
            if event_key not in grouped:
                grouped[event_key] = {
                    "event_id": event_id or event_key,
                    "event_key": event_key,
                    "event_title": self._market_event_title(raw_market),
                    "question": question,
                    "markets": [],
                }
                seen_outcomes[event_key] = set()
            if outcome_key in seen_outcomes[event_key]:
                continue
            grouped[event_key]["markets"].append(dict(raw_market))
            seen_outcomes[event_key].add(outcome_key)

        ordered = sorted(
            grouped.values(),
            key=lambda row: (-len(row["markets"]), str(row["event_title"]).lower(), str(row["event_id"]).lower()),
        )
        return [row for row in ordered if len(row["markets"]) >= self.min_event_markets]

    def _fetch_order_book(self, token_id: str) -> dict[str, Any] | None:
        clean_id = str(token_id).strip()
        if not clean_id:
            return None
        try:
            resp = self._session.get(
                CLOB_BOOK_URL,
                params={"token_id": clean_id},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        payload = resp.json()
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _best_bid_ask(book: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
        if not isinstance(book, Mapping):
            return None, None

        def _pick(levels: Any, *, side: str) -> float | None:
            if not isinstance(levels, list) or not levels:
                return None
            prices: list[float] = []
            for level in levels:
                if not isinstance(level, Mapping):
                    continue
                price = _as_float(level.get("price"), default=-1.0)
                if 0.0 <= price <= 1.0:
                    prices.append(price)
            if not prices:
                return None
            return max(prices) if side == "bid" else min(prices)

        best_bid = _pick(book.get("bids"), side="bid")
        best_ask = _pick(book.get("asks"), side="ask")
        if best_bid is None:
            fallback = _as_float(book.get("best_bid"), default=-1.0)
            best_bid = fallback if 0.0 <= fallback <= 1.0 else None
        if best_ask is None:
            fallback = _as_float(book.get("best_ask"), default=-1.0)
            best_ask = fallback if 0.0 <= fallback <= 1.0 else None
        return best_bid, best_ask

    @staticmethod
    def _depth_usd(levels: Any) -> float:
        if not isinstance(levels, list):
            return 0.0
        depth = 0.0
        for level in levels:
            if not isinstance(level, Mapping):
                continue
            price = _as_float(level.get("price"), default=-1.0)
            size = _as_float(level.get("size"), default=-1.0)
            if 0.0 <= price <= 1.0 and size > 0.0:
                depth += price * size
        return round(depth, 4)

    def scan_market_violations(
        self,
        markets: Sequence[Mapping[str, Any]] | None = None,
        *,
        threshold: float = 0.05,
    ) -> list[SumViolationOpportunity]:
        """Detect executable multi-outcome sum violations from Gamma `/markets`."""
        threshold = max(0.0, float(threshold))
        prefilter_slack = min(self.prefilter_buffer, threshold * 0.5)
        prefilter_threshold = max(0.0, threshold - prefilter_slack)

        grouped = self.group_market_siblings(markets or self.fetch_active_markets())
        candidates: list[tuple[float, dict[str, Any], float]] = []
        for group in grouped:
            approx_sum = 0.0
            valid_legs = 0
            for raw_market in group["markets"]:
                _, yes_ask = extract_gamma_yes_quotes(raw_market)
                if yes_ask is None:
                    continue
                approx_sum += yes_ask
                valid_legs += 1
            if valid_legs < self.min_event_markets:
                continue
            violation = abs(approx_sum - 1.0)
            if violation + 1e-9 < prefilter_threshold:
                continue
            candidates.append((violation, group, approx_sum))

        candidates.sort(key=lambda row: row[0], reverse=True)
        opportunities: list[SumViolationOpportunity] = []

        for _, group, _approx_sum in candidates[: self.max_events]:
            legs: list[SumViolationLeg] = []
            for raw_market in group["markets"]:
                yes_token_id, no_token_id = parse_clob_token_ids(raw_market.get("clobTokenIds"))
                yes_book = self._fetch_order_book(yes_token_id) if yes_token_id else None
                no_book = self._fetch_order_book(no_token_id) if no_token_id else None
                yes_bid, yes_ask = self._best_bid_ask(yes_book)
                no_bid, no_ask = self._best_bid_ask(no_book)

                if yes_bid is None or yes_ask is None:
                    fallback_bid, fallback_ask = extract_gamma_yes_quotes(raw_market)
                    yes_bid = yes_bid if yes_bid is not None else fallback_bid
                    yes_ask = yes_ask if yes_ask is not None else fallback_ask
                if no_bid is None and yes_ask is not None:
                    inferred = 1.0 - yes_ask
                    no_bid = inferred if 0.0 <= inferred <= 1.0 else None
                if no_ask is None and yes_bid is not None:
                    inferred = 1.0 - yes_bid
                    no_ask = inferred if 0.0 <= inferred <= 1.0 else None

                leg = SumViolationLeg(
                    market_id=str(raw_market.get("id") or raw_market.get("market_id") or "").strip(),
                    event_id=str(group["event_id"]),
                    question=str(raw_market.get("question") or raw_market.get("title") or group["question"]).strip(),
                    outcome=self._market_outcome(raw_market),
                    category=self._market_category(raw_market),
                    yes_token_id=yes_token_id,
                    no_token_id=no_token_id,
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    yes_depth_usd=self._depth_usd(yes_book.get("asks") if isinstance(yes_book, Mapping) else None),
                    no_depth_usd=self._depth_usd(no_book.get("asks") if isinstance(no_book, Mapping) else None),
                    resolution_hours=self._estimate_resolution_hours(raw_market),
                    tick_size=self._market_tick_size(raw_market),
                    raw_market=dict(raw_market),
                )
                if leg.market_id:
                    legs.append(leg)

            if len(legs) < self.min_event_markets:
                continue

            sum_yes_ask = (
                float(sum(leg.yes_ask for leg in legs if leg.yes_ask is not None))
                if all(leg.yes_ask is not None for leg in legs)
                else None
            )
            sum_yes_bid = (
                float(sum(leg.yes_bid for leg in legs if leg.yes_bid is not None))
                if all(leg.yes_bid is not None for leg in legs)
                else None
            )
            sum_no_ask = (
                float(sum(leg.no_ask for leg in legs if leg.no_ask is not None))
                if all(leg.no_ask is not None for leg in legs)
                else None
            )
            sum_no_bid = (
                float(sum(leg.no_bid for leg in legs if leg.no_bid is not None))
                if all(leg.no_bid is not None for leg in legs)
                else None
            )

            if sum_yes_ask is None:
                continue

            trade_side = ""
            execution_cost = 0.0
            payout_per_basket = 0.0
            violation_amount = 0.0
            gross_profit_per_basket = 0.0
            can_trade_half_dollar = False

            if sum_yes_ask <= 1.0 - threshold + 1e-9:
                trade_side = "buy_yes_basket"
                execution_cost = float(sum_yes_ask)
                payout_per_basket = 1.0
                violation_amount = float(1.0 - sum_yes_ask)
                gross_profit_per_basket = payout_per_basket - execution_cost
                can_trade_half_dollar = all(leg.yes_depth_usd + 1e-9 >= 0.50 for leg in legs)
            elif sum_yes_ask >= 1.0 + threshold - 1e-9:
                trade_side = "buy_no_basket"
                execution_cost = float(sum_no_ask) if sum_no_ask is not None else 0.0
                payout_per_basket = float(max(0, len(legs) - 1))
                violation_amount = float(sum_yes_ask - 1.0)
                gross_profit_per_basket = payout_per_basket - execution_cost if execution_cost > 0.0 else 0.0
                can_trade_half_dollar = all(leg.no_depth_usd + 1e-9 >= 0.50 for leg in legs)
            else:
                continue

            gross_profit_per_dollar = (
                float(gross_profit_per_basket / execution_cost)
                if execution_cost > 0.0
                else 0.0
            )
            raw_id = "|".join(
                [
                    str(group["event_id"]),
                    trade_side,
                    f"{sum_yes_ask:.6f}",
                    ",".join(sorted(leg.market_id for leg in legs)),
                ]
            )
            opportunities.append(
                SumViolationOpportunity(
                    violation_id=hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:20],
                    event_id=str(group["event_id"]),
                    event_key=str(group["event_key"]),
                    event_title=str(group["event_title"]),
                    market_ids=tuple(leg.market_id for leg in legs),
                    outcomes=tuple(leg.outcome for leg in legs),
                    legs=tuple(legs),
                    threshold=threshold,
                    sum_yes_bid=sum_yes_bid,
                    sum_yes_ask=sum_yes_ask,
                    sum_no_bid=sum_no_bid,
                    sum_no_ask=sum_no_ask,
                    trade_side=trade_side,
                    violation_amount=violation_amount,
                    gross_profit_per_basket=float(gross_profit_per_basket),
                    gross_profit_per_dollar=float(gross_profit_per_dollar),
                    execution_cost=float(execution_cost),
                    payout_per_basket=float(payout_per_basket),
                    can_trade_fifty_cents_per_leg=bool(can_trade_half_dollar),
                )
            )

        opportunities.sort(key=lambda row: row.violation_amount, reverse=True)
        return opportunities

    def _event_is_candidate(self, raw_event: Mapping[str, Any]) -> bool:
        if _as_bool(raw_event.get("cumulativeMarkets")):
            return False
        if self._looks_ladder_event(raw_event):
            return False
        return bool(self._watch_builder.build_watchlist([raw_event]))

    def _flatten_event_markets(self, raw_event: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self._watch_builder.flatten_markets([raw_event])

    def _looks_ladder_event(self, raw_event: Mapping[str, Any]) -> bool:
        raw_markets = raw_event.get("markets")
        if not isinstance(raw_markets, list) or len(raw_markets) < self.min_event_markets:
            return False

        questions = [
            str(market.get("question") or market.get("title") or raw_event.get("title") or "").strip()
            for market in raw_markets
            if isinstance(market, Mapping)
        ]
        questions = [question for question in questions if question]
        if len(questions) < self.min_event_markets:
            return False

        skeletons = {_question_skeleton(question) for question in questions}
        if len(skeletons) != 1:
            return False
        if sum(1 for question in questions if _DATE_OR_NUMERIC_RE.search(question)) < self.min_event_markets - 1:
            return False
        return len({_norm_text(question) for question in questions}) >= self.min_event_markets

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

    def _build_measurement_capture(self, *, scanner: A6SumScanner, batch: Any, now_ts: int) -> dict[str, Any]:
        cadence_seconds: float | None = None
        if self._measurement_last_scan_ts is not None:
            cadence_seconds = max(0.0, float(now_ts - self._measurement_last_scan_ts))
        records = scanner.build_measurement_records(batch, refresh_cadence_seconds=cadence_seconds)

        state_transitions: list[dict[str, Any]] = []
        for record in records:
            previous = self._measurement_event_state.get(record.event_id)
            if previous is not None and previous != record.state:
                state_transitions.append(
                    {
                        "event_id": record.event_id,
                        "from_state": previous,
                        "to_state": record.state,
                        "detected_at_ts": int(now_ts),
                    }
                )
            self._measurement_event_state[record.event_id] = record.state

        self._measurement_last_scan_ts = int(now_ts)
        executable_count = sum(1 for record in records if record.state == "executable")
        blocked_count = sum(1 for record in records if record.state == "blocked")
        return {
            "schema_version": "structural_measurement_capture.v1",
            "mode": "measurement_only" if self.measurement_only else "scan_with_measurement_capture",
            "generated_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
            "non_ordering_guardrail": {
                "measurement_only": bool(self.measurement_only),
                "order_routing_enabled": bool(self.enable_order_routing),
                "order_routing_reachable": False,
            },
            "summary": {
                "events_observed": len(records),
                "executable_events": executable_count,
                "blocked_events": blocked_count,
                "opportunity_frequency_per_hour": (
                    round((executable_count * 3600.0) / cadence_seconds, 6)
                    if cadence_seconds and cadence_seconds > 0
                    else None
                ),
            },
            "capture_window": {
                "scan_interval_seconds": int(self.interval_seconds),
                "observed_refresh_cadence_seconds": cadence_seconds,
                "scanned_at_ts": int(now_ts),
            },
            "state_transitions": state_transitions,
            "measurements": [record.to_dict() for record in records],
        }

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

        # Build executable A6Opportunity objects from the same engine state.
        self._latest_opportunities = []
        measurement_records = 0
        measurement_executable = 0
        if A6SumScanner is not None:
            try:
                a6_scanner = A6SumScanner(
                    config=A6ScannerConfig(
                        buy_threshold=self.buy_threshold,
                        upper_signal_threshold=self.unwind_threshold,
                        stale_quote_seconds=self.stale_quote_seconds,
                    )
                )
                batch = a6_scanner.scan_engine(engine, now_ts=now_ts)
                self._latest_opportunities = [
                    opp for opp in batch.opportunities if opp.executable
                ]
                capture = self._build_measurement_capture(scanner=a6_scanner, batch=batch, now_ts=now_ts)
                self._latest_measurement_capture = capture
                measurement_records = int(capture.get("summary", {}).get("events_observed") or 0)
                measurement_executable = int(capture.get("summary", {}).get("executable_events") or 0)
                if self.measurement_artifact_path is not None:
                    self.measurement_artifact_path.write_text(
                        json.dumps(capture, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
            except Exception as exc:
                logger.debug("A6 opportunity extraction failed: %s", exc)

        return ScanStats(
            timestamp_ts=now_ts,
            events_fetched=len(raw_events),
            candidate_events=len(candidate_events),
            candidate_markets=len(selected_markets),
            quotes_updated=len(quote_map),
            events_blocked_no_orderbook=len(blocked_event_ids),
            violations_found=len(violations),
            measurement_records=measurement_records,
            measurement_executable_records=measurement_executable,
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
    parser.add_argument("--measurement-only", action="store_true")
    parser.add_argument("--measurement-artifact-path", default=None)
    parser.add_argument("--enable-order-routing", action="store_true")
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
        measurement_only=bool(args.measurement_only),
        measurement_artifact_path=args.measurement_artifact_path,
        enable_order_routing=bool(args.enable_order_routing),
    )
    try:
        scanner.run(once=args.once, max_cycles=args.max_cycles)
    finally:
        scanner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
