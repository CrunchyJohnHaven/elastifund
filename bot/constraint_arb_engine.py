#!/usr/bin/env python3
"""Resolution-normalized constraint arbitrage engine for Polymarket."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from itertools import combinations
import logging
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any, Mapping, Sequence

try:
    from bot.cross_platform_arb import extract_keywords, normalize_title, title_similarity
except ImportError:  # pragma: no cover - direct script mode
    from cross_platform_arb import extract_keywords, normalize_title, title_similarity  # type: ignore

try:
    from bot.relation_classifier import RelationClassifier, RelationResult
except ImportError:  # pragma: no cover - direct script mode
    from relation_classifier import RelationClassifier, RelationResult  # type: ignore

try:
    from bot.neg_risk_inventory import NegRiskInventory
    from bot.resolution_normalizer import (
        NormalizedMarket,
        ResolutionGateResult,
        is_tradable_outcome,
        normalize_market,
        normalize_outcome_name,
        resolution_equivalence_gate,
    )
except ImportError:  # pragma: no cover - direct script mode
    from neg_risk_inventory import NegRiskInventory  # type: ignore
    from resolution_normalizer import (  # type: ignore
        NormalizedMarket,
        ResolutionGateResult,
        is_tradable_outcome,
        normalize_market,
        normalize_outcome_name,
        resolution_equivalence_gate,
    )

try:
    from bot.clob_ws_client import CLOBWebSocketClient
    from bot.gamma_market_cache import (
        GammaEventRecord,
        GammaMarketCache,
        GammaMarketRecord,
        GammaMarketUniverseSnapshot,
    )
except ImportError:  # pragma: no cover - direct script mode
    try:
        from clob_ws_client import CLOBWebSocketClient  # type: ignore
        from gamma_market_cache import (  # type: ignore
            GammaEventRecord,
            GammaMarketCache,
            GammaMarketRecord,
            GammaMarketUniverseSnapshot,
        )
    except ImportError:  # pragma: no cover - optional dependency
        CLOBWebSocketClient = None  # type: ignore[assignment]
        GammaEventRecord = None  # type: ignore[assignment]
        GammaMarketCache = None  # type: ignore[assignment]
        GammaMarketRecord = None  # type: ignore[assignment]
        GammaMarketUniverseSnapshot = None  # type: ignore[assignment]


logger = logging.getLogger("JJ.constraint_arb")


RELATION_LABELS = {
    "same_event_sum",
    "A_implies_B",
    "B_implies_A",
    "mutually_exclusive",
    "complementary",
    "subset",
    "independent",
    "ambiguous",
}

ANCHOR_STOPWORDS = {
    "market",
    "markets",
    "event",
    "events",
    "election",
    "elections",
    "price",
    "prices",
    "candidate",
    "candidates",
    "winner",
    "winners",
    "race",
    "races",
    "seat",
    "seats",
    "party",
    "parties",
}
ENTITY_STOPWORDS = {
    "will",
    "what",
    "when",
    "who",
    "which",
    "new",
    "before",
    "after",
}
MONTH_TOKENS = {
    "jan",
    "january",
    "feb",
    "february",
    "mar",
    "march",
    "apr",
    "april",
    "may",
    "jun",
    "june",
    "jul",
    "july",
    "aug",
    "august",
    "sep",
    "sept",
    "september",
    "oct",
    "october",
    "nov",
    "november",
    "dec",
    "december",
}
OFFICE_TOKENS = {
    "president",
    "presidency",
    "presidential",
    "senate",
    "senator",
    "house",
    "governor",
    "gubernatorial",
    "mayor",
    "prime minister",
    "parliament",
}
PARTY_TOKENS = {
    "democrat",
    "democratic",
    "republican",
    "gop",
    "labour",
    "labour party",
    "conservative",
    "liberal",
    "green",
}
DATE_TOKEN_RE = re.compile(
    r"\b(20\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)
ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|[A-Z]{2,}(?:\s+[A-Z]{2,}){0,2})\b"
)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
HTTP_TIMEOUT_SECONDS = 15
DEFAULT_HEADERS = {
    "User-Agent": "constraint-arb-engine/1.0",
    "Accept": "application/json",
}


def _now_ts() -> int:
    return int(time.time())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp_price(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _canonical_pair(market_a: NormalizedMarket, market_b: NormalizedMarket) -> tuple[NormalizedMarket, NormalizedMarket]:
    if (market_a.market_id, market_a.resolution_key) <= (market_b.market_id, market_b.resolution_key):
        return market_a, market_b
    return market_b, market_a


def build_pair_signature(market_a: NormalizedMarket, market_b: NormalizedMarket) -> str:
    left, right = _canonical_pair(market_a, market_b)
    payload = "|".join([left.market_id, right.market_id, left.resolution_key, right.resolution_key])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _slug_tokens(value: str) -> set[str]:
    if not value:
        return set()
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return {tok for tok in normalized.split() if tok and tok not in ANCHOR_STOPWORDS}


def _extract_named_entities(text: str) -> tuple[str, ...]:
    entities: set[str] = set()
    for match in ENTITY_RE.findall(text or ""):
        normalized = re.sub(r"\s+", " ", match.strip().lower())
        if normalized and normalized not in ENTITY_STOPWORDS:
            entities.add(normalized)
    return tuple(sorted(entities))


def _extract_date_tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted({token.lower() for token in DATE_TOKEN_RE.findall(text or "")}))


def _extract_office_tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {office for office in OFFICE_TOKENS if office in lowered}


def _office_hierarchy_cues(market_a: NormalizedMarket, market_b: NormalizedMarket) -> tuple[str, ...]:
    shared_offices = _extract_office_tokens(market_a.question) & _extract_office_tokens(market_b.question)
    if not shared_offices:
        return tuple()

    cues: list[str] = ["shared_office_scope"]
    tokens_a = extract_keywords(market_a.question) | _slug_tokens(market_a.event_id)
    tokens_b = extract_keywords(market_b.question) | _slug_tokens(market_b.event_id)
    if (tokens_a & PARTY_TOKENS and _extract_named_entities(market_b.question)) or (
        tokens_b & PARTY_TOKENS and _extract_named_entities(market_a.question)
    ):
        cues.append("party_candidate_hierarchy")
    return tuple(cues)


def _same_event_relation_hint(market_a: NormalizedMarket, market_b: NormalizedMarket) -> tuple[str, str] | None:
    if market_a.event_id != market_b.event_id:
        return None

    outcome_a = normalize_outcome_name(market_a.outcome or "")
    outcome_b = normalize_outcome_name(market_b.outcome or "")
    if outcome_a and outcome_b and outcome_a != outcome_b:
        combined_outcomes = {normalize_outcome_name(outcome) for outcome in market_a.outcomes + market_b.outcomes}
        combined_outcomes = {outcome for outcome in combined_outcomes if outcome}
        if len(combined_outcomes) > 2 or market_a.is_multi_outcome or market_b.is_multi_outcome:
            return ("mutually_exclusive", "same_event_distinct_named_outcomes")

    if normalize_title(market_a.question) == normalize_title(market_b.question):
        return ("complementary", "same_question_binary")
    return None


def _floor_to_tick(value: float, tick_size: float) -> float:
    if tick_size <= 0:
        return float(value)
    steps = math.floor((float(value) + 1e-12) / float(tick_size))
    return round(steps * float(tick_size), 10)


@dataclass(frozen=True)
class MarketQuote:
    market_id: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    updated_ts: int
    complete: bool = True
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)
    freshness_seconds: float | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class LiveConstraintMarket:
    market_id: str
    event_id: str
    slug: str
    question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    outcome_name: str | None
    category: str
    tags: tuple[str, ...]
    normalized_market: NormalizedMarket
    quote: MarketQuote | None
    freshness_seconds: float | None
    executable: bool
    blocked_reasons: tuple[str, ...]
    multi_outcome_event_id: str | None
    multi_outcome_size: int


@dataclass(frozen=True)
class LiveConstraintEvent:
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
    freshness_seconds: float | None


@dataclass(frozen=True)
class ConstraintRuntimeSnapshot:
    updated_ts: int
    markets: tuple[LiveConstraintMarket, ...]
    events: tuple[LiveConstraintEvent, ...]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    event_id: str
    market_a: str
    market_b: str
    relation_type: str
    semantic_confidence: float
    resolution_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrefilterFeatures:
    same_event: bool
    same_category: bool
    within_resolution_window: bool
    resolution_delta_hours: float | None
    title_similarity: float
    shared_question_tokens: tuple[str, ...]
    shared_event_anchors: tuple[str, ...]
    shared_entities: tuple[str, ...]
    shared_date_tokens: tuple[str, ...]
    lexical_cues: tuple[str, ...]
    office_hierarchy_cues: tuple[str, ...]
    outcome_overlap_ratio: float
    gate_passed: bool
    gate_reasons: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class CandidatePair:
    market_a: NormalizedMarket
    market_b: NormalizedMarket
    pair_key: tuple[str, str]
    pair_signature: str
    passed: bool
    priority: float
    sample_bucket: str
    suggested_label: str
    reason_codes: tuple[str, ...]
    features: PrefilterFeatures


@dataclass(frozen=True)
class ConstraintViolation:
    violation_id: str
    event_id: str
    relation_type: str
    market_ids: tuple[str, ...]
    semantic_confidence: float
    gross_edge: float
    slippage_est: float
    fill_risk: float
    semantic_penalty: float
    score: float
    vpin: float
    action: str
    theoretical_pnl: float
    realized_pnl: float
    details: dict[str, Any]
    detected_at_ts: int


@dataclass(frozen=True)
class ExecutionLeg:
    leg_id: str
    market_id: str
    side: str
    quantity: float
    limit_price: float


@dataclass(frozen=True)
class LegFill:
    filled_qty: float
    avg_price: float
    status: str
    ts: int


@dataclass(frozen=True)
class ExecutionPlan:
    violation_id: str
    event_id: str
    legs: tuple[ExecutionLeg, ...]
    payoff_if_complete: float


@dataclass(frozen=True)
class ExecutionResult:
    theoretical_pnl: float
    realized_pnl: float
    rollback_loss: float
    time_in_partial_basket: float
    peak_capital_tied: float
    complete: bool


class ConstraintArbDB:
    """SQLite persistence for graph edges, violations, and capture stats."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    edge_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    market_a TEXT NOT NULL,
                    market_b TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    semantic_confidence REAL NOT NULL,
                    resolution_key TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS constraint_violations (
                    violation_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    market_ids_json TEXT NOT NULL,
                    semantic_confidence REAL NOT NULL,
                    gross_edge REAL NOT NULL,
                    slippage_est REAL NOT NULL,
                    fill_risk REAL NOT NULL,
                    semantic_penalty REAL NOT NULL,
                    score REAL NOT NULL,
                    vpin REAL NOT NULL,
                    action TEXT NOT NULL,
                    theoretical_pnl REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    details_json TEXT NOT NULL,
                    detected_at_ts INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS arb_capture_stats (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    violation_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    theoretical_pnl REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    rollback_loss REAL NOT NULL,
                    time_in_partial_basket REAL NOT NULL,
                    peak_capital_tied REAL NOT NULL,
                    capture_ratio REAL NOT NULL,
                    created_at_ts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_graph_event ON graph_edges(event_id);
                CREATE INDEX IF NOT EXISTS idx_violations_event_ts ON constraint_violations(event_id, detected_at_ts);
                CREATE INDEX IF NOT EXISTS idx_capture_violation ON arb_capture_stats(violation_id);
                """
            )

    def upsert_edge(self, edge: GraphEdge) -> None:
        now = _now_ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_edges (
                    edge_id, event_id, market_a, market_b, relation_type,
                    semantic_confidence, resolution_key, metadata_json, created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                    relation_type=excluded.relation_type,
                    semantic_confidence=excluded.semantic_confidence,
                    resolution_key=excluded.resolution_key,
                    metadata_json=excluded.metadata_json,
                    updated_at_ts=excluded.updated_at_ts
                """,
                (
                    edge.edge_id,
                    edge.event_id,
                    edge.market_a,
                    edge.market_b,
                    edge.relation_type,
                    float(edge.semantic_confidence),
                    edge.resolution_key,
                    json.dumps(edge.metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()

    def insert_violation(self, violation: ConstraintViolation) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO constraint_violations (
                    violation_id, event_id, relation_type, market_ids_json,
                    semantic_confidence, gross_edge, slippage_est, fill_risk,
                    semantic_penalty, score, vpin, action,
                    theoretical_pnl, realized_pnl, details_json, detected_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    violation.violation_id,
                    violation.event_id,
                    violation.relation_type,
                    json.dumps(list(violation.market_ids)),
                    float(violation.semantic_confidence),
                    float(violation.gross_edge),
                    float(violation.slippage_est),
                    float(violation.fill_risk),
                    float(violation.semantic_penalty),
                    float(violation.score),
                    float(violation.vpin),
                    violation.action,
                    float(violation.theoretical_pnl),
                    float(violation.realized_pnl),
                    json.dumps(violation.details or {}, sort_keys=True),
                    int(violation.detected_at_ts),
                ),
            )
            conn.commit()

    def insert_capture_stat(
        self,
        *,
        violation_id: str,
        event_id: str,
        relation_type: str,
        result: ExecutionResult,
    ) -> None:
        capture_ratio = 0.0
        if abs(result.theoretical_pnl) > 1e-12:
            capture_ratio = result.realized_pnl / result.theoretical_pnl

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO arb_capture_stats (
                    violation_id, event_id, relation_type,
                    theoretical_pnl, realized_pnl, rollback_loss,
                    time_in_partial_basket, peak_capital_tied, capture_ratio, created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    violation_id,
                    event_id,
                    relation_type,
                    float(result.theoretical_pnl),
                    float(result.realized_pnl),
                    float(result.rollback_loss),
                    float(result.time_in_partial_basket),
                    float(result.peak_capital_tied),
                    float(capture_ratio),
                    _now_ts(),
                ),
            )
            conn.commit()

    @staticmethod
    def _avg(values: Sequence[float]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    @staticmethod
    def _fmt_ts(ts: int | None) -> str:
        if not ts:
            return "n/a"
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()

    @staticmethod
    def _edge_bucket(gross_edge: float) -> str:
        if gross_edge < 0.05:
            return "<5%"
        if gross_edge < 0.10:
            return "5-10%"
        if gross_edge < 0.20:
            return "10-20%"
        return "20%+"

    def write_shadow_report(self, output_path: str | Path, days: int = 14) -> Path:
        since_ts = _now_ts() - max(1, int(days)) * 86400
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            raw_rows = conn.execute(
                """
                SELECT
                    violation_id, event_id, relation_type, semantic_confidence,
                    gross_edge, slippage_est, fill_risk, semantic_penalty,
                    score, vpin, action, theoretical_pnl, realized_pnl,
                    details_json, detected_at_ts
                FROM constraint_violations
                WHERE detected_at_ts >= ?
                ORDER BY detected_at_ts DESC
                """,
                (since_ts,),
            ).fetchall()

        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            details: dict[str, Any] = {}
            try:
                parsed = json.loads(raw[13]) if raw[13] else {}
                if isinstance(parsed, dict):
                    details = parsed
            except json.JSONDecodeError:
                details = {}

            rows.append(
                {
                    "violation_id": str(raw[0]),
                    "event_id": str(raw[1]),
                    "relation_type": str(raw[2]),
                    "semantic_confidence": float(raw[3] or 0.0),
                    "gross_edge": float(raw[4] or 0.0),
                    "slippage_est": float(raw[5] or 0.0),
                    "fill_risk": float(raw[6] or 0.0),
                    "semantic_penalty": float(raw[7] or 0.0),
                    "score": float(raw[8] or 0.0),
                    "vpin": float(raw[9] or 0.0),
                    "action": str(raw[10]),
                    "theoretical_pnl": float(raw[11] or 0.0),
                    "realized_pnl": float(raw[12] or 0.0),
                    "details": details,
                    "detected_at_ts": int(raw[14] or 0),
                }
            )

        total = len(rows)
        theo = float(sum(row["theoretical_pnl"] for row in rows))
        real = float(sum(row["realized_pnl"] for row in rows))
        capture = (real / theo) if abs(theo) > 1e-12 else 0.0
        sem_conf = self._avg([row["semantic_confidence"] for row in rows])
        avg_gross = self._avg([row["gross_edge"] for row in rows])
        avg_slip = self._avg([row["slippage_est"] for row in rows])
        avg_vpin = self._avg([row["vpin"] for row in rows])
        vetoes = sum(1 for row in rows if row["action"] == "vpin_veto")
        unique_events = len({row["event_id"] for row in rows})

        first_ts = min((row["detected_at_ts"] for row in rows), default=None)
        last_ts = max((row["detected_at_ts"] for row in rows), default=None)
        observed_days = 0.0
        if first_ts is not None and last_ts is not None and last_ts >= first_ts:
            observed_days = float(last_ts - first_ts) / 86400.0

        sum_rows = [row for row in rows if row["relation_type"] == "same_event_sum"]
        tradable_sum_rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, int, int]] = set()
        for row in sum_rows:
            details = row["details"]
            if row["action"] == "buy_yes_basket" and not bool(details.get("complete_basket")):
                continue

            dedupe_key = (
                row["event_id"],
                row["action"],
                int(float(details.get("sum_yes_ask", 0.0)) * 10000),
                int(details.get("legs", 0)),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            tradable_sum_rows.append(row)

        modeled_positive = [row for row in tradable_sum_rows if row["action"] != "vpin_veto" and row["score"] > 0.0]
        qualifying_events = {row["event_id"] for row in modeled_positive}
        modeled_positive_rate = (
            float(len(modeled_positive)) / float(len(tradable_sum_rows))
            if tradable_sum_rows
            else 0.0
        )
        complete_underrounds = sum(
            1
            for row in tradable_sum_rows
            if row["action"] == "buy_yes_basket" and bool(row["details"].get("complete_basket"))
        )
        if observed_days >= float(days):
            kill_status = "CONTINUE" if len(qualifying_events) >= 5 else "KILL"
        else:
            kill_status = "IN PROGRESS"

        backtest_buckets: dict[str, list[dict[str, Any]]] = {}
        for row in tradable_sum_rows:
            bucket = self._edge_bucket(row["gross_edge"])
            backtest_buckets.setdefault(bucket, []).append(row)

        lines = [
            "# Constraint Arb Shadow Report",
            "",
            f"Requested window: last {days} day(s)",
            "",
            "## Summary",
            "",
            f"- Violations logged: {total}",
            f"- Unique events: {unique_events}",
            f"- Actual observed span: {self._fmt_ts(first_ts)} -> {self._fmt_ts(last_ts)} ({observed_days:.4f} day(s))",
            f"- Theoretical PnL: {theo:.6f}",
            f"- Realized PnL: {real:.6f}",
            f"- Capture ratio: {capture:.2%}",
            f"- Avg semantic confidence: {sem_conf:.3f}",
            f"- Avg gross edge: {avg_gross:.4f}",
            f"- Avg slippage estimate: {avg_slip:.4f}",
            f"- Avg VPIN at decision: {avg_vpin:.4f}",
            f"- VPIN veto count: {vetoes}",
            "",
            "## Sum-Violation Backtest",
            "",
            "- Basis: shadow captures only. Modeled net edge uses `score = gross_edge - slippage_est - fill_risk - semantic_penalty`.",
            f"- Same-event sum observations: {len(sum_rows)} raw / {len(tradable_sum_rows)} tradable after coverage filter",
            f"- Complete-basket underrounds: {complete_underrounds}",
            f"- Modeled net-positive opportunities: {len(modeled_positive)}/{len(tradable_sum_rows)} ({modeled_positive_rate:.2%})",
            f"- Avg modeled net edge: {self._avg([row['score'] for row in tradable_sum_rows]):.4f}",
            "",
            "| gross_edge bin | observations | unique events | modeled net-positive | avg gross_edge | avg modeled net edge |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]

        for bucket in ("<5%", "5-10%", "10-20%", "20%+"):
            bucket_rows = backtest_buckets.get(bucket, [])
            if not bucket_rows:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        bucket,
                        str(len(bucket_rows)),
                        str(len({row["event_id"] for row in bucket_rows})),
                        str(sum(1 for row in bucket_rows if row["action"] != "vpin_veto" and row["score"] > 0.0)),
                        f"{self._avg([row['gross_edge'] for row in bucket_rows]):.4f}",
                        f"{self._avg([row['score'] for row in bucket_rows]):.4f}",
                    ]
                )
                + " |"
            )

        lines.extend(
            [
                "",
                "## Kill Gate",
                "",
                "- Rule: kill A-6 on day 14 if fewer than 5 unique qualifying same-event sum events are detected.",
                f"- Status: {kill_status}",
                f"- Qualifying events so far: {len(qualifying_events)}",
                f"- Observation progress: {observed_days:.4f}/{float(days):.1f} day(s)",
                "",
                "## Attribution Table",
                "",
                "| violation_id | event_id | relation_type | semantic_confidence | gross_edge | score | slippage_est | vpin | action | sum_yes_ask | complete_basket | theoretical_pnl | realized_pnl |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |",
            ]
        )

        for row in rows[:50]:
            details = row["details"]
            sum_yes_ask = details.get("sum_yes_ask")
            complete_basket = details.get("complete_basket")
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["violation_id"]),
                        str(row["event_id"]),
                        str(row["relation_type"]),
                        f"{row['semantic_confidence']:.3f}",
                        f"{row['gross_edge']:.4f}",
                        f"{row['score']:.4f}",
                        f"{row['slippage_est']:.4f}",
                        f"{row['vpin']:.4f}",
                        str(row["action"]),
                        f"{float(sum_yes_ask):.4f}" if sum_yes_ask is not None else "",
                        str(bool(complete_basket)) if complete_basket is not None else "",
                        f"{row['theoretical_pnl']:.6f}",
                        f"{row['realized_pnl']:.6f}",
                    ]
                )
                + " |"
            )

        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output


