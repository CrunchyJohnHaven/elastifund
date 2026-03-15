#!/usr/bin/env python3
"""Empirical snapshot generator for A-6 / B-1 combinatorial arbitrage."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import json
import logging
from math import erf, sqrt
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.execution_readiness import (
    evaluate_structural_lane_readiness,
    StructuralLaneReadinessInputs,
)
from bot.resolution_normalizer import is_tradable_outcome, normalize_market
from bot.sum_violation_scanner import SumViolationScanner


logger = logging.getLogger("arb_empirics")

DATA_API_TRADES = "https://data-api.polymarket.com/trades"
DEFAULT_HEADERS = {
    "User-Agent": "arb-empirical-analysis/1.0",
    "Accept": "application/json",
}
DEFAULT_A6_PUBLIC_AUDIT_JSON = Path("reports/guaranteed_dollar_audit.json")
DEFAULT_A6_PUBLIC_AUDIT_MD = Path("reports/guaranteed_dollar_audit.md")
DEFAULT_B1_PUBLIC_AUDIT_JSON = Path("reports/b1_template_audit.json")
DEFAULT_B1_PUBLIC_AUDIT_MD = Path("reports/b1_template_audit.md")
DEFAULT_B1_AUDIT_MARKET_SAMPLE_SIZE = 1000


@dataclass(frozen=True)
class ReplayViolationRow:
    violation_id: str
    event_id: str
    detected_at_ts: int
    gross_edge: float
    score: float
    slippage_est: float
    fill_risk: float
    theoretical_pnl: float
    realized_pnl: float
    action: str
    relation_type: str
    event_legs: int
    missing_legs: int
    complete_basket: bool
    sum_yes_ask: float | None
    a6_mode: str | None = None
    settlement_path: str | None = None
    episode_id: str | None = None


@dataclass(frozen=True)
class EpisodeRow:
    episode_id: str
    event_id: str
    mode: str
    first_ts: int
    last_ts: int
    max_deviation: float

    @property
    def duration_seconds(self) -> int:
        return max(0, int(self.last_ts) - int(self.first_ts))


@dataclass(frozen=True)
class LegObservation:
    cycle_index: int
    observed_at_ts: int
    event_id: str
    event_title: str
    market_id: str
    condition_id: str
    question: str
    category: str
    outcome_name: str
    tick_size: float
    yes_bid: float | None
    yes_ask: float | None
    midpoint: float | None
    spread: float | None
    fetch_status: str
    is_tradable_outcome: bool


@dataclass(frozen=True)
class EventObservation:
    cycle_index: int
    observed_at_ts: int
    event_id: str
    event_title: str
    category: str
    tradable_legs: int
    priced_legs: int
    token_404_legs: int
    incomplete_legs: int
    complete_book: bool
    sum_yes_ask: float | None
    gross_deviation: float | None
    action: str | None


@dataclass(frozen=True)
class ViolationEpisode:
    event_id: str
    first_ts: int
    last_ts: int
    observations: int

    @property
    def duration_seconds(self) -> int:
        return max(0, self.last_ts - self.first_ts)


@dataclass(frozen=True)
class PassiveOrderProbe:
    cycle_index: int
    snapshot_ts: int
    condition_id: str
    market_id: str
    event_id: str
    midpoint: float
    price_bucket: str
    quote_price: float
    required_size: float


def utc_iso(ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else int(ts)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_best_quotes_from_book(book: Mapping[str, Any]) -> tuple[float | None, float | None]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    def best_price(levels: Sequence[Any], side: str) -> float | None:
        prices: list[float] = []
        for level in levels:
            if isinstance(level, Mapping):
                price = _safe_float(level.get("price"))
            elif isinstance(level, Sequence) and not isinstance(level, (str, bytes, bytearray)) and level:
                price = _safe_float(level[0])
            else:
                price = None
            if price is not None and 0.0 <= price <= 1.0:
                prices.append(price)
        if not prices:
            return None
        return max(prices) if side == "bid" else min(prices)

    return best_price(bids, "bid"), best_price(asks, "ask")


def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    q = min(1.0, max(0.0, float(q)))
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_numbers(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    vals = [float(value) for value in values]
    count = len(vals)
    return {
        "count": count,
        "min": min(vals),
        "p10": quantile(vals, 0.10),
        "p25": quantile(vals, 0.25),
        "median": quantile(vals, 0.50),
        "mean": sum(vals) / count,
        "p75": quantile(vals, 0.75),
        "p90": quantile(vals, 0.90),
        "max": max(vals),
    }


def midpoint_bucket(midpoint: float) -> str:
    if midpoint <= 0.05:
        return "tail_0_5pct"
    if midpoint <= 0.15:
        return "tail_5_15pct"
    if midpoint <= 0.35:
        return "mid_15_35pct"
    if midpoint <= 0.65:
        return "core_35_65pct"
    return "favorite_65_100pct"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total <= 0:
        return (None, None)
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = p + (z * z) / (2.0 * total)
    margin = z * sqrt((p * (1.0 - p) / total) + ((z * z) / (4.0 * total * total)))
    return ((centre - margin) / denom, (centre + margin) / denom)


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def serialize_for_json(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): serialize_for_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_for_json(item) for item in value]
    return value


def _json_loads(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _audit_summary_value(markdown_path: Path, label: str) -> int | None:
    if not markdown_path.exists():
        return None

    needle = f"- {label}:"
    with markdown_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith(needle):
                continue
            _, _, tail = line.partition(":")
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                return int(digits)
    return None


def summarize_public_a6_audit(
    *,
    json_path: Path = DEFAULT_A6_PUBLIC_AUDIT_JSON,
    markdown_path: Path = DEFAULT_A6_PUBLIC_AUDIT_MD,
    execute_threshold: float = 0.95,
) -> dict[str, Any]:
    allowed_event_count = _audit_summary_value(markdown_path, "Allowed neg-risk events audited")

    executable_below_threshold = None
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, list):
            executable_below_threshold = 0
            for row in payload:
                if not isinstance(row, Mapping):
                    continue
                constructions = row.get("constructions")
                if isinstance(constructions, list):
                    candidates = [candidate for candidate in constructions if isinstance(candidate, Mapping)]
                else:
                    best = row.get("best_construction")
                    candidates = [best] if isinstance(best, Mapping) else []
                for candidate in candidates:
                    top_of_book_cost = _safe_float(candidate.get("top_of_book_cost"))
                    if not bool(candidate.get("executable")) or top_of_book_cost is None:
                        continue
                    if top_of_book_cost <= float(execute_threshold):
                        executable_below_threshold += 1

    return {
        "source_json": str(json_path),
        "source_markdown": str(markdown_path),
        "allowed_neg_risk_event_count": allowed_event_count,
        "execute_threshold": float(execute_threshold),
        "executable_constructions_below_threshold": executable_below_threshold,
    }


def summarize_public_b1_audit(
    *,
    json_path: Path = DEFAULT_B1_PUBLIC_AUDIT_JSON,
    markdown_path: Path = DEFAULT_B1_PUBLIC_AUDIT_MD,
    market_sample_size: int = DEFAULT_B1_AUDIT_MARKET_SAMPLE_SIZE,
) -> dict[str, Any]:
    template_pair_count = _audit_summary_value(markdown_path, "Template-compatible pairs")
    if template_pair_count is None and json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, Mapping):
            pairs = payload.get("template_pairs")
            if isinstance(pairs, list):
                template_pair_count = len(pairs)

    return {
        "source_json": str(json_path),
        "source_markdown": str(markdown_path),
        "allowed_market_sample_size": int(market_sample_size),
        "deterministic_template_pair_count": template_pair_count,
    }


def parse_replay_row(payload: Mapping[str, Any]) -> ReplayViolationRow:
    details = _json_loads(payload.get("details_json") or payload.get("details"), {})
    if not isinstance(details, Mapping):
        details = {}
    return ReplayViolationRow(
        violation_id=str(payload.get("violation_id") or ""),
        event_id=str(payload.get("event_id") or ""),
        detected_at_ts=int(payload.get("detected_at_ts") or 0),
        gross_edge=float(payload.get("gross_edge") or 0.0),
        score=float(payload.get("score") or 0.0),
        slippage_est=float(payload.get("slippage_est") or 0.0),
        fill_risk=float(payload.get("fill_risk") or 0.0),
        theoretical_pnl=float(payload.get("theoretical_pnl") or 0.0),
        realized_pnl=float(payload.get("realized_pnl") or 0.0),
        action=str(payload.get("action") or ""),
        relation_type=str(payload.get("relation_type") or ""),
        event_legs=int(details.get("event_legs") or details.get("legs") or 0),
        missing_legs=int(details.get("missing_legs") or 0),
        complete_basket=bool(details.get("complete_basket")),
        sum_yes_ask=_safe_float(details.get("sum_yes_ask")),
        a6_mode=str(details.get("a6_mode") or "") or None,
        settlement_path=str(details.get("settlement_path") or "") or None,
        episode_id=str(details.get("episode_id") or "") or None,
    )


def load_replay_rows(db_path: Path, log_path: Path) -> list[ReplayViolationRow]:
    rows: list[ReplayViolationRow] = []
    seen: set[str] = set()

    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT *
                FROM constraint_violations
                WHERE relation_type = 'same_event_sum'
                ORDER BY detected_at_ts ASC
            """
            for raw in conn.execute(query):
                row = parse_replay_row(dict(raw))
                if row.violation_id and row.violation_id not in seen:
                    seen.add(row.violation_id)
                    rows.append(row)

    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                row = parse_replay_row(raw)
                if row.relation_type != "same_event_sum":
                    continue
                if row.violation_id and row.violation_id not in seen:
                    seen.add(row.violation_id)
                    rows.append(row)

    rows.sort(key=lambda row: (row.detected_at_ts, row.event_id, row.violation_id))
    return rows


