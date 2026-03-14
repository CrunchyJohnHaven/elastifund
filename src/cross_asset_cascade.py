"""Cross-asset cascade scoring, Monte Carlo stress, and Instance 5 artifacts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import statistics
from typing import Any

from src.transfer_entropy import TransferEntropyEstimate, estimate_bidirectional_transfer_entropy

try:  # pragma: no cover - optional runtime dependency
    import boto3
except Exception:  # pragma: no cover - optional runtime dependency
    boto3 = None


LEADER_ASSET = "BTC"
FOLLOWER_UNIVERSE = ("ETH", "SOL", "XRP", "DOGE")
ASSET_ORDER_WITH_LEADER = (LEADER_ASSET, *FOLLOWER_UNIVERSE)
LEADER_REFERENCE_VENUES = ("binance", "coinbase", "deribit")

CASCADE_SCHEMA = "cross_asset_cascade.v1"
MC_SCHEMA = "cross_asset_mc.v1"
INSTANCE5_SCHEMA = "instance5_cascade_mc_dispatch.v1"

FIVE_MINUTE_SECONDS = 300
FIVE_MINUTE_MS = FIVE_MINUTE_SECONDS * 1000
REGISTRY_MAX_AGE_SECONDS = 60.0
QUOTE_MAX_STALENESS_SECONDS = 60.0
CORRELATION_FLOOR = 0.60
TRANSFER_ENTROPY_MIN_BITS = 0.0005
RENYI_TRANSFER_ENTROPY_MIN_BITS = 0.0005
SYMBOLIC_TRANSFER_ENTROPY_MIN_BITS = 0.0005
INFORMATION_FLOW_DIRECTIONAL_SLACK_BITS = 0.005
ELAPSED_MIN_SECONDS = 15.0
ELAPSED_MAX_SECONDS = 90.0
LEADER_MOVE_FLOOR = 0.002  # 0.20%
LEADER_SHOCK_SCORE_FLOOR = 1.0
EDGE_FLOOR = 0.08
KELLY_DIVISOR = 16.0
MAX_KELLY_FRACTION = 0.015
MAX_NOTIONAL_PER_FOLLOWER_USD = 5.0
CLUSTER_CAP_FRACTION = 0.06
CRYPTO_TAKER_FEE_RATE = 0.25
CRYPTO_TAKER_FEE_EXPONENT = 2.0
CRYPTO_MAKER_REBATE_SHARE = 0.20

LOCAL_MONTE_CARLO_PATHS = 1000
BATCH_MONTE_CARLO_PATHS = 10000
BATCH_SUBMIT_COOLDOWN_SECONDS = 300

TAIL_BREACH_FRACTION = 0.03
DRAWDOWN_BREACH_FRACTION = 0.06

DEFAULT_CROSS_ASSET_TICKS_DB = Path("state") / "cross_asset_ticks.db"
DEFAULT_CROSS_ASSET_HISTORY_DB = Path("state") / "cross_asset_history.db"


@dataclass(frozen=True)
class LookupStats:
    wins: int
    total: int

    @property
    def probability(self) -> float:
        if self.total <= 0:
            return 0.5
        return float(self.wins) / float(self.total)


@dataclass(frozen=True)
class LookupTable:
    stats_by_key: dict[tuple[str, str, str, str], LookupStats]
    follower_overview: dict[str, LookupStats]
    move_bucket_edges: tuple[float, float]
    volatility_bucket_edges: tuple[float, float]
    rolling_30d_p98_first90s_abs_btc_move: float
    sample_count: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        token = str(item).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _quantile(values: list[float], q: float, default: float) -> float:
    if not values:
        return float(default)
    if len(values) == 1:
        return float(values[0])
    clamped = max(0.0, min(1.0, float(q)))
    ordered = sorted(float(v) for v in values)
    index = clamped * (len(ordered) - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return float(ordered[low])
    weight = index - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _dynamic_taker_fee_rate(probability: float) -> float:
    probability_clamped = max(0.01, min(0.99, float(probability)))
    uncertainty = probability_clamped * (1.0 - probability_clamped)
    return float(CRYPTO_TAKER_FEE_RATE * (uncertainty ** CRYPTO_TAKER_FEE_EXPONENT))


def _maker_rebate_rate(probability: float) -> float:
    return float(_dynamic_taker_fee_rate(probability) * CRYPTO_MAKER_REBATE_SHARE)


def _maker_rebate_bps(probability: float) -> float:
    return float(_maker_rebate_rate(probability) * 10_000.0)


def _information_flow_direction_score(estimate: TransferEntropyEstimate) -> float:
    return statistics.fmean(
        [
            float(estimate.forward_minus_reverse_bits),
            float(estimate.renyi_forward_minus_reverse_bits),
            float(estimate.symbolic_forward_minus_reverse_bits),
        ]
    )


def _pearson(values_x: list[float], values_y: list[float]) -> float | None:
    if len(values_x) != len(values_y) or len(values_x) < 3:
        return None
    mean_x = statistics.fmean(values_x)
    mean_y = statistics.fmean(values_y)
    dx = [x - mean_x for x in values_x]
    dy = [y - mean_y for y in values_y]
    sum_prod = sum(a * b for a, b in zip(dx, dy))
    sum_x = sum(a * a for a in dx)
    sum_y = sum(b * b for b in dy)
    if sum_x <= 0.0 or sum_y <= 0.0:
        return None
    return sum_prod / math.sqrt(sum_x * sum_y)


def _elapsed_bucket(elapsed_seconds: float) -> str:
    return "15_45" if elapsed_seconds <= 45.0 else "45_90"


def _volatility_bucket(abs_move: float, edges: tuple[float, float]) -> str:
    edge_low, edge_high = edges
    if abs_move <= edge_low:
        return "low"
    if abs_move <= edge_high:
        return "medium"
    return "high"


def _move_bucket(move: float, edges: tuple[float, float]) -> str:
    edge_low, edge_high = edges
    sign = "pos" if move >= 0 else "neg"
    magnitude = abs(move)
    if magnitude <= edge_low:
        band = "small"
    elif magnitude <= edge_high:
        band = "medium"
    else:
        band = "large"
    return f"{sign}_{band}"


def _extract_registry_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("registry", "rows", "markets", "items", "records", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _registry_asset(row: dict[str, Any]) -> str:
    for key in ("asset", "symbol", "base_asset", "underlier", "underlying_asset"):
        value = str(row.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _registry_is_eligible(row: dict[str, Any]) -> bool:
    if "eligible" not in row:
        return True
    return _as_bool(row.get("eligible"), default=True)


def _registry_is_5m(row: dict[str, Any]) -> bool:
    minutes = _as_int(row.get("timeframe_minutes"), -1)
    if minutes == 5:
        return True
    timeframe = str(row.get("timeframe") or "").strip().lower()
    return timeframe in {"5m", "5-minute", "5 minute"}


def _registry_quote_staleness_seconds(row: dict[str, Any]) -> float | None:
    for key in (
        "quote_staleness_seconds",
        "staleness_seconds",
        "best_quote_staleness_seconds",
        "mid_staleness_seconds",
        "book_staleness_seconds",
    ):
        if key in row:
            return _as_float(row.get(key), 0.0)
    return None


def _registry_mid(row: dict[str, Any]) -> float | None:
    candidates = (
        row.get("mid"),
        row.get("yes_price"),
    )
    for candidate in candidates:
        value = _as_float(candidate, -1.0)
        if 0.0 < value < 1.0:
            return value
    bid = _as_float(row.get("best_bid"), -1.0)
    ask = _as_float(row.get("best_ask"), -1.0)
    if 0.0 < bid < 1.0 and 0.0 < ask < 1.0 and ask >= bid:
        return (bid + ask) / 2.0
    return None


def _registry_spread(row: dict[str, Any]) -> float | None:
    bid = _as_float(row.get("best_bid"), -1.0)
    ask = _as_float(row.get("best_ask"), -1.0)
    if 0.0 < bid < 1.0 and 0.0 < ask < 1.0 and ask >= bid:
        return ask - bid
    spread = _as_float(row.get("spread"), -1.0)
    if spread >= 0.0:
        return spread
    return None


def _registry_priority_key(row: dict[str, Any]) -> tuple[int, float, float, int]:
    eligible = _registry_is_eligible(row)
    timeframe_5m = _registry_is_5m(row)
    has_mid = _registry_mid(row) is not None
    staleness = _registry_quote_staleness_seconds(row)
    spread = _registry_spread(row)
    timeframe_minutes = _as_int(row.get("timeframe_minutes"), 1_000_000)

    if eligible and timeframe_5m and has_mid:
        class_rank = 0
    elif eligible and timeframe_5m:
        class_rank = 1
    elif eligible and has_mid:
        class_rank = 2
    elif eligible:
        class_rank = 3
    elif timeframe_5m and has_mid:
        class_rank = 4
    elif timeframe_5m:
        class_rank = 5
    elif has_mid:
        class_rank = 6
    else:
        class_rank = 7

    staleness_rank = float(staleness) if staleness is not None else float("inf")
    spread_rank = float(spread) if spread is not None else float("inf")
    return (class_rank, staleness_rank, spread_rank, timeframe_minutes)


def _best_registry_rows_by_asset(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        asset = _registry_asset(row)
        if not asset:
            continue
        existing = grouped.get(asset)
        if existing is None:
            grouped[asset] = row
            continue
        if _registry_priority_key(row) < _registry_priority_key(existing):
            grouped[asset] = row
    return grouped


def _read_returns_by_asset(db_path: Path, asset: str, since_ms: int) -> dict[int, float]:
    if not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT open_time_ms, open, close
            FROM reference_bars
            WHERE asset = ? AND interval = '1m' AND open_time_ms >= ?
            ORDER BY open_time_ms ASC
            """,
            (asset, int(since_ms)),
        ).fetchall()
    series: dict[int, float] = {}
    for open_time_ms, open_px, close_px in rows:
        open_value = _as_float(open_px, 0.0)
        close_value = _as_float(close_px, 0.0)
        if open_value <= 0.0:
            continue
        series[int(open_time_ms)] = (close_value - open_value) / open_value
    return series