class CandidateGenerator:
    """Heuristic candidate reduction to avoid combinatorial pair explosion."""

    def __init__(
        self,
        min_token_overlap: int = 1,
        min_similarity: float = 0.60,
        resolution_window_hours: int = 72,
        prefilter_score_threshold: float = 4.0,
        max_same_event_pairs_per_event: int = 24,
        max_pairs_per_block: int = 80,
    ) -> None:
        self.min_token_overlap = min_token_overlap
        self.min_similarity = min_similarity
        self.resolution_window_hours = max(1, int(resolution_window_hours))
        self.prefilter_score_threshold = float(prefilter_score_threshold)
        self.max_same_event_pairs_per_event = max(1, int(max_same_event_pairs_per_event))
        self.max_pairs_per_block = max(1, int(max_pairs_per_block))
        self._last_stats: dict[str, int] = {}

    @property
    def last_stats(self) -> dict[str, int]:
        return dict(self._last_stats)

    def _resolution_delta_hours(self, left: NormalizedMarket, right: NormalizedMarket) -> float | None:
        left_cutoff = left.profile.cutoff_ts
        right_cutoff = right.profile.cutoff_ts
        if not left_cutoff or not right_cutoff:
            return None
        delta_seconds = abs(int(left_cutoff) - int(right_cutoff))
        return float(delta_seconds / 3600.0)

    def _within_resolution_window(self, left: NormalizedMarket, right: NormalizedMarket) -> bool:
        delta_hours = self._resolution_delta_hours(left, right)
        if delta_hours is None:
            return True
        return delta_hours <= self.resolution_window_hours

    def _market_blocks(self, market: NormalizedMarket) -> set[str]:
        blocks: set[str] = set()
        for token in sorted(_slug_tokens(market.event_id))[:4]:
            blocks.add(f"anchor:{token}")
        for entity in _extract_named_entities(market.question)[:3]:
            blocks.add(f"entity:{entity}")
        for office in sorted(_extract_office_tokens(market.question)):
            blocks.add(f"office:{office}")
        if market.profile.source != "unknown":
            blocks.add(f"source:{market.profile.source}")
        return blocks

    def score_pair(self, market_a: NormalizedMarket, market_b: NormalizedMarket) -> CandidatePair:
        left, right = _canonical_pair(market_a, market_b)
        pair_key = (left.market_id, right.market_id)
        signature = build_pair_signature(left, right)

        same_event = left.event_id == right.event_id
        same_category = bool(left.category and right.category and left.category == right.category and left.category != "unknown")
        resolution_delta_hours = self._resolution_delta_hours(left, right)
        within_window = self._within_resolution_window(left, right)
        shared_question_tokens = tuple(sorted(extract_keywords(left.question) & extract_keywords(right.question)))
        shared_event_anchors = tuple(sorted(_slug_tokens(left.event_id) & _slug_tokens(right.event_id)))
        shared_entities = tuple(sorted(set(_extract_named_entities(left.question)) & set(_extract_named_entities(right.question))))
        shared_date_tokens = tuple(sorted(set(_extract_date_tokens(left.question)) & set(_extract_date_tokens(right.question))))
        lexical_cues: list[str] = []

        threshold_rel = RelationClassifier._threshold_implication(left.question, right.question)
        if threshold_rel is not None:
            lexical_cues.append(threshold_rel[1])
        lexical_rel = RelationClassifier._lexical_implication(left.question, right.question)
        if lexical_rel is not None:
            lexical_cues.append("lexical_implication")
        if RelationClassifier._mutual_exclusion(left.question, right.question):
            lexical_cues.append("mutual_exclusion")

        same_event_hint = _same_event_relation_hint(left, right)
        if same_event_hint is not None:
            lexical_cues.append(same_event_hint[1])

        office_hierarchy_cues = _office_hierarchy_cues(left, right)
        title_sim = title_similarity(normalize_title(left.question), normalize_title(right.question))

        outcome_overlap_ratio = 0.0
        left_outcomes = {normalize_outcome_name(outcome) for outcome in left.outcomes if normalize_outcome_name(outcome)}
        right_outcomes = {normalize_outcome_name(outcome) for outcome in right.outcomes if normalize_outcome_name(outcome)}
        if left_outcomes and right_outcomes:
            outcome_overlap_ratio = len(left_outcomes & right_outcomes) / len(left_outcomes | right_outcomes)

        gate = resolution_equivalence_gate([left, right])

        score = 0.0
        if same_event:
            score += 5.0
        if same_category:
            score += 0.5
        if within_window:
            score += 1.0
        score += min(len(shared_event_anchors), 3) * 1.4
        score += min(len(shared_entities), 2) * 1.6
        score += min(len(shared_question_tokens), 3) * 0.8
        score += min(1.0, title_sim) * 2.0
        if shared_date_tokens:
            score += 0.5
        if lexical_cues:
            score += 2.0
        if office_hierarchy_cues:
            score += 1.5
        if outcome_overlap_ratio >= 0.5:
            score += 0.5
        if gate.passed:
            score += 1.0
        else:
            score -= 3.0
        if not within_window and not same_event:
            score -= 2.0

        evidence_points = sum(
            1
            for present in (
                same_event,
                bool(shared_event_anchors),
                bool(shared_entities),
                len(shared_question_tokens) >= self.min_token_overlap,
                title_sim >= self.min_similarity,
                bool(shared_date_tokens),
                bool(lexical_cues),
                bool(office_hierarchy_cues),
                outcome_overlap_ratio >= 0.5,
            )
            if present
        )

        suggested_label = "ambiguous"
        sample_bucket = "shared_anchor_candidate"
        if same_event_hint is not None:
            suggested_label, sample_bucket = same_event_hint[0], "same_event_cluster"
        elif threshold_rel is not None:
            suggested_label, sample_bucket = threshold_rel[0], "implication_candidate"
        elif lexical_rel is not None:
            suggested_label, sample_bucket = lexical_rel[0], "implication_candidate"
        elif "mutual_exclusion" in lexical_cues:
            suggested_label, sample_bucket = "mutually_exclusive", "mutual_exclusion_candidate"
        elif office_hierarchy_cues:
            sample_bucket = "office_hierarchy_candidate"
        elif same_event:
            sample_bucket = "same_event_cluster"
        elif title_sim < self.min_similarity and len(shared_question_tokens) < self.min_token_overlap:
            suggested_label, sample_bucket = "independent", "control_near_miss"

        strong_signal = same_event or bool(shared_event_anchors) or bool(shared_entities) or bool(lexical_cues) or bool(office_hierarchy_cues)
        passed = gate.passed and (
            same_event
            or (
                within_window
                and strong_signal
                and evidence_points >= 3
                and score >= self.prefilter_score_threshold
            )
        )
        if not passed and sample_bucket != "control_near_miss":
            sample_bucket = "control_near_miss"
            if suggested_label == "ambiguous":
                suggested_label = "independent"

        reason_codes = tuple(
            dict.fromkeys(
                [
                    *(["same_event"] if same_event else []),
                    *(["same_category"] if same_category else []),
                    *(["resolution_window_aligned"] if within_window else ["resolution_window_miss"]),
                    *(["shared_event_anchor"] if shared_event_anchors else []),
                    *(["shared_named_entity"] if shared_entities else []),
                    *(["shared_date_token"] if shared_date_tokens else []),
                    *(["title_similarity"] if title_sim >= self.min_similarity else []),
                    *lexical_cues,
                    *office_hierarchy_cues,
                    *gate.reasons,
                ]
            )
        )

        return CandidatePair(
            market_a=left,
            market_b=right,
            pair_key=pair_key,
            pair_signature=signature,
            passed=passed,
            priority=float(score),
            sample_bucket=sample_bucket,
            suggested_label=suggested_label,
            reason_codes=reason_codes,
            features=PrefilterFeatures(
                same_event=same_event,
                same_category=same_category,
                within_resolution_window=within_window,
                resolution_delta_hours=resolution_delta_hours,
                title_similarity=float(title_sim),
                shared_question_tokens=shared_question_tokens,
                shared_event_anchors=shared_event_anchors,
                shared_entities=shared_entities,
                shared_date_tokens=shared_date_tokens,
                lexical_cues=tuple(lexical_cues),
                office_hierarchy_cues=office_hierarchy_cues,
                outcome_overlap_ratio=float(outcome_overlap_ratio),
                gate_passed=gate.passed,
                gate_reasons=tuple(gate.reasons),
                score=float(score),
            ),
        )

    def generate_candidates(
        self,
        markets: Sequence[NormalizedMarket],
        *,
        max_pairs: int = 2000,
        include_rejected: bool = False,
    ) -> list[CandidatePair]:
        seen: set[tuple[str, str]] = set()
        candidates: dict[tuple[str, str], CandidatePair] = {}
        same_event_considered = 0
        block_considered = 0

        by_event: dict[str, list[NormalizedMarket]] = {}
        for market in markets:
            by_event.setdefault(market.event_id, []).append(market)

        for event_id in sorted(by_event):
            event_markets = sorted(by_event[event_id], key=lambda market: market.market_id)
            per_event = 0
            for left, right in combinations(event_markets, 2):
                if per_event >= self.max_same_event_pairs_per_event:
                    break
                pair = self.score_pair(left, right)
                seen.add(pair.pair_key)
                candidates[pair.pair_key] = pair
                same_event_considered += 1
                per_event += 1

        block_index: dict[str, list[NormalizedMarket]] = {}
        for market in markets:
            for block in self._market_blocks(market):
                block_index.setdefault(block, []).append(market)

        for block in sorted(block_index):
            block_markets = sorted({market.market_id: market for market in block_index[block]}.values(), key=lambda market: market.market_id)
            per_block = 0
            for left, right in combinations(block_markets, 2):
                if per_block >= self.max_pairs_per_block:
                    break
                pair_key = tuple(sorted((left.market_id, right.market_id)))
                if pair_key in seen:
                    continue
                pair = self.score_pair(left, right)
                candidates[pair.pair_key] = pair
                seen.add(pair.pair_key)
                block_considered += 1
                per_block += 1

        ordered = sorted(
            candidates.values(),
            key=lambda pair: (
                0 if pair.passed else 1,
                -pair.priority,
                pair.pair_key,
            ),
        )
        if not include_rejected:
            ordered = [pair for pair in ordered if pair.passed]
        ordered = ordered[: max(1, int(max_pairs))] if ordered else []

        naive_pairs = math.comb(len(markets), 2) if len(markets) >= 2 else 0
        self._last_stats = {
            "market_count": len(markets),
            "naive_pairs": naive_pairs,
            "same_event_considered": same_event_considered,
            "block_pairs_considered": block_considered,
            "unique_pairs_considered": len(candidates),
            "passed_pairs": sum(1 for pair in candidates.values() if pair.passed),
            "rejected_pairs": sum(1 for pair in candidates.values() if not pair.passed),
            "returned_pairs": len(ordered),
        }
        return ordered

    def generate(self, markets: Sequence[NormalizedMarket], max_pairs: int = 2000) -> list[tuple[NormalizedMarket, NormalizedMarket]]:
        return [
            (pair.market_a, pair.market_b)
            for pair in self.generate_candidates(markets, max_pairs=max_pairs, include_rejected=False)
        ]