def load_episode_rows(db_path: Path) -> list[EpisodeRow]:
    if not db_path.exists():
        return []

    rows: list[EpisodeRow] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            raw_rows = conn.execute(
                """
                SELECT episode_id, event_id, mode, ts_start_utc, ts_end_utc, max_deviation
                FROM a6_violation_episode
                ORDER BY ts_start_utc ASC, episode_id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    for raw in raw_rows:
        try:
            start_ts = int(datetime.fromisoformat(str(raw["ts_start_utc"])).timestamp())
            end_ts = int(datetime.fromisoformat(str(raw["ts_end_utc"] or raw["ts_start_utc"])).timestamp())
        except ValueError:
            continue
        rows.append(
            EpisodeRow(
                episode_id=str(raw["episode_id"] or ""),
                event_id=str(raw["event_id"] or ""),
                mode=str(raw["mode"] or ""),
                first_ts=start_ts,
                last_ts=end_ts,
                max_deviation=float(raw["max_deviation"] or 0.0),
            )
        )

    return rows


def build_violation_episodes(rows: Sequence[ReplayViolationRow | EventObservation], gap_seconds: int) -> list[ViolationEpisode]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        action = getattr(row, "action", None)
        if action is None:
            continue
        if isinstance(row, EventObservation) and row.action is None:
            continue
        event_id = str(getattr(row, "event_id"))
        grouped[event_id].append(int(getattr(row, "observed_at_ts", None) or getattr(row, "detected_at_ts")))

    episodes: list[ViolationEpisode] = []
    for event_id, timestamps in grouped.items():
        ordered = sorted(set(timestamps))
        if not ordered:
            continue
        first = ordered[0]
        prev = ordered[0]
        count = 1
        for ts in ordered[1:]:
            if ts - prev > gap_seconds:
                episodes.append(ViolationEpisode(event_id=event_id, first_ts=first, last_ts=prev, observations=count))
                first = ts
                count = 1
            else:
                count += 1
            prev = ts
        episodes.append(ViolationEpisode(event_id=event_id, first_ts=first, last_ts=prev, observations=count))
    return episodes


def leg_bucket_name(legs: int) -> str:
    if legs <= 5:
        return "3_5_legs"
    if legs <= 10:
        return "6_10_legs"
    if legs <= 20:
        return "11_20_legs"
    return "21_plus_legs"


def recommend_a6_thresholds(rows: Sequence[ReplayViolationRow]) -> dict[str, Any]:
    complete_rows = [
        row
        for row in rows
        if row.complete_basket and row.event_legs >= 3 and row.action == "buy_yes_basket"
    ]
    by_bucket: dict[str, list[ReplayViolationRow]] = defaultdict(list)
    for row in complete_rows:
        by_bucket[leg_bucket_name(row.event_legs)].append(row)

    recommendations: dict[str, Any] = {}
    threshold_candidates: list[tuple[float, int]] = []
    for bucket in ("3_5_legs", "6_10_legs", "11_20_legs", "21_plus_legs"):
        bucket_rows = by_bucket.get(bucket, [])
        positive_rows = [row for row in bucket_rows if row.score > 0.0]
        drag_values = [row.slippage_est + row.fill_risk for row in bucket_rows]
        if len(bucket_rows) < 3 and bucket_rows:
            required_edge = (quantile(drag_values, 0.75) or 0.0) + 0.01
            basis = "thin_sample_execution_drag_plus_buffer"
        elif positive_rows:
            required_edge = max(
                min(row.gross_edge for row in positive_rows),
                quantile(drag_values, 0.75) or 0.0,
            )
            basis = "observed_positive_score_floor"
        elif bucket_rows:
            required_edge = (quantile(drag_values, 0.75) or 0.0) + 0.01
            basis = "execution_drag_plus_buffer"
        else:
            recommendations[bucket] = {
                "sample_count": 0,
                "recommended_min_gross_edge": None,
                "recommended_sum_yes_ask_threshold": None,
                "basis": "no_samples",
            }
            continue

        threshold = max(0.0, min(1.0, 1.0 - required_edge))
        threshold_candidates.append((threshold, len(bucket_rows)))
        recommendations[bucket] = {
            "sample_count": len(bucket_rows),
            "positive_score_count": len(positive_rows),
            "recommended_min_gross_edge": round(required_edge, 4),
            "recommended_sum_yes_ask_threshold": round(threshold, 4),
            "basis": basis,
        }

    expanded: list[float] = []
    for threshold, weight in threshold_candidates:
        expanded.extend([threshold] * max(1, weight))
    global_threshold = quantile(expanded, 0.50) if expanded else None

    return {
        "global_underround_threshold": round(global_threshold, 4) if global_threshold is not None else None,
        "by_leg_bucket": recommendations,
    }


def summarize_replay(
    rows: Sequence[ReplayViolationRow],
    *,
    episode_rows: Sequence[EpisodeRow] | None = None,
) -> dict[str, Any]:
    episodes = list(episode_rows or [])
    if episodes:
        durations = [episode.duration_seconds for episode in episodes]
        mode_counts: dict[str, int] = defaultdict(int)
        for episode in episodes:
            mode_counts[episode.mode] += 1
    else:
        replay_episodes = build_violation_episodes(rows, gap_seconds=120)
        durations = [episode.duration_seconds for episode in replay_episodes if episode.observations >= 2]
        mode_counts = {"neg_risk_sum": len(replay_episodes)} if replay_episodes else {}
        episodes = list(replay_episodes)
    complete_rows = [row for row in rows if row.complete_basket]
    positive_complete = [row for row in complete_rows if row.score > 0.0]
    theoretical_total = sum(row.theoretical_pnl for row in complete_rows)
    realized_total = sum(row.realized_pnl for row in complete_rows)
    modeled_total = sum(max(row.score, 0.0) for row in positive_complete)

    return {
        "row_count": len(rows),
        "unique_events": len({row.event_id for row in rows}),
        "a6_modes": dict(sorted(mode_counts.items())),
        "settlement_paths": dict(
            sorted(
                (
                    path,
                    sum(1 for row in rows if row.settlement_path == path),
                )
                for path in {row.settlement_path for row in rows if row.settlement_path}
            )
        ),
        "observed_start": utc_iso(rows[0].detected_at_ts) if rows else None,
        "observed_end": utc_iso(rows[-1].detected_at_ts) if rows else None,
        "gross_edge": summarize_numbers([row.gross_edge for row in complete_rows]),
        "event_legs": summarize_numbers([float(row.event_legs) for row in complete_rows]),
        "complete_basket_count": len(complete_rows),
        "positive_score_count": len(positive_complete),
        "episode_count": len(episodes),
        "observed_persistence_lower_bound_seconds": quantile(durations, 0.50),
        "observed_persistence_p90_seconds": quantile(durations, 0.90),
        "actual_capture_rate": (realized_total / theoretical_total) if theoretical_total > 0 else None,
        "modeled_capture_rate": (modeled_total / theoretical_total) if theoretical_total > 0 else None,
        "threshold_recommendations": recommend_a6_thresholds(rows),
    }


def _fetch_book(raw_market: Mapping[str, Any], cycle_index: int, observed_at_ts: int, timeout_seconds: float) -> LegObservation:
    norm = normalize_market(raw_market)
    outcome_name = norm.outcome or (norm.outcomes[0] if norm.outcomes else "")

    if not is_tradable_outcome(norm, outcome_name):
        return LegObservation(
            cycle_index=cycle_index,
            observed_at_ts=observed_at_ts,
            event_id=norm.event_id,
            event_title=str(raw_market.get("eventTitle") or raw_market.get("question") or ""),
            market_id=norm.market_id,
            condition_id=str(raw_market.get("conditionId") or ""),
            question=norm.question,
            category=norm.category,
            outcome_name=outcome_name,
            tick_size=norm.tick_size,
            yes_bid=None,
            yes_ask=None,
            midpoint=None,
            spread=None,
            fetch_status="non_tradable_outcome",
            is_tradable_outcome=False,
        )

    if not norm.yes_token_id:
        return LegObservation(
            cycle_index=cycle_index,
            observed_at_ts=observed_at_ts,
            event_id=norm.event_id,
            event_title=str(raw_market.get("eventTitle") or raw_market.get("question") or ""),
            market_id=norm.market_id,
            condition_id=str(raw_market.get("conditionId") or ""),
            question=norm.question,
            category=norm.category,
            outcome_name=outcome_name,
            tick_size=norm.tick_size,
            yes_bid=None,
            yes_ask=None,
            midpoint=None,
            spread=None,
            fetch_status="missing_token",
            is_tradable_outcome=True,
        )

    try:
        response = requests.get(
            "https://clob.polymarket.com/book",
            params={"token_id": norm.yes_token_id},
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        if response.status_code == 404:
            status = "token_404"
            best_bid = None
            best_ask = None
        else:
            response.raise_for_status()
            best_bid, best_ask = extract_best_quotes_from_book(response.json())
            status = "ok" if best_bid is not None and best_ask is not None else "bad_book"
    except requests.HTTPError:
        status = "http_error"
        best_bid = None
        best_ask = None
    except requests.RequestException:
        status = "request_error"
        best_bid = None
        best_ask = None

    midpoint = None
    spread = None
    if best_bid is not None and best_ask is not None:
        midpoint = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid

    return LegObservation(
        cycle_index=cycle_index,
        observed_at_ts=observed_at_ts,
        event_id=norm.event_id,
        event_title=str(raw_market.get("eventTitle") or raw_market.get("question") or ""),
        market_id=norm.market_id,
        condition_id=str(raw_market.get("conditionId") or ""),
        question=norm.question,
        category=norm.category,
        outcome_name=outcome_name,
        tick_size=norm.tick_size,
        yes_bid=best_bid,
        yes_ask=best_ask,
        midpoint=midpoint,
        spread=spread,
        fetch_status=status,
        is_tradable_outcome=True,
    )


def scan_live_surface(
    *,
    cycles: int,
    interval_seconds: int,
    gamma_pages: int,
    page_size: int,
    book_sample_events: int,
    book_workers: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    scanner = SumViolationScanner(
        max_pages=gamma_pages,
        page_size=page_size,
        timeout_seconds=timeout_seconds,
        use_websocket=False,
    )
    try:
        cycle_summaries: list[dict[str, Any]] = []
        all_leg_observations: list[LegObservation] = []
        all_event_observations: list[EventObservation] = []

        for cycle_index in range(cycles):
            observed_at_ts = int(time.time())
            raw_events = scanner.fetch_active_events()

            total_multi_event_count = 0
            total_multi_market_count = 0
            candidate_events: list[tuple[Mapping[str, Any], list[dict[str, Any]]]] = []

            for event in raw_events:
                flattened = scanner._flatten_event_markets(event)
                if len(flattened) >= 3:
                    total_multi_event_count += 1
                    total_multi_market_count += len(flattened)
                if scanner._event_is_candidate(event):
                    candidate_events.append((event, flattened))

            candidate_events.sort(
                key=lambda item: (-len(item[1]), str(item[0].get("id") or item[0].get("slug") or "")),
            )
            sampled_events = candidate_events[:book_sample_events]

            raw_markets: list[dict[str, Any]] = []
            for event, flattened in sampled_events:
                event_title = str(event.get("title") or event.get("name") or "")
                event_category = str(event.get("category") or "")
                for raw in flattened:
                    merged = dict(raw)
                    merged.setdefault("eventTitle", event_title)
                    merged.setdefault("eventCategory", event_category)
                    raw_markets.append(merged)

            leg_observations: list[LegObservation] = []
            with ThreadPoolExecutor(max_workers=max(1, book_workers)) as executor:
                futures = [
                    executor.submit(_fetch_book, raw_market, cycle_index, observed_at_ts, timeout_seconds)
                    for raw_market in raw_markets
                ]
                for future in as_completed(futures):
                    leg_observations.append(future.result())

            by_event: dict[str, list[LegObservation]] = defaultdict(list)
            for leg in leg_observations:
                by_event[leg.event_id].append(leg)

            event_observations: list[EventObservation] = []
            for event_id, event_legs in by_event.items():
                tradable = [leg for leg in event_legs if leg.is_tradable_outcome]
                priced = [leg for leg in tradable if leg.fetch_status == "ok" and leg.yes_ask is not None]
                token_404s = sum(1 for leg in tradable if leg.fetch_status == "token_404")
                incomplete = sum(1 for leg in tradable if leg.fetch_status not in {"ok", "non_tradable_outcome"})
                complete_book = bool(tradable) and len(priced) == len(tradable)
                sum_yes_ask = sum(leg.yes_ask or 0.0 for leg in priced) if complete_book else None

                action = None
                gross_deviation = None
                if sum_yes_ask is not None:
                    gross_deviation = abs(sum_yes_ask - 1.0)
                    if sum_yes_ask < 0.97:
                        action = "buy_yes_basket"
                    elif sum_yes_ask > 1.03:
                        action = "unwind_basket"

                first_leg = event_legs[0]
                event_observations.append(
                    EventObservation(
                        cycle_index=cycle_index,
                        observed_at_ts=observed_at_ts,
                        event_id=event_id,
                        event_title=first_leg.event_title,
                        category=first_leg.category,
                        tradable_legs=len(tradable),
                        priced_legs=len(priced),
                        token_404_legs=token_404s,
                        incomplete_legs=incomplete,
                        complete_book=complete_book,
                        sum_yes_ask=sum_yes_ask,
                        gross_deviation=gross_deviation,
                        action=action,
                    )
                )

            cycle_summaries.append(
                {
                    "cycle_index": cycle_index,
                    "observed_at": utc_iso(observed_at_ts),
                    "active_multi_outcome_event_count": total_multi_event_count,
                    "active_multi_outcome_market_count": total_multi_market_count,
                    "candidate_event_count": len(candidate_events),
                    "book_sample_event_count": len(sampled_events),
                    "book_sample_market_count": len(raw_markets),
                }
            )
            all_leg_observations.extend(sorted(leg_observations, key=lambda leg: (leg.event_id, leg.market_id)))
            all_event_observations.extend(sorted(event_observations, key=lambda event: (event.event_id, event.cycle_index)))

            if cycle_index + 1 < cycles:
                time.sleep(max(0, interval_seconds))

        return {
            "cycle_summaries": cycle_summaries,
            "leg_observations": all_leg_observations,
            "event_observations": all_event_observations,
        }
    finally:
        scanner.close()


def fetch_recent_trade_tape(*, since_ts: int, max_rows: int, timeout_seconds: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = 100
    for offset in range(0, max_rows, page_size):
        response = requests.get(
            DATA_API_TRADES,
            params={"limit": page_size, "offset": offset},
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        oldest_ts = min(int(row.get("timestamp") or 0) for row in batch)
        if oldest_ts and oldest_ts <= since_ts:
            break
        if len(batch) < page_size:
            break
        time.sleep(0.15)
    return rows


def build_passive_order_probes(
    leg_observations: Sequence[LegObservation],
    *,
    fill_sample_size: int,
) -> list[PassiveOrderProbe]:
    eligible = [
        leg
        for leg in leg_observations
        if leg.fetch_status == "ok"
        and leg.yes_bid is not None
        and leg.yes_ask is not None
        and leg.midpoint is not None
        and leg.condition_id
    ]
    by_cycle: dict[int, list[LegObservation]] = defaultdict(list)
    for leg in eligible:
        by_cycle[leg.cycle_index].append(leg)
    for cycle_legs in by_cycle.values():
        cycle_legs.sort(key=lambda leg: (leg.midpoint or 0.0, leg.event_id, leg.market_id))

    sampled: list[LegObservation] = []
    cycles = sorted(by_cycle)
    if not cycles:
        return []

    per_cycle = max(1, fill_sample_size // len(cycles))
    for cycle in cycles:
        sampled.extend(by_cycle[cycle][:per_cycle])

    if len(sampled) < fill_sample_size:
        leftovers: list[LegObservation] = []
        for cycle in cycles:
            leftovers.extend(by_cycle[cycle][per_cycle:])
        leftovers.sort(key=lambda leg: (leg.cycle_index, leg.midpoint or 0.0, leg.event_id, leg.market_id))
        sampled.extend(leftovers[: max(0, fill_sample_size - len(sampled))])

    probes: list[PassiveOrderProbe] = []
    for leg in sampled:
        tick_size = max(0.001, leg.tick_size)
        quote_price = max(0.001, round((leg.yes_ask or 0.0) - tick_size, 6))
        if leg.yes_bid is not None:
            quote_price = max(quote_price, round(leg.yes_bid, 6))
        required_size = 5.0 / max(quote_price, 0.01)
        probes.append(
            PassiveOrderProbe(
                cycle_index=leg.cycle_index,
                snapshot_ts=leg.observed_at_ts,
                condition_id=leg.condition_id,
                market_id=leg.market_id,
                event_id=leg.event_id,
                midpoint=float(leg.midpoint),
                price_bucket=midpoint_bucket(float(leg.midpoint)),
                quote_price=quote_price,
                required_size=required_size,
            )
        )
    return probes


def trade_matches_passive_yes_buy(trade: Mapping[str, Any], probe: PassiveOrderProbe) -> float:
    if str(trade.get("conditionId") or "") != probe.condition_id:
        return 0.0

    timestamp = int(trade.get("timestamp") or 0)
    if timestamp < probe.snapshot_ts:
        return 0.0

    outcome = str(trade.get("outcome") or "").strip().lower()
    side = str(trade.get("side") or "").strip().upper()
    price = _safe_float(trade.get("price"))
    size = _safe_float(trade.get("size"))
    if price is None or size is None:
        return 0.0

    if outcome == "yes" and side == "SELL" and price <= probe.quote_price + 1e-9:
        return size
    if outcome == "no" and side == "BUY" and (1.0 - price) <= probe.quote_price + 1e-9:
        return size
    return 0.0


def measure_fill_proxy(
    probes: Sequence[PassiveOrderProbe],
    trade_rows: Sequence[Mapping[str, Any]],
    *,
    lookahead_seconds: int,
    trade_data_end_ts: int,
) -> dict[str, Any]:
    eligible = [
        probe
        for probe in probes
        if probe.snapshot_ts + lookahead_seconds <= trade_data_end_ts
    ]
    if not eligible:
        return {
            "lookahead_seconds": lookahead_seconds,
            "eligible_probe_count": 0,
            "full_fill_proxy_rate": None,
            "bucketed": {},
            "notes": "No probes had complete trade lookahead coverage.",
        }

    trades_by_condition: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in trade_rows:
        condition_id = str(row.get("conditionId") or "")
        if condition_id:
            trades_by_condition[condition_id].append(row)
    for bucket in trades_by_condition.values():
        bucket.sort(key=lambda row: int(row.get("timestamp") or 0))

    successes = 0
    bucket_stats: dict[str, list[bool]] = defaultdict(list)
    for probe in eligible:
        matched_size = 0.0
        for trade in trades_by_condition.get(probe.condition_id, []):
            timestamp = int(trade.get("timestamp") or 0)
            if timestamp < probe.snapshot_ts:
                continue
            if timestamp > probe.snapshot_ts + lookahead_seconds:
                break
            matched_size += trade_matches_passive_yes_buy(trade, probe)
            if matched_size >= probe.required_size:
                break
        filled = matched_size >= probe.required_size
        successes += int(filled)
        bucket_stats[probe.price_bucket].append(filled)

    lower, upper = wilson_interval(successes, len(eligible))
    bucketed: dict[str, Any] = {}
    for bucket, fills in sorted(bucket_stats.items()):
        bucket_successes = sum(1 for filled in fills if filled)
        bucket_lower, bucket_upper = wilson_interval(bucket_successes, len(fills))
        bucketed[bucket] = {
            "probe_count": len(fills),
            "full_fill_proxy_rate": bucket_successes / len(fills),
            "wilson_low": bucket_lower,
            "wilson_high": bucket_upper,
        }

    return {
        "lookahead_seconds": lookahead_seconds,
        "eligible_probe_count": len(eligible),
        "full_fill_proxy_rate": successes / len(eligible),
        "wilson_low": lower,
        "wilson_high": upper,
        "bucketed": bucketed,
        "notes": "Proxy only. Counts recent trade-through volume sufficient to fully fill a $5 passive YES order at one-tick improvement.",
    }


def summarize_live_surface(live_data: Mapping[str, Any]) -> dict[str, Any]:
    leg_observations: list[LegObservation] = list(live_data["leg_observations"])
    event_observations: list[EventObservation] = list(live_data["event_observations"])
    cycle_summaries: list[Mapping[str, Any]] = list(live_data["cycle_summaries"])

    complete_events = [event for event in event_observations if event.complete_book and event.sum_yes_ask is not None]
    qualified_a6 = [event for event in complete_events if event.action is not None]
    token_404_count = sum(1 for leg in leg_observations if leg.fetch_status == "token_404")
    incomplete_leg_count = sum(1 for leg in leg_observations if leg.fetch_status not in {"ok", "non_tradable_outcome"})
    total_book_attempts = sum(1 for leg in leg_observations if leg.is_tradable_outcome)

    spread_values = [leg.spread for leg in leg_observations if leg.spread is not None]
    spread_buckets: dict[str, list[float]] = defaultdict(list)
    for leg in leg_observations:
        if leg.spread is None or leg.midpoint is None:
            continue
        spread_buckets[midpoint_bucket(leg.midpoint)].append(leg.spread)

    bucket_summary: dict[str, Any] = {}
    for bucket, spreads in sorted(spread_buckets.items()):
        bucket_summary[bucket] = summarize_numbers(spreads)

    underrounds = [event for event in complete_events if (event.sum_yes_ask or 0.0) < 1.0]
    overrounds = [event for event in complete_events if (event.sum_yes_ask or 0.0) > 1.0]

    live_episodes = build_violation_episodes(qualified_a6, gap_seconds=45)
    live_episode_durations = [episode.duration_seconds for episode in live_episodes if episode.observations >= 2]

    latest_cycle = cycle_summaries[-1] if cycle_summaries else {}
    active_events = [summary.get("active_multi_outcome_event_count", 0) for summary in cycle_summaries]
    active_markets = [summary.get("active_multi_outcome_market_count", 0) for summary in cycle_summaries]

    top_violations = sorted(
        qualified_a6,
        key=lambda event: (event.gross_deviation or 0.0),
        reverse=True,
    )[:10]

    return {
        "cycle_count": len(cycle_summaries),
        "latest_cycle": latest_cycle,
        "active_multi_outcome_events_avg": sum(active_events) / len(active_events) if active_events else None,
        "active_multi_outcome_markets_avg": sum(active_markets) / len(active_markets) if active_markets else None,
        "sampled_event_observation_count": len(event_observations),
        "complete_book_event_count": len(complete_events),
        "qualified_a6_count": len(qualified_a6),
        "qualified_underround_count": len([event for event in qualified_a6 if event.action == "buy_yes_basket"]),
        "qualified_overround_count": len([event for event in qualified_a6 if event.action == "unwind_basket"]),
        "sum_yes_ask": summarize_numbers([event.sum_yes_ask or 0.0 for event in complete_events]),
        "gross_deviation": summarize_numbers([event.gross_deviation or 0.0 for event in complete_events]),
        "underround_gross_deviation": summarize_numbers([abs((event.sum_yes_ask or 1.0) - 1.0) for event in underrounds]),
        "overround_gross_deviation": summarize_numbers([abs((event.sum_yes_ask or 1.0) - 1.0) for event in overrounds]),
        "spread": summarize_numbers(spread_values),
        "spread_by_midpoint_bucket": bucket_summary,
        "token_404_rate": (token_404_count / total_book_attempts) if total_book_attempts > 0 else None,
        "token_404_count": token_404_count,
        "incomplete_book_leg_rate": (incomplete_leg_count / total_book_attempts) if total_book_attempts > 0 else None,
        "incomplete_book_leg_count": incomplete_leg_count,
        "a6_completed_half_life_seconds": quantile(live_episode_durations, 0.50),
        "a6_completed_half_life_p90_seconds": quantile(live_episode_durations, 0.90),
        "top_violations": [serialize_for_json(event) for event in top_violations],
    }


def summarize_b1(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "graph_edge_count": 0,
            "historical_violation_count": 0,
            "measurement_status": "db_missing",
            "recommended_implication_threshold": 0.04,
            "classification_accuracy": None,
            "false_positive_rate": None,
            "b1_half_life_lower_bound_seconds": None,
        }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        edge_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM graph_edges
            WHERE relation_type IN ('A_implies_B', 'B_implies_A', 'mutually_exclusive')
            """
        ).fetchone()[0]
        violation_rows = conn.execute(
            """
            SELECT detected_at_ts, event_id
            FROM constraint_violations
            WHERE relation_type IN ('A_implies_B', 'B_implies_A', 'mutually_exclusive')
            ORDER BY detected_at_ts ASC
            """
        ).fetchall()

    if not violation_rows:
        return {
            "graph_edge_count": int(edge_count),
            "historical_violation_count": 0,
            "measurement_status": "insufficient_live_samples",
            "b1_half_life_lower_bound_seconds": None,
            "recommended_implication_threshold": 0.04,
            "classification_accuracy": None,
            "false_positive_rate": None,
            "notes": "No historical B-1 violations are logged in constraint_arb.db yet.",
        }

    synthetic_rows = [
        EventObservation(
            cycle_index=0,
            observed_at_ts=int(row["detected_at_ts"]),
            event_id=str(row["event_id"]),
            event_title="",
            category="",
            tradable_legs=0,
            priced_legs=0,
            token_404_legs=0,
            incomplete_legs=0,
            complete_book=True,
            sum_yes_ask=None,
            gross_deviation=None,
            action="violation",
        )
        for row in violation_rows
    ]
    episodes = build_violation_episodes(synthetic_rows, gap_seconds=120)
    durations = [episode.duration_seconds for episode in episodes if episode.observations >= 2]
    return {
        "graph_edge_count": int(edge_count),
        "historical_violation_count": len(violation_rows),
        "measurement_status": "historical_only",
        "b1_half_life_lower_bound_seconds": quantile(durations, 0.50),
        "recommended_implication_threshold": 0.04,
        "classification_accuracy": None,
        "false_positive_rate": None,
    }


