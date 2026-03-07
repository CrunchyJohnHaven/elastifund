#!/usr/bin/env python3
"""Resolution-normalized constraint arbitrage engine for Polymarket."""

from __future__ import annotations

import argparse
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
    from bot.ws_trade_stream import TradeStreamManager
except ImportError:  # pragma: no cover - direct script mode
    try:
        from ws_trade_stream import TradeStreamManager  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        TradeStreamManager = None  # type: ignore[assignment]


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
    ) -> None:
        self.min_token_overlap = min_token_overlap
        self.min_similarity = min_similarity
        self.resolution_window_hours = max(1, int(resolution_window_hours))

    def _within_resolution_window(self, left: NormalizedMarket, right: NormalizedMarket) -> bool:
        left_cutoff = left.profile.cutoff_ts
        right_cutoff = right.profile.cutoff_ts
        if not left_cutoff or not right_cutoff:
            return True
        delta_seconds = abs(int(left_cutoff) - int(right_cutoff))
        return delta_seconds <= self.resolution_window_hours * 3600

    def generate(self, markets: Sequence[NormalizedMarket], max_pairs: int = 2000) -> list[tuple[NormalizedMarket, NormalizedMarket]]:
        pairs: list[tuple[NormalizedMarket, NormalizedMarket]] = []
        seen: set[tuple[str, str]] = set()

        by_event: dict[str, list[NormalizedMarket]] = {}
        for market in markets:
            by_event.setdefault(market.event_id, []).append(market)

        # Pass 1: same event pairs (highest priority)
        for event_markets in by_event.values():
            for left, right in combinations(event_markets, 2):
                key = tuple(sorted((left.market_id, right.market_id)))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((left, right))
                if len(pairs) >= max_pairs:
                    return pairs

        # Pass 2: same category, token overlap, same resolution month
        by_category: dict[str, list[NormalizedMarket]] = {}
        for market in markets:
            by_category.setdefault(market.category, []).append(market)

        for category_markets in by_category.values():
            for left, right in combinations(category_markets, 2):
                key = tuple(sorted((left.market_id, right.market_id)))
                if key in seen:
                    continue

                if not self._within_resolution_window(left, right):
                    continue

                left_tokens = extract_keywords(left.question)
                right_tokens = extract_keywords(right.question)
                overlap = len(left_tokens & right_tokens)
                sim = title_similarity(normalize_title(left.question), normalize_title(right.question))
                if overlap < self.min_token_overlap and sim < self.min_similarity:
                    continue

                seen.add(key)
                pairs.append((left, right))
                if len(pairs) >= max_pairs:
                    return pairs

        return pairs


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
    """Live monitor that wires Gamma polling + CLOB WebSocket stream into the engine."""

    def __init__(
        self,
        *,
        engine: ConstraintArbEngine,
        max_pages: int = 5,
        page_limit: int = 200,
        max_pairs: int = 1500,
        scan_interval_seconds: int = 60,
        market_refresh_seconds: int = 300,
    ) -> None:
        self.engine = engine
        self.max_pages = max_pages
        self.page_limit = page_limit
        self.max_pairs = max_pairs
        self.scan_interval_seconds = max(1, scan_interval_seconds)
        self.market_refresh_seconds = max(15, market_refresh_seconds)

        self._market_tokens: dict[str, tuple[str, str]] = {}
        self._last_market_refresh_ts = 0

        self._stream = None
        self._stream_loop: asyncio.AbstractEventLoop | None = None
        self._stream_thread: threading.Thread | None = None
        self._stream_ready = threading.Event()

    @property
    def stream_enabled(self) -> bool:
        return TradeStreamManager is not None

    def _build_token_map(self, raw_markets: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
        token_map: dict[str, tuple[str, str]] = {}
        for raw in raw_markets:
            market_id = _extract_market_id(raw)
            if not market_id:
                continue
            yes_token, no_token = parse_clob_token_ids(raw.get("clobTokenIds"))
            token_map[market_id] = (yes_token, no_token)
        return token_map

    def _seed_quotes_from_gamma(self, raw_markets: Sequence[Mapping[str, Any]]) -> None:
        now_ts = _now_ts()
        for raw in raw_markets:
            market_id = _extract_market_id(raw)
            if not market_id:
                continue
            yes_bid, yes_ask = _extract_yes_quote(raw)
            self.engine.update_quote(
                market_id=market_id,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                updated_ts=now_ts,
            )

    def refresh_markets(self, *, force: bool = False) -> int:
        now = _now_ts()
        if not force and now - self._last_market_refresh_ts < self.market_refresh_seconds:
            return 0

        raw_markets = fetch_gamma_markets(
            max_pages=self.max_pages,
            page_limit=self.page_limit,
            include_closed=False,
        )
        if not raw_markets:
            return 0

        self.engine.register_markets(raw_markets)
        self._seed_quotes_from_gamma(raw_markets)
        self._market_tokens = self._build_token_map(raw_markets)
        self._last_market_refresh_ts = now

        if self._stream is None:
            self._start_stream()
        else:
            self._update_stream_subscriptions()

        return len(raw_markets)

    def _start_stream(self) -> None:
        if TradeStreamManager is None:
            logger.warning("TradeStreamManager not available; running without live CLOB stream")
            return

        all_tokens = [tok for pair in self._market_tokens.values() for tok in pair if tok]
        manager = TradeStreamManager(token_ids=sorted(set(all_tokens)))
        self._stream = manager

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            self._stream_loop = loop
            asyncio.set_event_loop(loop)
            self._stream_ready.set()
            try:
                loop.run_until_complete(manager.start())
            finally:
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                except Exception:
                    pass
                loop.close()

        self._stream_thread = threading.Thread(target=_runner, name="constraint-arb-ws", daemon=True)
        self._stream_thread.start()
        self._stream_ready.wait(timeout=5)

    def _update_stream_subscriptions(self) -> None:
        if self._stream is None:
            return
        known = set(getattr(self._stream, "token_ids", []))
        for pair in self._market_tokens.values():
            for token_id in pair:
                if token_id and token_id not in known:
                    self._stream.add_token(token_id)
                    known.add(token_id)

    def _update_quotes_from_stream(self) -> int:
        if self._stream is None:
            return 0

        updated = 0
        now_ts = _now_ts()
        for market_id, (yes_token, no_token) in self._market_tokens.items():
            yes_bid = None
            yes_ask = None
            no_bid = None
            no_ask = None

            if yes_token:
                yes_book = self._stream.get_book(yes_token)
                if yes_book and yes_book.bids and yes_book.asks:
                    yes_bid = _clamp_price(yes_book.bids[0].price)
                    yes_ask = _clamp_price(yes_book.asks[0].price)

            if no_token:
                no_book = self._stream.get_book(no_token)
                if no_book and no_book.bids and no_book.asks:
                    no_bid = _clamp_price(no_book.bids[0].price)
                    no_ask = _clamp_price(no_book.asks[0].price)

            if yes_bid is None or yes_ask is None:
                if no_bid is not None and no_ask is not None:
                    yes_bid = _clamp_price(1.0 - no_ask)
                    yes_ask = _clamp_price(1.0 - no_bid)

            if yes_bid is None or yes_ask is None:
                continue
            if yes_ask < yes_bid:
                yes_bid, yes_ask = yes_ask, yes_bid

            self.engine.update_quote(
                market_id=market_id,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                updated_ts=now_ts,
            )
            updated += 1

        return updated

    def _collect_vpin(self) -> dict[str, float]:
        if self._stream is None:
            return {}

        vpin: dict[str, float] = {}
        for market_id, (yes_token, no_token) in self._market_tokens.items():
            vals: list[float] = []
            if yes_token:
                vals.append(_safe_float(self._stream.vpin.get_vpin(yes_token), 0.0))
            if no_token:
                vals.append(_safe_float(self._stream.vpin.get_vpin(no_token), 0.0))
            if vals:
                vpin[market_id] = max(vals)
        return vpin

    def run_cycle(self, *, force_market_refresh: bool = False) -> dict[str, int]:
        markets_refreshed = self.refresh_markets(force=force_market_refresh)
        ws_quotes_updated = self._update_quotes_from_stream()

        debate = getattr(self.engine.classifier, "debate_fallback", None)
        if debate is not None and hasattr(debate, "reset_budget"):
            debate.reset_budget()

        edges = self.engine.build_constraint_graph(max_pairs=self.max_pairs)
        vpin_by_id = self._collect_vpin()
        sum_violations = self.engine.scan_sum_violations(vpin_by_id=vpin_by_id)
        graph_violations = self.engine.scan_graph_violations(vpin_by_id=vpin_by_id)

        summary = {
            "markets_refreshed": markets_refreshed,
            "ws_quotes_updated": ws_quotes_updated,
            "edges_built": len(edges),
            "sum_violations": len(sum_violations),
            "graph_violations": len(graph_violations),
        }
        logger.info(
            "Constraint cycle: refreshed=%s ws_quotes=%s edges=%s sum=%s graph=%s",
            summary["markets_refreshed"],
            summary["ws_quotes_updated"],
            summary["edges_built"],
            summary["sum_violations"],
            summary["graph_violations"],
        )
        return summary

    def run(self, *, once: bool = False, max_cycles: int | None = None) -> list[dict[str, int]]:
        summaries: list[dict[str, int]] = []

        cycles = 0
        try:
            while True:
                cycles += 1
                force_refresh = cycles == 1
                cycle_summary = self.run_cycle(force_market_refresh=force_refresh)
                summaries.append(cycle_summary)
                if force_refresh and cycle_summary["markets_refreshed"] == 0:
                    logger.warning("No markets loaded from Gamma; aborting runtime loop")
                    break
                if once:
                    break
                if max_cycles is not None and cycles >= max_cycles:
                    break
                time.sleep(self.scan_interval_seconds)
        finally:
            self.stop()
        return summaries

    def stop(self) -> None:
        if self._stream is None or self._stream_loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._stream.stop(), self._stream_loop)
            fut.result(timeout=5)
        except Exception as exc:
            logger.debug("Error while stopping trade stream: %s", exc)
        if self._stream_thread:
            self._stream_thread.join(timeout=5)


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

    @property
    def quotes(self) -> dict[str, MarketQuote]:
        return dict(self._quotes)

    def register_markets(self, raw_markets: Sequence[Mapping[str, Any]]) -> list[NormalizedMarket]:
        normalized = [normalize_market(raw) for raw in raw_markets]
        self.register_normalized_markets(normalized)
        return normalized

    def register_normalized_markets(self, markets: Sequence[NormalizedMarket]) -> None:
        for market in markets:
            self._markets[market.market_id] = market
            self.inventory.register_market(market)

    def update_quote(
        self,
        *,
        market_id: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float | None = None,
        no_ask: float | None = None,
        updated_ts: int | None = None,
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
        )

    def get_quote(self, market_id: str) -> MarketQuote | None:
        return self._quotes.get(market_id)

    def _quote_fresh(self, quote: MarketQuote, now_ts: int) -> bool:
        return now_ts - quote.updated_ts <= self.stale_quote_seconds

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

                if not market.accepting_orders or not market.enable_order_book or not market.yes_token_id:
                    continue

                selected_outcomes[market.market_id] = outcome
                priced_markets.append((market, quote))
                spread = max(0.0, quote.yes_ask - quote.yes_bid)
                market_spreads[market.market_id] = float(spread)
                if spread > self.max_leg_spread:
                    liquidity_ok = False
                tick_size = max(market.tick_size, 0.001)
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
            if not gate.passed:
                continue

            total_yes_ask = sum(q.yes_ask for _, q in priced_markets)
            maker_sum_bid = sum(maker_targets.get(m.market_id, q.yes_bid) for m, q in priced_markets)
            n_legs = len(priced_markets)
            slippage_est = slippage_buffer * n_legs
            effective_fill_risk = float(fill_risk + (0.005 if not liquidity_ok else 0.0))
            vpin = self._event_vpin(event_id, [m.market_id for m, _ in priced_markets], vpin_by_id)

            if maker_sum_bid < self.buy_threshold:
                if not complete_basket:
                    continue
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
