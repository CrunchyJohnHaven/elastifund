#!/usr/bin/env python3
"""Async Gamma `/events` cache for structural arbitrage market discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
import logging
import re
import threading
import time
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from bot.resolution_normalizer import NormalizedMarket, normalize_market
except ImportError:  # pragma: no cover - direct script mode
    from resolution_normalizer import NormalizedMarket, normalize_market  # type: ignore


logger = logging.getLogger("JJ.gamma_cache")

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
HTTP_TIMEOUT_SECONDS = 20
DEFAULT_HEADERS = {
    "User-Agent": "constraint-arb-engine/1.0",
    "Accept": "application/json",
}

_DATE_OR_NUMERIC_RE = re.compile(
    r"\b(?:"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"20\d{2}|\d{1,2}/\d{1,2}|\d+(?:\.\d+)?%?"
    r")\b",
    flags=re.IGNORECASE,
)


PageFetcher = Callable[[int, int], Awaitable[Any] | Any]


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = [part.strip() for part in text.split(",") if part.strip()]
        raw = decoded

    out: list[str] = []
    if isinstance(raw, tuple):
        raw = list(raw)

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    out.append(value)
            elif isinstance(item, Mapping):
                value = (
                    item.get("name")
                    or item.get("label")
                    or item.get("slug")
                    or item.get("tag")
                    or item.get("outcome")
                )
                if isinstance(value, str) and value.strip():
                    out.append(value.strip())
    return out


def _parse_clob_token_ids(raw: Any) -> tuple[str, str]:
    tokens = _parse_json_list(raw)
    yes_token = tokens[0] if tokens else ""
    no_token = tokens[1] if len(tokens) > 1 else ""
    return yes_token, no_token


def _extract_market_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("market_id") or raw.get("id") or raw.get("conditionId") or raw.get("condition_id") or raw.get("slug")
    return str(value or "").strip()


def _extract_condition_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("conditionId") or raw.get("condition_id") or raw.get("market_id") or raw.get("id")
    return str(value or "").strip()


def _extract_question(raw: Mapping[str, Any]) -> str:
    value = raw.get("question") or raw.get("title") or raw.get("name")
    return str(value or "").strip()


def _extract_outcome_name(raw: Mapping[str, Any]) -> str:
    for key in ("groupItemTitle", "outcome", "outcomeName", "title"):
        value = raw.get(key)
        if isinstance(value, str):
            cleaned = re.sub(r"^[\s:\-–—]+", "", value).strip()
            if cleaned:
                return cleaned
    return ""


def _parse_tags(*values: Any) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        for tag in _parse_json_list(value):
            norm = tag.strip().lower()
            if norm and norm not in tags:
                tags.append(norm)
    return tuple(tags)


def _question_skeleton(question: str) -> str:
    skeleton = _DATE_OR_NUMERIC_RE.sub("<value>", question.lower())
    skeleton = re.sub(r"[^a-z<>\s]", " ", skeleton)
    return re.sub(r"\s+", " ", skeleton).strip()


def _looks_cumulative_ladder(markets: Sequence[Mapping[str, Any]]) -> bool:
    questions = [_extract_question(market) for market in markets]
    questions = [question for question in questions if question]
    if len(questions) < 3:
        return False
    skeletons = {_question_skeleton(question) for question in questions}
    if len(skeletons) != 1:
        return False
    decorated = sum(1 for question in questions if _DATE_OR_NUMERIC_RE.search(question))
    distinct = len({question.lower() for question in questions})
    return decorated >= len(questions) - 1 and distinct >= len(questions)


def _has_generic_binary_outcomes(raw: Mapping[str, Any]) -> bool:
    outcomes = {out.strip().lower() for out in _parse_json_list(raw.get("outcomes")) if out.strip()}
    return bool(outcomes) and outcomes <= {"yes", "no"}


def _http_json(url: str) -> Any:
    request = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _fetch_gamma_events_page(offset: int, limit: int) -> list[dict[str, Any]]:
    params = {
        "active": "true",
        "closed": "false",
        "limit": str(max(1, limit)),
        "offset": str(max(0, offset)),
    }
    url = f"{GAMMA_API_BASE}/events?{urlencode(params)}"
    payload = _http_json(url)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        data = payload.get("data", [])
        rows = data if isinstance(data, list) else []
    else:
        rows = []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


@dataclass(frozen=True)
class GammaMarketRecord:
    market_id: str
    event_id: str
    event_slug: str
    event_title: str
    market_slug: str
    question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    outcome_name: str
    outcome_names: tuple[str, ...]
    category: str
    tags: tuple[str, ...]
    enable_order_book: bool
    normalized_market: NormalizedMarket
    multi_outcome_event_id: str | None
    multi_outcome_size: int
    incomplete_reasons: tuple[str, ...]
    fetched_at_ts: float

    @property
    def token_ids(self) -> tuple[str, str]:
        return (self.yes_token_id, self.no_token_id)

    @property
    def executable(self) -> bool:
        return not self.incomplete_reasons and self.enable_order_book


@dataclass(frozen=True)
class GammaEventRecord:
    event_id: str
    slug: str
    title: str
    category: str
    tags: tuple[str, ...]
    market_ids: tuple[str, ...]
    outcome_names: tuple[str, ...]
    is_multi_outcome: bool
    executable: bool
    blocked_reasons: tuple[str, ...]
    fetched_at_ts: float


@dataclass(frozen=True)
class GammaCacheMetrics:
    refresh_count: int
    refresh_failures: int
    event_count: int
    market_count: int
    multi_outcome_event_count: int
    incomplete_market_count: int
    last_refresh_started_ts: float
    last_refresh_completed_ts: float
    last_error: str | None


@dataclass(frozen=True)
class GammaMarketUniverseSnapshot:
    refreshed_at_ts: float
    events: dict[str, GammaEventRecord]
    markets: dict[str, GammaMarketRecord]
    token_to_market_id: dict[str, str]
    metrics: GammaCacheMetrics

    def normalized_markets(self) -> tuple[NormalizedMarket, ...]:
        return tuple(record.normalized_market for record in self.markets.values())

    def multi_outcome_events(self) -> tuple[GammaEventRecord, ...]:
        return tuple(event for event in self.events.values() if event.is_multi_outcome)

    def all_token_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.token_to_market_id))


class GammaMarketCache:
    """Maintain an in-memory cache of active Gamma events and normalized markets."""

    def __init__(
        self,
        *,
        max_pages: int = 20,
        page_size: int = 100,
        refresh_interval_seconds: int = 300,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 60.0,
        page_fetcher: PageFetcher | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.max_pages = max(1, int(max_pages))
        self.page_size = max(1, min(500, int(page_size)))
        self.refresh_interval_seconds = max(10, int(refresh_interval_seconds))
        self.backoff_base_seconds = max(0.25, float(backoff_base_seconds))
        self.backoff_max_seconds = max(self.backoff_base_seconds, float(backoff_max_seconds))
        self._page_fetcher = page_fetcher
        self._clock = clock or time.time
        self._sleep = sleep or asyncio.sleep
        self._lock = threading.RLock()
        self._subscribers: list[asyncio.Queue[GammaMarketUniverseSnapshot]] = []
        self._snapshot = GammaMarketUniverseSnapshot(
            refreshed_at_ts=0.0,
            events={},
            markets={},
            token_to_market_id={},
            metrics=GammaCacheMetrics(
                refresh_count=0,
                refresh_failures=0,
                event_count=0,
                market_count=0,
                multi_outcome_event_count=0,
                incomplete_market_count=0,
                last_refresh_started_ts=0.0,
                last_refresh_completed_ts=0.0,
                last_error=None,
            ),
        )
        self._running = False

    def subscribe(self, *, maxsize: int = 1) -> asyncio.Queue[GammaMarketUniverseSnapshot]:
        queue: asyncio.Queue[GammaMarketUniverseSnapshot] = asyncio.Queue(maxsize=max(1, maxsize))
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def get_snapshot(self) -> GammaMarketUniverseSnapshot:
        with self._lock:
            return self._snapshot

    def get_metrics(self) -> GammaCacheMetrics:
        return self.get_snapshot().metrics

    async def run(self) -> None:
        if self._running:
            return
        self._running = True
        backoff = self.backoff_base_seconds
        try:
            while self._running:
                try:
                    await self.refresh_once(force=True)
                    backoff = self.backoff_base_seconds
                    await self._sleep(float(self.refresh_interval_seconds))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("gamma_cache_refresh_failed err=%s", exc)
                    self._bump_failure(str(exc))
                    await self._sleep(backoff)
                    backoff = min(self.backoff_max_seconds, max(self.backoff_base_seconds, backoff * 2.0))
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def refresh_once(self, *, force: bool = False) -> GammaMarketUniverseSnapshot:
        current = self.get_snapshot()
        now = self._clock()
        if (
            not force
            and current.refreshed_at_ts > 0
            and (now - current.refreshed_at_ts) < float(self.refresh_interval_seconds)
        ):
            return current

        started_at = now
        events: list[dict[str, Any]] = []
        for page in range(self.max_pages):
            offset = page * self.page_size
            batch = await self._fetch_page(offset=offset, limit=self.page_size)
            if not batch:
                break
            events.extend(batch)
            if len(batch) < self.page_size:
                break

        snapshot = self._build_snapshot(events=events, started_at=started_at, completed_at=self._clock())
        self._set_snapshot(snapshot)
        await self._broadcast(snapshot)
        return snapshot

    async def _fetch_page(self, *, offset: int, limit: int) -> list[dict[str, Any]]:
        if self._page_fetcher is None:
            return await asyncio.to_thread(_fetch_gamma_events_page, offset, limit)

        result = self._page_fetcher(offset, limit)
        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, list):
            rows = result
        elif isinstance(result, Mapping):
            data = result.get("data", [])
            rows = data if isinstance(data, list) else []
        else:
            rows = []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def _build_snapshot(
        self,
        *,
        events: Sequence[Mapping[str, Any]],
        started_at: float,
        completed_at: float,
    ) -> GammaMarketUniverseSnapshot:
        market_records: dict[str, GammaMarketRecord] = {}
        event_records: dict[str, GammaEventRecord] = {}
        token_to_market_id: dict[str, str] = {}
        incomplete_market_count = 0

        for event in events:
            flattened = self._flatten_event_markets(event)
            if not flattened:
                continue

            event_id = str(event.get("id") or event.get("slug") or "").strip()
            event_slug = str(event.get("slug") or "").strip()
            event_title = str(event.get("title") or event.get("name") or "").strip()
            event_category = str(event.get("category") or "").strip().lower() or "unknown"
            event_tags = _parse_tags(event.get("tags"))
            event_outcomes = self._collect_event_outcomes(flattened)
            is_multi_outcome = self._is_multi_outcome_event(event, flattened, event_outcomes)

            event_market_ids: list[str] = []
            event_market_records: list[GammaMarketRecord] = []
            for raw_market in flattened:
                record = self._build_market_record(
                    raw_market=raw_market,
                    event_id=event_id,
                    event_slug=event_slug,
                    event_title=event_title,
                    event_category=event_category,
                    event_tags=event_tags,
                    event_outcomes=event_outcomes,
                    is_multi_outcome=is_multi_outcome,
                    fetched_at_ts=completed_at,
                )
                if not record.market_id:
                    continue
                market_records[record.market_id] = record
                event_market_ids.append(record.market_id)
                event_market_records.append(record)
                if record.incomplete_reasons:
                    incomplete_market_count += 1
                for token_id in record.token_ids:
                    if token_id:
                        token_to_market_id[token_id] = record.market_id

            if not event_market_records:
                continue

            blocked_reasons = self._event_blocked_reasons(
                event=event,
                markets=flattened,
                records=event_market_records,
                outcome_names=event_outcomes,
                is_multi_outcome=is_multi_outcome,
            )
            event_record = GammaEventRecord(
                event_id=event_id or event_market_records[0].event_id,
                slug=event_slug,
                title=event_title,
                category=event_category,
                tags=event_tags,
                market_ids=tuple(event_market_ids),
                outcome_names=event_outcomes,
                is_multi_outcome=is_multi_outcome,
                executable=is_multi_outcome and not blocked_reasons,
                blocked_reasons=blocked_reasons,
                fetched_at_ts=completed_at,
            )
            event_records[event_record.event_id] = event_record

        metrics = GammaCacheMetrics(
            refresh_count=self._snapshot.metrics.refresh_count + 1,
            refresh_failures=self._snapshot.metrics.refresh_failures,
            event_count=len(event_records),
            market_count=len(market_records),
            multi_outcome_event_count=sum(1 for event in event_records.values() if event.is_multi_outcome),
            incomplete_market_count=incomplete_market_count,
            last_refresh_started_ts=started_at,
            last_refresh_completed_ts=completed_at,
            last_error=None,
        )
        return GammaMarketUniverseSnapshot(
            refreshed_at_ts=completed_at,
            events=event_records,
            markets=market_records,
            token_to_market_id=token_to_market_id,
            metrics=metrics,
        )

    def _flatten_event_markets(self, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw_markets = event.get("markets") or []
        if not isinstance(raw_markets, list):
            return []
        event_id = str(event.get("id") or event.get("slug") or "").strip()
        event_slug = str(event.get("slug") or "").strip()
        event_title = str(event.get("title") or event.get("name") or "").strip()
        event_category = str(event.get("category") or "").strip()
        event_tags = event.get("tags")
        flattened: list[dict[str, Any]] = []
        for raw_market in raw_markets:
            if not isinstance(raw_market, Mapping):
                continue
            market = dict(raw_market)
            if event_id:
                market.setdefault("event_id", event_id)
            if event_slug:
                market.setdefault("eventSlug", event_slug)
            if event_title:
                market.setdefault("eventTitle", event_title)
            if event_category:
                market.setdefault("eventCategory", event_category)
            market.setdefault("cumulativeMarkets", event.get("cumulativeMarkets"))
            market.setdefault("events", [{"id": event_id, "slug": event_slug}] if event_id or event_slug else [])
            if event_tags is not None and market.get("tags") is None:
                market["tags"] = event_tags
            flattened.append(market)
        return flattened

    def _collect_event_outcomes(self, markets: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        outcomes: list[str] = []
        for market in markets:
            label = _extract_outcome_name(market)
            if label and label not in outcomes:
                outcomes.append(label)
        return tuple(outcomes)

    def _is_multi_outcome_event(
        self,
        event: Mapping[str, Any],
        markets: Sequence[Mapping[str, Any]],
        outcome_names: Sequence[str],
    ) -> bool:
        if any(_safe_bool(market.get("isMultiOutcome")) for market in markets):
            return True
        neg_risk = any(
            _safe_bool(value)
            for value in (
                event.get("negRisk"),
                event.get("enableNegRisk"),
                event.get("negRiskAugmented"),
                event.get("showAllOutcomes"),
            )
        )
        if not neg_risk:
            return False
        if len(outcome_names) < 3:
            return False
        if _looks_cumulative_ladder(markets):
            return False
        return len(set(outcome_names)) == len(outcome_names)

    def _build_market_record(
        self,
        *,
        raw_market: Mapping[str, Any],
        event_id: str,
        event_slug: str,
        event_title: str,
        event_category: str,
        event_tags: tuple[str, ...],
        event_outcomes: Sequence[str],
        is_multi_outcome: bool,
        fetched_at_ts: float,
    ) -> GammaMarketRecord:
        market_id = _extract_market_id(raw_market)
        condition_id = _extract_condition_id(raw_market)
        question = _extract_question(raw_market)
        market_slug = str(raw_market.get("slug") or "").strip()
        outcome_name = _extract_outcome_name(raw_market)
        yes_token_id, no_token_id = _parse_clob_token_ids(raw_market.get("clobTokenIds"))
        enable_order_book = _safe_bool(raw_market.get("enableOrderBook"))
        tags = _parse_tags(event_tags, raw_market.get("tags"))

        augmented = dict(raw_market)
        if is_multi_outcome and outcome_name and not augmented.get("outcome"):
            augmented["outcome"] = outcome_name
        if is_multi_outcome and event_outcomes and (
            not augmented.get("outcomes") or _has_generic_binary_outcomes(augmented)
        ):
            augmented["outcomes"] = json.dumps(list(event_outcomes))
            augmented["isMultiOutcome"] = True

        normalized = normalize_market(augmented)

        incomplete_reasons: list[str] = []
        if not market_id:
            incomplete_reasons.append("missing_market_id")
        if not condition_id:
            incomplete_reasons.append("missing_condition_id")
        if not question:
            incomplete_reasons.append("missing_question")
        if not yes_token_id:
            incomplete_reasons.append("missing_yes_token")
        if not no_token_id:
            incomplete_reasons.append("missing_no_token")
        if not enable_order_book:
            incomplete_reasons.append("orderbook_disabled")
        if is_multi_outcome and not outcome_name:
            incomplete_reasons.append("missing_outcome_name")

        return GammaMarketRecord(
            market_id=market_id,
            event_id=event_id or normalized.event_id,
            event_slug=event_slug,
            event_title=event_title,
            market_slug=market_slug,
            question=question or normalized.question,
            condition_id=condition_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            outcome_name=outcome_name,
            outcome_names=tuple(event_outcomes),
            category=event_category or normalized.category,
            tags=tags,
            enable_order_book=enable_order_book,
            normalized_market=normalized,
            multi_outcome_event_id=(event_id or normalized.event_id) if is_multi_outcome else None,
            multi_outcome_size=len(event_outcomes) if is_multi_outcome else 0,
            incomplete_reasons=tuple(dict.fromkeys(incomplete_reasons)),
            fetched_at_ts=fetched_at_ts,
        )

    def _event_blocked_reasons(
        self,
        *,
        event: Mapping[str, Any],
        markets: Sequence[Mapping[str, Any]],
        records: Sequence[GammaMarketRecord],
        outcome_names: Sequence[str],
        is_multi_outcome: bool,
    ) -> tuple[str, ...]:
        if not is_multi_outcome:
            return tuple()

        reasons: list[str] = []
        if _safe_bool(event.get("cumulativeMarkets")) or _looks_cumulative_ladder(markets):
            reasons.append("cumulative_event")
        if len(outcome_names) < 3:
            reasons.append("insufficient_outcomes")
        if len(set(outcome_names)) != len(tuple(outcome_names)):
            reasons.append("duplicate_outcomes")
        if any(record.incomplete_reasons for record in records):
            reasons.append("incomplete_market")
        if any(not record.enable_order_book for record in records):
            reasons.append("orderbook_disabled")
        if any(not record.yes_token_id or not record.no_token_id for record in records):
            reasons.append("incomplete_token_coverage")
        return tuple(dict.fromkeys(reasons))

    def _set_snapshot(self, snapshot: GammaMarketUniverseSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def _bump_failure(self, error: str) -> None:
        with self._lock:
            metrics = self._snapshot.metrics
            self._snapshot = GammaMarketUniverseSnapshot(
                refreshed_at_ts=self._snapshot.refreshed_at_ts,
                events=self._snapshot.events,
                markets=self._snapshot.markets,
                token_to_market_id=self._snapshot.token_to_market_id,
                metrics=GammaCacheMetrics(
                    refresh_count=metrics.refresh_count,
                    refresh_failures=metrics.refresh_failures + 1,
                    event_count=metrics.event_count,
                    market_count=metrics.market_count,
                    multi_outcome_event_count=metrics.multi_outcome_event_count,
                    incomplete_market_count=metrics.incomplete_market_count,
                    last_refresh_started_ts=metrics.last_refresh_started_ts,
                    last_refresh_completed_ts=metrics.last_refresh_completed_ts,
                    last_error=error,
                ),
            )

    async def _broadcast(self, snapshot: GammaMarketUniverseSnapshot) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:  # pragma: no cover - guarded above
                continue