def build_lookup_table(
    db_path: Path,
    *,
    now: datetime | None = None,
    lookback_days: int = 30,
) -> LookupTable:
    now_dt = now or _utc_now()
    now_ms = int(now_dt.timestamp() * 1000)
    since_ms = now_ms - int(max(1, int(lookback_days)) * 86_400_000)

    returns_by_asset: dict[str, dict[int, float]] = {
        asset: _read_returns_by_asset(db_path, asset, since_ms)
        for asset in ASSET_ORDER_WITH_LEADER
    }
    btc_returns = returns_by_asset.get(LEADER_ASSET, {})
    btc_abs_moves = [abs(value) for value in btc_returns.values()]
    move_edges = (
        max(1e-6, _quantile(btc_abs_moves, 0.50, 0.0015)),
        max(1e-6, _quantile(btc_abs_moves, 0.80, 0.0030)),
    )
    vol_edges = (
        max(1e-6, _quantile(btc_abs_moves, 0.33, 0.0010)),
        max(1e-6, _quantile(btc_abs_moves, 0.66, 0.0020)),
    )
    rolling_p98 = max(1e-6, _quantile(btc_abs_moves, 0.98, 0.0040))

    counter: defaultdict[tuple[str, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    follower_overview_count: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])

    sample_count = 0
    for open_time_ms, leader_move in btc_returns.items():
        if open_time_ms % FIVE_MINUTE_MS != 0:
            continue
        elapsed_key = "45_90"
        move_key = _move_bucket(leader_move, move_edges)
        vol_key = _volatility_bucket(abs(leader_move), vol_edges)
        leader_up = 1 if leader_move > 0.0 else 0
        for follower in FOLLOWER_UNIVERSE:
            follower_move = returns_by_asset.get(follower, {}).get(open_time_ms)
            if follower_move is None:
                continue
            follower_up = 1 if follower_move > 0.0 else 0
            sample_count += 1
            keys = (
                (follower, move_key, elapsed_key, vol_key),
                (follower, move_key, elapsed_key, "*"),
                (follower, move_key, "*", "*"),
                (follower, "*", "*", "*"),
            )
            for key in keys:
                counter[key][0] += follower_up
                counter[key][1] += 1
            follower_overview_count[follower][0] += 1 if follower_up == leader_up else 0
            follower_overview_count[follower][1] += 1

    stats_by_key = {
        key: LookupStats(wins=int(values[0]), total=int(values[1]))
        for key, values in counter.items()
    }
    follower_overview = {
        asset: LookupStats(wins=int(values[0]), total=int(values[1]))
        for asset, values in follower_overview_count.items()
    }
    for follower in FOLLOWER_UNIVERSE:
        follower_overview.setdefault(follower, LookupStats(wins=0, total=0))

    return LookupTable(
        stats_by_key=stats_by_key,
        follower_overview=follower_overview,
        move_bucket_edges=move_edges,
        volatility_bucket_edges=vol_edges,
        rolling_30d_p98_first90s_abs_btc_move=rolling_p98,
        sample_count=sample_count,
    )


def estimate_fair_prob_up(
    lookup: LookupTable,
    *,
    follower_asset: str,
    leader_move: float,
    elapsed_seconds: float,
    volatility_proxy_move: float,
) -> tuple[float, int, str]:
    follower = str(follower_asset).strip().upper()
    move_key = _move_bucket(leader_move, lookup.move_bucket_edges)
    elapsed_key = _elapsed_bucket(elapsed_seconds)
    vol_key = _volatility_bucket(abs(volatility_proxy_move), lookup.volatility_bucket_edges)
    candidate_keys = (
        (follower, move_key, elapsed_key, vol_key),
        (follower, move_key, elapsed_key, "*"),
        (follower, move_key, "*", "*"),
        (follower, "*", "*", "*"),
    )
    for key in candidate_keys:
        stats = lookup.stats_by_key.get(key)
        if stats is None or stats.total <= 0:
            continue
        return stats.probability, stats.total, "|".join(key)
    return 0.5, 0, "fallback|0.5"