class ViolationScorer:
    @staticmethod
    def score(
        *,
        theoretical_edge: float,
        worst_case_slippage: float,
        fill_risk: float,
        semantic_penalty: float,
    ) -> float:
        return float(theoretical_edge - worst_case_slippage - fill_risk - semantic_penalty)


class ExecutionManager:
    """Simulate multi-leg passive execution and partial-basket risk."""

    def __init__(self, rollback_haircut: float = 0.2, reprice_penalty: float = 0.02) -> None:
        self.rollback_haircut = rollback_haircut
        self.reprice_penalty = reprice_penalty

    @staticmethod
    def _leg_cost(side: str, qty: float, price: float) -> float:
        # BUY consumes capital, SELL releases capital.
        sign = 1.0 if side.upper() == "BUY" else -1.0
        return sign * qty * price

    def simulate(self, plan: ExecutionPlan, fills: Mapping[str, LegFill]) -> ExecutionResult:
        theoretical_cost = 0.0
        for leg in plan.legs:
            theoretical_cost += self._leg_cost(leg.side, leg.quantity, leg.limit_price)
        theoretical_pnl = plan.payoff_if_complete - theoretical_cost

        realized_cost = 0.0
        incomplete = False
        has_reprice_or_halt = False
        ts_values: list[int] = []
        timeline: list[tuple[int, float]] = []

        for idx, leg in enumerate(plan.legs):
            fill = fills.get(leg.leg_id)
            if not fill:
                incomplete = True
                continue

            filled = max(0.0, min(fill.filled_qty, leg.quantity))
            realized_cost += self._leg_cost(leg.side, filled, fill.avg_price)
            ts = int(fill.ts or (_now_ts() + idx))
            ts_values.append(ts)
            timeline.append((ts, self._leg_cost(leg.side, filled, fill.avg_price)))

            if filled + 1e-9 < leg.quantity or fill.status in {"missed", "partial", "repriced", "halted"}:
                incomplete = True
            if fill.status in {"repriced", "halted"}:
                has_reprice_or_halt = True

        timeline.sort(key=lambda row: row[0])
        running = 0.0
        peak_capital = 0.0
        for _, flow in timeline:
            running += flow
            peak_capital = max(peak_capital, running)

        time_in_partial = 0.0
        if len(ts_values) >= 2:
            time_in_partial = float(max(ts_values) - min(ts_values))

        if not incomplete:
            return ExecutionResult(
                theoretical_pnl=float(theoretical_pnl),
                realized_pnl=float(plan.payoff_if_complete - realized_cost),
                rollback_loss=0.0,
                time_in_partial_basket=time_in_partial,
                peak_capital_tied=float(max(0.0, peak_capital)),
                complete=True,
            )

        rollback = abs(realized_cost) * self.rollback_haircut
        if has_reprice_or_halt:
            rollback += abs(realized_cost) * self.reprice_penalty

        return ExecutionResult(
            theoretical_pnl=float(theoretical_pnl),
            realized_pnl=float(-rollback),
            rollback_loss=float(rollback),
            time_in_partial_basket=time_in_partial,
            peak_capital_tied=float(max(0.0, peak_capital)),
            complete=False,
        )


