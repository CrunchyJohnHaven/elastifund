#!/usr/bin/env python3
"""Feature-flagged integration helpers for A-6 and B-1 combinatorial lanes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping


DEFAULT_CONSTRAINT_DB_PATH = Path("data") / "constraint_arb.db"
COMBINATORIAL_SOURCE_KEYS = {"a6", "b1"}


def _env_bool(name: str, default: bool = False, *, env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, env: Mapping[str, str] | None = None) -> float:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int, *, env: Mapping[str, str] | None = None) -> int:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_json_array(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


@dataclass(frozen=True)
class SignalSourceMeta:
    key: str
    source_id: int
    tag: str
    confirmation_mode: str
    strategy_type: str = "predictive"


SOURCE_REGISTRY: dict[str, SignalSourceMeta] = {
    "llm": SignalSourceMeta("llm", 1, "Signal 1", "predictive"),
    "wallet_flow": SignalSourceMeta("wallet_flow", 2, "Signal 2", "predictive"),
    "lmsr": SignalSourceMeta("lmsr", 3, "Signal 3", "predictive"),
    "cross_platform_arb": SignalSourceMeta("cross_platform_arb", 4, "Signal 4", "predictive"),
    "a6": SignalSourceMeta("a6", 5, "Signal 5 / A-6", "bypass", "combinatorial"),
    "b1": SignalSourceMeta("b1", 6, "Signal 6 / B-1", "bypass", "combinatorial"),
    "lead_lag": SignalSourceMeta("lead_lag", 7, "Signal 7", "predictive"),
    "unknown": SignalSourceMeta("unknown", 0, "Unknown", "predictive"),
}

SOURCE_ALIASES = {
    "a6_constraint_arb": "a6",
    "a6_sum": "a6",
    "same_event_sum": "a6",
    "signal_5": "a6",
    "b1_constraint_arb": "b1",
    "constraint_graph": "b1",
    "graph_relation": "b1",
    "signal_6": "b1",
}


def canonical_source_key(source: str | None) -> str:
    if not source:
        return "unknown"
    normalized = str(source).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in SOURCE_REGISTRY:
        return normalized
    return SOURCE_ALIASES.get(normalized, normalized if normalized in SOURCE_REGISTRY else "unknown")


def attach_signal_source_metadata(signal: dict[str, Any]) -> dict[str, Any]:
    key = canonical_source_key(
        str(signal.get("source_key") or signal.get("source") or signal.get("relation_type") or "unknown")
    )
    meta = SOURCE_REGISTRY.get(key, SOURCE_REGISTRY["unknown"])
    signal["source"] = meta.key
    signal["source_key"] = meta.key
    signal["source_id"] = meta.source_id
    signal["source_tag"] = meta.tag
    signal["confirmation_mode"] = meta.confirmation_mode
    signal["strategy_type"] = meta.strategy_type
    return signal


def is_combinatorial_signal(signal: Mapping[str, Any]) -> bool:
    source_key = canonical_source_key(str(signal.get("source_key") or signal.get("source") or ""))
    if source_key in COMBINATORIAL_SOURCE_KEYS:
        return True
    return str(signal.get("strategy_type") or "").lower() == "combinatorial"


@dataclass(frozen=True)
class CombinatorialConfig:
    enable_a6_shadow: bool = False
    enable_a6_live: bool = False
    enable_b1_shadow: bool = False
    enable_b1_live: bool = False
    a6_buy_threshold: float = 0.97
    a6_unwind_threshold: float = 1.03
    b1_implication_threshold: float = 0.03
    stale_book_max_age_seconds: int = 45
    fill_timeout_ms: int = 3000
    cancel_replace_count: int = 1
    max_notional_per_leg_usd: float = 5.0
    arb_budget_usd: float = 100.0
    merge_min_notional_usd: float = 20.0
    shadow_promotion_min_signals: int = 20
    required_capture_rate: float = 0.50
    required_classification_accuracy: float = 0.80
    max_false_positive_rate: float = 0.05
    max_consecutive_rollbacks: int = 3
    constraint_db_path: Path = DEFAULT_CONSTRAINT_DB_PATH
    embedded_a6_scanner_enabled: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "CombinatorialConfig":
        source = env or os.environ
        return cls(
            enable_a6_shadow=_env_bool("ENABLE_A6_SHADOW", False, env=source),
            enable_a6_live=_env_bool("ENABLE_A6_LIVE", False, env=source),
            enable_b1_shadow=_env_bool("ENABLE_B1_SHADOW", False, env=source),
            enable_b1_live=_env_bool("ENABLE_B1_LIVE", False, env=source),
            a6_buy_threshold=_env_float("JJ_A6_BUY_THRESHOLD", 0.97, env=source),
            a6_unwind_threshold=_env_float("JJ_A6_UNWIND_THRESHOLD", 1.03, env=source),
            b1_implication_threshold=_env_float("JJ_B1_IMPLICATION_THRESHOLD", 0.03, env=source),
            stale_book_max_age_seconds=_env_int(
                "JJ_COMBINATORIAL_STALE_BOOK_MAX_AGE_SECONDS", 45, env=source
            ),
            fill_timeout_ms=_env_int("JJ_COMBINATORIAL_FILL_TIMEOUT_MS", 3000, env=source),
            cancel_replace_count=_env_int("JJ_COMBINATORIAL_CANCEL_REPLACE_COUNT", 1, env=source),
            max_notional_per_leg_usd=_env_float(
                "JJ_COMBINATORIAL_MAX_NOTIONAL_PER_LEG_USD", 5.0, env=source
            ),
            arb_budget_usd=_env_float("JJ_COMBINATORIAL_ARB_BUDGET_USD", 100.0, env=source),
            merge_min_notional_usd=_env_float("JJ_COMBINATORIAL_MERGE_MIN_NOTIONAL_USD", 20.0, env=source),
            shadow_promotion_min_signals=_env_int(
                "JJ_COMBINATORIAL_PROMOTION_MIN_SIGNALS", 20, env=source
            ),
            required_capture_rate=_env_float(
                "JJ_COMBINATORIAL_REQUIRED_CAPTURE_RATE", 0.50, env=source
            ),
            required_classification_accuracy=_env_float(
                "JJ_COMBINATORIAL_REQUIRED_CLASSIFICATION_ACCURACY", 0.80, env=source
            ),
            max_false_positive_rate=_env_float(
                "JJ_COMBINATORIAL_MAX_FALSE_POSITIVE_RATE", 0.05, env=source
            ),
            max_consecutive_rollbacks=_env_int(
                "JJ_COMBINATORIAL_MAX_CONSECUTIVE_ROLLBACKS", 3, env=source
            ),
            constraint_db_path=Path(
                source.get("JJ_CONSTRAINT_ARB_DB_PATH", str(DEFAULT_CONSTRAINT_DB_PATH))
            ),
            embedded_a6_scanner_enabled=_env_bool(
                "JJ_A6_EMBEDDED_SHADOW_SCANNER",
                True,
                env=source,
            ),
        )

    def any_enabled(self) -> bool:
        return any(
            (
                self.enable_a6_shadow,
                self.enable_a6_live,
                self.enable_b1_shadow,
                self.enable_b1_live,
            )
        )

    def shadow_enabled(self, lane: str) -> bool:
        return self.enable_a6_shadow if lane == "a6" else self.enable_b1_shadow

    def live_enabled(self, lane: str) -> bool:
        return self.enable_a6_live if lane == "a6" else self.enable_b1_live


def _direction_for_relation(relation_type: str, action: str) -> str:
    if relation_type == "same_event_sum":
        return "buy_yes_basket" if action == "buy_yes_basket" else "unwind_basket"
    if relation_type == "A_implies_B":
        return "buy_no_a_buy_yes_b"
    if relation_type == "B_implies_A":
        return "buy_yes_a_buy_no_b"
    if relation_type == "mutually_exclusive":
        return "buy_no_pair"
    return action or relation_type


def _live_eligible_for_relation(
    lane: str,
    relation_type: str,
    action: str,
    details: Mapping[str, Any],
) -> bool:
    if action == "vpin_veto":
        return False
    if lane == "a6":
        return action == "buy_yes_basket" and bool(details.get("complete_basket", False))
    return relation_type in {"A_implies_B", "B_implies_A", "mutually_exclusive"}


@dataclass(frozen=True)
class CombinatorialOpportunity:
    basket_id: str
    violation_id: str
    lane: str
    relation_type: str
    action: str
    event_id: str
    market_ids: tuple[str, ...]
    theoretical_edge: float
    semantic_confidence: float
    detected_at_ts: int
    details: dict[str, Any]
    live_eligible: bool
    resolution_gate_status: str
    classification_accuracy: float | None
    estimated_budget_usd: float
    direction: str

    @classmethod
    def from_violation_row(
        cls,
        row: Mapping[str, Any],
        config: CombinatorialConfig,
    ) -> "CombinatorialOpportunity" | None:
        relation_type = str(row.get("relation_type") or "").strip()
        if relation_type == "same_event_sum":
            lane = "a6"
        elif relation_type in {"A_implies_B", "B_implies_A", "mutually_exclusive", "complementary", "subset"}:
            lane = "b1"
        else:
            return None

        if not (config.shadow_enabled(lane) or config.live_enabled(lane)):
            return None

        market_ids = _parse_json_array(row.get("market_ids_json"))
        details = _parse_json_object(row.get("details_json"))
        action = str(row.get("action") or "").strip()
        direction = _direction_for_relation(relation_type, action)
        market_count = len(market_ids) or max(1, int(_safe_float(details.get("legs"), 1.0)))
        estimated_budget_usd = round(config.max_notional_per_leg_usd * market_count, 2)
        classification_accuracy = _safe_optional_float(details.get("classification_accuracy"))
        live_eligible = _live_eligible_for_relation(lane, relation_type, action, details)
        gate_reasons = details.get("gate_reasons") or []
        resolution_gate_status = "passed" if not gate_reasons else f"passed:{','.join(map(str, gate_reasons))}"

        return cls(
            basket_id=str(row.get("violation_id") or row.get("basket_id") or ""),
            violation_id=str(row.get("violation_id") or ""),
            lane=lane,
            relation_type=relation_type,
            action=action,
            event_id=str(row.get("event_id") or ""),
            market_ids=market_ids,
            theoretical_edge=_safe_float(row.get("gross_edge"), 0.0),
            semantic_confidence=_safe_float(row.get("semantic_confidence"), 0.0),
            detected_at_ts=int(_safe_float(row.get("detected_at_ts"), 0.0)),
            details=details,
            live_eligible=live_eligible,
            resolution_gate_status=resolution_gate_status,
            classification_accuracy=classification_accuracy,
            estimated_budget_usd=estimated_budget_usd,
            direction=direction,
        )

    def to_signal(self) -> dict[str, Any]:
        if self.lane == "a6":
            question = f"A-6 YES basket {self.event_id} ({len(self.market_ids)} legs)"
        else:
            question = f"B-1 {self.relation_type} {', '.join(self.market_ids[:2])}"

        signal = {
            "basket_id": self.basket_id,
            "violation_id": self.violation_id,
            "event_id": self.event_id,
            "market_id": self.market_ids[0] if self.market_ids else self.event_id,
            "market_ids": list(self.market_ids),
            "question": question,
            "direction": self.direction,
            "edge": self.theoretical_edge,
            "theoretical_edge": self.theoretical_edge,
            "confidence": self.semantic_confidence,
            "semantic_confidence": self.semantic_confidence,
            "estimated_prob": None,
            "reasoning": self.action,
            "source": self.lane,
            "relation_type": self.relation_type,
            "resolution_gate_status": self.resolution_gate_status,
            "classification_accuracy": self.classification_accuracy,
            "estimated_budget_usd": self.estimated_budget_usd,
            "live_eligible": self.live_eligible,
            "bypass_confirmation": True,
            "details": dict(self.details),
        }
        return attach_signal_source_metadata(signal)


@dataclass(frozen=True)
class CombinatorialRiskDecision:
    allow: bool
    reason: str
    reserved_budget_usd: float = 0.0
    kill_trigger: str | None = None


def evaluate_combinatorial_risk(
    opportunity: CombinatorialOpportunity,
    *,
    config: CombinatorialConfig,
    daily_pnl: float,
    max_daily_loss_usd: float,
    open_positions: int,
    open_baskets: int,
    max_open_positions: int,
    arb_budget_in_use_usd: float,
) -> CombinatorialRiskDecision:
    if daily_pnl <= -abs(max_daily_loss_usd):
        return CombinatorialRiskDecision(
            allow=False,
            reason="daily_loss_limit",
            kill_trigger="daily_loss_limit",
        )

    if open_positions + open_baskets >= max_open_positions:
        return CombinatorialRiskDecision(
            allow=False,
            reason="max_open_positions",
            kill_trigger="max_open_positions",
        )

    if arb_budget_in_use_usd + opportunity.estimated_budget_usd > config.arb_budget_usd + 1e-9:
        return CombinatorialRiskDecision(
            allow=False,
            reason="arb_budget_exhausted",
            kill_trigger="arb_budget_exhausted",
        )

    return CombinatorialRiskDecision(
        allow=True,
        reason="ok",
        reserved_budget_usd=opportunity.estimated_budget_usd,
    )


class CombinatorialSignalStore:
    """Read normalized A-6/B-1 opportunities from the shared constraint-arb DB."""

    def __init__(self, db_path: str | Path = DEFAULT_CONSTRAINT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def poll_new_opportunities(
        self,
        *,
        since_ts: int,
        config: CombinatorialConfig,
        now_ts: int | None = None,
    ) -> list[CombinatorialOpportunity]:
        if not self.db_path.exists():
            return []

        now_ts = int(now_ts or time.time())
        min_detected_ts = max(0, now_ts - max(1, int(config.stale_book_max_age_seconds)))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    violation_id,
                    event_id,
                    relation_type,
                    market_ids_json,
                    semantic_confidence,
                    gross_edge,
                    action,
                    details_json,
                    detected_at_ts
                FROM constraint_violations
                WHERE detected_at_ts > ?
                  AND detected_at_ts >= ?
                ORDER BY detected_at_ts ASC, violation_id ASC
                """,
                (int(since_ts), min_detected_ts),
            ).fetchall()

        seen: set[str] = set()
        opportunities: list[CombinatorialOpportunity] = []
        for row in rows:
            payload = dict(row)
            opportunity = CombinatorialOpportunity.from_violation_row(payload, config)
            if not opportunity:
                continue
            if opportunity.violation_id in seen:
                continue
            seen.add(opportunity.violation_id)
            opportunities.append(opportunity)
        return opportunities