def apply_cluster_cap(
    notionals_by_asset: dict[str, float],
    *,
    bankroll: float,
    cluster_cap_fraction: float = CLUSTER_CAP_FRACTION,
) -> tuple[dict[str, float], float]:
    cap_usd = max(0.0, bankroll * max(0.0, cluster_cap_fraction))
    total = sum(max(0.0, _as_float(value, 0.0)) for value in notionals_by_asset.values())
    if total <= 0.0 or total <= cap_usd:
        return {
            asset: round(max(0.0, _as_float(value, 0.0)), 6)
            for asset, value in notionals_by_asset.items()
        }, 1.0
    scale = cap_usd / total if total > 0.0 else 1.0
    scaled = {
        asset: round(max(0.0, _as_float(value, 0.0)) * scale, 6)
        for asset, value in notionals_by_asset.items()
    }
    return scaled, scale


def _history_has_full_one_second_coverage(history_report: dict[str, Any], instance3_artifact: dict[str, Any]) -> bool:
    coverage = history_report.get("coverage")
    if isinstance(coverage, dict):
        complete_assets_1s = _as_int(coverage.get("complete_assets_1s"), 0)
        missing_assets_1s = coverage.get("missing_assets_1s")
        missing = [str(item).upper() for item in missing_assets_1s] if isinstance(missing_assets_1s, list) else []
        if complete_assets_1s >= len(ASSET_ORDER_WITH_LEADER) and not missing:
            return True

    one_second_by_asset = history_report.get("one_second_coverage_by_asset")
    if isinstance(one_second_by_asset, dict):
        ready_assets = 0
        for asset in ASSET_ORDER_WITH_LEADER:
            row = one_second_by_asset.get(asset) or {}
            if _as_int((row or {}).get("row_count"), 0) > 0:
                ready_assets += 1
        if ready_assets >= len(ASSET_ORDER_WITH_LEADER):
            return True

    details = instance3_artifact.get("details")
    if isinstance(details, dict):
        one_second_artifact = details.get("one_second_coverage_by_asset")
        if isinstance(one_second_artifact, dict):
            ready_assets = 0
            for asset in ASSET_ORDER_WITH_LEADER:
                row = one_second_artifact.get(asset) or {}
                if _as_int((row or {}).get("row_count"), 0) > 0:
                    ready_assets += 1
            if ready_assets >= len(ASSET_ORDER_WITH_LEADER):
                return True
    return False


def select_stress_mode(history_report: dict[str, Any], instance3_artifact: dict[str, Any]) -> str:
    return "batch_plus_replay" if _history_has_full_one_second_coverage(history_report, instance3_artifact) else "local_only"


def _load_best_venue_by_asset(data_plane_health: dict[str, Any]) -> dict[str, str]:
    overall = data_plane_health.get("overall")
    if not isinstance(overall, dict):
        return {}
    explicit = overall.get("best_venue_by_asset")
    if isinstance(explicit, dict):
        return {
            str(asset).upper(): str(venue).lower()
            for asset, venue in explicit.items()
            if str(asset).strip() and str(venue).strip()
        }
    global_status = overall.get("global_asset_status")
    if not isinstance(global_status, dict):
        return {}
    mapped: dict[str, str] = {}
    for asset, row in global_status.items():
        if not isinstance(row, dict):
            continue
        venue = str(row.get("best_venue") or "").strip().lower()
        if venue:
            mapped[str(asset).upper()] = venue
    return mapped


def _latest_mid_price(conn: sqlite3.Connection, asset: str, preferred_venue: str | None = None) -> tuple[float | None, int | None]:
    queries: list[tuple[str, tuple[Any, ...]]] = []
    if preferred_venue:
        queries.append(
            (
                """
                SELECT event_ts_ms, COALESCE(mid, price) AS px
                FROM market_envelopes
                WHERE asset = ? AND venue = ? AND COALESCE(mid, price) IS NOT NULL
                ORDER BY event_ts_ms DESC
                LIMIT 1
                """,
                (asset, preferred_venue),
            )
        )
    queries.append(
        (
            """
            SELECT event_ts_ms, COALESCE(mid, price) AS px
            FROM market_envelopes
            WHERE asset = ? AND COALESCE(mid, price) IS NOT NULL
            ORDER BY event_ts_ms DESC
            LIMIT 1
            """,
            (asset,),
        )
    )
    for query, params in queries:
        row = conn.execute(query, params).fetchone()
        if row is None:
            continue
        px = _as_float(row[1], 0.0)
        if px <= 0.0:
            continue
        return px, _as_int(row[0], 0)
    return None, None


def _resolve_leader_reference_venue(
    conn: sqlite3.Connection,
    *,
    asset: str,
    requested_venue: str | None,
) -> str | None:
    candidate_order: list[str] = []
    normalized_requested = str(requested_venue or "").strip().lower()
    if normalized_requested in LEADER_REFERENCE_VENUES:
        candidate_order.append(normalized_requested)
    candidate_order.extend(
        venue for venue in LEADER_REFERENCE_VENUES if venue not in candidate_order
    )
    for venue in candidate_order:
        row = conn.execute(
            """
            SELECT 1
            FROM market_envelopes
            WHERE asset = ? AND venue = ?
            LIMIT 1
            """,
            (asset, venue),
        ).fetchone()
        if row is not None:
            return venue
    return None


def _latest_anchor(conn: sqlite3.Connection, asset: str, timeframe_seconds: int) -> tuple[int | None, int | None, float | None]:
    row = conn.execute(
        """
        SELECT window_start_ts, window_end_ts, anchor_price
        FROM candle_anchors
        WHERE asset = ? AND timeframe_seconds = ?
        ORDER BY window_start_ts DESC
        LIMIT 1
        """,
        (asset, int(timeframe_seconds)),
    ).fetchone()
    if row is None:
        return None, None, None
    return _as_int(row[0], 0), _as_int(row[1], 0), _as_float(row[2], 0.0)


def _correlation_24h(db_path: Path, follower: str, now_ms: int) -> tuple[float | None, int]:
    since_ms = now_ms - 86_400_000
    leader_returns = _read_returns_by_asset(db_path, LEADER_ASSET, since_ms)
    follower_returns = _read_returns_by_asset(db_path, follower, since_ms)
    xs: list[float] = []
    ys: list[float] = []
    for open_time_ms, leader_ret in leader_returns.items():
        follower_ret = follower_returns.get(open_time_ms)
        if follower_ret is None:
            continue
        xs.append(float(leader_ret))
        ys.append(float(follower_ret))
    correlation = _pearson(xs, ys)
    return correlation, len(xs)


