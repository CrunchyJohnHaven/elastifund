#!/usr/bin/env python3
"""Score tightly bounded BTC5 paper candidates around the current champion edge.

The goal is not to invent a brand-new strategy family. It is to keep a narrow
mutation loop alive around the currently best-known BTC5 slice until one
candidate shows paper-quality evidence worth forwarding into the broader
autoresearch stack.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.btc_5min_maker import (  # noqa: E402
    OBSERVED_BTC5_LOSS_CLUSTERS,
    _btc5_cluster_price_bucket,
    _btc5_delta_bucket,
    _btc5_session_bucket,
)

DEFAULT_DB_PATH = ROOT / "data" / "btc_5min_maker.db"
DEFAULT_STATE_IMPROVEMENT = ROOT / "reports" / "state_improvement_latest.json"
DEFAULT_FAST_MARKET_SEARCH = ROOT / "reports" / "fast_market_search" / "latest.json"
DEFAULT_CURRENT_PROBE = ROOT / "reports" / "btc5_autoresearch_current_probe" / "latest.json"
DEFAULT_OUTPUT_JSON = ROOT / "reports" / "autoresearch" / "btc5_micro_edge" / "latest.json"
DEFAULT_OUTPUT_MD = ROOT / "reports" / "autoresearch" / "btc5_micro_edge" / "latest.md"

SESSION_FALLBACKS = ("open_et", "midday_et", "hour_et_11", "hour_et_04")
DELTA_GRID = (0.00002, 0.00005, 0.00010, 0.00015)

CHAMPION_PATTERN = re.compile(
    r"grid_d(?P<delta>0\.\d+)_up(?P<up>0\.\d+)_down(?P<down>0\.\d+)",
    re.IGNORECASE,
)
SESSION_PATTERN = re.compile(
    r"__(?P<session>(?:open_et|midday_et|late_et|hour_et_\d{2}))__grid_d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateProfile:
    session_name: str
    max_abs_delta: float
    up_max_buy_price: float
    down_max_buy_price: float
    source: str = "micro_edge_search"
    candidate_id_override: str | None = None
    historical_ranking_score: float | None = None
    historical_validation_rows: int | None = None
    evidence_band: str | None = None
    deployment_class: str | None = None

    @property
    def candidate_id(self) -> str:
        if self.candidate_id_override:
            return str(self.candidate_id_override)
        return (
            f"btc5:{self.source}__{self.session_name}"
            f"__grid_d{self.max_abs_delta:0.5f}"
            f"_up{self.up_max_buy_price:0.2f}"
            f"_down{self.down_max_buy_price:0.2f}"
        )


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_candidate(candidate_id: str) -> CandidateProfile | None:
    text = str(candidate_id or "").strip()
    match = CHAMPION_PATTERN.search(text)
    session_match = SESSION_PATTERN.search(text)
    if not match or not session_match:
        return None
    return CandidateProfile(
        session_name=str(session_match.group("session")).strip().lower(),
        max_abs_delta=float(match.group("delta")),
        up_max_buy_price=float(match.group("up")),
        down_max_buy_price=float(match.group("down")),
        source="champion_seed",
    )


def _champion_from_state_improvement(payload: dict[str, Any]) -> CandidateProfile | None:
    champion_id = (
        (
            ((payload.get("strategy_recommendations") or {}).get("btc5_candidate_recovery") or {})
            .get("champion_lane")
            or {}
        ).get("top_candidate_id")
        or ""
    )
    return _parse_candidate(str(champion_id))


def _policy_to_profile(
    policy: dict[str, Any],
    *,
    source: str,
    candidate_id_override: str | None = None,
    historical_ranking_score: float | None = None,
    historical_validation_rows: int | None = None,
    evidence_band: str | None = None,
    deployment_class: str | None = None,
) -> CandidateProfile | None:
    session_name = str(policy.get("name") or "").strip().lower()
    if not session_name:
        return None
    max_abs_delta = _safe_float(policy.get("max_abs_delta"), None)
    up_max_buy_price = _safe_float(policy.get("up_max_buy_price"), None)
    down_max_buy_price = _safe_float(policy.get("down_max_buy_price"), None)
    if (
        max_abs_delta is None
        or up_max_buy_price is None
        or down_max_buy_price is None
        or max_abs_delta <= 0.0
    ):
        return None
    return CandidateProfile(
        session_name=session_name,
        max_abs_delta=max_abs_delta,
        up_max_buy_price=up_max_buy_price,
        down_max_buy_price=down_max_buy_price,
        source=source,
        candidate_id_override=candidate_id_override,
        historical_ranking_score=historical_ranking_score,
        historical_validation_rows=historical_validation_rows,
        evidence_band=evidence_band,
        deployment_class=deployment_class,
    )


def _fast_market_seed_candidates(payload: dict[str, Any], top_k: int) -> list[CandidateProfile]:
    ranked = payload.get("ranked_candidates")
    if not isinstance(ranked, list):
        return []
    candidates: list[CandidateProfile] = []
    for item in ranked[: max(1, int(top_k))]:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        ranking_score = _safe_float(item.get("ranking_score"), 0.0)
        validation_rows = _safe_int((item.get("validation_counts") or {}).get("validation_live_filled_rows"), 0)
        evidence_band = str(item.get("evidence_band") or "").strip() or None
        deployment_class = str(item.get("deployment_class") or "").strip() or None
        session_policy = item.get("session_policy")
        if isinstance(session_policy, list) and session_policy:
            for policy in session_policy:
                if not isinstance(policy, dict):
                    continue
                profile = _policy_to_profile(
                    policy,
                    source="fast_market_search",
                    candidate_id_override=candidate_id,
                    historical_ranking_score=ranking_score,
                    historical_validation_rows=validation_rows,
                    evidence_band=evidence_band,
                    deployment_class=deployment_class,
                )
                if profile is not None:
                    candidates.append(profile)
            continue
        parsed = _parse_candidate(candidate_id)
        if parsed is None:
            continue
        candidates.append(
            CandidateProfile(
                session_name=parsed.session_name,
                max_abs_delta=parsed.max_abs_delta,
                up_max_buy_price=parsed.up_max_buy_price,
                down_max_buy_price=parsed.down_max_buy_price,
                source="fast_market_search",
                candidate_id_override=candidate_id,
                historical_ranking_score=ranking_score,
                historical_validation_rows=validation_rows,
                evidence_band=evidence_band,
                deployment_class=deployment_class,
            )
        )
    return candidates


def _current_probe_seed_candidates(payload: dict[str, Any], fallback_up: float, fallback_down: float) -> list[CandidateProfile]:
    candidates: list[CandidateProfile] = []
    for policy in payload.get("recommended_session_policy") or []:
        if not isinstance(policy, dict):
            continue
        profile = _policy_to_profile(policy, source="current_probe_recommendation")
        if profile is not None:
            candidates.append(profile)

    best_candidate = payload.get("best_candidate")
    if isinstance(best_candidate, dict):
        profile = dict(best_candidate.get("profile") or {})
        session_name = str(profile.get("session_name") or "").strip().lower()
        if session_name and _safe_float(profile.get("max_abs_delta"), None):
            candidates.append(
                CandidateProfile(
                    session_name=session_name,
                    max_abs_delta=float(profile["max_abs_delta"]),
                    up_max_buy_price=float(_safe_float(profile.get("up_max_buy_price"), fallback_up) or fallback_up),
                    down_max_buy_price=float(_safe_float(profile.get("down_max_buy_price"), fallback_down) or fallback_down),
                    source="current_probe_best",
                    historical_validation_rows=_safe_int(
                        ((best_candidate.get("scoring") or {}).get("validation_live_filled_rows")),
                        0,
                    ),
                    evidence_band=str(((best_candidate.get("scoring") or {}).get("evidence_band")) or "").strip() or None,
                )
            )
    return candidates


def _recent_profitable_local_candidates(
    rows: list[dict[str, Any]],
    *,
    champion: CandidateProfile,
    top_k: int,
) -> list[CandidateProfile]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "up_prices": [],
            "down_prices": [],
            "deltas": [],
            "fills": 0,
            "pnl_usd": 0.0,
        }
    )
    for row in rows:
        if _safe_int(row.get("filled"), 0) != 1:
            continue
        pnl_usd = _safe_float(row.get("pnl_usd"), 0.0) or 0.0
        if pnl_usd <= 0.0 or _loss_cluster_key(row) in OBSERVED_BTC5_LOSS_CLUSTERS:
            continue
        features = _row_features(row)
        session_name = str(features["session_name"])
        if not session_name:
            continue
        group = grouped[session_name]
        direction = str(row.get("direction") or "").strip().upper()
        order_price = _safe_float(row.get("order_price"), None)
        abs_delta = abs(_safe_float(row.get("delta"), 0.0) or 0.0)
        if direction == "UP" and order_price is not None:
            group["up_prices"].append(order_price)
        elif direction == "DOWN" and order_price is not None:
            group["down_prices"].append(order_price)
        if abs_delta > 0.0:
            group["deltas"].append(abs_delta)
        group["fills"] = int(group["fills"]) + 1
        group["pnl_usd"] = float(group["pnl_usd"]) + pnl_usd

    ranked_sessions = sorted(
        grouped.items(),
        key=lambda item: (float(item[1]["pnl_usd"]), int(item[1]["fills"])),
        reverse=True,
    )[: max(1, int(top_k))]
    candidates: list[CandidateProfile] = []
    for session_name, item in ranked_sessions:
        up_max_buy_price = max(item["up_prices"]) if item["up_prices"] else champion.up_max_buy_price
        down_max_buy_price = max(item["down_prices"]) if item["down_prices"] else champion.down_max_buy_price
        max_abs_delta = max(item["deltas"]) if item["deltas"] else champion.max_abs_delta
        candidates.append(
            CandidateProfile(
                session_name=session_name,
                max_abs_delta=max_abs_delta,
                up_max_buy_price=up_max_buy_price,
                down_max_buy_price=down_max_buy_price,
                source="recent_profitable_local",
                historical_validation_rows=int(item["fills"]),
            )
        )
    return candidates


def _candidate_key(candidate: CandidateProfile) -> tuple[str, float, float, float]:
    return (
        str(candidate.session_name),
        round(float(candidate.max_abs_delta), 8),
        round(float(candidate.up_max_buy_price), 4),
        round(float(candidate.down_max_buy_price), 4),
    )


def _candidate_grid(champion: CandidateProfile, extra_sessions: Iterable[str]) -> list[CandidateProfile]:
    sessions: list[str] = []
    for session_name in (champion.session_name, *extra_sessions):
        normalized = str(session_name or "").strip().lower()
        if normalized and normalized not in sessions:
            sessions.append(normalized)

    up_grid = sorted(
        {
            round(value, 2)
            for value in (
                champion.up_max_buy_price - 0.02,
                champion.up_max_buy_price - 0.01,
                champion.up_max_buy_price,
                champion.up_max_buy_price + 0.01,
            )
            if 0.45 <= value <= 0.55
        }
    )
    down_grid = sorted(
        {
            round(value, 2)
            for value in (
                champion.down_max_buy_price - 0.01,
                champion.down_max_buy_price,
                champion.down_max_buy_price + 0.01,
            )
            if 0.45 <= value <= 0.55
        }
    )

    candidates: list[CandidateProfile] = [
        CandidateProfile(
            session_name=champion.session_name,
            max_abs_delta=champion.max_abs_delta,
            up_max_buy_price=champion.up_max_buy_price,
            down_max_buy_price=champion.down_max_buy_price,
            source="champion_seed",
        )
    ]
    seen = {_candidate_key(candidates[0])}

    for session_name in sessions:
        for max_abs_delta in DELTA_GRID:
            for up_price in up_grid:
                for down_price in down_grid:
                    profile = CandidateProfile(
                        session_name=session_name,
                        max_abs_delta=max_abs_delta,
                        up_max_buy_price=up_price,
                        down_max_buy_price=down_price,
                    )
                    key = _candidate_key(profile)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(profile)
    return candidates


def _merge_candidates(*candidate_lists: Iterable[CandidateProfile]) -> list[CandidateProfile]:
    ranked: dict[tuple[str, float, float, float], CandidateProfile] = {}
    for candidate_list in candidate_lists:
        for candidate in candidate_list:
            key = _candidate_key(candidate)
            current = ranked.get(key)
            if current is None:
                ranked[key] = candidate
                continue
            current_rows = _safe_int(current.historical_validation_rows, 0)
            candidate_rows = _safe_int(candidate.historical_validation_rows, 0)
            current_score = _safe_float(current.historical_ranking_score, 0.0) or 0.0
            candidate_score = _safe_float(candidate.historical_ranking_score, 0.0) or 0.0
            if (candidate_rows, candidate_score) > (current_rows, current_score):
                ranked[key] = candidate
    return list(ranked.values())


def _load_rows(db_path: Path, row_limit: int) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT
                window_start_ts,
                slug,
                direction,
                delta,
                order_price,
                trade_size_usd,
                shares,
                filled,
                order_status,
                COALESCE(realized_pnl_usd, pnl_usd, 0) AS pnl_usd
            FROM window_trades
            ORDER BY window_start_ts DESC, id DESC
        """
        params: tuple[Any, ...] = ()
        if row_limit > 0:
            query += " LIMIT ?"
            params = (int(row_limit),)
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def _row_features(row: dict[str, Any]) -> dict[str, Any]:
    session_name = str(row.get("session_name") or "").strip().lower()
    price_bucket = str(row.get("price_bucket") or "").strip()
    delta_bucket = str(row.get("delta_bucket") or "").strip()
    window_start_ts = int(_safe_float(row.get("window_start_ts"), 0.0) or 0)
    order_price = _safe_float(row.get("order_price"), None)
    delta = _safe_float(row.get("delta"), 0.0) or 0.0
    return {
        "session_name": session_name or _btc5_session_bucket(window_start_ts),
        "price_bucket": price_bucket or _btc5_cluster_price_bucket(order_price),
        "delta_bucket": delta_bucket or _btc5_delta_bucket(delta),
        "abs_delta": abs(delta),
    }