def _parse_outcome_prices(raw: Any) -> tuple[float, float]:
    values: list[float] = []
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                raw = decoded
        except json.JSONDecodeError:
            raw = []

    if isinstance(raw, list):
        for item in raw[:2]:
            values.append(_safe_float(item, 0.5))

    while len(values) < 2:
        values.append(0.5)

    yes = _clamp_price(values[0])
    no = _clamp_price(values[1])
    return yes, no


def parse_clob_token_ids(raw: Any) -> tuple[str, str]:
    """Parse Gamma `clobTokenIds` payload into (yes_token_id, no_token_id)."""
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return ("", "")
        try:
            decoded = json.loads(stripped)
            raw = decoded
        except json.JSONDecodeError:
            if "," in stripped:
                parts = [part.strip().strip('"').strip("'") for part in stripped.split(",") if part.strip()]
            else:
                parts = [stripped.strip('"').strip("'")]
            yes = parts[0] if parts else ""
            no = parts[1] if len(parts) > 1 else ""
            return (yes, no)

    parts: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, Mapping):
                token = item.get("token_id") or item.get("id")
                if isinstance(token, str) and token.strip():
                    parts.append(token.strip())

    yes = parts[0] if parts else ""
    no = parts[1] if len(parts) > 1 else ""
    return (yes, no)