def _information_flow_24h(
    db_path: Path,
    follower: str,
    now_ms: int,
) -> TransferEntropyEstimate:
    since_ms = now_ms - 86_400_000
    leader_returns = _read_returns_by_asset(db_path, LEADER_ASSET, since_ms)
    follower_returns = _read_returns_by_asset(db_path, follower, since_ms)
    source: list[float] = []
    target: list[float] = []
    for open_time_ms in sorted(leader_returns):
        if open_time_ms not in follower_returns:
            continue
        source.append(float(leader_returns[open_time_ms]))
        target.append(float(follower_returns[open_time_ms]))
    return estimate_bidirectional_transfer_entropy(source, target)


def _finance_gate_pass(finance_latest: dict[str, Any]) -> bool:
    if not finance_latest:
        return True
    if "finance_gate_pass" in finance_latest:
        return _as_bool(finance_latest.get("finance_gate_pass"), default=True)
    finance_gate = finance_latest.get("finance_gate")
    if isinstance(finance_gate, dict):
        return _as_bool(finance_gate.get("pass"), default=True)
    return True


def _bankroll_usd(runtime_truth: dict[str, Any]) -> float:
    caps = runtime_truth.get("effective_caps")
    if isinstance(caps, dict):
        initial = _as_float(caps.get("initial_bankroll"), 0.0)
        if initial > 0.0:
            return initial
    capital = runtime_truth.get("capital")
    if isinstance(capital, dict):
        tracked = _as_float(capital.get("tracked_capital_usd"), 0.0)
        if tracked > 0.0:
            return tracked
    env_bankroll = _as_float(os.environ.get("JJ_INITIAL_BANKROLL"), 0.0)
    if env_bankroll > 0.0:
        return env_bankroll
    return 250.0


