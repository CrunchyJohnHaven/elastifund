#!/usr/bin/env python3
"""Neg-risk sum-violation scanner for multi-outcome basket arbitrage."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

import requests

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT_SECONDS = 12.0

logger = logging.getLogger("negrisk_arb_scanner")


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


def _clamp_price(value: float | None) -> float | None:
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return value
    return None


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [part.strip() for part in text.split(",") if part.strip()]
        if isinstance(payload, list):
            return list(payload)
    return []


def parse_clob_token_ids(raw: Any) -> tuple[str, str]:
    """Parse Gamma `clobTokenIds` payload into (yes_token_id, no_token_id)."""
    parts: list[str] = []
    for item in _parse_json_list(raw):
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
        elif isinstance(item, Mapping):
            token = item.get("token_id") or item.get("id")
            if isinstance(token, str) and token.strip():
                parts.append(token.strip())
    yes = parts[0] if parts else ""
    no = parts[1] if len(parts) > 1 else ""
    return yes, no


def _parse_outcome_prices(raw: Any) -> tuple[float | None, float | None]:
    parsed = _parse_json_list(raw)
    if len(parsed) < 2:
        return None, None
    yes = _clamp_price(_as_float(parsed[0], default=-1.0))
    no = _clamp_price(_as_float(parsed[1], default=-1.0))
    return yes, no


def _parse_iso_ts(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


def _norm_outcome(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9\s\+\-]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


@dataclass(frozen=True)
class NegRiskLegQuote:
    market_id: str
    condition_id: str
    outcome: str
    yes_token_id: str
    no_token_id: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    volume24hr_usd: float


@dataclass(frozen=True)
class NegRiskOpportunity:
    event_id: str
    event_slug: str
    event_title: str
    strategy: str
    outcomes_count: int
    volume24hr_usd: float
    sum_yes_ask: float
    sum_no_ask: float
    deviation: float
    required_capital_usd: float
    payout_usd: float
    expected_profit_usd: float
    profit_per_capital: float
    profit_per_capital_day: float | None
    resolution_hours: float | None
    resolution_time_utc: str | None
    legs: tuple[NegRiskLegQuote, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legs"] = [asdict(leg) for leg in self.legs]
        return payload


class NegRiskArbScanner:
    """Scan active Gamma neg-risk events for executable sum violations."""

    def __init__(
        self,
        *,
        min_overround_sum: float = 1.02,
        max_underround_sum: float = 0.98,
        min_deviation: float = 0.03,
        min_volume24hr_usd: float = 500.0,
        min_outcomes: int = 2,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_pages: int = 40,
        page_size: int = 100,
    ) -> None:
        self.min_overround_sum = float(min_overround_sum)
        self.max_underround_sum = float(max_underround_sum)
        self.min_deviation = float(min_deviation)
        self.min_volume24hr_usd = float(min_volume24hr_usd)
        self.min_outcomes = max(2, int(min_outcomes))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_pages = max(1, int(max_pages))
        self.page_size = max(1, min(500, int(page_size)))
        self._session = requests.Session()

    def close(self) -> None:
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
            resp = self._session.get(
                f"{GAMMA_API_BASE}/events",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []
            cast_batch = [dict(row) for row in batch if isinstance(row, Mapping)]
            events.extend(cast_batch)
            if len(cast_batch) < self.page_size:
                break
            time.sleep(0.1)
        return events

    @staticmethod
    def _is_neg_risk_event(raw_event: Mapping[str, Any]) -> bool:
        if _as_bool(raw_event.get("negRisk") or raw_event.get("enableNegRisk")):
            return True
        markets = raw_event.get("markets")
        if isinstance(markets, list):
            return any(_as_bool(m.get("negRisk")) for m in markets if isinstance(m, Mapping))
        return False

    @staticmethod
    def _market_outcome(raw_market: Mapping[str, Any]) -> str:
        for key in ("groupItemTitle", "outcome", "outcomeName", "title"):
            value = raw_market.get(key)
            if isinstance(value, str):
                cleaned = re.sub(r"^[\s:\-–—]+", "", value).strip()
                if cleaned:
                    return cleaned
        return str(raw_market.get("id") or "").strip()

    @staticmethod
    def _extract_market_quotes(raw_market: Mapping[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
        yes_bid = _clamp_price(_as_float(raw_market.get("bestBid"), default=-1.0))
        yes_ask = _clamp_price(_as_float(raw_market.get("bestAsk"), default=-1.0))

        no_bid = _clamp_price(_as_float(raw_market.get("noBid"), default=-1.0))
        no_ask = _clamp_price(_as_float(raw_market.get("noAsk"), default=-1.0))
        if no_bid is None:
            no_bid = _clamp_price(_as_float(raw_market.get("bestBidNo"), default=-1.0))
        if no_ask is None:
            no_ask = _clamp_price(_as_float(raw_market.get("bestAskNo"), default=-1.0))

        outcome_yes, outcome_no = _parse_outcome_prices(raw_market.get("outcomePrices"))
        if yes_bid is None:
            yes_bid = outcome_yes
        if yes_ask is None:
            yes_ask = outcome_yes
        if no_bid is None:
            no_bid = outcome_no
        if no_ask is None:
            no_ask = outcome_no

        if yes_bid is not None and yes_ask is not None and yes_bid > yes_ask:
            yes_bid, yes_ask = yes_ask, yes_bid
        if no_bid is not None and no_ask is not None and no_bid > no_ask:
            no_bid, no_ask = no_ask, no_bid

        # Complementary fallback when only one side is present.
        if no_bid is None and yes_ask is not None:
            no_bid = _clamp_price(1.0 - yes_ask)
        if no_ask is None and yes_bid is not None:
            no_ask = _clamp_price(1.0 - yes_bid)
        if yes_bid is None and no_ask is not None:
            yes_bid = _clamp_price(1.0 - no_ask)
        if yes_ask is None and no_bid is not None:
            yes_ask = _clamp_price(1.0 - no_bid)
        return yes_bid, yes_ask, no_bid, no_ask

    @staticmethod
    def _event_volume24hr(raw_event: Mapping[str, Any], legs: Sequence[NegRiskLegQuote]) -> float:
        direct = _as_float(raw_event.get("volume24hr"), default=-1.0)
        if direct >= 0.0:
            return direct
        direct_alt = _as_float(raw_event.get("volume24Hours"), default=-1.0)
        if direct_alt >= 0.0:
            return direct_alt
        return round(sum(max(0.0, leg.volume24hr_usd) for leg in legs), 6)

    @staticmethod
    def _event_resolution_ts(raw_event: Mapping[str, Any]) -> int | None:
        candidates: list[int] = []
        for key in ("endDate", "end_date", "resolutionDate", "resolveBy"):
            ts = _parse_iso_ts(raw_event.get(key))
            if ts is not None:
                candidates.append(ts)

        markets = raw_event.get("markets")
        if isinstance(markets, list):
            for raw_market in markets:
                if not isinstance(raw_market, Mapping):
                    continue
                for key in ("endDate", "end_date", "resolutionDate", "resolveBy"):
                    ts = _parse_iso_ts(raw_market.get(key))
                    if ts is not None:
                        candidates.append(ts)
                        break
        if not candidates:
            return None
        return min(candidates)

    def _collect_event_legs(self, raw_event: Mapping[str, Any]) -> tuple[NegRiskLegQuote, ...]:
        markets = raw_event.get("markets")
        if not isinstance(markets, list):
            return tuple()

        legs_by_outcome: dict[str, NegRiskLegQuote] = {}
        for raw_market in markets:
            if not isinstance(raw_market, Mapping):
                continue
            if _as_bool(raw_market.get("closed")):
                continue
            if raw_market.get("active") is False:
                continue
            yes_bid, yes_ask, no_bid, no_ask = self._extract_market_quotes(raw_market)
            if yes_ask is None:
                continue
            outcome = self._market_outcome(raw_market)
            if not outcome:
                continue
            yes_token_id, no_token_id = parse_clob_token_ids(raw_market.get("clobTokenIds"))
            leg = NegRiskLegQuote(
                market_id=str(raw_market.get("id") or raw_market.get("market_id") or "").strip(),
                condition_id=str(raw_market.get("conditionId") or raw_market.get("condition_id") or raw_market.get("id") or "").strip(),
                outcome=outcome,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                volume24hr_usd=_as_float(raw_market.get("volume24hr"), default=0.0),
            )
            outcome_key = _norm_outcome(outcome) or outcome
            existing = legs_by_outcome.get(outcome_key)
            if existing is None or leg.volume24hr_usd > existing.volume24hr_usd:
                legs_by_outcome[outcome_key] = leg
        return tuple(sorted(legs_by_outcome.values(), key=lambda row: row.outcome.lower()))

    def scan(self) -> tuple[list[NegRiskOpportunity], dict[str, int]]:
        raw_events = self.fetch_active_events()
        now_ts = int(time.time())
        opportunities: list[NegRiskOpportunity] = []
        stats = {
            "events_fetched": len(raw_events),
            "neg_risk_events": 0,
            "events_with_enough_outcomes": 0,
            "events_passing_volume": 0,
            "events_passing_deviation": 0,
            "opportunities_found": 0,
        }

        for raw_event in raw_events:
            if not self._is_neg_risk_event(raw_event):
                continue
            stats["neg_risk_events"] += 1
            legs = self._collect_event_legs(raw_event)
            if len(legs) < self.min_outcomes:
                continue
            stats["events_with_enough_outcomes"] += 1

            volume24hr = self._event_volume24hr(raw_event, legs)
            if volume24hr + 1e-9 < self.min_volume24hr_usd:
                continue
            stats["events_passing_volume"] += 1

            if any(leg.yes_ask is None for leg in legs):
                continue
            if any(leg.no_ask is None for leg in legs):
                continue

            sum_yes_ask = float(sum(leg.yes_ask or 0.0 for leg in legs))
            sum_no_ask = float(sum(leg.no_ask or 0.0 for leg in legs))
            deviation = float(sum_yes_ask - 1.0)
            if abs(deviation) + 1e-9 < self.min_deviation:
                continue
            stats["events_passing_deviation"] += 1

            strategy = ""
            required_capital = 0.0
            payout = 0.0
            if sum_yes_ask >= self.min_overround_sum - 1e-9:
                strategy = "buy_all_no"
                required_capital = sum_no_ask
                payout = float(max(0, len(legs) - 1))
            elif sum_yes_ask <= self.max_underround_sum + 1e-9:
                strategy = "buy_all_yes"
                required_capital = sum_yes_ask
                payout = 1.0
            else:
                continue

            if required_capital <= 0.0:
                continue
            expected_profit = payout - required_capital
            if expected_profit <= 0.0:
                continue

            profit_per_capital = expected_profit / required_capital
            resolution_ts = self._event_resolution_ts(raw_event)
            resolution_hours = None
            resolution_time_utc = None
            profit_per_capital_day = None
            if resolution_ts is not None and resolution_ts > now_ts:
                resolution_hours = (resolution_ts - now_ts) / 3600.0
                resolution_time_utc = datetime.fromtimestamp(
                    resolution_ts,
                    tz=timezone.utc,
                ).isoformat()
                if resolution_hours > 0:
                    profit_per_capital_day = profit_per_capital / (resolution_hours / 24.0)

            opportunities.append(
                NegRiskOpportunity(
                    event_id=str(raw_event.get("id") or "").strip(),
                    event_slug=str(raw_event.get("slug") or "").strip(),
                    event_title=str(raw_event.get("title") or raw_event.get("name") or "").strip(),
                    strategy=strategy,
                    outcomes_count=len(legs),
                    volume24hr_usd=round(volume24hr, 6),
                    sum_yes_ask=round(sum_yes_ask, 6),
                    sum_no_ask=round(sum_no_ask, 6),
                    deviation=round(deviation, 6),
                    required_capital_usd=round(required_capital, 6),
                    payout_usd=round(payout, 6),
                    expected_profit_usd=round(expected_profit, 6),
                    profit_per_capital=round(profit_per_capital, 8),
                    profit_per_capital_day=(
                        round(profit_per_capital_day, 8)
                        if profit_per_capital_day is not None
                        else None
                    ),
                    resolution_hours=(
                        round(resolution_hours, 6)
                        if resolution_hours is not None
                        else None
                    ),
                    resolution_time_utc=resolution_time_utc,
                    legs=tuple(legs),
                )
            )

        opportunities.sort(
            key=lambda row: (
                row.profit_per_capital_day if row.profit_per_capital_day is not None else -1.0,
                row.profit_per_capital,
                row.expected_profit_usd,
            ),
            reverse=True,
        )
        stats["opportunities_found"] = len(opportunities)
        return opportunities, stats


def scan_to_report(
    *,
    output_path: str | Path,
    min_overround_sum: float = 1.02,
    max_underround_sum: float = 0.98,
    min_deviation: float = 0.03,
    min_volume24hr_usd: float = 500.0,
    min_outcomes: int = 2,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_pages: int = 40,
    page_size: int = 100,
) -> dict[str, Any]:
    scanner = NegRiskArbScanner(
        min_overround_sum=min_overround_sum,
        max_underround_sum=max_underround_sum,
        min_deviation=min_deviation,
        min_volume24hr_usd=min_volume24hr_usd,
        min_outcomes=min_outcomes,
        timeout_seconds=timeout_seconds,
        max_pages=max_pages,
        page_size=page_size,
    )
    try:
        opportunities, stats = scanner.scan()
    finally:
        scanner.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanner": {
            "min_overround_sum": min_overround_sum,
            "max_underround_sum": max_underround_sum,
            "min_deviation": min_deviation,
            "min_volume24hr_usd": min_volume24hr_usd,
            "min_outcomes": min_outcomes,
            "max_pages": max_pages,
            "page_size": page_size,
        },
        "stats": stats,
        "opportunities": [opp.to_dict() for opp in opportunities],
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Neg-risk sum-violation arbitrage scanner")
    parser.add_argument("--output-path", default="reports/negrisk_opportunities.json")
    parser.add_argument("--min-overround-sum", type=float, default=1.02)
    parser.add_argument("--max-underround-sum", type=float, default=0.98)
    parser.add_argument("--min-deviation", type=float, default=0.03)
    parser.add_argument("--min-volume24hr-usd", type=float, default=500.0)
    parser.add_argument("--min-outcomes", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    report = scan_to_report(
        output_path=args.output_path,
        min_overround_sum=args.min_overround_sum,
        max_underround_sum=args.max_underround_sum,
        min_deviation=args.min_deviation,
        min_volume24hr_usd=args.min_volume24hr_usd,
        min_outcomes=args.min_outcomes,
        timeout_seconds=args.timeout_seconds,
        max_pages=args.max_pages,
        page_size=args.page_size,
    )
    logger.info(
        "negrisk scan complete events=%s neg_events=%s opportunities=%s report=%s",
        report["stats"].get("events_fetched"),
        report["stats"].get("neg_risk_events"),
        report["stats"].get("opportunities_found"),
        args.output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