def _row_matches(candidate: CandidateProfile, row: dict[str, Any]) -> bool:
    direction = str(row.get("direction") or "").strip().upper()
    if direction not in {"UP", "DOWN"}:
        return False
    features = _row_features(row)
    if features["session_name"] != candidate.session_name:
        return False
    if float(features["abs_delta"]) > float(candidate.max_abs_delta):
        return False
    order_price = _safe_float(row.get("order_price"), None)
    if order_price is None or order_price <= 0.0 or order_price >= 1.0:
        return False
    if direction == "UP":
        return order_price <= candidate.up_max_buy_price
    return order_price <= candidate.down_max_buy_price


def _loss_cluster_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    features = _row_features(row)
    return (
        str(features["session_name"]),
        str(row.get("direction") or "").strip().upper(),
        str(features["price_bucket"]),
        str(features["delta_bucket"]),
    )


def _evaluate_candidate(candidate: CandidateProfile, rows: list[dict[str, Any]], min_filled: int) -> dict[str, Any]:
    session_rows = [row for row in rows if _row_features(row)["session_name"] == candidate.session_name]
    matched = [row for row in session_rows if _row_matches(candidate, row)]
    filled_rows = [row for row in matched if int(_safe_float(row.get("filled"), 0.0) or 0) == 1]
    skip_rows = [row for row in matched if str(row.get("order_status") or "").startswith("skip_")]
    priced_rows = [
        row
        for row in session_rows
        if str(row.get("direction") or "").strip().upper() in {"UP", "DOWN"}
        and (_safe_float(row.get("order_price"), None) is not None)
    ]
    price_eligible_rows = []
    delta_eligible_rows = []
    for row in session_rows:
        direction = str(row.get("direction") or "").strip().upper()
        order_price = _safe_float(row.get("order_price"), None)
        features = _row_features(row)
        if float(features["abs_delta"]) <= float(candidate.max_abs_delta):
            delta_eligible_rows.append(row)
        if direction == "UP" and order_price is not None and order_price <= candidate.up_max_buy_price:
            price_eligible_rows.append(row)
        elif direction == "DOWN" and order_price is not None and order_price <= candidate.down_max_buy_price:
            price_eligible_rows.append(row)
    pnl_usd = round(sum(_safe_float(row.get("pnl_usd"), 0.0) or 0.0 for row in filled_rows), 4)
    traded_notional_usd = round(sum(_safe_float(row.get("trade_size_usd"), 0.0) or 0.0 for row in filled_rows), 4)
    loss_cluster_hits = [row for row in filled_rows if _loss_cluster_key(row) in OBSERVED_BTC5_LOSS_CLUSTERS]
    loss_cluster_pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) or 0.0 for row in loss_cluster_hits), 4)
    wins = sum(1 for row in filled_rows if (_safe_float(row.get("pnl_usd"), 0.0) or 0.0) > 0.0)
    losses = sum(1 for row in filled_rows if (_safe_float(row.get("pnl_usd"), 0.0) or 0.0) < 0.0)
    fill_rate = (len(filled_rows) / len(matched)) if matched else 0.0
    skip_rate = (len(skip_rows) / len(matched)) if matched else 0.0
    session_skip_counter = Counter(str(row.get("order_status") or "unknown") for row in session_rows)
    guardrail_skip_counter = Counter(str(row.get("order_status") or "unknown") for row in matched)
    profit_per_fill = (pnl_usd / len(filled_rows)) if filled_rows else 0.0
    historical_validation_rows = _safe_int(candidate.historical_validation_rows, 0)
    historical_ranking_score = _safe_float(candidate.historical_ranking_score, 0.0) or 0.0
    exact_guardrail_ratio = (len(matched) / len(session_rows)) if session_rows else 0.0
    price_eligibility_ratio = (len(price_eligible_rows) / len(priced_rows)) if priced_rows else 0.0
    delta_eligibility_ratio = (len(delta_eligible_rows) / len(session_rows)) if session_rows else 0.0

    if len(filled_rows) < min_filled:
        if loss_cluster_hits:
            recommendation = "cluster_blocked"
        elif len(filled_rows) >= 1 and pnl_usd > 0:
            recommendation = "watch_candidate"
        elif historical_validation_rows >= 12 and len(delta_eligible_rows) == 0:
            recommendation = "inactive_recent_regime"
        elif historical_validation_rows >= 12 and (len(matched) >= 1 or len(price_eligible_rows) >= 3):
            recommendation = "watch_candidate"
        else:
            recommendation = "insufficient_fills"
    elif pnl_usd <= 0:
        recommendation = "non_positive_pnl"
    elif loss_cluster_hits:
        recommendation = "cluster_blocked"
    else:
        recommendation = "paper_candidate"

    score = round(
        (historical_ranking_score * 0.8)
        + (historical_validation_rows * 0.35)
        + (pnl_usd * 4.0)
        + (len(filled_rows) * 3.0)
        + (len(matched) * 1.2)
        + (profit_per_fill * 2.0)
        + (price_eligibility_ratio * 8.0)
        + (delta_eligibility_ratio * 10.0)
        + (exact_guardrail_ratio * 10.0)
        - (len(loss_cluster_hits) * 18.0)
        - (skip_rate * 5.0),
        6,
    )

    return {
        "candidate_id": candidate.candidate_id,
        "session_name": candidate.session_name,
        "max_abs_delta": candidate.max_abs_delta,
        "up_max_buy_price": candidate.up_max_buy_price,
        "down_max_buy_price": candidate.down_max_buy_price,
        "historical_ranking_score": round(historical_ranking_score, 6),
        "historical_validation_rows": historical_validation_rows,
        "evidence_band": candidate.evidence_band,
        "deployment_class": candidate.deployment_class,
        "session_rows": len(session_rows),
        "price_eligible_rows": len(price_eligible_rows),
        "delta_eligible_rows": len(delta_eligible_rows),
        "matched_rows": len(matched),
        "filled_rows": len(filled_rows),
        "wins": wins,
        "losses": losses,
        "fill_rate": round(fill_rate, 6),
        "skip_rate": round(skip_rate, 6),
        "exact_guardrail_ratio": round(exact_guardrail_ratio, 6),
        "price_eligibility_ratio": round(price_eligibility_ratio, 6),
        "delta_eligibility_ratio": round(delta_eligibility_ratio, 6),
        "pnl_usd": pnl_usd,
        "profit_per_fill_usd": round(profit_per_fill, 6),
        "traded_notional_usd": traded_notional_usd,
        "loss_cluster_hits": len(loss_cluster_hits),
        "loss_cluster_pnl_usd": loss_cluster_pnl,
        "top_session_statuses": [[label, count] for label, count in session_skip_counter.most_common(3)],
        "top_guardrail_statuses": [[label, count] for label, count in guardrail_skip_counter.most_common(3)],
        "recommendation": recommendation,
        "score": score,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    champion = payload.get("champion_seed") or {}
    lines = [
        "# BTC5 Micro Edge Paper Search",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Rows scanned: `{payload.get('rows_scanned', 0)}`",
        f"- Candidate count: `{payload.get('candidate_count', 0)}`",
        f"- Champion seed: `{champion.get('candidate_id') or 'unknown'}`",
        f"- Action: `{payload.get('action')}`",
        "",
    ]
    if payload.get("best_candidate"):
        best = payload["best_candidate"]
        lines.extend(
            [
                "## Best Candidate",
                "",
                f"- Candidate: `{best.get('candidate_id')}`",
                f"- Recommendation: `{best.get('recommendation')}`",
                f"- Score: `{best.get('score')}`",
                f"- Historical score: `{best.get('historical_ranking_score')}`",
                f"- PnL: `{best.get('pnl_usd')}`",
                f"- Session rows: `{best.get('session_rows')}`",
                f"- Price-eligible rows: `{best.get('price_eligible_rows')}`",
                f"- Delta-eligible rows: `{best.get('delta_eligible_rows')}`",
                f"- Filled rows: `{best.get('filled_rows')}`",
                f"- Loss cluster hits: `{best.get('loss_cluster_hits')}`",
                "",
            ]
        )
    lines.append("## Top Ranked")
    lines.append("")
    for item in payload.get("top_ranked", []):
        lines.append(
            f"- `{item['candidate_id']}` score=`{item['score']}` hist=`{item.get('historical_ranking_score', 0)}` "
            f"pnl=`{item['pnl_usd']}` fills=`{item['filled_rows']}` "
            f"guardrail=`{item.get('matched_rows', 0)}` rec=`{item['recommendation']}`"
        )
    lines.append("")
    lines.append("Paper ranking is triage evidence, not deploy permission.")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Local BTC5 SQLite path")
    parser.add_argument(
        "--state-improvement",
        default=str(DEFAULT_STATE_IMPROVEMENT),
        help="State improvement JSON used to seed the champion candidate",
    )
    parser.add_argument(
        "--fast-market-search",
        default=str(DEFAULT_FAST_MARKET_SEARCH),
        help="Fast market search JSON used to import validated candidate priors",
    )
    parser.add_argument(
        "--current-probe",
        default=str(DEFAULT_CURRENT_PROBE),
        help="Current probe JSON used to import recent session policy hints",
    )
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Latest JSON output path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Latest markdown output path")
    parser.add_argument(
        "--extra-sessions",
        default=",".join(SESSION_FALLBACKS[1:]),
        help="Comma-separated extra session buckets to sweep alongside the champion session",
    )
    parser.add_argument("--row-limit", type=int, default=1500, help="Recent local rows to scan; <=0 means all")
    parser.add_argument("--min-filled", type=int, default=2, help="Minimum filled rows required to consider a candidate")
    parser.add_argument("--top-k", type=int, default=12, help="Number of ranked candidates to keep")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path).expanduser()
    state_improvement_path = Path(args.state_improvement).expanduser()
    fast_market_search_path = Path(args.fast_market_search).expanduser()
    current_probe_path = Path(args.current_probe).expanduser()
    output_json = Path(args.output_json).expanduser()
    output_md = Path(args.output_md).expanduser()

    state_improvement = _read_json(state_improvement_path)
    fast_market_search = _read_json(fast_market_search_path)
    current_probe = _read_json(current_probe_path)
    champion = _champion_from_state_improvement(state_improvement)
    if champion is None:
        raise SystemExit("No champion BTC5 candidate found in state improvement JSON")

    extra_sessions = [item.strip().lower() for item in str(args.extra_sessions).split(",") if item.strip()]
    rows = _load_rows(db_path, int(args.row_limit))
    seed_candidates = _merge_candidates(
        [champion],
        _fast_market_seed_candidates(fast_market_search, top_k=max(4, int(args.top_k))),
        _current_probe_seed_candidates(current_probe, champion.up_max_buy_price, champion.down_max_buy_price),
        _recent_profitable_local_candidates(rows, champion=champion, top_k=4),
        _candidate_grid(champion, extra_sessions),
    )
    ranked = sorted(
        (
            _evaluate_candidate(candidate, rows, int(args.min_filled))
            for candidate in seed_candidates
        ),
        key=lambda item: (
            {
                "paper_candidate": 0,
                "watch_candidate": 1,
                "inactive_recent_regime": 2,
                "non_positive_pnl": 3,
                "cluster_blocked": 4,
                "insufficient_fills": 5,
            }.get(str(item.get("recommendation") or ""), 6),
            -float(item["score"]),
            -int(item["historical_validation_rows"]),
            -float(item["pnl_usd"]),
            -int(item["filled_rows"]),
        ),
    )

    best_candidate = ranked[0] if ranked else None
    paper_candidates = [item for item in ranked if item["recommendation"] == "paper_candidate"]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "artifact": "btc5_micro_edge_paper_search.v1",
        "db_path": str(db_path),
        "state_improvement_path": str(state_improvement_path),
        "fast_market_search_path": str(fast_market_search_path),
        "current_probe_path": str(current_probe_path),
        "rows_scanned": len(rows),
        "candidate_count": len(ranked),
        "champion_seed": {
            **asdict(champion),
            "candidate_id": champion.candidate_id,
        },
        "action": "paper_forward_candidate_found" if paper_candidates else "hold_current_shadow",
        "best_candidate": best_candidate,
        "paper_candidates": paper_candidates[: max(1, int(args.top_k))],
        "top_ranked": ranked[: max(1, int(args.top_k))],
    }
    _write_json(output_json, payload)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