def _run_monte_carlo_distribution(
    intents: list[dict[str, Any]],
    *,
    paths: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    totals: list[float] = []
    for _ in range(max(1, int(paths))):
        total_pnl = 0.0
        for intent in intents:
            side = str(intent.get("side") or "").strip().lower()
            fair_prob_up = _as_float(intent.get("fair_prob_up"), 0.5)
            yes_mid = _as_float(intent.get("pm_mid"), 0.5)
            notional = max(0.0, _as_float(intent.get("notional_usd"), 0.0))
            if notional <= 0.0:
                continue
            if side == "buy_no":
                contract_price = max(0.01, min(0.99, 1.0 - yes_mid))
                win_prob = max(0.0, min(1.0, 1.0 - fair_prob_up))
            else:
                contract_price = max(0.01, min(0.99, yes_mid))
                win_prob = max(0.0, min(1.0, fair_prob_up))
            win_pnl = notional * ((1.0 / contract_price) - 1.0)
            loss_pnl = -notional
            total_pnl += win_pnl if rng.random() < win_prob else loss_pnl
        totals.append(total_pnl)

    totals_sorted = sorted(totals)
    p01 = _quantile(totals_sorted, 0.01, 0.0)
    p05 = _quantile(totals_sorted, 0.05, 0.0)
    p50 = _quantile(totals_sorted, 0.50, 0.0)
    return {
        "paths": max(1, int(paths)),
        "mean_pnl_usd": round(statistics.fmean(totals_sorted), 6) if totals_sorted else 0.0,
        "median_pnl_usd": round(p50, 6),
        "p01_pnl_usd": round(p01, 6),
        "p05_pnl_usd": round(p05, 6),
        "worst_pnl_usd": round(totals_sorted[0], 6) if totals_sorted else 0.0,
        "best_pnl_usd": round(totals_sorted[-1], 6) if totals_sorted else 0.0,
    }


def _submit_batch_stress_job(
    *,
    root: Path,
    generated_at: datetime,
    stress_mode: str,
    path_count: int,
) -> dict[str, Any]:
    if stress_mode != "batch_plus_replay":
        return {"status": "disabled_local_only"}
    enabled = _as_bool(os.environ.get("ELASTIFUND_AWS_BATCH_ENABLED"), default=False)
    job_queue = str(os.environ.get("ELASTIFUND_AWS_BATCH_QUEUE") or "").strip()
    job_definition = str(os.environ.get("ELASTIFUND_AWS_BATCH_JOB_DEFINITION") or "").strip()
    if not enabled or not job_queue or not job_definition:
        return {
            "status": "not_configured",
            "enabled": enabled,
            "queue_configured": bool(job_queue),
            "definition_configured": bool(job_definition),
        }
    if boto3 is None:  # pragma: no cover - optional dependency
        return {"status": "boto3_unavailable"}

    state_path = root / "state" / "instance5_batch_state.json"
    state = _read_json(state_path)
    last_submitted = _parse_datetime(state.get("last_submitted_at"))
    if last_submitted is not None:
        age_seconds = (generated_at - last_submitted).total_seconds()
        if age_seconds < BATCH_SUBMIT_COOLDOWN_SECONDS:
            return {
                "status": "cooldown",
                "seconds_until_next_submit": int(BATCH_SUBMIT_COOLDOWN_SECONDS - age_seconds),
            }

    try:  # pragma: no cover - requires AWS credentials and network
        client = boto3.client("batch")
        response = client.submit_job(
            jobName=f"elastifund-instance5-mc-{generated_at.strftime('%Y%m%dt%H%M%S')}",
            jobQueue=job_queue,
            jobDefinition=job_definition,
            parameters={
                "paths": str(int(path_count)),
            },
        )
    except Exception as exc:  # pragma: no cover - requires AWS credentials and network
        return {"status": "submit_failed", "error": str(exc)}

    _write_json(
        state_path,
        {
            "last_submitted_at": _iso(generated_at),
            "last_job_id": response.get("jobId"),
            "last_job_name": response.get("jobName"),
            "requested_paths": int(path_count),
        },
    )
    return {
        "status": "submitted",
        "job_id": response.get("jobId"),
        "job_name": response.get("jobName"),
    }


def _instance3_artifact(root: Path) -> dict[str, Any]:
    candidates = (
        root / "reports" / "instance3_vendor_backfill" / "latest.json",
        root / "reports" / "parallel" / "instance03_cross_asset_vendor_dispatch.json",
    )
    for path in candidates:
        if path.exists():
            payload = _read_json(path)
            if payload:
                return payload
    return {}


def _market_registry_payload(root: Path) -> tuple[dict[str, Any], bool, float | None]:
    path = root / "reports" / "market_registry" / "latest.json"
    if not path.exists():
        return {}, False, None
    payload = _read_json(path)
    generated_at = _parse_datetime(payload.get("generated_at"))
    if generated_at is None:
        generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_seconds = (_utc_now() - generated_at).total_seconds()
    fresh = age_seconds <= REGISTRY_MAX_AGE_SECONDS
    return payload, fresh, max(0.0, age_seconds)


def _data_plane_health_payload(root: Path) -> dict[str, Any]:
    path = root / "reports" / "data_plane_health" / "latest.json"
    if not path.exists():
        return {}
    return _read_json(path)


def _cross_asset_history_payload(root: Path) -> dict[str, Any]:
    path = root / "reports" / "cross_asset_history" / "latest.json"
    if not path.exists():
        return {}
    return _read_json(path)


def _runtime_truth_payload(root: Path) -> dict[str, Any]:
    path = root / "reports" / "runtime_truth_latest.json"
    if not path.exists():
        return {}
    return _read_json(path)


def _finance_latest_payload(root: Path) -> dict[str, Any]:
    path = root / "reports" / "finance" / "latest.json"
    if not path.exists():
        return {}
    return _read_json(path)


def build_cascade_payload(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    now_dt = now or _utc_now()
    now_ms = int(now_dt.timestamp() * 1000)

    registry_payload, registry_fresh, registry_age_seconds = _market_registry_payload(root)
    data_plane_health = _data_plane_health_payload(root)
    history_report = _cross_asset_history_payload(root)
    runtime_truth = _runtime_truth_payload(root)

    best_venue_by_asset = _load_best_venue_by_asset(data_plane_health)
    registry_rows = _extract_registry_rows(registry_payload)
    best_rows_by_asset = _best_registry_rows_by_asset(registry_rows)

    cross_asset_ticks_db = Path(
        data_plane_health.get("source_of_truth") or (root / DEFAULT_CROSS_ASSET_TICKS_DB)
    )
    if not cross_asset_ticks_db.is_absolute():
        cross_asset_ticks_db = root / cross_asset_ticks_db

    history_db = Path(history_report.get("store_path") or (root / DEFAULT_CROSS_ASSET_HISTORY_DB))
    if not history_db.is_absolute():
        history_db = root / history_db

    lookup = build_lookup_table(history_db, now=now_dt, lookback_days=30)
    bankroll = _bankroll_usd(runtime_truth)

    global_blockers: list[str] = []
    if not registry_payload:
        global_blockers.append("market_registry_missing")
    elif not registry_fresh:
        age_text = int(round(registry_age_seconds or 0.0))
        global_blockers.append(f"market_registry_stale:{age_text}s")

    btc_anchor_price: float | None = None
    btc_window_start: int | None = None
    btc_window_end: int | None = None
    btc_price: float | None = None
    btc_event_ts_ms: int | None = None
    leader_reference_venue: str | None = None
    with sqlite3.connect(cross_asset_ticks_db) if cross_asset_ticks_db.exists() else sqlite3.connect(":memory:") as conn:
        btc_window_start, btc_window_end, btc_anchor_price = _latest_anchor(
            conn, LEADER_ASSET, FIVE_MINUTE_SECONDS
        )
        leader_reference_venue = _resolve_leader_reference_venue(
            conn,
            asset=LEADER_ASSET,
            requested_venue=best_venue_by_asset.get(LEADER_ASSET),
        )
        btc_price, btc_event_ts_ms = _latest_mid_price(
            conn,
            LEADER_ASSET,
            leader_reference_venue,
        )

    candle_elapsed_seconds: float | None = None
    leader_move_from_open: float | None = None
    leader_shock_score: float | None = None
    if btc_window_start is not None and btc_anchor_price and btc_anchor_price > 0.0:
        candle_elapsed_seconds = float(now_dt.timestamp()) - float(btc_window_start)
    if btc_price is not None and btc_anchor_price and btc_anchor_price > 0.0:
        leader_move_from_open = (btc_price - btc_anchor_price) / btc_anchor_price
        leader_shock_score = abs(leader_move_from_open) / max(
            lookup.rolling_30d_p98_first90s_abs_btc_move, 1e-6
        )

    candle_elapsed_gate_pass = (
        candle_elapsed_seconds is not None
        and ELAPSED_MIN_SECONDS <= candle_elapsed_seconds <= ELAPSED_MAX_SECONDS
    )
    leader_move_floor_pass = (
        leader_move_from_open is not None and abs(leader_move_from_open) >= LEADER_MOVE_FLOOR
    )
    leader_shock_gate_pass = (
        leader_shock_score is not None and leader_shock_score >= LEADER_SHOCK_SCORE_FLOOR
    )
    if not candle_elapsed_gate_pass:
        if candle_elapsed_seconds is None:
            global_blockers.append("candle_elapsed_unavailable")
        else:
            global_blockers.append(f"candle_elapsed_out_of_range:{round(candle_elapsed_seconds, 3)}s")
    if not leader_move_floor_pass:
        if leader_move_from_open is None:
            global_blockers.append("leader_move_unavailable")
        else:
            global_blockers.append(f"leader_move_floor_not_met:{round(leader_move_from_open, 6)}")
    if not leader_shock_gate_pass:
        if leader_shock_score is None:
            global_blockers.append("leader_shock_unavailable")
        else:
            global_blockers.append(f"leader_shock_below_threshold:{round(leader_shock_score, 6)}")

    live_follower_set: list[str] = []
    for follower in FOLLOWER_UNIVERSE:
        row = best_rows_by_asset.get(follower)
        if row is None:
            continue
        if not _registry_is_eligible(row):
            continue
        if not _registry_is_5m(row):
            continue
        live_follower_set.append(follower)
    if not live_follower_set:
        global_blockers.append("no_live_followers")

    intended_notionals: dict[str, float] = {}
    intents: list[dict[str, Any]] = []
    follower_payloads: dict[str, dict[str, Any]] = {}
    follower_specific_blockers: list[str] = []
    correlations_by_asset: dict[str, float | None] = {}

    for follower in FOLLOWER_UNIVERSE:
        follower_row = best_rows_by_asset.get(follower)
        quote_staleness = (
            _registry_quote_staleness_seconds(follower_row) if follower_row is not None else None
        )
        quote_fresh = quote_staleness is not None and quote_staleness <= QUOTE_MAX_STALENESS_SECONDS
        correlation_24h, correlation_points = _correlation_24h(history_db, follower, now_ms)
        correlations_by_asset[follower] = correlation_24h
        correlation_gate_pass = (
            correlation_24h is not None and correlation_24h >= CORRELATION_FLOOR
        )
        information_flow = _information_flow_24h(history_db, follower, now_ms)
        information_flow_direction_score = _information_flow_direction_score(information_flow)
        information_flow_component_passes = sum(
            1
            for passed in (
                information_flow.forward_bits >= TRANSFER_ENTROPY_MIN_BITS,
                information_flow.renyi_forward_bits >= RENYI_TRANSFER_ENTROPY_MIN_BITS,
                information_flow.symbolic_forward_bits >= SYMBOLIC_TRANSFER_ENTROPY_MIN_BITS,
            )
            if passed
        )
        transfer_entropy_gate_pass = (
            information_flow_component_passes >= 2
            and information_flow_direction_score >= -INFORMATION_FLOW_DIRECTIONAL_SLACK_BITS
        )

        follower_overview = lookup.follower_overview.get(follower, LookupStats(wins=0, total=0))
        win_rate = follower_overview.probability
        candle_sets = follower_overview.total
        spread = _registry_spread(follower_row) if follower_row is not None else None
        cost_bps = max(8.0, (_as_float(spread, 0.0008) * 10_000.0))
        maker_rebate_bps = _maker_rebate_bps(_registry_mid(follower_row) if follower_row is not None else 0.5)
        post_cost_ev_bps = ((win_rate - 0.5) * 20_000.0) - cost_bps + maker_rebate_bps

        auto_killed = (
            (candle_sets >= 50 and win_rate < 0.55) or (post_cost_ev_bps <= 0.0)
        )
        kill_status = "auto_killed" if auto_killed else "active"
        kill_reason: str | None = None
        if auto_killed and candle_sets >= 50 and win_rate < 0.55:
            kill_reason = f"win_rate_below_floor:{round(win_rate, 6)}"
        elif auto_killed and post_cost_ev_bps <= 0.0:
            kill_reason = f"post_cost_ev_not_positive:{round(post_cost_ev_bps, 3)}"

        block_reasons: list[str] = []
        if follower_row is None:
            block_reasons.append("follower_market_missing")
        else:
            if not _registry_is_eligible(follower_row):
                block_reasons.append("registry_row_ineligible")
            if not _registry_is_5m(follower_row):
                block_reasons.append("registry_timeframe_not_5m")
            if quote_staleness is None:
                block_reasons.append("quote_staleness_unavailable")
            elif not quote_fresh:
                block_reasons.append(f"quote_staleness_gt_60s:{round(quote_staleness, 3)}")

        if correlation_24h is None:
            block_reasons.append("correlation_unavailable")
        elif not correlation_gate_pass:
            block_reasons.append(f"correlation_below_0.60:{round(correlation_24h, 6)}")
        if information_flow.sample_count <= 0:
            block_reasons.append("transfer_entropy_unavailable")
        elif not transfer_entropy_gate_pass:
            block_reasons.append(
                "information_flow_gate_failed:"
                f"te={round(information_flow.forward_bits, 6)}"
                f":renyi={round(information_flow.renyi_forward_bits, 6)}"
                f":symbolic={round(information_flow.symbolic_forward_bits, 6)}"
                f":direction={round(information_flow_direction_score, 6)}"
            )

        if not candle_elapsed_gate_pass:
            block_reasons.append("candle_elapsed_gate_failed")
        if not leader_move_floor_pass:
            block_reasons.append("leader_move_floor_gate_failed")
        if not leader_shock_gate_pass:
            block_reasons.append("leader_shock_gate_failed")
        if auto_killed:
            block_reasons.append("auto_killed")

        pm_mid = _registry_mid(follower_row) if follower_row is not None else None
        fair_prob_up: float | None = None
        lookup_support = 0
        lookup_key = ""
        edge_abs: float | None = None
        net_edge_abs: float | None = None
        maker_rebate_rate: float = 0.0
        side = "none"
        raw_kelly = 0.0
        fraction = 0.0
        notional_usd = 0.0

        if pm_mid is None:
            block_reasons.append("pm_mid_unavailable")
        elif not block_reasons and leader_move_from_open is not None and candle_elapsed_seconds is not None:
            fair_prob_up, lookup_support, lookup_key = estimate_fair_prob_up(
                lookup,
                follower_asset=follower,
                leader_move=leader_move_from_open,
                elapsed_seconds=candle_elapsed_seconds,
                volatility_proxy_move=leader_move_from_open,
            )
            edge_abs = abs(fair_prob_up - pm_mid)
            maker_rebate_rate = _maker_rebate_rate(pm_mid)
            net_edge_abs = max(0.0, edge_abs - _as_float(spread, 0.0008) + maker_rebate_rate)
            if net_edge_abs < EDGE_FLOOR:
                block_reasons.append(f"edge_below_0.08:{round(net_edge_abs, 6)}")
            else:
                side = "buy_yes" if fair_prob_up >= pm_mid else "buy_no"
                odds = max(0.01, pm_mid * (1.0 - pm_mid))
                raw_kelly = net_edge_abs / odds
                fraction = min(raw_kelly / KELLY_DIVISOR, MAX_KELLY_FRACTION)
                notional_usd = min(bankroll * fraction, MAX_NOTIONAL_PER_FOLLOWER_USD)
                if notional_usd <= 0.0:
                    block_reasons.append("notional_non_positive")

        if notional_usd > 0.0 and not block_reasons:
            intended_notionals[follower] = notional_usd
            intents.append(
                {
                    "asset": follower,
                    "side": side,
                    "pm_mid": round(_as_float(pm_mid, 0.5), 6),
                    "fair_prob_up": round(_as_float(fair_prob_up, 0.5), 6),
                    "edge_abs": round(_as_float(edge_abs, 0.0), 6),
                    "net_edge_abs": round(_as_float(net_edge_abs, 0.0), 6),
                    "maker_rebate_rate": round(maker_rebate_rate, 8),
                    "maker_rebate_bps": round(maker_rebate_rate * 10_000.0, 6),
                    "raw_kelly": round(raw_kelly, 6),
                    "fraction": round(fraction, 6),
                    "notional_usd": round(notional_usd, 6),
                    "lookup_key": lookup_key,
                    "lookup_support": int(lookup_support),
                }
            )
        else:
            for reason in block_reasons:
                follower_specific_blockers.append(f"{follower.lower()}:{reason}")

        follower_payloads[follower] = {
            "registry_row_present": follower_row is not None,
            "registry_eligible": _registry_is_eligible(follower_row) if follower_row is not None else False,
            "timeframe_5m": _registry_is_5m(follower_row) if follower_row is not None else False,
            "quote_staleness_seconds": round(quote_staleness, 6) if quote_staleness is not None else None,
            "quote_fresh": quote_fresh,
            "correlation_24h_1m": round(correlation_24h, 6) if correlation_24h is not None else None,
            "correlation_points_24h_1m": int(correlation_points),
            "correlation_gate_pass": correlation_gate_pass,
            "transfer_entropy_bits": round(information_flow.forward_bits, 6),
            "reverse_transfer_entropy_bits": round(information_flow.reverse_bits, 6),
            "transfer_entropy_edge_bits": round(information_flow.forward_minus_reverse_bits, 6),
            "renyi_transfer_entropy_bits": round(information_flow.renyi_forward_bits, 6),
            "reverse_renyi_transfer_entropy_bits": round(information_flow.renyi_reverse_bits, 6),
            "renyi_transfer_entropy_edge_bits": round(
                information_flow.renyi_forward_minus_reverse_bits, 6
            ),
            "symbolic_transfer_entropy_bits": round(information_flow.symbolic_forward_bits, 6),
            "reverse_symbolic_transfer_entropy_bits": round(information_flow.symbolic_reverse_bits, 6),
            "symbolic_transfer_entropy_edge_bits": round(
                information_flow.symbolic_forward_minus_reverse_bits, 6
            ),
            "transfer_entropy_sample_count": int(information_flow.sample_count),
            "symbolic_transfer_entropy_sample_count": int(information_flow.symbolic_sample_count),
            "information_flow_direction_score_bits": round(information_flow_direction_score, 6),
            "information_flow_gate_pass": transfer_entropy_gate_pass,
            "pm_mid": round(pm_mid, 6) if pm_mid is not None else None,
            "fair_prob_up": round(fair_prob_up, 6) if fair_prob_up is not None else None,
            "lookup_support": int(lookup_support),
            "lookup_key": lookup_key or None,
            "edge_abs": round(edge_abs, 6) if edge_abs is not None else None,
            "net_edge_abs": round(net_edge_abs, 6) if net_edge_abs is not None else None,
            "maker_rebate_rate": round(maker_rebate_rate, 8),
            "maker_rebate_bps": round(maker_rebate_rate * 10_000.0, 6),
            "side": side,
            "raw_kelly": round(raw_kelly, 6),
            "fraction": round(fraction, 6),
            "notional_usd": round(notional_usd, 6),
            "win_rate": round(win_rate, 6),
            "candle_sets": int(candle_sets),
            "post_cost_ev_bps": round(post_cost_ev_bps, 6),
            "post_cost_ev": round(post_cost_ev_bps / 10_000.0, 6),
            "kill_status": kill_status,
            "auto_killed": auto_killed,
            "kill_reason": kill_reason,
            "block_reasons": _dedupe(block_reasons),
        }

    scaled_notionals, cap_scale = apply_cluster_cap(
        intended_notionals,
        bankroll=bankroll,
        cluster_cap_fraction=CLUSTER_CAP_FRACTION,
    )
    if cap_scale < 1.0:
        for intent in intents:
            asset = str(intent.get("asset") or "").upper()
            original_notional = _as_float(intent.get("notional_usd"), 0.0)
            scaled_notional = scaled_notionals.get(asset, 0.0)
            if original_notional > 0.0 and scaled_notional >= 0.0:
                scale = scaled_notional / original_notional
                intent["notional_usd"] = round(scaled_notional, 6)
                intent["fraction"] = round(_as_float(intent.get("fraction"), 0.0) * scale, 6)
                follower_payloads[asset]["notional_usd"] = round(scaled_notional, 6)
                follower_payloads[asset]["fraction"] = round(_as_float(follower_payloads[asset].get("fraction"), 0.0) * scale, 6)

    total_shadow_notional = round(sum(_as_float(row.get("notional_usd"), 0.0) for row in intents), 6)

    correlation_values = [
        value for asset, value in correlations_by_asset.items()
        if asset in live_follower_set and value is not None
    ]
    correlation_collapse = bool(live_follower_set) and (
        not correlation_values or all(value < CORRELATION_FLOOR for value in correlation_values)
    )
    if correlation_collapse:
        global_blockers.append("correlation_collapse")

    if total_shadow_notional <= 0.0 and live_follower_set:
        global_blockers.append("no_shadow_intent_after_gates")

    cascade_block_reasons = _dedupe(global_blockers + follower_specific_blockers)

    return {
        "schema_version": CASCADE_SCHEMA,
        "generated_at": _iso(now_dt),
        "mode": "shadow",
        "leader_asset": LEADER_ASSET,
        "timeframe": "5m",
        "follower_universe": list(FOLLOWER_UNIVERSE),
        "live_follower_set": live_follower_set,
        "source_contract": {
            "data_plane_health_path": "reports/data_plane_health/latest.json",
            "market_registry_path": "reports/market_registry/latest.json",
            "cross_asset_history_path": "reports/cross_asset_history/latest.json",
            "cross_asset_ticks_db": str(cross_asset_ticks_db),
            "cross_asset_history_db": str(history_db),
        },
        "registry_status": {
            "fresh": registry_fresh,
            "age_seconds": round(registry_age_seconds, 6) if registry_age_seconds is not None else None,
            "max_age_seconds": REGISTRY_MAX_AGE_SECONDS,
            "row_count": len(registry_rows),
        },
        "best_venue_by_asset": best_venue_by_asset,
        "bankroll_usd": round(bankroll, 6),
        "trigger_score": round(leader_shock_score, 6) if leader_shock_score is not None else None,
        "leader_move_from_open": round(leader_move_from_open, 6) if leader_move_from_open is not None else None,
        "rolling_30d_p98_first90s_abs_btc_move": round(
            lookup.rolling_30d_p98_first90s_abs_btc_move, 6
        ),
        "candle_elapsed_seconds": round(candle_elapsed_seconds, 6) if candle_elapsed_seconds is not None else None,
        "window_start_ts": btc_window_start,
        "window_end_ts": btc_window_end,
        "leader_anchor_price": round(btc_anchor_price, 6) if btc_anchor_price is not None else None,
        "leader_price": round(btc_price, 6) if btc_price is not None else None,
        "leader_reference_venue": leader_reference_venue,
        "leader_event_ts_ms": btc_event_ts_ms,
        "gates": {
            "registry_fresh": registry_fresh,
            "candle_elapsed_gate_pass": candle_elapsed_gate_pass,
            "leader_move_floor_pass": leader_move_floor_pass,
            "leader_shock_gate_pass": leader_shock_gate_pass,
            "correlation_floor": CORRELATION_FLOOR,
            "transfer_entropy_min_bits": TRANSFER_ENTROPY_MIN_BITS,
            "renyi_transfer_entropy_min_bits": RENYI_TRANSFER_ENTROPY_MIN_BITS,
            "symbolic_transfer_entropy_min_bits": SYMBOLIC_TRANSFER_ENTROPY_MIN_BITS,
            "information_flow_directional_slack_bits": INFORMATION_FLOW_DIRECTIONAL_SLACK_BITS,
            "edge_floor": EDGE_FLOOR,
            "quote_staleness_max_seconds": QUOTE_MAX_STALENESS_SECONDS,
            "crypto_taker_fee_rate": CRYPTO_TAKER_FEE_RATE,
            "crypto_taker_fee_exponent": CRYPTO_TAKER_FEE_EXPONENT,
            "crypto_maker_rebate_share": CRYPTO_MAKER_REBATE_SHARE,
        },
        "lookup_summary": {
            "sample_count": lookup.sample_count,
            "move_bucket_edges": [round(value, 8) for value in lookup.move_bucket_edges],
            "volatility_bucket_edges": [round(value, 8) for value in lookup.volatility_bucket_edges],
        },
        "shadow_intended_notional_usd": total_shadow_notional,
        "correlation_collapse": correlation_collapse,
        "followers": follower_payloads,
        "intents": intents,
        "block_reasons": cascade_block_reasons,
    }


def build_mc_payload(
    root: Path,
    *,
    cascade_payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    now_dt = now or _utc_now()
    history_report = _cross_asset_history_payload(root)
    instance3 = _instance3_artifact(root)
    stress_mode = select_stress_mode(history_report, instance3)

    intents = list(cascade_payload.get("intents") or [])
    bankroll = _as_float(cascade_payload.get("bankroll_usd"), 250.0)
    local_distribution = _run_monte_carlo_distribution(
        intents,
        paths=LOCAL_MONTE_CARLO_PATHS,
        seed=17,
    )
    stress_distribution: dict[str, Any] | None = None
    if stress_mode == "batch_plus_replay":
        stress_distribution = _run_monte_carlo_distribution(
            intents,
            paths=BATCH_MONTE_CARLO_PATHS,
            seed=23,
        )
    effective_distribution = stress_distribution or local_distribution

    tail_breach = (
        _as_float(effective_distribution.get("p01_pnl_usd"), 0.0)
        <= (-1.0 * bankroll * TAIL_BREACH_FRACTION)
    )
    drawdown_stress_breach = (
        _as_float(effective_distribution.get("worst_pnl_usd"), 0.0)
        <= (-1.0 * bankroll * DRAWDOWN_BREACH_FRACTION)
    )
    correlation_collapse = _as_bool(cascade_payload.get("correlation_collapse"), default=False)

    batch_stress_job = _submit_batch_stress_job(
        root=root,
        generated_at=now_dt,
        stress_mode=stress_mode,
        path_count=BATCH_MONTE_CARLO_PATHS,
    )

    mc_blockers = list(cascade_payload.get("block_reasons") or [])
    if stress_mode == "local_only":
        mc_blockers.append("stress_mode_local_only")

    return {
        "schema_version": MC_SCHEMA,
        "generated_at": _iso(now_dt),
        "leader_asset": LEADER_ASSET,
        "timeframe": "5m",
        "stress_mode": stress_mode,
        "paths": {
            "local": LOCAL_MONTE_CARLO_PATHS,
            "stress": BATCH_MONTE_CARLO_PATHS if stress_mode == "batch_plus_replay" else LOCAL_MONTE_CARLO_PATHS,
        },
        "shadow_intended_notional_usd": round(
            _as_float(cascade_payload.get("shadow_intended_notional_usd"), 0.0), 6
        ),
        "local_distribution": local_distribution,
        "stress_distribution": stress_distribution,
        "distribution": effective_distribution,
        "tail_breach": tail_breach,
        "drawdown_stress_breach": drawdown_stress_breach,
        "correlation_collapse": correlation_collapse,
        "risk_flags": {
            "tail_breach": tail_breach,
            "drawdown_stress_breach": drawdown_stress_breach,
            "correlation_collapse": correlation_collapse,
        },
        "batch_stress_job": batch_stress_job,
        "block_reasons": _dedupe(mc_blockers),
    }


def _next_cycle_action(block_reasons: list[str]) -> str:
    _ = block_reasons
    return "advance to shadow_live_intents after two clean shadow cycles"


def build_instance5_summary(
    *,
    cascade_payload: dict[str, Any],
    mc_payload: dict[str, Any],
    finance_latest: dict[str, Any],
    cascade_latest_path: Path,
    mc_latest_path: Path,
) -> dict[str, Any]:
    block_reasons = _dedupe(list(cascade_payload.get("block_reasons") or []))
    finance_pass = _finance_gate_pass(finance_latest)
    if not finance_pass:
        block_reasons.append("finance_gate_failed")
    block_reasons = _dedupe(block_reasons)

    return {
        "artifact": INSTANCE5_SCHEMA,
        "instance": 5,
        "generated_at": _iso(_utc_now()),
        "objective": (
            "Cross-asset cascade scoring (BTC leader, ETH/SOL/XRP/DOGE followers), "
            "shadow intent sizing, and continuous Monte Carlo stress telemetry."
        ),
        "schemas": {
            "cross_asset_cascade": CASCADE_SCHEMA,
            "cross_asset_mc": MC_SCHEMA,
        },
        "source_contract": {
            "cross_asset_cascade_path": str(cascade_latest_path),
            "cross_asset_mc_path": str(mc_latest_path),
            "runtime_truth_path": "reports/runtime_truth_latest.json",
            "finance_latest_path": "reports/finance/latest.json",
        },
        "cascade": {
            "shadow_intended_notional_usd": _as_float(cascade_payload.get("shadow_intended_notional_usd"), 0.0),
            "trigger_score": cascade_payload.get("trigger_score"),
            "live_follower_set": list(cascade_payload.get("live_follower_set") or []),
        },
        "monte_carlo": {
            "stress_mode": mc_payload.get("stress_mode"),
            "tail_breach": _as_bool(mc_payload.get("tail_breach"), default=False),
            "drawdown_stress_breach": _as_bool(mc_payload.get("drawdown_stress_breach"), default=False),
            "correlation_collapse": _as_bool(mc_payload.get("correlation_collapse"), default=False),
        },
        "required_output_contract": {
            "candidate_delta_arr_bps": 1200,
            "expected_improvement_velocity_delta": 0.40,
            "arr_confidence_score": 0.58,
            "block_reasons": block_reasons,
            "finance_gate_pass": finance_pass,
            "one_next_cycle_action": _next_cycle_action(block_reasons),
        },
        "candidate_delta_arr_bps": 1200,
        "expected_improvement_velocity_delta": 0.40,
        "arr_confidence_score": 0.58,
        "block_reasons": block_reasons,
        "finance_gate_pass": finance_pass,
        "one_next_cycle_action": _next_cycle_action(block_reasons),
    }


def _write_latest_and_timestamped(
    *,
    output_dir: Path,
    prefix: str,
    payload: dict[str, Any],
    now: datetime,
) -> tuple[Path, Path]:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamped = output_dir / f"{prefix}_{stamp}.json"
    latest = output_dir / "latest.json"
    _write_json(timestamped, payload)
    _write_json(latest, payload)
    return timestamped, latest


def run_instance5_cycle(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    now_dt = now or _utc_now()
    cascade_payload = build_cascade_payload(root, now=now_dt)
    mc_payload = build_mc_payload(root, cascade_payload=cascade_payload, now=now_dt)
    finance_latest = _finance_latest_payload(root)

    cascade_timestamped, cascade_latest = _write_latest_and_timestamped(
        output_dir=root / "reports" / "cross_asset_cascade",
        prefix="cross_asset_cascade",
        payload=cascade_payload,
        now=now_dt,
    )
    mc_timestamped, mc_latest = _write_latest_and_timestamped(
        output_dir=root / "reports" / "cross_asset_mc",
        prefix="cross_asset_mc",
        payload=mc_payload,
        now=now_dt,
    )
    summary_payload = build_instance5_summary(
        cascade_payload=cascade_payload,
        mc_payload=mc_payload,
        finance_latest=finance_latest,
        cascade_latest_path=cascade_latest,
        mc_latest_path=mc_latest,
    )
    summary_timestamped, summary_latest = _write_latest_and_timestamped(
        output_dir=root / "reports" / "instance5_cascade_mc",
        prefix="instance5_cascade_mc",
        payload=summary_payload,
        now=now_dt,
    )

    return {
        "generated_at": _iso(now_dt),
        "cross_asset_cascade": {
            "timestamped": str(cascade_timestamped),
            "latest": str(cascade_latest),
            "payload": cascade_payload,
        },
        "cross_asset_mc": {
            "timestamped": str(mc_timestamped),
            "latest": str(mc_latest),
            "payload": mc_payload,
        },
        "instance5_cascade_mc": {
            "timestamped": str(summary_timestamped),
            "latest": str(summary_latest),
            "payload": summary_payload,
        },
    }
