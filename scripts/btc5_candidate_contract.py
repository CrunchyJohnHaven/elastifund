#!/usr/bin/env python3
"""Shared BTC5 package-contract and wallet-intel helpers."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from scripts.btc5_policy_benchmark import runtime_package_hash, runtime_package_id


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WALLET_DB = ROOT / "data" / "wallet_scores.db"
DEFAULT_SMART_WALLETS = ROOT / "data" / "smart_wallets.json"
DEFAULT_MIRROR_WALLET_ROSTER = ROOT / "reports" / "parallel" / "instance03_mirror_wallet_roster.json"
DEFAULT_WALLET_PRIOR_SURFACE = ROOT / "reports" / "wallet_intelligence_prior_latest.json"
DEFAULT_BTC5_MAKER_DB = ROOT / "data" / "btc_5min_maker.db"
DEFAULT_BTC5_CONFIRMATION_ARCHIVE = ROOT / "reports" / "btc_fast_window_confirmation_archive.json"
DEFAULT_BTC5_AUTORESEARCH = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_BTC5_AUTORESEARCH_LOOP = ROOT / "reports" / "btc5_autoresearch_loop" / "latest.json"
DEFAULT_ET_ZONE = ZoneInfo("America/New_York")
BTC5_SLUG_PREFIX = "btc-updown-5m-"

STRATEGY_FAMILY_BOOTSTRAP = "maker_bootstrap_live"
STRATEGY_FAMILY_POLICY_SHADOW = "maker_policy_shadow"
STRATEGY_FAMILY_DIRECTIONAL_SHADOW = "directional_shadow"
STRATEGY_FAMILY_RESEARCH_SHADOW = "research_candidate_shadow"
EDGE_PROMOTION_STRATEGY_FAMILIES = {
    STRATEGY_FAMILY_DIRECTIONAL_SHADOW,
    STRATEGY_FAMILY_RESEARCH_SHADOW,
}


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _price_bucket(price: Any) -> str:
    value = _safe_float(price, None)
    if value is None:
        return "unknown"
    if value < 0.49:
        return "lt_0.49"
    if value <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def _family_tokens(label: Any) -> set[str]:
    return {
        token
        for token in str(label or "").strip().lower().replace("-", "_").split("_")
        if token
    }


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row[1]) for row in rows if len(row) > 1}


def _normalize_resolved_side(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"UP", "YES", "OUTCOME_0", "0"}:
        return "UP"
    if text in {"DOWN", "NO", "OUTCOME_1", "1"}:
        return "DOWN"
    return None


def _resolved_outcome_index(value: Any) -> int | None:
    normalized = _normalize_resolved_side(value)
    if normalized == "UP":
        return 0
    if normalized == "DOWN":
        return 1
    return None


def _top_counter_keys(counter: Counter[Any], *, limit: int = 3) -> list[Any]:
    return [key for key, _count in counter.most_common(limit)]


def _edge_support_score(
    *,
    realized_edge_rate: float,
    win_rate: float,
    resolved_trade_count: int,
) -> float:
    sample_score = min(1.0, max(0.0, resolved_trade_count / 12.0))
    edge_term = 0.5 + (0.5 * math.tanh(realized_edge_rate * 3.0))
    base_score = (0.55 * edge_term) + (0.45 * max(0.0, min(1.0, win_rate)))
    return round((sample_score * base_score) + ((1.0 - sample_score) * 0.5), 4)


def _wallet_cluster_from_behavior(
    *,
    effective_outcome_counter: Counter[int],
    price_counter: Counter[str],
) -> tuple[str, float, float]:
    total = float(sum(effective_outcome_counter.values()) or sum(price_counter.values()) or 0.0)
    if total <= 0:
        return "hybrid", 0.5, 0.5

    midpoint_share = price_counter.get("0.49_to_0.51", 0) / total
    up_share = effective_outcome_counter.get(0, 0) / total
    down_share = effective_outcome_counter.get(1, 0) / total
    balance_score = 1.0 - abs(up_share - down_share)
    maker_score = round((0.55 * balance_score) + (0.45 * midpoint_share), 4)
    directional_score = round(1.0 - maker_score, 4)
    if abs(maker_score - directional_score) < 0.12:
        return "hybrid", maker_score, directional_score
    return (
        ("maker", maker_score, directional_score)
        if maker_score > directional_score
        else ("directional", maker_score, directional_score)
    )


def _default_strategy_family_for_cluster(cluster: str) -> str:
    if cluster == "maker":
        return "btc_fast_maker_cluster"
    if cluster == "directional":
        return "btc_fast_directional_cluster"
    return "btc_fast_hybrid_cluster"


def _load_btc5_resolution_map(
    *,
    btc5_confirmation_archive_path: Path,
    btc5_maker_db_path: Path,
) -> dict[str, str]:
    resolution_map: dict[str, str] = {}

    archive_payload = _load_json(btc5_confirmation_archive_path)
    archive_rows = archive_payload.get("windows") if isinstance(archive_payload.get("windows"), list) else []
    for row in archive_rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "").strip()
        resolved_side = _normalize_resolved_side(row.get("resolved_side"))
        if slug.startswith(BTC5_SLUG_PREFIX) and resolved_side:
            resolution_map[slug] = resolved_side

    if btc5_maker_db_path.exists():
        conn = sqlite3.connect(str(btc5_maker_db_path))
        try:
            for slug, resolved_side in conn.execute(
                """
                SELECT slug, resolved_side
                FROM window_trades
                WHERE slug LIKE ? AND resolved_side IS NOT NULL
                """,
                (f"{BTC5_SLUG_PREFIX}%",),
            ):
                normalized = _normalize_resolved_side(resolved_side)
                if str(slug or "").strip() and normalized:
                    resolution_map[str(slug)] = normalized
        except sqlite3.DatabaseError:
            pass
        finally:
            conn.close()

    return resolution_map


def _trade_realized_outcome(
    *,
    side: Any,
    outcome_index: Any,
    price: Any,
    size: Any,
    resolved_side: Any,
) -> tuple[bool, float] | None:
    normalized_side = str(side or "").strip().upper()
    winner_index = _resolved_outcome_index(resolved_side)
    if normalized_side not in {"BUY", "SELL"} or winner_index is None:
        return None

    outcome_idx = _safe_int(outcome_index, -1)
    trade_price = _safe_float(price, None)
    trade_size = _safe_float(size, None)
    if outcome_idx not in {0, 1} or trade_price is None or trade_size is None or trade_size <= 0:
        return None

    if normalized_side == "BUY":
        won = outcome_idx == winner_index
        pnl = ((1.0 - trade_price) * trade_size) if won else (-trade_price * trade_size)
    else:
        won = outcome_idx != winner_index
        pnl = (trade_price * trade_size) if won else (-(1.0 - trade_price) * trade_size)
    return won, round(pnl, 8)


def _normalize_hours(hours: Iterable[Any] | None) -> list[int]:
    normalized: list[int] = []
    for raw in hours or []:
        try:
            normalized.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted({hour for hour in normalized if 0 <= hour <= 23})


def _candidate_hours(runtime_package: dict[str, Any] | None) -> list[int]:
    package = runtime_package if isinstance(runtime_package, dict) else {}
    session_policy = package.get("session_policy") if isinstance(package.get("session_policy"), list) else []
    hours: list[int] = []
    for item in session_policy:
        if not isinstance(item, dict):
            continue
        hours.extend(_normalize_hours(item.get("et_hours")))
    return sorted(set(hours))


def _candidate_price_buckets(runtime_package: dict[str, Any] | None) -> list[str]:
    package = runtime_package if isinstance(runtime_package, dict) else {}
    profile = package.get("profile") if isinstance(package.get("profile"), dict) else {}
    buckets = {
        _price_bucket(profile.get("up_max_buy_price")),
        _price_bucket(profile.get("down_max_buy_price")),
    }
    return sorted(bucket for bucket in buckets if bucket != "unknown")


def infer_strategy_family(
    *,
    runtime_package: dict[str, Any] | None,
    candidate_family: str | None = None,
    source: str | None = None,
    role: str | None = None,
) -> str:
    if str(role or "").strip().lower() == "live":
        return STRATEGY_FAMILY_BOOTSTRAP

    profile = (runtime_package or {}).get("profile") if isinstance((runtime_package or {}).get("profile"), dict) else {}
    name = str(profile.get("name") or "").strip().lower()
    source_name = str(source or "").strip().lower()
    family_name = str(candidate_family or "").strip().lower()
    joined = " ".join(part for part in (name, source_name, family_name) if part)

    if family_name == "hypothesis" or any(token in joined for token in ("directional", "momentum", "wallet", "intel")):
        return STRATEGY_FAMILY_DIRECTIONAL_SHADOW
    if family_name == "regime_policy" or any(token in joined for token in ("policy", "probe", "session")):
        return STRATEGY_FAMILY_POLICY_SHADOW
    if family_name == "global_profile" or any(token in joined for token in ("active_profile", "current_live", "baseline")):
        return STRATEGY_FAMILY_BOOTSTRAP
    return STRATEGY_FAMILY_RESEARCH_SHADOW


def benchmark_objective_for_strategy_family(strategy_family: str) -> str:
    if strategy_family == STRATEGY_FAMILY_BOOTSTRAP:
        return "collect_bounded_stage1_execution_evidence"
    if strategy_family == STRATEGY_FAMILY_POLICY_SHADOW:
        return "minimize_policy_loss_vs_market_champion_replay"
    if strategy_family == STRATEGY_FAMILY_DIRECTIONAL_SHADOW:
        return "improve_wallet_intel_shadow_alignment"
    return "rank_shadow_candidates_without_live_promotion"


def load_wallet_intel_snapshot(
    *,
    wallet_db_path: Path = DEFAULT_WALLET_DB,
    smart_wallets_path: Path = DEFAULT_SMART_WALLETS,
    mirror_wallet_roster_path: Path = DEFAULT_MIRROR_WALLET_ROSTER,
    btc5_maker_db_path: Path = DEFAULT_BTC5_MAKER_DB,
    btc5_confirmation_archive_path: Path = DEFAULT_BTC5_CONFIRMATION_ARCHIVE,
) -> dict[str, Any]:
    smart_wallets_payload = _load_json(smart_wallets_path)
    smart_wallets = smart_wallets_payload.get("wallets") if isinstance(smart_wallets_payload.get("wallets"), dict) else {}
    mirror_wallet_payload = _load_json(mirror_wallet_roster_path)
    roster = mirror_wallet_payload.get("wallets") if isinstance(mirror_wallet_payload.get("wallets"), list) else []
    resolution_map = _load_btc5_resolution_map(
        btc5_confirmation_archive_path=btc5_confirmation_archive_path,
        btc5_maker_db_path=btc5_maker_db_path,
    )
    roster_by_wallet = {
        str(item.get("address") or "").strip(): item
        for item in roster
        if isinstance(item, dict) and str(item.get("address") or "").strip()
    }

    wallet_count = int(smart_wallets_payload.get("count") or len(smart_wallets))
    wallet_trade_count = 0
    hour_counter: Counter[int] = Counter()
    price_counter: Counter[str] = Counter()
    smart_trade_count = 0
    wallet_stats: dict[str, dict[str, Any]] = {}
    score_rows_by_wallet: dict[str, dict[str, Any]] = {}

    if wallet_db_path.exists():
        conn = sqlite3.connect(str(wallet_db_path))
        conn.row_factory = sqlite3.Row
        try:
            trade_columns = _table_columns(conn, "wallet_trades")
            score_columns = _table_columns(conn, "wallet_scores")
            if score_columns:
                score_selects = [
                    "wallet",
                    "COALESCE(activity_score, 0.0) AS activity_score" if "activity_score" in score_columns else "0.0 AS activity_score",
                    "COALESCE(total_pnl, 0.0) AS total_pnl" if "total_pnl" in score_columns else "0.0 AS total_pnl",
                    "COALESCE(win_rate, 0.0) AS win_rate" if "win_rate" in score_columns else "0.0 AS win_rate",
                    "COALESCE(resolved_trades, 0) AS resolved_trades" if "resolved_trades" in score_columns else "0 AS resolved_trades",
                    "COALESCE(realized_roi, 0.0) AS realized_roi" if "realized_roi" in score_columns else "0.0 AS realized_roi",
                    "COALESCE(realized_edge, 0.0) AS realized_edge" if "realized_edge" in score_columns else "0.0 AS realized_edge",
                    "COALESCE(ranking_score, 0.0) AS ranking_score" if "ranking_score" in score_columns else "0.0 AS ranking_score",
                    "behavior_cluster" if "behavior_cluster" in score_columns else "NULL AS behavior_cluster",
                    "COALESCE(neutral_price_share, 0.0) AS neutral_price_share" if "neutral_price_share" in score_columns else "0.0 AS neutral_price_share",
                    "COALESCE(directional_conviction_share, 0.0) AS directional_conviction_share" if "directional_conviction_share" in score_columns else "0.0 AS directional_conviction_share",
                    "COALESCE(is_smart, 0) AS is_smart" if "is_smart" in score_columns else "0 AS is_smart",
                ]
                score_query = f"SELECT {', '.join(score_selects)} FROM wallet_scores"
                for row in conn.execute(score_query):
                    wallet = str(row["wallet"] or "").strip()
                    if wallet:
                        score_rows_by_wallet[wallet] = dict(row)
            join_wallet_scores = "LEFT JOIN wallet_scores s ON s.wallet = t.wallet" if score_columns else ""
            select_clauses = [
                "t.wallet AS wallet" if "wallet" in trade_columns else "'' AS wallet",
                "t.price AS price" if "price" in trade_columns else "NULL AS price",
                "t.timestamp AS timestamp" if "timestamp" in trade_columns else "NULL AS timestamp",
                "t.side AS side" if "side" in trade_columns else "'' AS side",
                "t.outcome_index AS outcome_index" if "outcome_index" in trade_columns else "NULL AS outcome_index",
                "t.effective_outcome AS effective_outcome" if "effective_outcome" in trade_columns else "NULL AS effective_outcome",
                "t.size AS size" if "size" in trade_columns else "NULL AS size",
                "t.event_slug AS event_slug" if "event_slug" in trade_columns else "'' AS event_slug",
                "COALESCE(t.is_crypto_fast, 0) AS is_crypto_fast" if "is_crypto_fast" in trade_columns else "0 AS is_crypto_fast",
                "COALESCE(s.is_smart, 0) AS is_smart" if "is_smart" in score_columns else "0 AS is_smart",
                "COALESCE(s.activity_score, 0.0) AS activity_score" if "activity_score" in score_columns else "0.0 AS activity_score",
            ]
            query = f"SELECT {', '.join(select_clauses)} FROM wallet_trades t {join_wallet_scores}"

            for row in conn.execute(query):
                wallet_trade_count += 1
                wallet = str(row["wallet"] or "").strip()
                is_smart_wallet = bool(row["is_smart"]) or wallet in smart_wallets or wallet in roster_by_wallet
                if not is_smart_wallet:
                    continue
                if int(_safe_float(row["is_crypto_fast"], 0.0) or 0) <= 0:
                    continue
                ts_value = int(_safe_float(row["timestamp"], 0.0) or 0)
                price_bucket = _price_bucket(row["price"])
                event_slug = str(row["event_slug"] or "").strip()
                if not wallet:
                    continue

                wallet_entry = wallet_stats.setdefault(
                    wallet,
                    {
                        "wallet": wallet,
                        "trade_count": 0,
                        "resolved_trade_count": 0,
                        "realized_pnl": 0.0,
                        "resolved_notional": 0.0,
                        "wins": 0,
                        "losses": 0,
                        "price_counter": Counter(),
                        "hour_counter": Counter(),
                        "effective_outcome_counter": Counter(),
                        "btc5_trade_count": 0,
                        "btc5_resolved_trade_count": 0,
                        "btc5_realized_pnl": 0.0,
                        "btc5_resolved_notional": 0.0,
                        "btc5_wins": 0,
                        "btc5_losses": 0,
                        "btc5_price_counter": Counter(),
                        "btc5_hour_counter": Counter(),
                        "activity_score": _safe_float(row["activity_score"], 0.0) or 0.0,
                    },
                )
                wallet_entry["trade_count"] += 1
                wallet_entry["price_counter"][price_bucket] += 1
                effective_outcome = _safe_int(row["effective_outcome"], -1)
                if effective_outcome in {0, 1}:
                    wallet_entry["effective_outcome_counter"][effective_outcome] += 1
                if ts_value > 0:
                    dt = datetime.fromtimestamp(ts_value, tz=UTC).astimezone(DEFAULT_ET_ZONE)
                    hour_counter[dt.hour] += 1
                    wallet_entry["hour_counter"][dt.hour] += 1
                    if event_slug.startswith(BTC5_SLUG_PREFIX):
                        wallet_entry["btc5_hour_counter"][dt.hour] += 1
                price_counter[price_bucket] += 1
                if event_slug.startswith(BTC5_SLUG_PREFIX):
                    wallet_entry["btc5_trade_count"] += 1
                    wallet_entry["btc5_price_counter"][price_bucket] += 1

                resolved_side = resolution_map.get(event_slug)
                realized_outcome = _trade_realized_outcome(
                    side=row["side"],
                    outcome_index=row["outcome_index"],
                    price=row["price"],
                    size=row["size"],
                    resolved_side=resolved_side,
                )
                if realized_outcome is None:
                    smart_trade_count += 1
                    continue

                won_trade, trade_pnl = realized_outcome
                notional = (_safe_float(row["price"], 0.0) or 0.0) * (_safe_float(row["size"], 0.0) or 0.0)
                wallet_entry["resolved_trade_count"] += 1
                wallet_entry["realized_pnl"] += trade_pnl
                wallet_entry["resolved_notional"] += notional
                if won_trade:
                    wallet_entry["wins"] += 1
                else:
                    wallet_entry["losses"] += 1
                if event_slug.startswith(BTC5_SLUG_PREFIX):
                    wallet_entry["btc5_resolved_trade_count"] += 1
                    wallet_entry["btc5_realized_pnl"] += trade_pnl
                    wallet_entry["btc5_resolved_notional"] += notional
                    if won_trade:
                        wallet_entry["btc5_wins"] += 1
                    else:
                        wallet_entry["btc5_losses"] += 1
                smart_trade_count += 1
        finally:
            conn.close()

    maker_confidences = []
    directional_confidences = []
    family_counter: Counter[str] = Counter()
    for item in roster:
        if not isinstance(item, dict):
            continue
        family = str(item.get("strategy_family") or "").strip()
        if family:
            family_counter[family] += 1
        confidence = item.get("maker_vs_directional_confidence") if isinstance(item.get("maker_vs_directional_confidence"), dict) else {}
        maker_confidences.append(_safe_float(confidence.get("maker_confidence"), 0.5) or 0.5)
        directional_confidences.append(_safe_float(confidence.get("directional_confidence"), 0.5) or 0.5)

    ranked_wallets: list[dict[str, Any]] = []
    ranked_hour_counter: Counter[int] = Counter()
    ranked_price_counter: Counter[str] = Counter()
    weighted_maker = 0.0
    weighted_directional = 0.0
    weighted_support = 0.0
    realized_wallet_count = 0
    resolved_trade_count = 0
    btc5_resolved_trade_count = 0

    for wallet, stats in wallet_stats.items():
        score_row = score_rows_by_wallet.get(wallet, {})
        stats_resolved_count = int(stats["resolved_trade_count"])
        db_resolved_count = _safe_int(score_row.get("resolved_trades"), 0)
        resolved_count = max(stats_resolved_count, db_resolved_count)
        if resolved_count <= 0:
            continue
        use_db_metrics = db_resolved_count >= stats_resolved_count and db_resolved_count > 0

        realized_wallet_count += 1
        resolved_trade_count += resolved_count
        btc5_resolved_count = int(stats["btc5_resolved_trade_count"] or 0)
        if use_db_metrics and btc5_resolved_count <= 0:
            btc5_resolved_count = db_resolved_count
        btc5_resolved_trade_count += btc5_resolved_count

        if use_db_metrics:
            win_rate = _safe_float(score_row.get("win_rate"), 0.5) or 0.5
            realized_pnl_value = _safe_float(score_row.get("total_pnl"), 0.0) or 0.0
            realized_edge_rate = _safe_float(score_row.get("realized_roi"), 0.0) or 0.0
            btc5_win_rate = win_rate
            btc5_edge_rate = realized_edge_rate
            btc5_realized_pnl = realized_pnl_value
        else:
            win_rate = (stats["wins"] / resolved_count) if resolved_count > 0 else 0.5
            realized_pnl_value = float(stats["realized_pnl"])
            realized_edge_rate = (
                stats["realized_pnl"] / stats["resolved_notional"]
                if float(stats["resolved_notional"] or 0.0) > 0
                else (_safe_float(score_row.get("realized_roi"), 0.0) or 0.0)
            )
            btc5_win_rate = (stats["btc5_wins"] / btc5_resolved_count) if btc5_resolved_count > 0 else win_rate
            btc5_edge_rate = (
                stats["btc5_realized_pnl"] / stats["btc5_resolved_notional"]
                if float(stats["btc5_resolved_notional"] or 0.0) > 0
                else realized_edge_rate
            )
            btc5_realized_pnl = float(stats["btc5_realized_pnl"])
        derived_cluster, maker_score, directional_score = _wallet_cluster_from_behavior(
            effective_outcome_counter=stats["effective_outcome_counter"],
            price_counter=stats["btc5_price_counter"] or stats["price_counter"],
        )
        cluster = str(score_row.get("behavior_cluster") or derived_cluster).strip() or derived_cluster
        if cluster == "maker":
            maker_score = max(maker_score, 0.7)
            directional_score = min(directional_score, 0.3)
        elif cluster == "directional":
            maker_score = min(maker_score, 0.3)
            directional_score = max(directional_score, 0.7)
        wallet_edge_support_score = _edge_support_score(
            realized_edge_rate=realized_edge_rate,
            win_rate=win_rate,
            resolved_trade_count=resolved_count,
        )
        btc5_edge_support_score = _edge_support_score(
            realized_edge_rate=btc5_edge_rate,
            win_rate=btc5_win_rate,
            resolved_trade_count=btc5_resolved_count if btc5_resolved_count > 0 else resolved_count,
        )
        roster_item = roster_by_wallet.get(wallet, {})
        strategy_family = str(roster_item.get("strategy_family") or _default_strategy_family_for_cluster(cluster)).strip()
        label = str(roster_item.get("label") or wallet).strip()
        confidence = roster_item.get("maker_vs_directional_confidence") if isinstance(roster_item.get("maker_vs_directional_confidence"), dict) else {}
        maker_confidence = _safe_float(confidence.get("maker_confidence"), maker_score) or maker_score
        directional_confidence = _safe_float(confidence.get("directional_confidence"), directional_score) or directional_score
        support_weight = max(0.05, btc5_edge_support_score)
        weighted_maker += maker_confidence * support_weight
        weighted_directional += directional_confidence * support_weight
        weighted_support += support_weight
        ranking_score = _safe_float(score_row.get("ranking_score"), btc5_edge_support_score * 100.0) or 0.0
        realized_pnl = _safe_float(score_row.get("total_pnl"), realized_pnl_value) or realized_pnl_value

        wallet_record = {
            "wallet": wallet,
            "label": label,
            "strategy_family": strategy_family,
            "wallet_cluster": cluster,
            "ranking_score": round(ranking_score, 4),
            "resolved_trade_count": resolved_count,
            "realized_pnl": round(realized_pnl, 6),
            "win_rate": round(win_rate, 4),
            "realized_edge_rate": round(realized_edge_rate, 6),
            "wallet_edge_support_score": wallet_edge_support_score,
            "btc5_trade_count": int(stats["btc5_trade_count"]),
            "btc5_resolved_trade_count": btc5_resolved_count,
            "btc5_realized_pnl": round(btc5_realized_pnl, 6),
            "btc5_win_rate": round(btc5_win_rate, 4),
            "btc5_realized_edge_rate": round(btc5_edge_rate, 6),
            "realized_roi": round(_safe_float(score_row.get("realized_roi"), btc5_edge_rate) or btc5_edge_rate, 6),
            "realized_edge": round(_safe_float(score_row.get("realized_edge"), 0.0) or 0.0, 6),
            "btc5_edge_support_score": btc5_edge_support_score,
            "maker_vs_directional_confidence": {
                "maker_confidence": round(maker_confidence, 4),
                "directional_confidence": round(directional_confidence, 4),
            },
            "dominant_hours_et": _top_counter_keys(stats["btc5_hour_counter"] or stats["hour_counter"]),
            "dominant_price_buckets": _top_counter_keys(stats["btc5_price_counter"] or stats["price_counter"]),
            "activity_score": round(float(stats["activity_score"]), 4),
        }
        ranked_wallets.append(wallet_record)
        family_counter[strategy_family] += 1
        for hour in wallet_record["dominant_hours_et"]:
            ranked_hour_counter[int(hour)] += max(1, round(support_weight * 10))
        for bucket in wallet_record["dominant_price_buckets"]:
            ranked_price_counter[str(bucket)] += max(1, round(support_weight * 10))

    ranked_wallets.sort(
        key=lambda item: (
            float(item.get("ranking_score") or 0.0),
            float(item.get("btc5_edge_support_score") or 0.0),
            float(item.get("wallet_edge_support_score") or 0.0),
            int(item.get("btc5_resolved_trade_count") or 0),
            int(item.get("resolved_trade_count") or 0),
            float(item.get("btc5_realized_pnl") or 0.0),
            float(item.get("realized_pnl") or 0.0),
        ),
        reverse=True,
    )

    cluster_rollup: dict[str, dict[str, Any]] = {}
    for item in ranked_wallets:
        cluster = str(item.get("wallet_cluster") or "hybrid")
        entry = cluster_rollup.setdefault(
            cluster,
            {
                "wallet_cluster": cluster,
                "wallet_count": 0,
                "resolved_trade_count": 0,
                "btc5_resolved_trade_count": 0,
                "realized_pnl": 0.0,
                "btc5_realized_pnl": 0.0,
                "wallet_edge_support_sum": 0.0,
                "btc5_edge_support_sum": 0.0,
                "win_rate_weighted_sum": 0.0,
                "strategy_family_counter": Counter(),
            },
        )
        weight = max(0.25, float(item.get("btc5_edge_support_score") or 0.5))
        entry["wallet_count"] += 1
        entry["resolved_trade_count"] += int(item.get("resolved_trade_count") or 0)
        entry["btc5_resolved_trade_count"] += int(item.get("btc5_resolved_trade_count") or 0)
        entry["realized_pnl"] += float(item.get("realized_pnl") or 0.0)
        entry["btc5_realized_pnl"] += float(item.get("btc5_realized_pnl") or 0.0)
        entry["wallet_edge_support_sum"] += float(item.get("wallet_edge_support_score") or 0.5)
        entry["btc5_edge_support_sum"] += float(item.get("btc5_edge_support_score") or 0.5)
        entry["win_rate_weighted_sum"] += float(item.get("btc5_win_rate") or item.get("win_rate") or 0.5) * weight
        entry["strategy_family_counter"][str(item.get("strategy_family") or "")] += 1

    wallet_cluster_rankings = []
    for cluster, item in cluster_rollup.items():
        wallet_count_in_cluster = int(item["wallet_count"] or 0)
        avg_wallet_support = (
            float(item["wallet_edge_support_sum"]) / float(wallet_count_in_cluster or 1)
        )
        avg_btc5_support = (
            float(item["btc5_edge_support_sum"]) / float(wallet_count_in_cluster or 1)
        )
        win_rate_score = min(
            1.0,
            max(
                0.0,
                (
                    float(item["win_rate_weighted_sum"])
                    / float(
                        sum(
                            max(0.25, float(wallet.get("btc5_edge_support_score") or 0.5))
                            for wallet in ranked_wallets
                            if str(wallet.get("wallet_cluster") or "hybrid") == cluster
                        )
                        or 1.0
                    )
                ),
            ),
        )
        wallet_cluster_rankings.append(
            {
                "wallet_cluster": cluster,
                "wallet_count": wallet_count_in_cluster,
                "resolved_trade_count": int(item["resolved_trade_count"] or 0),
                "btc5_resolved_trade_count": int(item["btc5_resolved_trade_count"] or 0),
                "realized_pnl": round(float(item["realized_pnl"]), 6),
                "btc5_realized_pnl": round(float(item["btc5_realized_pnl"]), 6),
                "support_score": round((0.55 * avg_btc5_support) + (0.30 * avg_wallet_support) + (0.15 * win_rate_score), 4),
                "dominant_strategy_families": [family for family, _count in item["strategy_family_counter"].most_common(3)],
            }
        )
    wallet_cluster_rankings.sort(
        key=lambda item: (
            float(item.get("support_score") or 0.0),
            int(item.get("btc5_resolved_trade_count") or 0),
            float(item.get("btc5_realized_pnl") or 0.0),
        ),
        reverse=True,
    )

    dominant_hours = _top_counter_keys(ranked_hour_counter) or _top_counter_keys(hour_counter)
    dominant_price_buckets = _top_counter_keys(ranked_price_counter) or _top_counter_keys(price_counter)
    maker_support_share = (
        round(weighted_maker / weighted_support, 4)
        if weighted_support > 0
        else (
            round(sum(maker_confidences) / len(maker_confidences), 4)
            if maker_confidences
            else 0.5
        )
    )
    directional_support_share = (
        round(weighted_directional / weighted_support, 4)
        if weighted_support > 0
        else (
            round(sum(directional_confidences) / len(directional_confidences), 4)
            if directional_confidences
            else 0.5
        )
    )
    return {
        "wallet_count": int(wallet_count),
        "wallet_trade_count": int(wallet_trade_count),
        "smart_wallet_trade_count": int(smart_trade_count),
        "mirror_wallet_count": len(roster),
        "resolved_wallet_count": int(realized_wallet_count),
        "resolved_trade_count": int(resolved_trade_count),
        "btc5_resolved_trade_count": int(btc5_resolved_trade_count),
        "wallet_realized_outcome_available": bool(realized_wallet_count > 0 and resolved_trade_count > 0),
        "wallet_realized_outcome_wallet_count": int(realized_wallet_count),
        "wallet_resolved_trade_count": int(resolved_trade_count),
        "maker_support_share": maker_support_share,
        "directional_support_share": directional_support_share,
        "dominant_hours_et": dominant_hours,
        "dominant_price_buckets": dominant_price_buckets,
        "top_strategy_families": [family for family, _count in family_counter.most_common(5)],
        "ranked_wallet_prior_surface": {
            "lane": "btc5_shadow",
            "generated_at": datetime.now(UTC).isoformat(),
            "realized_wallet_count": int(realized_wallet_count),
            "resolved_trade_count": int(resolved_trade_count),
            "btc5_resolved_trade_count": int(btc5_resolved_trade_count),
            "top_wallets": ranked_wallets[:25],
            "wallet_cluster_rankings": wallet_cluster_rankings,
        },
        "ranked_wallets": ranked_wallets[:25],
        "wallet_cluster_rankings": wallet_cluster_rankings,
        "mirror_wallet_roster": roster,
        "smart_wallets_artifact_present": bool(smart_wallets),
        "artifact_paths": {
            "wallet_db_path": str(wallet_db_path),
            "smart_wallets_path": str(smart_wallets_path),
            "mirror_wallet_roster_path": str(mirror_wallet_roster_path),
            "wallet_prior_surface_path": str(DEFAULT_WALLET_PRIOR_SURFACE),
            "btc5_maker_db_path": str(btc5_maker_db_path),
            "btc5_confirmation_archive_path": str(btc5_confirmation_archive_path),
        },
    }


def publish_wallet_prior_surface(
    *,
    wallet_db_path: Path = DEFAULT_WALLET_DB,
    smart_wallets_path: Path = DEFAULT_SMART_WALLETS,
    mirror_wallet_roster_path: Path = DEFAULT_MIRROR_WALLET_ROSTER,
    btc5_maker_db_path: Path = DEFAULT_BTC5_MAKER_DB,
    btc5_confirmation_archive_path: Path = DEFAULT_BTC5_CONFIRMATION_ARCHIVE,
    output_path: Path = DEFAULT_WALLET_PRIOR_SURFACE,
) -> dict[str, Any]:
    """Persist the BTC5 wallet prior surface for downstream shadow-lane readers."""
    snapshot = load_wallet_intel_snapshot(
        wallet_db_path=wallet_db_path,
        smart_wallets_path=smart_wallets_path,
        mirror_wallet_roster_path=mirror_wallet_roster_path,
        btc5_maker_db_path=btc5_maker_db_path,
        btc5_confirmation_archive_path=btc5_confirmation_archive_path,
    )
    surface = snapshot.get("ranked_wallet_prior_surface")
    if not isinstance(surface, dict):
        surface = {}
    payload = {
        **surface,
        "maker_support_share": snapshot.get("maker_support_share"),
        "directional_support_share": snapshot.get("directional_support_share"),
        "dominant_hours_et": snapshot.get("dominant_hours_et"),
        "dominant_price_buckets": snapshot.get("dominant_price_buckets"),
        "top_strategy_families": snapshot.get("top_strategy_families"),
        "artifact_paths": snapshot.get("artifact_paths"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _candidate_fingerprint(strategy_family: str) -> dict[str, float]:
    if strategy_family == STRATEGY_FAMILY_BOOTSTRAP:
        maker = 0.9
        directional = 0.1
    elif strategy_family == STRATEGY_FAMILY_POLICY_SHADOW:
        maker = 0.75
        directional = 0.25
    elif strategy_family == STRATEGY_FAMILY_DIRECTIONAL_SHADOW:
        maker = 0.25
        directional = 0.75
    else:
        maker = 0.5
        directional = 0.5
    return {
        "maker_score": round(maker, 4),
        "directional_score": round(directional, 4),
    }


def _wallet_cluster_support(
    *,
    strategy_family: str,
    candidate_fingerprint: dict[str, float],
    wallet_intel_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = wallet_intel_snapshot if isinstance(wallet_intel_snapshot, dict) else {}
    ranked_wallets = snapshot.get("ranked_wallets") if isinstance(snapshot.get("ranked_wallets"), list) else []
    roster = snapshot.get("mirror_wallet_roster") if isinstance(snapshot.get("mirror_wallet_roster"), list) else []
    candidates = ranked_wallets or roster
    candidate_tokens = _family_tokens(strategy_family)
    candidate_maker = _safe_float(candidate_fingerprint.get("maker_score"), 0.5) or 0.5
    candidate_directional = _safe_float(candidate_fingerprint.get("directional_score"), 0.5) or 0.5

    matches: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        wallet_family = str(item.get("strategy_family") or item.get("wallet_cluster") or "").strip()
        wallet_tokens = _family_tokens(wallet_family)
        overlap = len(candidate_tokens & wallet_tokens) / float(len(candidate_tokens | wallet_tokens) or 1)
        confidence = item.get("maker_vs_directional_confidence") if isinstance(item.get("maker_vs_directional_confidence"), dict) else {}
        wallet_maker = _safe_float(confidence.get("maker_confidence"), 0.5) or 0.5
        wallet_directional = _safe_float(confidence.get("directional_confidence"), 0.5) or 0.5
        if ranked_wallets and not confidence:
            wallet_maker = _safe_float(item.get("maker_confidence"), _safe_float(item.get("maker_like_score"), 0.5)) or 0.5
            wallet_directional = _safe_float(item.get("directional_confidence"), _safe_float(item.get("directional_like_score"), 0.5)) or 0.5
        fingerprint_alignment = max(
            0.0,
            1.0 - ((abs(candidate_maker - wallet_maker) + abs(candidate_directional - wallet_directional)) / 2.0),
        )
        wallet_edge_support = _safe_float(item.get("wallet_edge_support_score"), 0.5) or 0.5
        btc5_edge_support = _safe_float(item.get("btc5_edge_support_score"), wallet_edge_support) or wallet_edge_support
        support_score = round(
            (0.25 * overlap)
            + (0.25 * fingerprint_alignment)
            + (0.25 * wallet_edge_support)
            + (0.25 * btc5_edge_support),
            4,
        )
        matches.append(
            {
                "wallet": item.get("wallet") or item.get("address"),
                "label": item.get("label"),
                "strategy_family": wallet_family,
                "wallet_cluster": item.get("wallet_cluster"),
                "resolved_trade_count": int(item.get("resolved_trade_count") or 0),
                "btc5_resolved_trade_count": int(item.get("btc5_resolved_trade_count") or 0),
                "wallet_edge_support_score": round(wallet_edge_support, 4),
                "btc5_edge_support_score": round(btc5_edge_support, 4),
                "support_score": support_score,
            }
        )

    matches.sort(key=lambda item: (item["support_score"], str(item.get("label") or "")), reverse=True)
    top_matches = matches[:3]
    agreement = round(sum(item["support_score"] for item in top_matches) / float(len(top_matches) or 1), 4)
    return {
        "agreement_score": agreement if top_matches else 0.0,
        "matched_wallets": [item.get("label") or item.get("wallet") for item in top_matches],
        "matched_strategy_families": [item.get("strategy_family") for item in top_matches],
        "matched_clusters": [item.get("wallet_cluster") for item in top_matches if item.get("wallet_cluster")],
        "top_matches": top_matches,
    }


def _time_of_day_specialization(
    *,
    runtime_package: dict[str, Any] | None,
    wallet_intel_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = wallet_intel_snapshot if isinstance(wallet_intel_snapshot, dict) else {}
    candidate_hours = _candidate_hours(runtime_package)
    dominant_hours = _normalize_hours(snapshot.get("dominant_hours_et"))
    if not dominant_hours:
        return {
            "candidate_hours_et": candidate_hours,
            "dominant_hours_et": [],
            "overlap_hours_et": [],
            "support_score": 0.0,
        }
    if not candidate_hours:
        return {
            "candidate_hours_et": [],
            "dominant_hours_et": dominant_hours,
            "overlap_hours_et": [],
            "support_score": 0.5,
        }
    overlap = sorted(set(candidate_hours) & set(dominant_hours))
    support_score = len(overlap) / float(len(candidate_hours) or 1)
    return {
        "candidate_hours_et": candidate_hours,
        "dominant_hours_et": dominant_hours,
        "overlap_hours_et": overlap,
        "support_score": round(support_score, 4),
    }


def _price_bucket_specialization(
    *,
    runtime_package: dict[str, Any] | None,
    wallet_intel_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = wallet_intel_snapshot if isinstance(wallet_intel_snapshot, dict) else {}
    candidate_buckets = _candidate_price_buckets(runtime_package)
    dominant_buckets = [
        str(bucket)
        for bucket in (snapshot.get("dominant_price_buckets") or [])
        if str(bucket).strip()
    ]
    if not dominant_buckets:
        return {
            "candidate_price_buckets": candidate_buckets,
            "dominant_price_buckets": [],
            "overlap_price_buckets": [],
            "support_score": 0.0,
        }
    if not candidate_buckets:
        return {
            "candidate_price_buckets": [],
            "dominant_price_buckets": dominant_buckets,
            "overlap_price_buckets": [],
            "support_score": 0.5,
        }
    overlap = sorted(set(candidate_buckets) & set(dominant_buckets))
    support_score = len(overlap) / float(len(candidate_buckets) or 1)
    return {
        "candidate_price_buckets": candidate_buckets,
        "dominant_price_buckets": dominant_buckets,
        "overlap_price_buckets": overlap,
        "support_score": round(support_score, 4),
    }


def _runtime_package_from_candidate_record(record: dict[str, Any] | None) -> dict[str, Any]:
    payload = record if isinstance(record, dict) else {}
    runtime_package = payload.get("runtime_package") if isinstance(payload.get("runtime_package"), dict) else {}
    if runtime_package:
        return runtime_package
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    if not profile:
        profile = payload.get("base_profile") if isinstance(payload.get("base_profile"), dict) else {}
    session_policy = payload.get("recommended_session_policy") if isinstance(payload.get("recommended_session_policy"), list) else []
    if not session_policy and isinstance(payload.get("session_policy"), list):
        session_policy = payload.get("session_policy")
    if not profile and not session_policy:
        return {}
    return {
        "profile": profile,
        "session_policy": session_policy or [],
    }


def _candidate_artifact_record(
    *,
    payload: dict[str, Any],
    section: str,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scoring = payload.get("scoring") if isinstance(payload.get("scoring"), dict) else {}
    historical = payload.get("historical") if isinstance(payload.get("historical"), dict) else {}
    continuation = payload.get("continuation") if isinstance(payload.get("continuation"), dict) else {}
    decision_payload = decision if isinstance(decision, dict) else {}
    candidate_family = str(payload.get("candidate_family") or "").strip()
    source = str(payload.get("source") or section).strip()
    runtime_package = _runtime_package_from_candidate_record(payload)
    return {
        "section": section,
        "source": source,
        "strategy_family": infer_strategy_family(
            runtime_package=runtime_package,
            candidate_family=candidate_family,
            source=source,
            role="shadow",
        ),
        "candidate_class": str(payload.get("candidate_class") or "").strip().lower(),
        "action": str(decision_payload.get("action") or "").strip().lower(),
        "validation_live_filled_rows": _safe_int(
            payload.get("validation_live_filled_rows"),
            _safe_int(scoring.get("validation_live_filled_rows"), 0),
        ),
        "median_arr_delta_pct": _safe_float(
            decision_payload.get("median_arr_delta_pct"),
            _safe_float(payload.get("median_arr_delta_pct"), _safe_float(continuation.get("median_arr_pct"), 0.0)),
        )
        or 0.0,
        "historical_arr_delta_pct": _safe_float(
            decision_payload.get("historical_arr_delta_pct"),
            _safe_float(payload.get("historical_arr_delta_pct"), _safe_float(continuation.get("historical_arr_pct"), 0.0)),
        )
        or 0.0,
        "replay_pnl_delta_usd": _safe_float(
            decision_payload.get("replay_pnl_delta_usd"),
            _safe_float(payload.get("replay_pnl_delta_usd"), _safe_float(historical.get("replay_live_filled_pnl_usd"), 0.0)),
        )
        or 0.0,
        "fill_retention_ratio": _safe_float(
            decision_payload.get("fill_retention_ratio"),
            _safe_float(payload.get("fill_retention_ratio"), _safe_float(historical.get("fill_coverage_ratio"), 0.0)),
        )
        or 0.0,
        "observed_live_strategy_family": str(
            payload.get("observed_live_strategy_family")
            or payload.get("live_strategy_family")
            or decision_payload.get("observed_live_strategy_family")
            or ""
        ).strip(),
    }


def _candidate_artifact_records(*artifact_payloads: dict[str, Any] | None) -> list[dict[str, Any]]:
    sections = (
        "best_live_package",
        "best_raw_research_package",
        "best_candidate",
        "current_candidate",
        "global_best_candidate",
        "hypothesis_best_candidate",
        "regime_best_candidate",
    )
    records: list[dict[str, Any]] = []
    for artifact in artifact_payloads:
        payload = artifact if isinstance(artifact, dict) else {}
        for section in sections:
            candidate_payload = payload.get(section)
            if isinstance(candidate_payload, dict) and candidate_payload:
                records.append(_candidate_artifact_record(payload=candidate_payload, section=section))
        promotion_candidates = payload.get("promotion_candidates") if isinstance(payload.get("promotion_candidates"), list) else []
        for item in promotion_candidates:
            if not isinstance(item, dict):
                continue
            candidate_payload = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
            if not candidate_payload:
                continue
            decision_payload = item.get("decision") if isinstance(item.get("decision"), dict) else {}
            records.append(
                _candidate_artifact_record(
                    payload=candidate_payload,
                    section=str(item.get("source") or "promotion_candidates").strip(),
                    decision=decision_payload,
                )
            )
    return records


def _matching_artifact_records(
    *,
    strategy_family: str,
    btc5_autoresearch_latest: dict[str, Any] | None,
    btc5_autoresearch_loop_latest: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    latest_payload = btc5_autoresearch_latest if isinstance(btc5_autoresearch_latest, dict) else _load_json(DEFAULT_BTC5_AUTORESEARCH)
    loop_payload = btc5_autoresearch_loop_latest if isinstance(btc5_autoresearch_loop_latest, dict) else _load_json(DEFAULT_BTC5_AUTORESEARCH_LOOP)
    return [
        record
        for record in _candidate_artifact_records(latest_payload, loop_payload)
        if record.get("strategy_family") == strategy_family
    ]


def _benchmark_requirement(
    *,
    strategy_family: str,
    artifact_records: list[dict[str, Any]],
) -> dict[str, Any]:
    required = strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES
    benchmark_improved = any(
        str(record.get("candidate_class") or "") == "promote"
        or str(record.get("action") or "") == "promote"
        or (_safe_float(record.get("median_arr_delta_pct"), 0.0) or 0.0) > 0.0
        or (_safe_float(record.get("historical_arr_delta_pct"), 0.0) or 0.0) > 0.0
        or (_safe_float(record.get("replay_pnl_delta_usd"), 0.0) or 0.0) > 0.0
        for record in artifact_records
    )
    return {
        "required": required,
        "passed": benchmark_improved if required else False,
        "status": "passed" if required and benchmark_improved else "missing" if required else "not_applicable",
        "supporting_records": len(artifact_records),
        "strongest_deltas": {
            "median_arr_delta_pct": max((_safe_float(record.get("median_arr_delta_pct"), 0.0) or 0.0) for record in artifact_records)
            if artifact_records
            else 0.0,
            "historical_arr_delta_pct": max(
                (_safe_float(record.get("historical_arr_delta_pct"), 0.0) or 0.0) for record in artifact_records
            )
            if artifact_records
            else 0.0,
            "replay_pnl_delta_usd": max((_safe_float(record.get("replay_pnl_delta_usd"), 0.0) or 0.0) for record in artifact_records)
            if artifact_records
            else 0.0,
        },
    }


def _wallet_prior_requirement(
    *,
    strategy_family: str,
    wallet_prior_support_score: float,
    wallet_intel_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    required = strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES
    snapshot = wallet_intel_snapshot if isinstance(wallet_intel_snapshot, dict) else {}
    realized_outcomes_available = bool(snapshot.get("wallet_realized_outcome_available"))
    if not required:
        status = "not_applicable"
        passed = False
    elif not realized_outcomes_available:
        status = "explicit_absence"
        passed = True
    elif wallet_prior_support_score >= 0.45:
        status = "supported"
        passed = True
    else:
        status = "unsupported"
        passed = False
    return {
        "required": required,
        "passed": passed,
        "status": status,
        "support_score": round(wallet_prior_support_score, 4),
        "realized_outcome_available": realized_outcomes_available,
        "realized_outcome_wallet_count": _safe_int(snapshot.get("wallet_realized_outcome_wallet_count"), 0),
        "resolved_trade_count": _safe_int(snapshot.get("wallet_resolved_trade_count"), 0),
    }


def _live_quality_requirement(
    *,
    strategy_family: str,
    canonical_live_strategy_family: str,
    artifact_records: list[dict[str, Any]],
) -> dict[str, Any]:
    required = strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES
    validation_live_filled_rows = max(
        (_safe_int(record.get("validation_live_filled_rows"), 0) for record in artifact_records),
        default=0,
    )
    observed_families = {
        str(record.get("observed_live_strategy_family") or canonical_live_strategy_family or "").strip()
        for record in artifact_records
        if _safe_int(record.get("validation_live_filled_rows"), 0) > 0
    }
    observed_families.discard("")
    same_family_live_evidence = bool(validation_live_filled_rows > 0 and strategy_family in observed_families)
    return {
        "required": required,
        "passed": same_family_live_evidence if required else False,
        "status": "passed" if required and same_family_live_evidence else "missing" if required else "not_applicable",
        "validation_live_filled_rows": validation_live_filled_rows,
        "canonical_live_strategy_family": canonical_live_strategy_family,
        "observed_live_strategy_families": sorted(observed_families),
    }


def _promotion_barrier(
    *,
    role: str | None,
    strategy_family: str,
    benchmark_requirement: dict[str, Any],
    wallet_prior_requirement: dict[str, Any],
    live_quality_requirement: dict[str, Any],
) -> dict[str, Any]:
    role_name = str(role or "").strip().lower()
    if role_name == "live":
        return {
            "status": "bootstrap_execution_only",
            "promotable": False,
            "blocking_reasons": ["bootstrap_execution_evidence_only"],
            "execution_evidence_scope": "execution_viability_only",
        }

    blocking_reasons: list[str] = []
    if benchmark_requirement.get("required") and not benchmark_requirement.get("passed"):
        blocking_reasons.append("benchmark_improvement_missing")
    if wallet_prior_requirement.get("required") and not wallet_prior_requirement.get("passed"):
        blocking_reasons.append("wallet_prior_support_missing")
    if live_quality_requirement.get("required") and not live_quality_requirement.get("passed"):
        blocking_reasons.append("same_family_live_quality_evidence_missing")
    promotable = not blocking_reasons and strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES
    return {
        "status": "promotable" if promotable else "blocked",
        "promotable": promotable,
        "blocking_reasons": blocking_reasons,
        "execution_evidence_scope": "strategy_family_qualified" if promotable else "execution_viability_only",
    }


def build_runtime_candidate_metadata(
    *,
    runtime_package: dict[str, Any] | None,
    candidate_family: str | None = None,
    source: str | None = None,
    role: str | None = None,
    wallet_intel_snapshot: dict[str, Any] | None = None,
    live_runtime_package: dict[str, Any] | None = None,
    btc5_autoresearch_latest: dict[str, Any] | None = None,
    btc5_autoresearch_loop_latest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package = runtime_package if isinstance(runtime_package, dict) else {}
    strategy_family = infer_strategy_family(
        runtime_package=package,
        candidate_family=candidate_family,
        source=source,
        role=role,
    )
    benchmark_objective = benchmark_objective_for_strategy_family(strategy_family)
    fingerprint = _candidate_fingerprint(strategy_family)
    cluster_support = _wallet_cluster_support(
        strategy_family=strategy_family,
        candidate_fingerprint=fingerprint,
        wallet_intel_snapshot=wallet_intel_snapshot,
    )
    time_specialization = _time_of_day_specialization(
        runtime_package=package,
        wallet_intel_snapshot=wallet_intel_snapshot,
    )
    price_specialization = _price_bucket_specialization(
        runtime_package=package,
        wallet_intel_snapshot=wallet_intel_snapshot,
    )
    wallet_prior_support_score = round(
        (0.45 * (_safe_float(cluster_support.get("agreement_score"), 0.0) or 0.0))
        + (0.25 * (_safe_float(time_specialization.get("support_score"), 0.0) or 0.0))
        + (0.15 * (_safe_float(price_specialization.get("support_score"), 0.0) or 0.0))
        + (
            0.15
            * (
                1.0
                - (
                    abs((_safe_float(fingerprint.get("maker_score"), 0.5) or 0.5) - (_safe_float((wallet_intel_snapshot or {}).get("maker_support_share"), 0.5) or 0.5))
                    + abs((_safe_float(fingerprint.get("directional_score"), 0.5) or 0.5) - (_safe_float((wallet_intel_snapshot or {}).get("directional_support_share"), 0.5) or 0.5))
                )
                / 2.0
            )
        ),
        4,
    )
    live_package = live_runtime_package if isinstance(live_runtime_package, dict) else {}
    canonical_live_strategy_family = (
        infer_strategy_family(runtime_package=live_package, role="live")
        if live_package
        else STRATEGY_FAMILY_BOOTSTRAP
    )
    artifact_records = _matching_artifact_records(
        strategy_family=strategy_family,
        btc5_autoresearch_latest=btc5_autoresearch_latest,
        btc5_autoresearch_loop_latest=btc5_autoresearch_loop_latest,
    )
    benchmark_requirement = _benchmark_requirement(
        strategy_family=strategy_family,
        artifact_records=artifact_records,
    )
    wallet_prior_requirement = _wallet_prior_requirement(
        strategy_family=strategy_family,
        wallet_prior_support_score=wallet_prior_support_score,
        wallet_intel_snapshot=wallet_intel_snapshot,
    )
    live_quality_requirement = _live_quality_requirement(
        strategy_family=strategy_family,
        canonical_live_strategy_family=canonical_live_strategy_family,
        artifact_records=artifact_records,
    )
    promotion_barrier = _promotion_barrier(
        role=role,
        strategy_family=strategy_family,
        benchmark_requirement=benchmark_requirement,
        wallet_prior_requirement=wallet_prior_requirement,
        live_quality_requirement=live_quality_requirement,
    )
    if str(role or "").strip().lower() == "live":
        promotion_readiness = "bootstrap_only"
    elif strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES and promotion_barrier.get("promotable"):
        promotion_readiness = "promotable"
    elif strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES and "same_family_live_quality_evidence_missing" in (
        promotion_barrier.get("blocking_reasons") or []
    ):
        promotion_readiness = "shadow_candidate_needs_same_family_live_evidence"
    elif strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES and "wallet_prior_support_missing" in (
        promotion_barrier.get("blocking_reasons") or []
    ):
        promotion_readiness = "insufficient_wallet_support"
    elif strategy_family in EDGE_PROMOTION_STRATEGY_FAMILIES:
        promotion_readiness = "shadow_candidate_needs_validation"
    elif wallet_prior_support_score >= 0.7:
        promotion_readiness = "shadow_candidate_supported"
    elif wallet_prior_support_score >= 0.45:
        promotion_readiness = "shadow_candidate_needs_validation"
    else:
        promotion_readiness = "insufficient_wallet_support"
    return {
        "profile_id": runtime_package_id(package) if package else None,
        "package_hash": runtime_package_hash(package) if package else None,
        "strategy_family": strategy_family,
        "benchmark_objective": benchmark_objective,
        "wallet_prior_support_score": wallet_prior_support_score,
        "wallet_cluster_support": cluster_support,
        "maker_vs_directional_fingerprint": fingerprint,
        "time_of_day_specialization": time_specialization,
        "price_bucket_specialization": price_specialization,
        "benchmark_requirement": benchmark_requirement,
        "wallet_prior_requirement": wallet_prior_requirement,
        "live_quality_requirement": live_quality_requirement,
        "promotion_barrier": promotion_barrier,
        "promotion_readiness": promotion_readiness,
    }


def build_canonical_package_contract(
    *,
    live_runtime_package: dict[str, Any] | None,
    shadow_candidates: list[dict[str, Any] | None] | None = None,
    live_source: str | None = None,
    wallet_intel_snapshot: dict[str, Any] | None = None,
    btc5_autoresearch_latest: dict[str, Any] | None = None,
    btc5_autoresearch_loop_latest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    live_package = live_runtime_package if isinstance(live_runtime_package, dict) else {}
    live_metadata = build_runtime_candidate_metadata(
        runtime_package=live_package,
        source=live_source,
        role="live",
        wallet_intel_snapshot=wallet_intel_snapshot,
        live_runtime_package=live_package,
        btc5_autoresearch_latest=btc5_autoresearch_latest,
        btc5_autoresearch_loop_latest=btc5_autoresearch_loop_latest,
    )
    live_signature = runtime_package_hash(live_package) if live_package else None
    shadow_metadata: dict[str, Any] | None = None
    for item in shadow_candidates or []:
        payload = item if isinstance(item, dict) else {}
        package = payload.get("runtime_package") if isinstance(payload.get("runtime_package"), dict) else payload
        if not package:
            continue
        package_hash = runtime_package_hash(package)
        if live_signature and package_hash == live_signature:
            continue
        shadow_metadata = build_runtime_candidate_metadata(
            runtime_package=package,
            candidate_family=str(payload.get("candidate_family") or "").strip() or None,
            source=str(payload.get("source") or "").strip() or None,
            role="shadow",
            wallet_intel_snapshot=wallet_intel_snapshot,
            live_runtime_package=live_package,
            btc5_autoresearch_latest=btc5_autoresearch_latest,
            btc5_autoresearch_loop_latest=btc5_autoresearch_loop_latest,
        )
        break

    return {
        "canonical_live_profile_id": live_metadata.get("profile_id"),
        "canonical_live_package_hash": live_metadata.get("package_hash"),
        "strategy_family": live_metadata.get("strategy_family"),
        "benchmark_objective": live_metadata.get("benchmark_objective"),
        "wallet_prior_support_score": live_metadata.get("wallet_prior_support_score"),
        "wallet_cluster_support": live_metadata.get("wallet_cluster_support"),
        "maker_vs_directional_fingerprint": live_metadata.get("maker_vs_directional_fingerprint"),
        "time_of_day_specialization": live_metadata.get("time_of_day_specialization"),
        "price_bucket_specialization": live_metadata.get("price_bucket_specialization"),
        "benchmark_requirement": live_metadata.get("benchmark_requirement"),
        "wallet_prior_requirement": live_metadata.get("wallet_prior_requirement"),
        "live_quality_requirement": live_metadata.get("live_quality_requirement"),
        "promotion_barrier": live_metadata.get("promotion_barrier"),
        "promotion_readiness": live_metadata.get("promotion_readiness"),
        "shadow_comparator_profile_id": (shadow_metadata or {}).get("profile_id"),
        "shadow_comparator_package_hash": (shadow_metadata or {}).get("package_hash"),
        "shadow_comparator_strategy_family": (shadow_metadata or {}).get("strategy_family"),
        "shadow_comparator_benchmark_objective": (shadow_metadata or {}).get("benchmark_objective"),
        "shadow_comparator_wallet_prior_support_score": (shadow_metadata or {}).get("wallet_prior_support_score"),
        "shadow_comparator_wallet_prior_requirement": (shadow_metadata or {}).get("wallet_prior_requirement"),
        "shadow_comparator_live_quality_requirement": (shadow_metadata or {}).get("live_quality_requirement"),
        "shadow_comparator_promotion_barrier": (shadow_metadata or {}).get("promotion_barrier"),
    }


__all__ = [
    "STRATEGY_FAMILY_BOOTSTRAP",
    "STRATEGY_FAMILY_DIRECTIONAL_SHADOW",
    "STRATEGY_FAMILY_POLICY_SHADOW",
    "STRATEGY_FAMILY_RESEARCH_SHADOW",
    "benchmark_objective_for_strategy_family",
    "build_canonical_package_contract",
    "build_runtime_candidate_metadata",
    "infer_strategy_family",
    "load_wallet_intel_snapshot",
    "publish_wallet_prior_surface",
]