def _extract_market_id(raw: Mapping[str, Any]) -> str:
    return str(
        raw.get("market_id")
        or raw.get("id")
        or raw.get("conditionId")
        or raw.get("condition_id")
        or raw.get("slug")
        or ""
    )


def _extract_yes_quote(raw: Mapping[str, Any]) -> tuple[float, float]:
    yes_from_outcomes, _ = _parse_outcome_prices(raw.get("outcomePrices"))
    best_bid = _safe_float(raw.get("bestBid"), yes_from_outcomes)
    best_ask = _safe_float(raw.get("bestAsk"), yes_from_outcomes)

    yes_bid = _clamp_price(best_bid)
    yes_ask = _clamp_price(best_ask)
    if yes_ask < yes_bid:
        yes_bid, yes_ask = yes_ask, yes_bid
    return yes_bid, yes_ask


def _http_json(url: str) -> Any:
    req = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def fetch_gamma_markets(*, max_pages: int = 5, page_limit: int = 200, include_closed: bool = False) -> list[dict[str, Any]]:
    """Fetch active Polymarket markets from Gamma API."""
    markets: list[dict[str, Any]] = []
    limit = max(1, int(page_limit))
    pages = max(1, int(max_pages))

    for page in range(pages):
        params = {
            "closed": "true" if include_closed else "false",
            "limit": str(limit),
            "offset": str(page * limit),
        }
        url = f"{GAMMA_API_BASE}/markets?{urlencode(params)}"
        try:
            payload = _http_json(url)
        except Exception as exc:
            logger.warning("Gamma fetch failed (page=%s): %s", page, exc)
            break

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, Mapping):
            data = payload.get("data", [])
            rows = data if isinstance(data, list) else []
        else:
            rows = []

        if not rows:
            break

        for row in rows:
            if isinstance(row, Mapping):
                question = str(row.get("question") or row.get("title") or "").strip()
                market_id = _extract_market_id(row)
                if question and market_id:
                    markets.append(dict(row))

        if len(rows) < limit:
            break
        time.sleep(0.05)

    return markets


class ConstraintArbRuntime:
    """Live runtime that merges Gamma `/events` discovery with CLOB market books."""

    def __init__(
        self,
        *,
        engine: ConstraintArbEngine,
        max_pages: int = 20,
        page_limit: int = 100,
        max_pairs: int = 1500,
        scan_interval_seconds: int = 60,
        market_refresh_seconds: int = 300,
        gamma_cache: GammaMarketCache | None = None,
        clob_client: CLOBWebSocketClient | None = None,
    ) -> None:
        if GammaMarketCache is None or CLOBWebSocketClient is None:
            raise RuntimeError("GammaMarketCache and CLOBWebSocketClient are required for the live runtime")

        self.engine = engine
        self.max_pairs = max_pairs
        self.scan_interval_seconds = max(1, int(scan_interval_seconds))
        self.market_refresh_seconds = max(15, int(market_refresh_seconds))
        self.gamma_cache = gamma_cache or GammaMarketCache(
            max_pages=max_pages,
            page_size=page_limit,
            refresh_interval_seconds=self.market_refresh_seconds,
        )
        self.clob_client = clob_client or CLOBWebSocketClient(
            stale_book_seconds=float(self.engine.stale_quote_seconds),
            quarantine_retry_seconds=max(120.0, float(self.market_refresh_seconds)),
        )

        self._clob_task: asyncio.Task[None] | None = None
        self._latest_snapshot: ConstraintRuntimeSnapshot | None = None

    @property
    def stream_enabled(self) -> bool:
        return CLOBWebSocketClient is not None

    @property
    def latest_snapshot(self) -> ConstraintRuntimeSnapshot | None:
        return self._latest_snapshot

    async def _ensure_clob_running(self) -> None:
        if self._clob_task is None or self._clob_task.done():
            self._clob_task = asyncio.create_task(self.clob_client.run(), name="constraint-clob-client")

    async def refresh_markets(self, *, force: bool = False) -> int:
        snapshot = await self.gamma_cache.refresh_once(force=force)
        self.engine.sync_normalized_markets(snapshot.normalized_markets())
        self.clob_client.sync_tokens(snapshot.token_to_market_id)
        await self._ensure_clob_running()

        bootstrap_tokens = [
            token_id
            for token_id in snapshot.all_token_ids()
            if self.clob_client.get_book(token_id, require_fresh=False) is None
        ]
        if bootstrap_tokens:
            await self.clob_client.bootstrap_tokens(bootstrap_tokens)
        return len(snapshot.markets)

    def _token_block_reason(self, token_id: str, *, side: str) -> str:
        if not token_id:
            return f"missing_{side}_token"
        state = self.clob_client.get_token_state(token_id)
        if state is None:
            return f"{side}_book_unavailable"
        if state.status == "quarantined":
            return f"{side}_token_404"
        if state.status == "stale":
            return f"{side}_stale_book"
        if state.status == "error":
            return f"{side}_book_error"
        if state.status == "tracking":
            return f"{side}_book_pending"
        return f"{side}_book_unavailable"

    def _build_market_view(
        self,
        *,
        record: GammaMarketRecord,
        now_ts: int,
    ) -> LiveConstraintMarket:
        blocked_reasons = list(record.incomplete_reasons)
        yes_book = self.clob_client.get_book(record.yes_token_id) if record.yes_token_id else None
        no_book = self.clob_client.get_book(record.no_token_id) if record.no_token_id else None

        if yes_book is None:
            blocked_reasons.append(self._token_block_reason(record.yes_token_id, side="yes"))
        if no_book is None:
            blocked_reasons.append(self._token_block_reason(record.no_token_id, side="no"))

        freshness_values: list[float] = []
        if yes_book is not None:
            freshness_values.append(max(0.0, float(now_ts) - yes_book.received_ts))
        if no_book is not None:
            freshness_values.append(max(0.0, float(now_ts) - no_book.received_ts))
        freshness_seconds = max(freshness_values) if freshness_values else None

        quote = None
        executable = False
        if (
            yes_book is not None
            and no_book is not None
            and yes_book.best_bid is not None
            and yes_book.best_ask is not None
            and no_book.best_bid is not None
            and no_book.best_ask is not None
        ):
            executable = not blocked_reasons
            quote = MarketQuote(
                market_id=record.market_id,
                yes_bid=_clamp_price(yes_book.best_bid),
                yes_ask=_clamp_price(yes_book.best_ask),
                no_bid=_clamp_price(no_book.best_bid),
                no_ask=_clamp_price(no_book.best_ask),
                updated_ts=now_ts,
                complete=executable,
                blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                freshness_seconds=freshness_seconds,
                source="ws",
            )

        return LiveConstraintMarket(
            market_id=record.market_id,
            event_id=record.event_id,
            slug=record.market_slug,
            question=record.question,
            condition_id=record.condition_id,
            yes_token_id=record.yes_token_id,
            no_token_id=record.no_token_id,
            outcome_name=record.outcome_name or record.normalized_market.outcome,
            category=record.category,
            tags=record.tags,
            normalized_market=record.normalized_market,
            quote=quote,
            freshness_seconds=freshness_seconds,
            executable=executable,
            blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
            multi_outcome_event_id=record.multi_outcome_event_id,
            multi_outcome_size=record.multi_outcome_size,
        )

    def build_runtime_snapshot(self, *, now_ts: int | None = None) -> ConstraintRuntimeSnapshot:
        now_ts = int(now_ts or _now_ts())
        gamma_snapshot = self.gamma_cache.get_snapshot()
        market_views = tuple(
            self._build_market_view(record=record, now_ts=now_ts)
            for record in gamma_snapshot.markets.values()
        )
        market_view_by_id = {market.market_id: market for market in market_views}

        event_views: list[LiveConstraintEvent] = []
        for event in gamma_snapshot.events.values():
            event_markets = [market_view_by_id[market_id] for market_id in event.market_ids if market_id in market_view_by_id]
            blocked_reasons = list(event.blocked_reasons)
            if event.is_multi_outcome and any(not market.executable for market in event_markets):
                blocked_reasons.append("live_book_incomplete")
            freshness_values = [market.freshness_seconds for market in event_markets if market.freshness_seconds is not None]
            event_views.append(
                LiveConstraintEvent(
                    event_id=event.event_id,
                    slug=event.slug,
                    title=event.title,
                    category=event.category,
                    tags=event.tags,
                    market_ids=event.market_ids,
                    outcome_names=event.outcome_names,
                    is_multi_outcome=event.is_multi_outcome,
                    executable=bool(event.is_multi_outcome and event.executable and not any(not market.executable for market in event_markets)),
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    freshness_seconds=max(freshness_values) if freshness_values else None,
                )
            )

        executable_quotes = [market.quote for market in market_views if market.quote is not None and market.executable]
        self.engine.replace_quotes(executable_quotes)

        gamma_metrics = gamma_snapshot.metrics
        clob_metrics = self.clob_client.get_metrics()
        metrics = {
            "event_count": gamma_metrics.event_count,
            "market_count": gamma_metrics.market_count,
            "multi_outcome_event_count": gamma_metrics.multi_outcome_event_count,
            "incomplete_market_count": gamma_metrics.incomplete_market_count,
            "executable_market_count": len(executable_quotes),
            "blocked_market_count": sum(1 for market in market_views if not market.executable),
            "gamma_refresh_count": gamma_metrics.refresh_count,
            "gamma_refresh_failures": gamma_metrics.refresh_failures,
            "gamma_last_error": gamma_metrics.last_error,
            **clob_metrics,
        }
        snapshot = ConstraintRuntimeSnapshot(
            updated_ts=now_ts,
            markets=market_views,
            events=tuple(event_views),
            metrics=metrics,
        )
        self._latest_snapshot = snapshot
        return snapshot

    async def run_cycle_async(self, *, force_market_refresh: bool = False) -> dict[str, Any]:
        markets_refreshed = await self.refresh_markets(force=force_market_refresh)
        runtime_snapshot = self.build_runtime_snapshot()

        reset_budget = getattr(self.engine.classifier, "reset_debate_budget", None)
        if callable(reset_budget):
            reset_budget()

        edges = self.engine.build_constraint_graph(max_pairs=self.max_pairs)
        sum_violations = self.engine.scan_sum_violations()
        graph_violations = self.engine.scan_graph_violations()

        summary: dict[str, Any] = {
            "markets_refreshed": markets_refreshed,
            "executable_markets": runtime_snapshot.metrics.get("executable_market_count", 0),
            "incomplete_market_count": runtime_snapshot.metrics.get("incomplete_market_count", 0),
            "ws_reconnect_count": runtime_snapshot.metrics.get("ws_reconnect_count", 0),
            "stale_book_drop_count": runtime_snapshot.metrics.get("stale_book_drop_count", 0),
            "token_404_count": runtime_snapshot.metrics.get("token_404_count", 0),
            "edges_built": len(edges),
            "sum_violations": len(sum_violations),
            "graph_violations": len(graph_violations),
        }
        logger.info(
            "Constraint cycle: refreshed=%s executable=%s incomplete=%s reconnects=%s stale=%s token404=%s edges=%s sum=%s graph=%s",
            summary["markets_refreshed"],
            summary["executable_markets"],
            summary["incomplete_market_count"],
            summary["ws_reconnect_count"],
            summary["stale_book_drop_count"],
            summary["token_404_count"],
            summary["edges_built"],
            summary["sum_violations"],
            summary["graph_violations"],
        )
        return summary

    async def _run_async(self, *, once: bool = False, max_cycles: int | None = None) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        cycles = 0
        try:
            while True:
                cycles += 1
                cycle_summary = await self.run_cycle_async(force_market_refresh=(cycles == 1))
                summaries.append(cycle_summary)
                if cycles == 1 and cycle_summary["markets_refreshed"] == 0:
                    logger.warning("No markets loaded from Gamma; aborting runtime loop")
                    break
                if once:
                    break
                if max_cycles is not None and cycles >= max_cycles:
                    break
                await asyncio.sleep(self.scan_interval_seconds)
        finally:
            await self._stop_async()
        return summaries

    def run(self, *, once: bool = False, max_cycles: int | None = None) -> list[dict[str, Any]]:
        return asyncio.run(self._run_async(once=once, max_cycles=max_cycles))

    async def _stop_async(self) -> None:
        self.gamma_cache.stop()
        await self.clob_client.stop()
        if self._clob_task is not None:
            self._clob_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._clob_task
            self._clob_task = None

    def stop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._stop_async())
            return
        loop.create_task(self._stop_async())