def summarize_settlement(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"total": 0, "successful": 0, "success_rate": None, "ops_by_type": {}, "avg_cost_usd": None}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT op_type, success, effective_cost_usd
                FROM arb_settlement_op
                ORDER BY COALESCE(ts_submitted_utc, ts_confirmed_utc) DESC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return {"total": 0, "successful": 0, "success_rate": None, "ops_by_type": {}, "avg_cost_usd": None}

    costs = [float(row["effective_cost_usd"]) for row in rows if row["effective_cost_usd"] is not None]
    ops_by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        ops_by_type[str(row["op_type"] or "unknown")] += 1
    successful = sum(1 for row in rows if row["success"] == 1)
    total = len(rows)
    return {
        "total": total,
        "successful": successful,
        "success_rate": (successful / total) if total else None,
        "ops_by_type": dict(sorted(ops_by_type.items())),
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else None,
    }


def evaluate_lane_statuses(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    fill = snapshot.get("fill_proxy", {})
    replay = snapshot.get("a6_replay", {})
    b1 = snapshot.get("b1", {})
    settlement = snapshot.get("settlement", {})
    repo_truth = snapshot.get("repo_truth", {})

    public_a6 = repo_truth.get("public_a6_audit", {})
    public_b1 = repo_truth.get("public_b1_audit", {})
    settlement_count = int(settlement.get("total") or 0)

    a6_status = evaluate_structural_lane_readiness(
        StructuralLaneReadinessInputs(
            lane="a6",
            maker_fill_proxy_rate=_safe_float(fill.get("full_fill_proxy_rate")),
            maker_fill_wilson_lower=_safe_float(fill.get("wilson_low")),
            violation_half_life_seconds=_safe_float(replay.get("observed_persistence_lower_bound_seconds")),
            settlement_evidence_count=settlement_count,
            classification_accuracy=None,
            false_positive_rate=None,
            public_a6_executable_count=int(public_a6.get("executable_constructions_below_threshold") or 0)
            if public_a6.get("executable_constructions_below_threshold") is not None
            else None,
            public_a6_threshold=float(public_a6.get("execute_threshold") or 0.95),
        )
    )
    b1_status = evaluate_structural_lane_readiness(
        StructuralLaneReadinessInputs(
            lane="b1",
            maker_fill_proxy_rate=_safe_float(fill.get("full_fill_proxy_rate")),
            maker_fill_wilson_lower=_safe_float(fill.get("wilson_low")),
            violation_half_life_seconds=_safe_float(b1.get("b1_half_life_lower_bound_seconds")),
            settlement_evidence_count=settlement_count,
            classification_accuracy=_safe_float(b1.get("classification_accuracy")),
            false_positive_rate=_safe_float(b1.get("false_positive_rate")),
            public_b1_template_pair_count=int(public_b1.get("deterministic_template_pair_count") or 0)
            if public_b1.get("deterministic_template_pair_count") is not None
            else None,
            public_b1_market_sample_size=int(public_b1.get("allowed_market_sample_size") or DEFAULT_B1_AUDIT_MARKET_SAMPLE_SIZE),
        )
    )
    return {
        "a6": serialize_for_json(a6_status),
        "b1": serialize_for_json(b1_status),
    }


def _structural_gate_requirements() -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    a6_defaults = StructuralLaneReadinessInputs(lane="a6")
    b1_defaults = StructuralLaneReadinessInputs(lane="b1")
    return {
        "a6": {
            "ready_for_shadow": {
                "maker_fill_wilson_lower": {
                    "comparison": ">",
                    "value": float(a6_defaults.minimum_fill_wilson_lower),
                },
                "violation_half_life_seconds": {
                    "comparison": ">=",
                    "value": float(a6_defaults.minimum_violation_half_life_seconds),
                },
                "public_a6_executable_count": {
                    "comparison": ">=",
                    "value": 1,
                },
            },
            "ready_for_micro_live": {
                "maker_fill_wilson_lower": {
                    "comparison": ">",
                    "value": float(a6_defaults.minimum_fill_wilson_lower),
                },
                "violation_half_life_seconds": {
                    "comparison": ">=",
                    "value": float(a6_defaults.minimum_violation_half_life_seconds),
                },
                "public_a6_executable_count": {
                    "comparison": ">=",
                    "value": 1,
                },
                "settlement_evidence_count": {
                    "comparison": ">=",
                    "value": int(a6_defaults.minimum_settlement_evidence_count),
                },
            },
        },
        "b1": {
            "ready_for_shadow": {
                "classification_accuracy": {
                    "comparison": ">=",
                    "value": float(b1_defaults.minimum_classification_accuracy),
                },
                "false_positive_rate": {
                    "comparison": "<=",
                    "value": float(b1_defaults.maximum_false_positive_rate),
                },
                "public_b1_template_pair_count": {
                    "comparison": ">=",
                    "value": 1,
                },
            },
            "ready_for_micro_live": {
                "classification_accuracy": {
                    "comparison": ">=",
                    "value": float(b1_defaults.minimum_classification_accuracy),
                },
                "false_positive_rate": {
                    "comparison": "<=",
                    "value": float(b1_defaults.maximum_false_positive_rate),
                },
                "public_b1_template_pair_count": {
                    "comparison": ">=",
                    "value": 1,
                },
                "violation_half_life_seconds": {
                    "comparison": ">=",
                    "value": float(b1_defaults.minimum_violation_half_life_seconds),
                },
                "settlement_evidence_count": {
                    "comparison": ">=",
                    "value": int(b1_defaults.minimum_settlement_evidence_count),
                },
            },
        },
    }


def _threshold_delta(current: float | int | None, *, value: float | int, comparison: str) -> float | None:
    if current is None:
        return None
    current_value = float(current)
    required_value = float(value)
    if comparison in {">", ">="}:
        return round(current_value - required_value, 4)
    if comparison in {"<", "<="}:
        return round(required_value - current_value, 4)
    raise ValueError(f"Unsupported comparison: {comparison}")


def _threshold_passes(current: float | int | None, *, value: float | int, comparison: str) -> bool:
    if current is None:
        return False
    current_value = float(current)
    required_value = float(value)
    if comparison == ">":
        return current_value > required_value
    if comparison == ">=":
        return current_value >= required_value
    if comparison == "<":
        return current_value < required_value
    if comparison == "<=":
        return current_value <= required_value
    raise ValueError(f"Unsupported comparison: {comparison}")


def _stage_is_ready(
    current_metrics: Mapping[str, float | int | None],
    requirements: Mapping[str, Mapping[str, Any]],
) -> bool:
    for metric_name, requirement in requirements.items():
        if not _threshold_passes(
            current_metrics.get(metric_name),
            value=requirement["value"],
            comparison=str(requirement["comparison"]),
        ):
            return False
    return True


def _structural_gate_current_metrics(
    lane: str,
    lane_status: Mapping[str, Any],
) -> dict[str, float | int | None]:
    if lane == "a6":
        return {
            "maker_fill_proxy_rate": _safe_float(lane_status.get("maker_fill_proxy_rate")),
            "maker_fill_wilson_lower": _safe_float(lane_status.get("maker_fill_wilson_lower")),
            "violation_half_life_seconds": _safe_float(lane_status.get("violation_half_life_seconds")),
            "settlement_evidence_count": int(lane_status.get("settlement_evidence_count") or 0),
            "public_a6_executable_count": (
                int(lane_status.get("public_a6_executable_count"))
                if lane_status.get("public_a6_executable_count") is not None
                else None
            ),
            "public_a6_threshold": _safe_float(lane_status.get("public_a6_threshold")),
        }
    if lane == "b1":
        return {
            "classification_accuracy": _safe_float(lane_status.get("classification_accuracy")),
            "false_positive_rate": _safe_float(lane_status.get("false_positive_rate")),
            "violation_half_life_seconds": _safe_float(lane_status.get("violation_half_life_seconds")),
            "settlement_evidence_count": int(lane_status.get("settlement_evidence_count") or 0),
            "public_b1_template_pair_count": (
                int(lane_status.get("public_b1_template_pair_count"))
                if lane_status.get("public_b1_template_pair_count") is not None
                else None
            ),
            "public_b1_market_sample_size": (
                int(lane_status.get("public_b1_market_sample_size"))
                if lane_status.get("public_b1_market_sample_size") is not None
                else None
            ),
        }
    raise ValueError(f"Unsupported structural lane: {lane}")


def build_structural_gate_pack(
    snapshot: Mapping[str, Any],
    *,
    source_snapshot: str | None = None,
) -> dict[str, Any]:
    lane_status = snapshot.get("lane_status") or evaluate_lane_statuses(snapshot)
    requirements_by_lane = _structural_gate_requirements()
    per_lane_status: dict[str, Any] = {}

    for lane in ("a6", "b1"):
        lane_payload = lane_status.get(lane, {})
        current_metrics = _structural_gate_current_metrics(lane, lane_payload)
        required_thresholds = requirements_by_lane[lane]
        threshold_deltas = {
            stage: {
                metric_name: _threshold_delta(
                    current_metrics.get(metric_name),
                    value=requirement["value"],
                    comparison=str(requirement["comparison"]),
                )
                for metric_name, requirement in stage_requirements.items()
            }
            for stage, stage_requirements in required_thresholds.items()
        }
        stage_readiness = {
            stage: _stage_is_ready(current_metrics, stage_requirements)
            for stage, stage_requirements in required_thresholds.items()
        }
        per_lane_status[lane] = {
            "status": lane_payload.get("status"),
            "blocked_reasons": list(lane_payload.get("blocked_reasons") or []),
            "current_metrics": current_metrics,
            "required_thresholds": required_thresholds,
            "threshold_deltas": threshold_deltas,
            "stage_readiness": stage_readiness,
        }

    return {
        "generated_at": snapshot.get("generated_at"),
        "source_snapshot": source_snapshot or "reports/arb_empirical_snapshot.json",
        "threshold_delta_semantics": (
            "For minimum gates, delta = current - threshold. For maximum gates, delta = threshold - current. "
            "Positive values mean the metric is through the gate, zero means it is exactly on the threshold, "
            "negative values mean remaining shortfall or excess, and null means the metric is unmeasured."
        ),
        "per_lane_status": per_lane_status,
    }


def evaluate_gating_metrics(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the three gating metrics from the research dispatch.

    1. Maker fill probability curve on neg-risk outcomes
    2. Violation frequency and half-life in allowed categories
    3. Settlement path viability for proxy wallet in neg-risk events

    Returns a dict of gating decisions and supporting evidence.
    """
    fill = snapshot.get("fill_proxy", {})
    live = snapshot.get("live_surface", {})
    replay = snapshot.get("a6_replay", {})
    b1 = snapshot.get("b1", {})
    settlement = snapshot.get("settlement", {})
    lane_status = snapshot.get("lane_status", {})

    # Gate 1: Fill probability — need Wilson lower bound > 0.20
    fill_rate = fill.get("full_fill_proxy_rate")
    wilson_low = fill.get("wilson_low")
    fill_gate = "unknown"
    if fill_rate is not None and wilson_low is not None:
        fill_gate = "pass" if wilson_low > 0.20 else "fail"
    elif fill.get("eligible_probe_count", 0) == 0:
        fill_gate = "insufficient_data"

    # Gate 2: Violation half-life — need sufficient observations
    half_life = replay.get("observed_persistence_lower_bound_seconds")
    violation_count = replay.get("row_count", 0)
    half_life_gate = "unknown"
    if violation_count >= 20 and half_life is not None:
        half_life_gate = "pass" if half_life >= 10 else "fail"
    elif violation_count < 20:
        half_life_gate = "insufficient_data"

    # Gate 3: Settlement path — requires at least a small manual validation set.
    settlement_gate = "untested"
    if settlement.get("total", 0) >= 3 and settlement.get("success_rate") is not None:
        settlement_gate = "pass" if float(settlement["success_rate"]) >= 0.80 else "fail"

    # Confidence-interval kill criterion on effective edge
    capture_rate = replay.get("actual_capture_rate")
    kill_decision = "continue"
    kill_reason = None
    if capture_rate is not None and violation_count >= 20:
        # One-sided upper confidence bound on capture rate
        low, high = wilson_interval(
            int(capture_rate * violation_count),
            violation_count,
        )
        if high is not None and high < 0.50:
            kill_decision = "kill"
            kill_reason = f"upper_confidence_bound={round(high, 4)}<0.50 over {violation_count} completed cycles"

    return {
        "fill_probability_gate": fill_gate,
        "fill_wilson_lower": wilson_low,
        "half_life_gate": half_life_gate,
        "half_life_seconds": half_life,
        "settlement_path_gate": settlement_gate,
        "kill_decision": kill_decision,
        "kill_reason": kill_reason,
        "all_gates_pass": fill_gate == "pass" and half_life_gate == "pass",
        "promotion_eligible": (
            fill_gate == "pass"
            and half_life_gate == "pass"
            and kill_decision == "continue"
        ),
        "a6_status": lane_status.get("a6", {}).get("status"),
        "b1_status": lane_status.get("b1", {}).get("status"),
    }


def derive_execution_tasks(snapshot: Mapping[str, Any]) -> list[dict[str, str]]:
    settlement = snapshot.get("settlement", {})
    b1 = snapshot.get("b1", {})
    lane_status = snapshot.get("lane_status", {})
    a6_blocked_reasons = set(lane_status.get("a6", {}).get("blocked_reasons", []))
    b1_blocked_reasons = set(lane_status.get("b1", {}).get("blocked_reasons", []))

    tasks = [
        {
            "status": "done_in_this_pass",
            "title": "Clarify A-6 lane as neg-risk YES-basket only",
            "why": "The current implementation targets neg-risk sum rebalancing, not binary YES+NO merge baskets.",
        },
        {
            "status": "done_in_this_pass",
            "title": "Add combinatorial telemetry schema and A-6 episode tracking",
            "why": "Maker-fill, half-life, settlement, and basket telemetry now have dedicated tables instead of only generic violation rows.",
        },
        {
            "status": "done_in_this_pass",
            "title": "Upgrade empirical snapshot reporting",
            "why": "The report now exposes A-6 mode, episode counts, settlement coverage, and a research-derived task list.",
        },
        {
            "status": "done_in_this_pass",
            "title": "Propagate tick-size changes through the shared quote store",
            "why": "Tick-size changes are now preserved alongside best bid/ask updates for A-6 and B-1 consumers.",
        },
        {
            "status": (
                "next"
                if "maker_fill_proxy_unmeasured" in a6_blocked_reasons
                or "maker_fill_proxy_below_confidence_floor" in a6_blocked_reasons
                else "monitor"
            ),
            "title": "Run a 72h maker-fill curve measurement",
            "why": "Promotion still depends on measured joint fill probability, not the current trade-through proxy.",
        },
        {
            "status": "blocked_external" if settlement.get("total", 0) == 0 else "monitor",
            "title": "Execute settlement-path validation",
            "why": "No confirmed merge/redeem/convert operations are logged yet, so settlement remains unproven.",
        },
        {
            "status": "next" if b1_blocked_reasons else ("monitor" if b1.get("historical_violation_count", 0) > 0 else "next"),
            "title": "Finish the 50-pair B-1 gold set and precision audit",
            "why": "B-1 promotion should be gated on validated precision, not only graph size or classifier confidence.",
        },
        {
            "status": "next",
            "title": "Route live order groups and legs into executor telemetry",
            "why": "The new order-group tables exist, but live jj_live routing and user-channel fill persistence are still pending.",
        },
        {
            "status": "backlog",
            "title": "Split binary Dutch-book A-6 into a separate lane",
            "why": "The research report treats YES+NO merge baskets as a distinct settlement path and risk model.",
        },
    ]
    return tasks


def build_markdown_report(snapshot: Mapping[str, Any]) -> str:
    replay = snapshot["a6_replay"]
    live = snapshot["live_surface"]
    fill_proxy = snapshot["fill_proxy"]
    b1 = snapshot["b1"]
    settlement = snapshot["settlement"]
    recs = replay["threshold_recommendations"]
    tasks = snapshot.get("execution_tasks", [])
    lane_status = snapshot.get("lane_status", {})
    repo_truth = snapshot.get("repo_truth", {})
    a6_status = lane_status.get("a6", {})
    b1_status = lane_status.get("b1", {})
    public_a6 = repo_truth.get("public_a6_audit", {})
    public_b1 = repo_truth.get("public_b1_audit", {})

    lines = [
        "# Arb Empirical Snapshot",
        "",
        f"- Generated: {snapshot['generated_at']}",
        f"- Live cycles: {snapshot['inputs']['scan_cycles']}",
        f"- Scan interval seconds: {snapshot['inputs']['scan_interval_seconds']}",
        f"- Book sample events per cycle: {snapshot['inputs']['book_sample_events']}",
        "",
        "## Measured Facts",
        "",
        f"- Public A-6 audit: {public_a6.get('executable_constructions_below_threshold')} executable constructions below the {public_a6.get('execute_threshold')} gate across {public_a6.get('allowed_neg_risk_event_count')} allowed neg-risk events",
        f"- Public B-1 audit: {public_b1.get('deterministic_template_pair_count')} deterministic template pairs in the first {public_b1.get('allowed_market_sample_size')} allowed markets",
        f"- Active multi-outcome events: latest {live['latest_cycle'].get('active_multi_outcome_event_count', 0)}; avg {live.get('active_multi_outcome_events_avg')}",
        f"- Active multi-outcome markets: latest {live['latest_cycle'].get('active_multi_outcome_market_count', 0)}; avg {live.get('active_multi_outcome_markets_avg')}",
        f"- Complete-book A-6 event observations: {live['complete_book_event_count']}/{live['sampled_event_observation_count']}",
        f"- Token-404 rate: {None if live['token_404_rate'] is None else round(live['token_404_rate'], 4)}",
        f"- Incomplete-book leg rate: {None if live['incomplete_book_leg_rate'] is None else round(live['incomplete_book_leg_rate'], 4)}",
        "",
        "## Explicit Lane Status",
        "",
        f"- A-6 status: **{a6_status.get('status', 'blocked')}**",
        f"- A-6 evidence: maker_fill_proxy_rate={a6_status.get('maker_fill_proxy_rate')}, violation_half_life_seconds={a6_status.get('violation_half_life_seconds')}, settlement_evidence_count={a6_status.get('settlement_evidence_count')}, classification_accuracy={a6_status.get('classification_accuracy')}, false_positive_rate={a6_status.get('false_positive_rate')}",
        f"- A-6 blocked reasons: {a6_status.get('blocked_reasons', [])}",
        f"- B-1 status: **{b1_status.get('status', 'blocked')}**",
        f"- B-1 evidence: maker_fill_proxy_rate={b1_status.get('maker_fill_proxy_rate')}, violation_half_life_seconds={b1_status.get('violation_half_life_seconds')}, settlement_evidence_count={b1_status.get('settlement_evidence_count')}, classification_accuracy={b1_status.get('classification_accuracy')}, false_positive_rate={b1_status.get('false_positive_rate')}",
        f"- B-1 blocked reasons: {b1_status.get('blocked_reasons', [])}",
        "",
        "## A-6",
        "",
        f"- Replay rows: {replay['row_count']} across {replay['unique_events']} unique events",
        f"- A-6 modes observed: {replay.get('a6_modes')}",
        f"- Settlement paths observed: {replay.get('settlement_paths')}",
        f"- Episode count: {replay.get('episode_count', 0)}",
        f"- Qualified live A-6 observations: {live['qualified_a6_count']} ({live['qualified_underround_count']} underround / {live['qualified_overround_count']} overround)",
        f"- YES-sum deviation median: {round(live['gross_deviation'].get('median') or 0.0, 4)}",
        f"- YES-sum deviation p90: {round(live['gross_deviation'].get('p90') or 0.0, 4)}",
        f"- A-6 persistence lower bound from replay: {replay.get('observed_persistence_lower_bound_seconds')}s",
        f"- Actual capture rate: {None if replay['actual_capture_rate'] is None else round(replay['actual_capture_rate'], 4)}",
        f"- Modeled capture rate: {None if replay['modeled_capture_rate'] is None else round(replay['modeled_capture_rate'], 4)}",
        "",
        "## Spread Buckets",
        "",
        "| Bucket | Count | Median Spread | P90 Spread |",
        "| --- | ---: | ---: | ---: |",
    ]
    for bucket, stats in live["spread_by_midpoint_bucket"].items():
        lines.append(
            f"| {bucket} | {stats['count']} | {round(stats.get('median') or 0.0, 4)} | {round(stats.get('p90') or 0.0, 4)} |"
        )

    lines.extend(
        [
            "",
            "## Fill Proxy",
            "",
            f"- Eligible probes: {fill_proxy['eligible_probe_count']}",
            f"- Full $5 fill proxy rate: {None if fill_proxy['full_fill_proxy_rate'] is None else round(fill_proxy['full_fill_proxy_rate'], 4)}",
            f"- Wilson 95% interval: {None if fill_proxy.get('wilson_low') is None else round(fill_proxy['wilson_low'], 4)} to {None if fill_proxy.get('wilson_high') is None else round(fill_proxy['wilson_high'], 4)}",
            f"- Notes: {fill_proxy['notes']}",
            "",
            "## Recommendations",
            "",
            f"- Provisional global A-6 underround threshold: {recs['global_underround_threshold']}",
            f"- Provisional B-1 implication threshold: {b1['recommended_implication_threshold']}",
            "",
            "| Leg Bucket | Samples | Recommended Gross Edge | Recommended Sum Threshold | Basis |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for bucket, row in recs["by_leg_bucket"].items():
        lines.append(
            f"| {bucket} | {row['sample_count']} | {row['recommended_min_gross_edge']} | {row['recommended_sum_yes_ask_threshold']} | {row['basis']} |"
        )

    lines.extend(
        [
            "",
            "## B-1",
            "",
            f"- Historical graph edges: {b1['graph_edge_count']}",
            f"- Historical violation rows: {b1['historical_violation_count']}",
            f"- Measurement status: {b1['measurement_status']}",
            "",
            "## Settlement",
            "",
            f"- Logged settlement ops: {settlement['successful']}/{settlement['total']} successful",
            f"- Success rate: {None if settlement['success_rate'] is None else round(settlement['success_rate'], 4)}",
            f"- Ops by type: {settlement['ops_by_type']}",
            f"- Avg effective cost USD: {None if settlement['avg_cost_usd'] is None else round(settlement['avg_cost_usd'], 4)}",
            "",
            "## Shadow-to-Live Gating Metrics",
            "",
        ]
    )
    gates = snapshot.get("gating_metrics", {})
    lines.extend(
        [
            f"- Fill probability gate: **{gates.get('fill_probability_gate', 'unknown')}** (Wilson lower={gates.get('fill_wilson_lower')})",
            f"- Violation half-life gate: **{gates.get('half_life_gate', 'unknown')}** ({gates.get('half_life_seconds')}s)",
            f"- Settlement path gate: **{gates.get('settlement_path_gate', 'untested')}**",
            f"- Kill decision: **{gates.get('kill_decision', 'continue')}**" + (f" ({gates.get('kill_reason')})" if gates.get('kill_reason') else ""),
            f"- Promotion eligible: **{gates.get('promotion_eligible', False)}**",
            "",
            "## Unknowns",
            "",
            "- B-1 live correction half-life remains unmeasured until the live monitor writes non-sum violations to `constraint_arb.db`.",
            "- Fill proxy is not the same as actual queue-position fill rate; it only measures whether recent trade-through volume was sufficient to fully fill a $5 passive YES order at one-tick improvement.",
            "- Actual realized capture is still zero because the current dataset is shadow-only.",
            "",
            "## Execution Tasks",
            "",
            "| Status | Task | Why |",
            "| --- | --- | --- |",
        ]
    )
    for task in tasks:
        lines.append(f"| {task.get('status', '')} | {task.get('title', '')} | {task.get('why', '')} |")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an empirical A-6/B-1 snapshot.")
    parser.add_argument("--db-path", default="data/constraint_arb.db")
    parser.add_argument("--log-path", default="logs/sum_violation_events.jsonl")
    parser.add_argument("--output-json", default="reports/arb_empirical_snapshot.json")
    parser.add_argument("--output-md", default="reports/arb_empirical_snapshot.md")
    parser.add_argument("--output-structural-gate-pack", default=None)
    parser.add_argument("--scan-cycles", type=int, default=3)
    parser.add_argument("--scan-interval-seconds", type=int, default=20)
    parser.add_argument("--gamma-pages", type=int, default=12)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--book-sample-events", type=int, default=60)
    parser.add_argument("--book-workers", type=int, default=12)
    parser.add_argument("--fill-lookahead-seconds", type=int, default=30)
    parser.add_argument("--fill-sample-size", type=int, default=80)
    parser.add_argument("--trade-limit", type=int, default=5000)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = Path(args.db_path)
    log_path = Path(args.log_path)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_structural_gate_pack = (
        Path(args.output_structural_gate_pack) if args.output_structural_gate_pack else None
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    if output_structural_gate_pack is not None:
        output_structural_gate_pack.parent.mkdir(parents=True, exist_ok=True)

    replay_rows = load_replay_rows(db_path, log_path)
    episode_rows = load_episode_rows(db_path)
    replay_summary = summarize_replay(replay_rows, episode_rows=episode_rows)

    logger.info("Starting live surface scan cycles=%s sample_events=%s", args.scan_cycles, args.book_sample_events)
    live_data = scan_live_surface(
        cycles=max(1, int(args.scan_cycles)),
        interval_seconds=max(0, int(args.scan_interval_seconds)),
        gamma_pages=max(1, int(args.gamma_pages)),
        page_size=max(1, min(100, int(args.page_size))),
        book_sample_events=max(1, int(args.book_sample_events)),
        book_workers=max(1, int(args.book_workers)),
        timeout_seconds=max(1.0, float(args.timeout_seconds)),
    )
    live_summary = summarize_live_surface(live_data)

    leg_observations: list[LegObservation] = list(live_data["leg_observations"])
    probes = build_passive_order_probes(leg_observations, fill_sample_size=max(1, int(args.fill_sample_size)))
    if probes:
        min_probe_ts = min((probe.snapshot_ts for probe in probes), default=int(time.time()))
        logger.info("Fetching recent trade tape since_ts=%s max_rows=%s", min_probe_ts, args.trade_limit)
        trade_rows = fetch_recent_trade_tape(
            since_ts=min_probe_ts,
            max_rows=max(100, int(args.trade_limit)),
            timeout_seconds=max(1.0, float(args.timeout_seconds)),
        )
        trade_data_end_ts = max((int(row.get("timestamp") or 0) for row in trade_rows), default=min_probe_ts)
        fill_proxy = measure_fill_proxy(
            probes,
            trade_rows,
            lookahead_seconds=max(1, int(args.fill_lookahead_seconds)),
            trade_data_end_ts=trade_data_end_ts,
        )
    else:
        missing_condition_count = sum(
            1
            for leg in leg_observations
            if leg.fetch_status == "ok" and not leg.condition_id
        )
        fill_proxy = {
            "lookahead_seconds": max(1, int(args.fill_lookahead_seconds)),
            "eligible_probe_count": 0,
            "full_fill_proxy_rate": None,
            "bucketed": {},
            "notes": (
                "No eligible probes. The current Gamma /events A-6 watchlist flattening does not preserve "
                f"conditionId for {missing_condition_count} otherwise-quotable legs, so the live trade tape "
                "cannot be joined back to those markets."
            ),
        }

    b1_summary = summarize_b1(db_path)
    settlement_summary = summarize_settlement(db_path)
    repo_truth = {
        "public_a6_audit": summarize_public_a6_audit(),
        "public_b1_audit": summarize_public_b1_audit(),
    }

    snapshot = {
        "generated_at": utc_iso(),
        "inputs": {
            "db_path": str(db_path),
            "log_path": str(log_path),
            "scan_cycles": int(args.scan_cycles),
            "scan_interval_seconds": int(args.scan_interval_seconds),
            "gamma_pages": int(args.gamma_pages),
            "page_size": int(args.page_size),
            "book_sample_events": int(args.book_sample_events),
            "book_workers": int(args.book_workers),
            "fill_lookahead_seconds": int(args.fill_lookahead_seconds),
            "fill_sample_size": int(args.fill_sample_size),
            "trade_limit": int(args.trade_limit),
        },
        "a6_replay": replay_summary,
        "live_surface": live_summary,
        "fill_proxy": fill_proxy,
        "b1": b1_summary,
        "settlement": settlement_summary,
        "repo_truth": repo_truth,
    }
    snapshot["lane_status"] = evaluate_lane_statuses(snapshot)
    snapshot["gating_metrics"] = evaluate_gating_metrics(snapshot)
    snapshot["execution_tasks"] = derive_execution_tasks(snapshot)

    output_json.write_text(json.dumps(serialize_for_json(snapshot), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(build_markdown_report(snapshot), encoding="utf-8")
    if output_structural_gate_pack is not None:
        gate_pack = build_structural_gate_pack(snapshot, source_snapshot=str(output_json))
        output_structural_gate_pack.write_text(
            json.dumps(serialize_for_json(gate_pack), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote %s", output_structural_gate_pack)
    logger.info("Wrote %s and %s", output_json, output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