class ConstraintArbEngine:
    """A-6 + B-1 engine with resolution-normalized hard-constraint checks."""

    def __init__(
        self,
        *,
        db_path: str | Path = Path("data") / "constraint_arb.db",
        buy_threshold: float = 0.97,
        execute_threshold: float = 0.95,
        unwind_threshold: float = 1.03,
        implication_threshold: float = 0.02,
        stale_quote_seconds: int = 30,
        max_leg_spread: float = 0.03,
        vpin_veto_threshold: float = 0.75,
        snapshot_dedupe_seconds: int = 15,
        relation_classifier: RelationClassifier | None = None,
    ) -> None:
        self.db = ConstraintArbDB(db_path)
        self.inventory = NegRiskInventory()
        self.candidate_generator = CandidateGenerator()
        self.classifier = relation_classifier or RelationClassifier()
        self.scorer = ViolationScorer()

        self.buy_threshold = buy_threshold
        self.execute_threshold = execute_threshold
        self.unwind_threshold = unwind_threshold
        self.implication_threshold = implication_threshold
        self.stale_quote_seconds = stale_quote_seconds
        self.max_leg_spread = max_leg_spread
        self.vpin_veto_threshold = vpin_veto_threshold
        self.snapshot_dedupe_seconds = snapshot_dedupe_seconds

        self._markets: dict[str, NormalizedMarket] = {}
        self._quotes: dict[str, MarketQuote] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._seen_sum_snapshots: set[tuple[str, int, int]] = set()

    @property
    def markets(self) -> dict[str, NormalizedMarket]:
        return dict(self._markets)

    @property
    def quotes(self) -> dict[str, MarketQuote]:
        return dict(self._quotes)

    @property
    def edges(self) -> dict[str, GraphEdge]:
        return dict(self._edges)

    def register_markets(self, raw_markets: Sequence[Mapping[str, Any]]) -> list[NormalizedMarket]:
        normalized = [normalize_market(raw) for raw in raw_markets]
        self.register_normalized_markets(normalized)
        return normalized

    def sync_normalized_markets(self, markets: Sequence[NormalizedMarket]) -> None:
        active_ids = {market.market_id for market in markets}
        self._markets = {market.market_id: market for market in markets}
        self._quotes = {
            market_id: quote
            for market_id, quote in self._quotes.items()
            if market_id in active_ids
        }
        self._edges = {
            edge_id: edge
            for edge_id, edge in self._edges.items()
            if edge.market_a in active_ids and edge.market_b in active_ids
        }
        self.inventory = NegRiskInventory()
        for market in markets:
            self.inventory.register_market(market)

    def register_normalized_markets(self, markets: Sequence[NormalizedMarket]) -> None:
        for market in markets:
            self._markets[market.market_id] = market
            self.inventory.register_market(market)

    def replace_quotes(self, quotes: Sequence[MarketQuote]) -> None:
        self._quotes = {quote.market_id: quote for quote in quotes}

    def update_quote(
        self,
        *,
        market_id: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float | None = None,
        no_ask: float | None = None,
        updated_ts: int | None = None,
        complete: bool = True,
        blocked_reasons: Sequence[str] | None = None,
        freshness_seconds: float | None = None,
        source: str = "unknown",
    ) -> None:
        if no_bid is None:
            no_bid = max(0.0, 1.0 - yes_ask)
        if no_ask is None:
            no_ask = max(0.0, 1.0 - yes_bid)
        self._quotes[market_id] = MarketQuote(
            market_id=market_id,
            yes_bid=float(yes_bid),
            yes_ask=float(yes_ask),
            no_bid=float(no_bid),
            no_ask=float(no_ask),
            updated_ts=int(updated_ts or _now_ts()),
            complete=bool(complete),
            blocked_reasons=tuple(blocked_reasons or ()),
            freshness_seconds=freshness_seconds,
            source=str(source),
        )

    def get_quote(self, market_id: str) -> MarketQuote | None:
        return self._quotes.get(market_id)

    def _quote_fresh(self, quote: MarketQuote, now_ts: int) -> bool:
        return bool(quote.complete) and now_ts - quote.updated_ts <= self.stale_quote_seconds

    def _event_vpin(self, event_id: str, market_ids: Sequence[str], vpin_by_id: Mapping[str, float] | None) -> float:
        if not vpin_by_id:
            return 0.0
        vals: list[float] = []
        if event_id in vpin_by_id:
            vals.append(float(vpin_by_id[event_id]))
        for market_id in market_ids:
            if market_id in vpin_by_id:
                vals.append(float(vpin_by_id[market_id]))
        return max(vals) if vals else 0.0

    def _make_violation_id(self, payload: str) -> str:
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]

    def scan_sum_violations(
        self,
        *,
        now_ts: int | None = None,
        slippage_buffer: float = 0.003,
        fill_risk: float = 0.003,
        vpin_by_id: Mapping[str, float] | None = None,
    ) -> list[ConstraintViolation]:
        now_ts = int(now_ts or _now_ts())
        by_event: dict[str, list[NormalizedMarket]] = {}
        for market in self._markets.values():
            if not (market.profile.is_neg_risk or market.is_multi_outcome):
                continue
            by_event.setdefault(market.event_id, []).append(market)

        out: list[ConstraintViolation] = []
        for event_id, event_markets in by_event.items():
            selected_outcomes: dict[str, str] = {}
            priced_markets: list[tuple[NormalizedMarket, MarketQuote]] = []
            tradable_event_markets: list[NormalizedMarket] = []
            market_spreads: dict[str, float] = {}
            maker_targets: dict[str, float] = {}
            liquidity_ok = True

            for market in event_markets:
                outcome = market.outcome or (market.outcomes[0] if market.outcomes else "")
                if market.profile.is_augmented_neg_risk and not is_tradable_outcome(market, outcome):
                    continue

                tradable_event_markets.append(market)

                quote = self._quotes.get(market.market_id)
                if not quote or not self._quote_fresh(quote, now_ts):
                    continue

                accepting_orders = bool(getattr(market, "accepting_orders", True))
                enable_order_book = bool(getattr(market, "enable_order_book", True))
                yes_token_id = str(getattr(market, "yes_token_id", "") or "")
                if not accepting_orders or not enable_order_book or not yes_token_id:
                    continue

                selected_outcomes[market.market_id] = outcome
                priced_markets.append((market, quote))
                spread = max(0.0, quote.yes_ask - quote.yes_bid)
                market_spreads[market.market_id] = float(spread)
                if spread > self.max_leg_spread:
                    liquidity_ok = False
                tick_size = max(_safe_float(getattr(market, "tick_size", 0.001), 0.001), 0.001)
                maker_target = _floor_to_tick(max(0.0, quote.yes_ask - tick_size), tick_size)
                if maker_target <= 0.0:
                    liquidity_ok = False
                maker_targets[market.market_id] = float(maker_target)

            if len(priced_markets) < 2:
                continue

            tradable_market_ids = {market.market_id for market in tradable_event_markets}
            priced_market_ids = {market.market_id for market, _ in priced_markets}
            missing_market_ids = tuple(sorted(tradable_market_ids - priced_market_ids))
            complete_basket = bool(tradable_market_ids) and not missing_market_ids

            markets_for_gate = [m for m, _ in priced_markets]
            gate: ResolutionGateResult = resolution_equivalence_gate(
                markets_for_gate,
                selected_outcomes=selected_outcomes,
            )
            # A-6 legs already come from the same Gamma event grouping. If Gamma
            # omits explicit source/cutoff metadata, keep the basket tradable in
            # shadow/live scans but preserve the penalty and gate annotations.
            if gate.safety_status == "hard_blocked":
                continue

            total_yes_ask = sum(q.yes_ask for _, q in priced_markets)
            maker_sum_bid = sum(maker_targets.get(m.market_id, q.yes_bid) for m, q in priced_markets)
            n_legs = len(priced_markets)
            slippage_est = slippage_buffer * n_legs
            effective_fill_risk = float(fill_risk + (0.005 if not liquidity_ok else 0.0))
            vpin = self._event_vpin(event_id, [m.market_id for m, _ in priced_markets], vpin_by_id)

            if maker_sum_bid < self.buy_threshold:
                gross_edge = 1.0 - maker_sum_bid
                score = self.scorer.score(
                    theoretical_edge=gross_edge,
                    worst_case_slippage=slippage_est,
                    fill_risk=effective_fill_risk,
                    semantic_penalty=gate.semantic_penalty,
                )

                snap_bucket = now_ts // self.snapshot_dedupe_seconds
                dedupe_key = (event_id, snap_bucket, int(maker_sum_bid * 10000))
                if dedupe_key in self._seen_sum_snapshots:
                    continue
                self._seen_sum_snapshots.add(dedupe_key)

                execute_ready = complete_basket and (maker_sum_bid < self.execute_threshold or liquidity_ok)
                action = "buy_yes_basket" if execute_ready else "watch_yes_basket"
                if vpin >= self.vpin_veto_threshold:
                    action = "vpin_veto"

                violation = ConstraintViolation(
                    violation_id=self._make_violation_id(f"sum_under|{event_id}|{snap_bucket}|{maker_sum_bid:.6f}"),
                    event_id=event_id,
                    relation_type="same_event_sum",
                    market_ids=tuple(sorted(m.market_id for m, _ in priced_markets)),
                    semantic_confidence=max(0.0, 1.0 - gate.semantic_penalty),
                    gross_edge=float(gross_edge),
                    slippage_est=float(slippage_est),
                    fill_risk=float(effective_fill_risk),
                    semantic_penalty=float(gate.semantic_penalty),
                    score=float(score),
                    vpin=float(vpin),
                    action=action,
                    theoretical_pnl=float(gross_edge),
                    realized_pnl=0.0,
                    details={
                        "maker_sum_bid": maker_sum_bid,
                        "sum_yes_ask": total_yes_ask,
                        "legs": n_legs,
                        "event_legs": len(tradable_market_ids),
                        "missing_legs": len(missing_market_ids),
                        "missing_market_ids": list(missing_market_ids),
                        "execute_ready": execute_ready,
                        "execute_threshold": self.execute_threshold,
                        "complete_basket": complete_basket,
                        "liquidity_ok": liquidity_ok,
                        "max_leg_spread": self.max_leg_spread,
                        "market_spreads": market_spreads,
                        "gate_safety_status": gate.safety_status,
                        "gate_reasons": list(gate.reasons),
                    },
                    detected_at_ts=now_ts,
                )
                self.db.insert_violation(violation)
                out.append(violation)

            elif total_yes_ask > self.unwind_threshold:
                gross_edge = total_yes_ask - 1.0
                score = self.scorer.score(
                    theoretical_edge=gross_edge,
                    worst_case_slippage=slippage_est,
                    fill_risk=effective_fill_risk,
                    semantic_penalty=gate.semantic_penalty,
                )
                action = "unwind_basket"
                if vpin >= self.vpin_veto_threshold:
                    action = "vpin_veto"

                violation = ConstraintViolation(
                    violation_id=self._make_violation_id(f"sum_over|{event_id}|{now_ts}|{total_yes_ask:.6f}"),
                    event_id=event_id,
                    relation_type="same_event_sum",
                    market_ids=tuple(sorted(m.market_id for m, _ in priced_markets)),
                    semantic_confidence=max(0.0, 1.0 - gate.semantic_penalty),
                    gross_edge=float(gross_edge),
                    slippage_est=float(slippage_est),
                    fill_risk=float(effective_fill_risk),
                    semantic_penalty=float(gate.semantic_penalty),
                    score=float(score),
                    vpin=float(vpin),
                    action=action,
                    theoretical_pnl=float(gross_edge),
                    realized_pnl=0.0,
                    details={
                        "maker_sum_bid": maker_sum_bid,
                        "sum_yes_ask": total_yes_ask,
                        "legs": n_legs,
                        "event_legs": len(tradable_market_ids),
                        "missing_legs": len(missing_market_ids),
                        "missing_market_ids": list(missing_market_ids),
                        "execute_ready": complete_basket and liquidity_ok,
                        "execute_threshold": self.execute_threshold,
                        "complete_basket": complete_basket,
                        "liquidity_ok": liquidity_ok,
                        "max_leg_spread": self.max_leg_spread,
                        "market_spreads": market_spreads,
                        "gate_safety_status": gate.safety_status,
                        "gate_reasons": list(gate.reasons),
                    },
                    detected_at_ts=now_ts,
                )
                self.db.insert_violation(violation)
                out.append(violation)

        return out

    def build_constraint_graph(self, max_pairs: int = 2000) -> list[GraphEdge]:
        markets = list(self._markets.values())
        reset_budget = getattr(self.classifier, "reset_debate_budget", None)
        if callable(reset_budget):
            reset_budget()
        pairs = self.candidate_generator.generate(markets, max_pairs=max_pairs)

        out: list[GraphEdge] = []
        for market_a, market_b in pairs:
            gate = resolution_equivalence_gate([market_a, market_b])
            if not gate.passed:
                continue

            relation = self.classifier.classify(market_a, market_b)
            if relation.relation_type not in {
                "same_event_sum",
                "A_implies_B",
                "B_implies_A",
                "mutually_exclusive",
                "complementary",
                "subset",
            }:
                continue

            conf = max(0.0, min(1.0, relation.confidence - gate.semantic_penalty))
            edge_id = self._make_violation_id(
                f"{market_a.market_id}|{market_b.market_id}|{relation.relation_type}|{market_a.resolution_key}|{market_b.resolution_key}"
            )
            edge = GraphEdge(
                edge_id=edge_id,
                event_id=market_a.event_id if market_a.event_id == market_b.event_id else "cross_market",
                market_a=market_a.market_id,
                market_b=market_b.market_id,
                relation_type=relation.relation_type,
                semantic_confidence=conf,
                resolution_key=f"{market_a.resolution_key}:{market_b.resolution_key}",
                metadata={
                    "reason": relation.reason,
                    "source": getattr(relation, "source", ""),
                    "prompt_version": getattr(relation, "prompt_version", ""),
                    "needs_human_review": bool(getattr(relation, "needs_human_review", False)),
                    "gate_reasons": list(gate.reasons),
                },
            )
            self._edges[edge.edge_id] = edge
            self.db.upsert_edge(edge)
            out.append(edge)
        return out

    def scan_graph_violations(
        self,
        *,
        now_ts: int | None = None,
        slippage_buffer: float = 0.004,
        fill_risk: float = 0.01,
        implication_threshold: float | None = None,
        vpin_by_id: Mapping[str, float] | None = None,
    ) -> list[ConstraintViolation]:
        now_ts = int(now_ts or _now_ts())
        implication_threshold = implication_threshold if implication_threshold is not None else self.implication_threshold

        out: list[ConstraintViolation] = []
        for edge in self._edges.values():
            market_a = self._markets.get(edge.market_a)
            market_b = self._markets.get(edge.market_b)
            quote_a = self._quotes.get(edge.market_a)
            quote_b = self._quotes.get(edge.market_b)
            if not market_a or not market_b or not quote_a or not quote_b:
                continue
            if not (self._quote_fresh(quote_a, now_ts) and self._quote_fresh(quote_b, now_ts)):
                continue

            gross_edge = 0.0
            action = "no_action"

            if edge.relation_type == "A_implies_B":
                if quote_a.yes_bid > quote_b.yes_ask + implication_threshold:
                    gross_edge = quote_a.yes_bid - quote_b.yes_ask
                    action = "buy_B_sell_A"
            elif edge.relation_type == "B_implies_A":
                if quote_b.yes_bid > quote_a.yes_ask + implication_threshold:
                    gross_edge = quote_b.yes_bid - quote_a.yes_ask
                    action = "buy_A_sell_B"
            elif edge.relation_type == "mutually_exclusive":
                if quote_a.yes_bid + quote_b.yes_bid > 1.0 + implication_threshold:
                    gross_edge = quote_a.yes_bid + quote_b.yes_bid - 1.0
                    action = "buy_NO_pair"
            else:
                continue

            if gross_edge <= 0:
                continue

            semantic_penalty = max(0.0, 1.0 - edge.semantic_confidence)
            score = self.scorer.score(
                theoretical_edge=gross_edge,
                worst_case_slippage=slippage_buffer,
                fill_risk=fill_risk,
                semantic_penalty=semantic_penalty,
            )

            event_id = market_a.event_id if market_a.event_id == market_b.event_id else "cross_market"
            vpin = self._event_vpin(event_id, [market_a.market_id, market_b.market_id], vpin_by_id)
            if vpin >= self.vpin_veto_threshold:
                action = "vpin_veto"

            violation = ConstraintViolation(
                violation_id=self._make_violation_id(f"graph|{edge.edge_id}|{now_ts}|{gross_edge:.6f}"),
                event_id=event_id,
                relation_type=edge.relation_type,
                market_ids=(market_a.market_id, market_b.market_id),
                semantic_confidence=edge.semantic_confidence,
                gross_edge=float(gross_edge),
                slippage_est=float(slippage_buffer),
                fill_risk=float(fill_risk),
                semantic_penalty=float(semantic_penalty),
                score=float(score),
                vpin=float(vpin),
                action=action,
                theoretical_pnl=float(gross_edge),
                realized_pnl=0.0,
                details={
                    "edge_id": edge.edge_id,
                    "quote_a": quote_a.yes_bid,
                    "quote_b": quote_b.yes_bid,
                },
                detected_at_ts=now_ts,
            )
            self.db.insert_violation(violation)
            out.append(violation)

        return out


def _parse_market_ids(raw: str) -> tuple[str, ...]:
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(ids)


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", default="data/constraint_arb.db")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--page-limit", type=int, default=200)
    parser.add_argument("--max-pairs", type=int, default=1500)
    parser.add_argument("--buy-threshold", type=float, default=0.97)
    parser.add_argument("--execute-threshold", type=float, default=0.95)
    parser.add_argument("--unwind-threshold", type=float, default=1.03)
    parser.add_argument("--implication-threshold", type=float, default=0.02)
    parser.add_argument("--stale-quote-seconds", type=int, default=30)
    parser.add_argument("--vpin-veto-threshold", type=float, default=0.75)
    parser.add_argument("--scan-interval", type=int, default=60)
    parser.add_argument("--market-refresh", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 = run indefinitely")
    parser.add_argument("--relation-cache-path", default="data/relation_cache.db")
    parser.add_argument("--debate-fallback", action="store_true")
    parser.add_argument("--debate-min-similarity", type=float, default=0.62)
    parser.add_argument("--debate-low-confidence", type=float, default=0.72)
    parser.add_argument("--debate-max-calls", type=int, default=100)
    parser.add_argument("--log-level", default="INFO")


def _build_engine_from_args(args: argparse.Namespace) -> ConstraintArbEngine:
    classifier = RelationClassifier(
        cache_path=args.relation_cache_path,
        prefilter_min_similarity=float(args.debate_min_similarity),
        low_confidence_threshold=float(args.debate_low_confidence),
        enable_debate_fallback=bool(getattr(args, "debate_fallback", False)),
        max_debate_calls=max(0, int(args.debate_max_calls)),
    )
    return ConstraintArbEngine(
        db_path=args.db_path,
        buy_threshold=float(args.buy_threshold),
        execute_threshold=float(args.execute_threshold),
        unwind_threshold=float(args.unwind_threshold),
        implication_threshold=float(args.implication_threshold),
        stale_quote_seconds=int(args.stale_quote_seconds),
        vpin_veto_threshold=float(args.vpin_veto_threshold),
        relation_classifier=classifier,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Constraint arb engine utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="Initialize SQLite tables")
    p_init.add_argument("--db-path", default="data/constraint_arb.db")

    p_log = sub.add_parser("shadow-log", help="Log a shadow violation record")
    p_log.add_argument("--db-path", default="data/constraint_arb.db")
    p_log.add_argument("--violation-id", required=True)
    p_log.add_argument("--event-id", required=True)
    p_log.add_argument("--relation-type", required=True)
    p_log.add_argument("--market-ids", required=True, help="comma-separated market ids")
    p_log.add_argument("--semantic-confidence", type=float, required=True)
    p_log.add_argument("--gross-edge", type=float, required=True)
    p_log.add_argument("--slippage-est", type=float, required=True)
    p_log.add_argument("--fill-risk", type=float, default=0.0)
    p_log.add_argument("--semantic-penalty", type=float, default=0.0)
    p_log.add_argument("--score", type=float, required=True)
    p_log.add_argument("--vpin", type=float, default=0.0)
    p_log.add_argument("--action", default="shadow")
    p_log.add_argument("--theoretical-pnl", type=float, default=0.0)
    p_log.add_argument("--realized-pnl", type=float, default=0.0)

    p_report = sub.add_parser("shadow-report", help="Write 14-day shadow report")
    p_report.add_argument("--db-path", default="data/constraint_arb.db")
    p_report.add_argument("--days", type=int, default=14)
    p_report.add_argument("--output", default="reports/constraint_arb_shadow_report.md")

    p_scan = sub.add_parser("scan-once", help="Run a single live scan cycle (Gamma + CLOB stream)")
    _add_runtime_args(p_scan)

    p_live = sub.add_parser("run-live", help="Run continuous live monitor for constraint violations")
    _add_runtime_args(p_live)

    return parser


def _cmd_init_db(args: argparse.Namespace) -> int:
    ConstraintArbDB(args.db_path)
    print(f"Initialized constraint arb DB at {args.db_path}")
    return 0


def _cmd_shadow_log(args: argparse.Namespace) -> int:
    db = ConstraintArbDB(args.db_path)
    violation = ConstraintViolation(
        violation_id=args.violation_id,
        event_id=args.event_id,
        relation_type=args.relation_type,
        market_ids=_parse_market_ids(args.market_ids),
        semantic_confidence=float(args.semantic_confidence),
        gross_edge=float(args.gross_edge),
        slippage_est=float(args.slippage_est),
        fill_risk=float(args.fill_risk),
        semantic_penalty=float(args.semantic_penalty),
        score=float(args.score),
        vpin=float(args.vpin),
        action=str(args.action),
        theoretical_pnl=float(args.theoretical_pnl),
        realized_pnl=float(args.realized_pnl),
        details={"source": "shadow_log_cli"},
        detected_at_ts=_now_ts(),
    )
    db.insert_violation(violation)
    print(f"Logged violation {args.violation_id}")
    return 0


def _cmd_shadow_report(args: argparse.Namespace) -> int:
    db = ConstraintArbDB(args.db_path)
    output = db.write_shadow_report(args.output, days=args.days)
    print(f"Wrote report to {output}")
    return 0


def _cmd_scan_once(args: argparse.Namespace) -> int:
    level_name = str(args.log_level).upper()
    logging.basicConfig(level=getattr(logging, level_name, logging.INFO))
    engine = _build_engine_from_args(args)
    runtime = ConstraintArbRuntime(
        engine=engine,
        max_pages=int(args.max_pages),
        page_limit=int(args.page_limit),
        max_pairs=int(args.max_pairs),
        scan_interval_seconds=int(args.scan_interval),
        market_refresh_seconds=int(args.market_refresh),
    )
    summaries = runtime.run(once=True)
    if summaries:
        print(json.dumps(summaries[-1], sort_keys=True))
        return 0
    print("{}")
    return 2


def _cmd_run_live(args: argparse.Namespace) -> int:
    level_name = str(args.log_level).upper()
    logging.basicConfig(level=getattr(logging, level_name, logging.INFO))
    engine = _build_engine_from_args(args)
    runtime = ConstraintArbRuntime(
        engine=engine,
        max_pages=int(args.max_pages),
        page_limit=int(args.page_limit),
        max_pairs=int(args.max_pairs),
        scan_interval_seconds=int(args.scan_interval),
        market_refresh_seconds=int(args.market_refresh),
    )
    max_cycles = int(args.max_cycles)
    summaries = runtime.run(once=False, max_cycles=max_cycles if max_cycles > 0 else None)
    if summaries:
        print(json.dumps(summaries[-1], sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "init-db":
        return _cmd_init_db(args)
    if args.cmd == "shadow-log":
        return _cmd_shadow_log(args)
    if args.cmd == "shadow-report":
        return _cmd_shadow_report(args)
    if args.cmd == "scan-once":
        return _cmd_scan_once(args)
    if args.cmd == "run-live":
        return _cmd_run_live(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
