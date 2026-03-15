"""
Autoresearch closed loop for BTC5 maker — v3 (optimal).

Cycle (runs every 3 hours via timer):
1. OBSERVE: Pull fills + ALL skip windows with full context (price, delta, direction, hour)
2. COUNTERFACTUAL: For each skip reason, estimate expected PnL if those windows had traded
3. HYPOTHESIZE: Generate parameter variations grounded in counterfactual EV
4. BACKTEST: Full-cascade simulation (not just fill filtering)
5. RANK & PROMOTE: Score by risk-adjusted PnL/fill, not raw PnL
6. AUTO-APPLY: Write promoted overrides; support multiple orthogonal trials

Mutable surface: price caps, delta thresholds, direction bias, hour suppression
Immutable surface: daily loss limit, max position, kill rules, Kelly fraction

March 15, 2026 — Elastifund Autoresearch v3
"""
import json
import logging
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("AutoresearchLoop")

DB_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db")
RESULTS_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/autoresearch_results.json")
OVERRIDES_PATH = Path("/home/ubuntu/polymarket-trading-bot/config/autoresearch_overrides.json")
TRACKING_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/autoresearch_tracking.json")

# Pipeline constants.
TRIAL_HOURS = 12           # Faster iteration: evaluate trials every 12h.
VALIDATED_ARCHIVE_HOURS = 48
OVERRIDE_EXPIRY_HOURS = 48
MIN_FILLS_FOR_HYPOTHESIS = 3   # Lower threshold: act on less data.
DECAY_WIN_RATE_THRESHOLD = 0.35
DIRECTION_WIN_RATE_THRESHOLD = 0.40
DIRECTION_MIN_FILLS = 3

# Risk-adjusted scoring.
MIN_PNL_PER_FILL_USD = 0.05   # Minimum EV per fill to consider positive.
SHARPE_LOOKBACK_FILLS = 20


@dataclass
class Hypothesis:
    hypothesis_id: str
    description: str
    params: dict = field(default_factory=dict)
    predicted_improvement: float = 0.0
    predicted_fills: int = 0
    predicted_pnl_per_fill: float = 0.0
    confidence: float = 0.0
    status: str = "generated"
    shadow_pnl: float = 0.0
    shadow_fills: int = 0
    shadow_win_rate: float = 0.0
    live_pnl_at_generation: float = 0.0
    created_at: str = ""
    resolved_at: str = ""
    promoted_at: str = ""
    policy_family: str = ""
    changed_decision_count: int = 0


# ---------------------------------------------------------------------------
# Observation layer
# ---------------------------------------------------------------------------

def _db_connect() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def observe_recent_performance(hours: int = 24) -> dict:
    """Pull fills from last N hours and compute performance by segment."""
    conn = _db_connect()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    fills = conn.execute("""
        SELECT direction, order_price, pnl_usd, won,
               created_at, edge_tier, delta
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
        ORDER BY created_at
    """, (cutoff,)).fetchall()
    conn.close()

    if not fills:
        return {"total_fills": 0, "total_pnl": 0.0, "win_rate": 0.0,
                "pnl_per_fill": 0.0, "segments": {}}

    total_pnl = sum(f[2] or 0 for f in fills)
    total_wins = sum(1 for f in fills if f[3])
    pnl_list = [f[2] or 0 for f in fills]

    # Segment by direction
    dir_stats: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        if d not in dir_stats:
            dir_stats[d] = {"fills": 0, "wins": 0, "pnl": 0.0,
                            "avg_delta": 0.0, "total_delta": 0.0,
                            "avg_price": 0.0, "total_price": 0.0,
                            "pnl_list": []}
        dir_stats[d]["fills"] += 1
        dir_stats[d]["wins"] += 1 if won else 0
        dir_stats[d]["pnl"] += pnl or 0
        dir_stats[d]["total_delta"] += abs(delta or 0)
        dir_stats[d]["total_price"] += price or 0
        dir_stats[d]["pnl_list"].append(pnl or 0)
    for d in dir_stats:
        n = dir_stats[d]["fills"]
        if n > 0:
            dir_stats[d]["avg_delta"] = round(dir_stats[d]["total_delta"] / n, 6)
            dir_stats[d]["avg_price"] = round(dir_stats[d]["total_price"] / n, 4)
            dir_stats[d]["win_rate"] = round(dir_stats[d]["wins"] / n, 3)
            dir_stats[d]["pnl_per_fill"] = round(dir_stats[d]["pnl"] / n, 4)
            dir_stats[d]["sharpe"] = _sharpe(dir_stats[d]["pnl_list"])
        del dir_stats[d]["total_delta"]
        del dir_stats[d]["total_price"]
        del dir_stats[d]["pnl_list"]

    # Segment by price bucket (0.05 granularity for more precision)
    price_buckets: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        bucket = f"{round((price or 0) * 20) / 20:.2f}"
        if bucket not in price_buckets:
            price_buckets[bucket] = {"fills": 0, "wins": 0, "pnl": 0.0}
        price_buckets[bucket]["fills"] += 1
        price_buckets[bucket]["wins"] += 1 if won else 0
        price_buckets[bucket]["pnl"] += pnl or 0
    # Add break-even win rate and edge for each price bucket.
    for bucket_key, stats in price_buckets.items():
        try:
            bp = float(bucket_key)
        except (ValueError, TypeError):
            bp = 0.50
        stats["break_even_wr"] = round(break_even_win_rate(bp), 3)
        actual_wr = round(stats["wins"] / stats["fills"], 3) if stats["fills"] > 0 else 0.0
        stats["win_rate"] = actual_wr
        stats["wr_edge"] = round(actual_wr - stats["break_even_wr"], 3)

    # Segment by hour (UTC)
    hour_stats: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        try:
            h_key = f"{datetime.fromisoformat(ts).hour:02d}"
        except (ValueError, TypeError):
            h_key = "unknown"
        if h_key not in hour_stats:
            hour_stats[h_key] = {"fills": 0, "wins": 0, "pnl": 0.0}
        hour_stats[h_key]["fills"] += 1
        hour_stats[h_key]["wins"] += 1 if won else 0
        hour_stats[h_key]["pnl"] += pnl or 0

    # Segment by delta magnitude
    delta_buckets: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        bucket = _delta_bucket_label(abs(delta or 0))
        if bucket not in delta_buckets:
            delta_buckets[bucket] = {"fills": 0, "wins": 0, "pnl": 0.0}
        delta_buckets[bucket]["fills"] += 1
        delta_buckets[bucket]["wins"] += 1 if won else 0
        delta_buckets[bucket]["pnl"] += pnl or 0

    return {
        "total_fills": len(fills),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(total_wins / len(fills), 3),
        "pnl_per_fill": round(total_pnl / len(fills), 4),
        "sharpe": _sharpe(pnl_list),
        "segments": {
            "by_price_bucket": price_buckets,
            "by_direction": dir_stats,
            "by_hour": hour_stats,
            "by_delta": delta_buckets,
        },
    }


def observe_capital_velocity(hours: int = 24) -> dict:
    """Observe the full window funnel including counterfactual data on skip windows."""
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, COUNT(*) as cnt
        FROM window_trades
        WHERE window_start_ts > ?
        GROUP BY order_status
        ORDER BY cnt DESC
    """, (cutoff_ts,)).fetchall()

    total_windows = sum(r[1] for r in rows)
    status_counts = {r[0]: r[1] for r in rows}
    fills = status_counts.get("live_filled", 0)
    live_attempts = sum(v for k, v in status_counts.items() if k.startswith("live_"))
    skip_reasons = {k: v for k, v in status_counts.items() if k.startswith("skip_")}

    # Counterfactual: get characteristics of skip_price_outside_guardrails windows.
    price_skip_profile = _profile_skip_windows(
        conn, cutoff_ts, "skip_price_outside_guardrails"
    )

    # Counterfactual: get characteristics of skip_delta_too_large windows.
    delta_skip_profile = _profile_skip_windows(
        conn, cutoff_ts, "skip_delta_too_large"
    )

    conn.close()
    return {
        "total_windows": total_windows,
        "fills": fills,
        "live_attempts": live_attempts,
        "fill_rate": round(fills / total_windows, 4) if total_windows else 0.0,
        "attempt_rate": round(live_attempts / total_windows, 4) if total_windows else 0.0,
        "skip_reasons": skip_reasons,
        "top_blocker": max(skip_reasons, key=skip_reasons.get) if skip_reasons else None,
        "top_blocker_count": max(skip_reasons.values()) if skip_reasons else 0,
        "counterfactual": {
            "price_guardrail_skips": price_skip_profile,
            "delta_too_large_skips": delta_skip_profile,
        },
    }


def _profile_skip_windows(conn: sqlite3.Connection, cutoff_ts: int, status: str) -> dict:
    """Profile skip windows to estimate counterfactual fill characteristics."""
    rows = conn.execute("""
        SELECT direction, best_ask, best_bid, delta, order_price,
               window_start_ts
        FROM window_trades
        WHERE order_status = ?
          AND window_start_ts > ?
    """, (status, cutoff_ts)).fetchall()

    if not rows:
        return {"count": 0}

    directions = {}
    best_asks = []
    deltas = []
    hours_utc = []

    for direction, best_ask, best_bid, delta, order_price, wts in rows:
        d = direction or "UNKNOWN"
        directions[d] = directions.get(d, 0) + 1
        if best_ask is not None:
            best_asks.append(best_ask)
        if delta is not None:
            deltas.append(abs(delta))
        try:
            hours_utc.append(datetime.fromtimestamp(wts, tz=timezone.utc).hour)
        except (ValueError, TypeError, OSError):
            pass

    return {
        "count": len(rows),
        "direction_distribution": directions,
        "avg_best_ask": round(sum(best_asks) / len(best_asks), 4) if best_asks else None,
        "median_best_ask": round(sorted(best_asks)[len(best_asks) // 2], 4) if best_asks else None,
        "avg_abs_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
        "hour_distribution": _bucket_hours(hours_utc),
    }


def _bucket_hours(hours: list[int]) -> dict[str, int]:
    """Bucket hours into trading sessions."""
    buckets = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
    for h in hours:
        if h < 6:
            buckets["00-06"] += 1
        elif h < 12:
            buckets["06-12"] += 1
        elif h < 18:
            buckets["12-18"] += 1
        else:
            buckets["18-24"] += 1
    return {k: v for k, v in buckets.items() if v > 0}


# ---------------------------------------------------------------------------
# Counterfactual expected value model
# ---------------------------------------------------------------------------

def compute_fill_ev(obs: dict) -> dict:
    """Compute expected value per fill by direction and price range.

    Uses the actual PnL distribution of recent fills to estimate what
    additional fills would be worth, rather than arbitrary constants.
    """
    dir_stats = obs.get("segments", {}).get("by_direction", {})
    price_stats = obs.get("segments", {}).get("by_price_bucket", {})

    # Base EV: overall PnL per fill.
    base_ev = obs.get("pnl_per_fill", 0.0)

    # Direction-specific EV.
    dir_ev: dict[str, float] = {}
    for d, stats in dir_stats.items():
        n = stats.get("fills", 0)
        if n > 0:
            dir_ev[d] = stats.get("pnl_per_fill", 0.0)

    # Price-range EV: fills at price < 0.55 win more (lower cost, higher payoff).
    cheap_pnl = sum(s["pnl"] for p, s in price_stats.items()
                     if float(p) < 0.55 and s["fills"] > 0)
    cheap_fills = sum(s["fills"] for p, s in price_stats.items()
                      if float(p) < 0.55)
    cheap_ev = round(cheap_pnl / cheap_fills, 4) if cheap_fills > 0 else base_ev

    expensive_pnl = sum(s["pnl"] for p, s in price_stats.items()
                         if float(p) >= 0.55 and s["fills"] > 0)
    expensive_fills = sum(s["fills"] for p, s in price_stats.items()
                           if float(p) >= 0.55)
    expensive_ev = round(expensive_pnl / expensive_fills, 4) if expensive_fills > 0 else base_ev

    return {
        "base_ev": round(base_ev, 4),
        "direction_ev": dir_ev,
        "cheap_entry_ev": cheap_ev,      # price < 0.55
        "expensive_entry_ev": expensive_ev,  # price >= 0.55
    }


# ---------------------------------------------------------------------------
# Hypothesis generation
# ---------------------------------------------------------------------------

def generate_hypotheses(obs: dict, velocity: dict) -> list[Hypothesis]:
    """Generate hypotheses from performance data AND velocity analysis."""
    hypotheses = []
    now = datetime.now(timezone.utc).isoformat()
    segments = obs.get("segments", {})
    fill_ev = compute_fill_ev(obs)
    skip_reasons = velocity.get("skip_reasons", {})
    total_windows = velocity.get("total_windows", 0)
    counterfactual = velocity.get("counterfactual", {})

    # --- Performance-based hypotheses ---

    # H1: Direction bias — if one direction dominates on PnL/fill.
    dir_data = segments.get("by_direction", {})
    for direction, stats in dir_data.items():
        fills_n = stats.get("fills", 0)
        if fills_n >= 3 and stats.get("pnl", 0) > 0:
            other_pnl = sum(s["pnl"] for d, s in dir_data.items() if d != direction)
            if stats["pnl"] > other_pnl + 1.0:
                hypotheses.append(Hypothesis(
                    hypothesis_id=f"h_dir_{direction.lower()}_{now[:10]}",
                    description=(
                        f"{direction}-only mode "
                        f"(PnL: ${stats['pnl']:.2f}, win_rate: {stats.get('win_rate', 0):.0%} "
                        f"vs rest: ${other_pnl:.2f})"
                    ),
                    params={"BTC5_DIRECTIONAL_MODE": f"{direction.lower()}_only"},
                    predicted_improvement=stats["pnl"] - other_pnl,
                    predicted_pnl_per_fill=stats.get("pnl_per_fill", 0),
                    confidence=min(1.0, fills_n / 10),
                    live_pnl_at_generation=obs["total_pnl"],
                    created_at=now,
                    policy_family="direction_bias",
                ))

    # H2: Direction-specific delta threshold increase for losing direction.
    for direction, stats in dir_data.items():
        fills_n = stats.get("fills", 0)
        if fills_n >= DIRECTION_MIN_FILLS:
            wr = stats.get("win_rate", 1.0)
            if wr < DIRECTION_WIN_RATE_THRESHOLD:
                current_avg = stats.get("avg_delta", 0.0003)
                # Scale delta increase by how bad the win rate is.
                multiplier = 2.0 + (DIRECTION_WIN_RATE_THRESHOLD - wr) * 5
                proposed = round(max(current_avg * multiplier, 0.0006), 6)
                hypotheses.append(Hypothesis(
                    hypothesis_id=f"h_delta_{direction.lower()}_{now[:10]}",
                    description=(
                        f"Increase {direction} min_delta "
                        f"(wr={wr:.0%}, avg_delta={current_avg:.6f} → {proposed:.6f})"
                    ),
                    params={f"BTC5_{direction.upper()}_MIN_DELTA": proposed},
                    predicted_improvement=abs(stats["pnl"]) * 0.5,
                    confidence=min(1.0, fills_n / 8),
                    live_pnl_at_generation=obs["total_pnl"],
                    created_at=now,
                    policy_family="delta_threshold",
                ))

    # H3: Suppress losing hours.
    hour_data = segments.get("by_hour", {})
    losing_hours = [h for h, s in hour_data.items()
                    if s["pnl"] < -0.50 and s["fills"] >= 2]
    if losing_hours:
        saved = sum(abs(hour_data[h]["pnl"]) for h in losing_hours)
        hypotheses.append(Hypothesis(
            hypothesis_id=f"h_suppress_hours_{now[:10]}",
            description=f"Suppress hours: {', '.join(sorted(losing_hours))} UTC "
                        f"(total loss: ${saved:.2f})",
            params={"BTC5_SUPPRESS_HOURS_UTC": ",".join(sorted(losing_hours))},
            predicted_improvement=saved,
            confidence=min(1.0, sum(hour_data[h]["fills"] for h in losing_hours) / 10),
            live_pnl_at_generation=obs["total_pnl"],
            created_at=now,
            policy_family="hour_suppression",
        ))

    # H4: Optimal price floor from data.
    price_data = segments.get("by_price_bucket", {})
    losing_buckets = {k: v for k, v in price_data.items()
                      if v["pnl"] < -1.0 and v["fills"] >= 2}
    if losing_buckets:
        # Set floor above the worst losing bucket.
        worst = max(losing_buckets, key=lambda k: abs(losing_buckets[k]["pnl"]))
        new_floor = round(float(worst) + 0.05, 2)
        hypotheses.append(Hypothesis(
            hypothesis_id=f"h_floor_{new_floor}_{now[:10]}",
            description=(
                f"Raise min_buy_price to {new_floor} "
                f"(bucket {worst} lost ${losing_buckets[worst]['pnl']:.2f})"
            ),
            params={"BTC5_MIN_BUY_PRICE": new_floor},
            predicted_improvement=abs(losing_buckets[worst]["pnl"]),
            confidence=min(1.0, losing_buckets[worst]["fills"] / 5),
            live_pnl_at_generation=obs["total_pnl"],
            created_at=now,
            policy_family="price_floor",
        ))

    # --- Velocity-based hypotheses with counterfactual EV ---

    if total_windows >= 20:
        # H5: Widen price caps — use counterfactual analysis.
        price_skips = skip_reasons.get("skip_price_outside_guardrails", 0)
        price_cf = counterfactual.get("price_guardrail_skips", {})
        if price_skips > total_windows * 0.05 and price_cf.get("count", 0) > 0:
            median_ask = price_cf.get("median_best_ask")
            dir_dist = price_cf.get("direction_distribution", {})
            # Use direction-specific EV to predict what these fills would yield.
            # DOWN fills at high ask prices (0.85+) have been very profitable.
            down_frac = dir_dist.get("DOWN", 0) / max(price_cf["count"], 1)
            # EV estimate: DOWN fills at high prices are worth ~$0.50 each,
            # UP fills at mid prices are risky.
            down_ev = fill_ev.get("direction_ev", {}).get("DOWN", fill_ev["base_ev"])
            up_ev = fill_ev.get("direction_ev", {}).get("UP", fill_ev["base_ev"])
            weighted_ev = down_frac * max(down_ev, 0.10) + (1 - down_frac) * up_ev
            # Only suggest if positive EV.
            if weighted_ev > MIN_PNL_PER_FILL_USD:
                # Determine new caps from the actual best_ask distribution.
                new_up_cap = min(0.58, round((median_ask or 0.55) + 0.02, 2))
                new_down_cap = min(0.60, round((median_ask or 0.55) + 0.04, 2))
                est_new_fills = int(price_skips * 0.3)  # ~30% would actually fill
                hypotheses.append(Hypothesis(
                    hypothesis_id=f"h_widen_caps_{now[:10]}",
                    description=(
                        f"Widen price caps to UP≤{new_up_cap}/DOWN≤{new_down_cap} "
                        f"({price_skips} skips, ~{est_new_fills} est. fills, "
                        f"EV/fill: ${weighted_ev:.2f})"
                    ),
                    params={
                        "BTC5_UP_MAX_BUY_PRICE": new_up_cap,
                        "BTC5_DOWN_MAX_BUY_PRICE": new_down_cap,
                    },
                    predicted_improvement=round(est_new_fills * weighted_ev, 2),
                    predicted_fills=est_new_fills,
                    predicted_pnl_per_fill=round(weighted_ev, 4),
                    confidence=min(1.0, price_skips / 50),
                    created_at=now,
                    policy_family="price_caps",
                ))

        # H6: Delta range tuning.
        delta_skips = skip_reasons.get("skip_delta_too_large", 0)
        delta_cf = counterfactual.get("delta_too_large_skips", {})
        if delta_skips > total_windows * 0.15 and delta_cf.get("count", 0) > 0:
            avg_skip_delta = delta_cf.get("avg_abs_delta", 0.004)
            # Widen MAX_ABS_DELTA to capture more windows (but only moderately).
            new_max = round(min(avg_skip_delta * 1.5, 0.01), 4)
            if new_max > 0.004:
                dir_dist = delta_cf.get("direction_distribution", {})
                down_frac = dir_dist.get("DOWN", 0) / max(delta_cf["count"], 1)
                ev = down_frac * max(fill_ev.get("direction_ev", {}).get("DOWN", 0), 0.10)
                est_fills = int(delta_skips * 0.2)
                hypotheses.append(Hypothesis(
                    hypothesis_id=f"h_widen_delta_{now[:10]}",
                    description=(
                        f"Widen MAX_ABS_DELTA to {new_max:.4f} "
                        f"({delta_skips} skips, avg_delta={avg_skip_delta:.4f})"
                    ),
                    params={"BTC5_MAX_ABS_DELTA": new_max},
                    predicted_improvement=round(est_fills * ev, 2) if ev > 0 else 0,
                    predicted_fills=est_fills,
                    confidence=0.3,  # Low confidence — high delta is inherently riskier.
                    created_at=now,
                    policy_family="delta_range",
                ))

    return hypotheses


def detect_performance_decay(current_obs: dict) -> Hypothesis | None:
    """Detect if recent performance is decaying and generate tightening hypothesis."""
    recent = observe_recent_performance(hours=12)
    if recent["total_fills"] < 3:
        return None
    if recent["win_rate"] >= DECAY_WIN_RATE_THRESHOLD:
        return None

    now = datetime.now(timezone.utc).isoformat()
    return Hypothesis(
        hypothesis_id=f"h_decay_tighten_{now[:10]}",
        description=(
            f"Performance decay: {recent['win_rate']:.0%} win rate in last 12h "
            f"({recent['total_fills']} fills, ${recent['total_pnl']:.2f} PnL). "
            f"Tightening min_delta to 0.0005."
        ),
        params={"BTC5_MIN_DELTA": 0.0005},
        predicted_improvement=abs(recent["total_pnl"]) * 0.3,
        confidence=min(1.0, recent["total_fills"] / 8),
        live_pnl_at_generation=current_obs["total_pnl"],
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Full-cascade backtesting
# ---------------------------------------------------------------------------

def backtest_hypothesis(hypothesis: Hypothesis, lookback_hours: int = 48) -> dict:
    """Full-cascade backtest: simulate what PnL would look like with params applied.

    Unlike v2's fill-only filter, this considers:
    1. Existing fills that would be KEPT or REMOVED by the hypothesis
    2. Skip windows that would BECOME fills (for velocity hypotheses)

    Returns dict with shadow_pnl, shadow_fills, shadow_win_rate, shadow_pnl_per_fill.
    """
    conn = _db_connect()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    params = hypothesis.params

    # Part 1: Filter existing fills.
    fills = conn.execute("""
        SELECT direction, order_price, pnl_usd, won, created_at, delta
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
    """, (cutoff,)).fetchall()

    kept_pnl = 0.0
    kept_fills = 0
    kept_wins = 0
    removed_fills = 0
    removed_winning = 0
    removed_losing = 0
    changed_decision_count = 0

    # "Why this arm wins" decomposition.
    decomp = {
        "removed_winning_UP": 0, "removed_losing_UP": 0,
        "removed_winning_DOWN": 0, "removed_losing_DOWN": 0,
        "added_profitable_UP": 0, "added_unprofitable_UP": 0,
        "added_profitable_DOWN": 0, "added_unprofitable_DOWN": 0,
        "avg_removed_entry_price": 0.0, "avg_added_entry_price": 0.0,
    }
    removed_prices: list[float] = []
    added_prices: list[float] = []

    for direction, price, pnl, won, ts, delta in fills:
        if _fill_passes_hypothesis(direction, price, pnl, won, ts, delta, params):
            kept_pnl += pnl or 0
            kept_fills += 1
            if won:
                kept_wins += 1
        else:
            # This fill would be REMOVED by the hypothesis.
            removed_fills += 1
            changed_decision_count += 1
            d = direction or "UNKNOWN"
            if won:
                removed_winning += 1
                decomp[f"removed_winning_{d}"] = decomp.get(f"removed_winning_{d}", 0) + 1
            else:
                removed_losing += 1
                decomp[f"removed_losing_{d}"] = decomp.get(f"removed_losing_{d}", 0) + 1
            if price and price > 0:
                removed_prices.append(price)

    # Part 2: Estimate new fills from skip windows (for loosening hypotheses).
    # Prefer exact counterfactual_pnl_usd (from outcome reconciler) over heuristic.
    new_fill_ev = 0.0
    new_fill_count = 0
    new_fill_wins = 0
    exact_counterfactual_count = 0

    # If widening price caps, check what skip_price_outside_guardrails windows look like.
    if "BTC5_UP_MAX_BUY_PRICE" in params or "BTC5_DOWN_MAX_BUY_PRICE" in params:
        up_cap = params.get("BTC5_UP_MAX_BUY_PRICE", 99)
        down_cap = params.get("BTC5_DOWN_MAX_BUY_PRICE", 99)
        price_skips = conn.execute("""
            SELECT direction, best_ask, delta, pnl_usd, won,
                   counterfactual_pnl_usd, resolved_outcome, order_price
            FROM window_trades
            WHERE order_status = 'skip_price_outside_guardrails'
              AND window_start_ts > ?
        """, (cutoff_ts,)).fetchall()

        for row in price_skips:
            d, best_ask, delta, _, _, cf_pnl, resolved, order_price = row
            if best_ask is None:
                continue
            cap = up_cap if d == "UP" else down_cap
            if best_ask <= cap:
                new_fill_count += 1
                changed_decision_count += 1
                entry_px = best_ask or order_price or 0
                if entry_px > 0:
                    added_prices.append(entry_px)
                if cf_pnl is not None:
                    new_fill_ev += cf_pnl
                    exact_counterfactual_count += 1
                    is_win = resolved and d == resolved
                    if is_win:
                        new_fill_wins += 1
                    dk = d or "UNKNOWN"
                    if cf_pnl > 0:
                        decomp[f"added_profitable_{dk}"] = decomp.get(f"added_profitable_{dk}", 0) + 1
                    else:
                        decomp[f"added_unprofitable_{dk}"] = decomp.get(f"added_unprofitable_{dk}", 0) + 1
                else:
                    new_fill_ev += _estimate_fill_ev(d, best_ask, fills)

    # If widening MAX_ABS_DELTA, check skip_delta_too_large windows.
    if "BTC5_MAX_ABS_DELTA" in params:
        new_max_delta = params["BTC5_MAX_ABS_DELTA"]
        delta_skips = conn.execute("""
            SELECT direction, best_ask, delta,
                   counterfactual_pnl_usd, resolved_outcome, order_price
            FROM window_trades
            WHERE order_status = 'skip_delta_too_large'
              AND window_start_ts > ?
        """, (cutoff_ts,)).fetchall()

        for row in delta_skips:
            d, best_ask, delta, cf_pnl, resolved, order_price = row
            if delta is not None and abs(delta) <= new_max_delta:
                new_fill_count += 1
                changed_decision_count += 1
                entry_px = best_ask or order_price or 0
                if entry_px > 0:
                    added_prices.append(entry_px)
                if cf_pnl is not None:
                    new_fill_ev += cf_pnl
                    exact_counterfactual_count += 1
                    if resolved and d == resolved:
                        new_fill_wins += 1
                    dk = d or "UNKNOWN"
                    if cf_pnl > 0:
                        decomp[f"added_profitable_{dk}"] = decomp.get(f"added_profitable_{dk}", 0) + 1
                    else:
                        decomp[f"added_unprofitable_{dk}"] = decomp.get(f"added_unprofitable_{dk}", 0) + 1
                else:
                    new_fill_ev += _estimate_fill_ev(d, best_ask, fills)

    conn.close()

    total_pnl = round(kept_pnl + new_fill_ev, 2)
    total_fills = kept_fills + new_fill_count
    # Use exact win counts when available; fall back to 60% assumption for heuristic fills.
    heuristic_new_count = new_fill_count - exact_counterfactual_count
    total_wins = kept_wins + new_fill_wins + int(heuristic_new_count * 0.6)

    # Finalize decomposition averages.
    decomp["avg_removed_entry_price"] = round(
        sum(removed_prices) / len(removed_prices), 4
    ) if removed_prices else 0.0
    decomp["avg_added_entry_price"] = round(
        sum(added_prices) / len(added_prices), 4
    ) if added_prices else 0.0
    decomp["net_fill_rate_change"] = new_fill_count - removed_fills

    return {
        "shadow_pnl": total_pnl,
        "shadow_fills": total_fills,
        "shadow_win_rate": round(total_wins / total_fills, 3) if total_fills > 0 else 0.0,
        "shadow_pnl_per_fill": round(total_pnl / total_fills, 4) if total_fills > 0 else 0.0,
        "kept_fills": kept_fills,
        "removed_fills": removed_fills,
        "estimated_new_fills": new_fill_count,
        "exact_counterfactual_fills": exact_counterfactual_count,
        "new_fill_ev": round(new_fill_ev, 2),
        "changed_decision_count": changed_decision_count,
        "decomposition": decomp,
    }


def _fill_passes_hypothesis(
    direction: str | None, price: float | None, pnl: float | None,
    won: bool | None, ts: str | None, delta: float | None,
    params: dict,
) -> bool:
    """Check if an existing fill would survive under hypothesis params."""
    if "BTC5_MIN_BUY_PRICE" in params:
        if (price or 0) < params["BTC5_MIN_BUY_PRICE"]:
            return False

    if "BTC5_DIRECTIONAL_MODE" in params:
        mode = params["BTC5_DIRECTIONAL_MODE"]
        if mode == "up_only" and direction != "UP":
            return False
        if mode == "down_only" and direction != "DOWN":
            return False

    if "BTC5_SUPPRESS_HOURS_UTC" in params and ts:
        try:
            trade_hour = f"{datetime.fromisoformat(ts).hour:02d}"
            suppressed = params["BTC5_SUPPRESS_HOURS_UTC"].split(",")
            if trade_hour in suppressed:
                return False
        except (ValueError, TypeError):
            pass

    # Direction-specific min delta.
    dir_key = f"BTC5_{direction}_MIN_DELTA" if direction else None
    if dir_key and dir_key in params:
        if abs(delta or 0) < params[dir_key]:
            return False

    # Global min delta.
    if "BTC5_MIN_DELTA" in params:
        if dir_key and dir_key in params:
            pass  # Direction-specific already handled.
        elif abs(delta or 0) < params["BTC5_MIN_DELTA"]:
            return False

    return True


def _estimate_fill_ev(direction: str | None, best_ask: float | None,
                      recent_fills: list) -> float:
    """Estimate EV of a hypothetical fill based on direction and recent fill distribution.

    Uses the actual PnL distribution of matching fills, not arbitrary constants.
    """
    # Find fills with matching direction.
    matching = [(pnl or 0) for d, _, pnl, _, _, _ in recent_fills
                if d == direction and pnl is not None]

    if matching:
        # Use average PnL of matching-direction fills, discounted for uncertainty.
        avg = sum(matching) / len(matching)
        # Discount by 50% for estimation uncertainty.
        return avg * 0.5

    # Fallback: use price-based estimate.
    # At price P, you pay P and get 1 if win, 0 if lose.
    # With ~70% base win rate: EV = 0.7 * (1-P) - 0.3 * P = 0.7 - P
    if best_ask is not None:
        return max((0.7 - best_ask) * 5.0, -1.0)  # Scale to USD

    return 0.0


# ---------------------------------------------------------------------------
# Scoring and ranking
# ---------------------------------------------------------------------------

def break_even_win_rate(price: float, fee_rate_bps: int = 0) -> float:
    """Compute break-even win rate for a binary option at a given price.

    At price P with fee rate F:
      Win payoff = (1 - P) - P*F/10000
      Loss = P + P*F/10000
      Break-even: WR * Win = (1-WR) * Loss
      WR = Loss / (Win + Loss) = P / 1.0 (simplified when fees=0)
    """
    fee_frac = fee_rate_bps / 10000.0
    win_payoff = (1.0 - price) - price * fee_frac
    loss_cost = price + price * fee_frac
    if win_payoff + loss_cost <= 0:
        return 1.0
    return loss_cost / (win_payoff + loss_cost)


def bayesian_p_ev_positive(wins: int, fills: int, price: float, fee_rate_bps: int = 0) -> float:
    """Compute P(EV > 0) using Beta-Binomial model.

    Uses a Beta(1,1) uniform prior. Returns the probability that the
    true win rate exceeds the break-even win rate.
    """
    if fills <= 0:
        return 0.5  # Uninformative
    be_wr = break_even_win_rate(price, fee_rate_bps)
    # Beta posterior: Beta(1 + wins, 1 + fills - wins)
    alpha = 1 + wins
    beta_param = 1 + fills - wins
    # P(WR > be_wr) = 1 - I(be_wr; alpha, beta) where I is regularized incomplete beta
    try:
        from math import lgamma, exp
        # Use numerical approximation: normal approximation for large samples.
        mean = alpha / (alpha + beta_param)
        var = (alpha * beta_param) / ((alpha + beta_param) ** 2 * (alpha + beta_param + 1))
        std = var ** 0.5 if var > 0 else 1e-9
        # P(WR > be_wr) ≈ Φ((mean - be_wr) / std)
        z = (mean - be_wr) / std
        # Standard normal CDF approximation.
        from math import erf
        return 0.5 * (1.0 + erf(z / (2 ** 0.5)))
    except Exception:
        # Fallback: simple point estimate.
        return 1.0 if (wins / max(fills, 1)) > be_wr else 0.0


# ---------------------------------------------------------------------------
# Counterfactual quality classification
# ---------------------------------------------------------------------------

# Quality tiers for PnL evidence.
# Live execution data is always the most trustworthy.
CQ_LIVE_ACTUAL = "live_actual"                   # Filled trade — actual execution PnL.
CQ_EXACT = "exact_price_exact_resolution"        # Skip with price AND resolution data.
CQ_MISSING_PRICE = "exact_resolution_missing_price"  # Has resolution, no entry price.
CQ_HEURISTIC = "heuristic_price"                 # Price inferred/estimated.
CQ_NONE = "no_counterfactual"                    # No resolution data.

ALL_CQ_TIERS = [CQ_LIVE_ACTUAL, CQ_EXACT, CQ_MISSING_PRICE, CQ_HEURISTIC, CQ_NONE]

# Fillability model metadata.
FILLABILITY_MODEL_VERSION = "exp_decay_v1"
FILLABILITY_CALIBRATION_NOTES = (
    "Heuristic exponential decay: P(fill) = empirical_rate * exp(-15 * dist_from_ask). "
    "Calibrated against 8 fills with avg dist 0.01-0.07. Conservative upper bound."
)


def classify_counterfactual_quality(
    *,
    best_ask: float | None,
    order_price: float | None,
    resolved_outcome: str | None,
    counterfactual_pnl: float | None,
    is_live_fill: bool = False,
) -> str:
    """Classify the quality tier of a PnL observation.

    Returns one of CQ_LIVE_ACTUAL, CQ_EXACT, CQ_MISSING_PRICE, CQ_HEURISTIC, CQ_NONE.
    """
    if is_live_fill:
        return CQ_LIVE_ACTUAL

    has_resolution = resolved_outcome is not None and resolved_outcome != ""
    has_price = (best_ask is not None and best_ask > 0) or (order_price is not None and order_price > 0)

    if not has_resolution:
        return CQ_NONE
    if has_price and counterfactual_pnl is not None:
        return CQ_EXACT
    if has_resolution and not has_price:
        return CQ_MISSING_PRICE
    return CQ_HEURISTIC


def estimate_fill_probability(
    order_price: float,
    best_ask: float | None,
    best_bid: float | None,
    *,
    empirical_fill_rate: float = 0.50,
) -> float:
    """Estimate fill probability for a hypothetical maker buy order.

    Model: fillability_model_version = exp_decay_v1
    calibration_sample_n = 8 (fills at dist 0.01-0.07)

    THIS IS A HEURISTIC UPPER BOUND. Counterfactual PnL adjusted by this
    model should be labeled as fillability_adjusted, never raw.

    Returns fill probability in [0.05, 0.95].
    """
    if best_ask is None or order_price is None or order_price <= 0:
        return 0.30  # Conservative default when no book data

    dist_from_ask = best_ask - order_price
    if dist_from_ask <= 0:
        # Would cross the spread — in a post-only regime this gets rejected,
        # but conceptually it means the price moved to us.
        return min(0.95, empirical_fill_rate * 1.5)

    # Exponential decay: at dist=0.01, prob ≈ empirical; at dist=0.10, prob is much lower.
    # Calibrated against our data: 8/16 fills at dist 0.01-0.07.
    # e^(-15*0.02) ≈ 0.74, e^(-15*0.05) ≈ 0.47, e^(-15*0.10) ≈ 0.22
    decay = math.exp(-15.0 * dist_from_ask)
    prob = empirical_fill_rate * decay

    return max(0.05, min(0.95, prob))


def score_hypothesis(hypothesis: Hypothesis, fee_rate_bps: int = 0) -> float:
    """Score hypothesis by EV net of price/fees and expected log growth.

    Components:
    1. Shadow PnL (actual or counterfactual)
    2. Bayesian P(EV>0) gating — heavily penalize hypotheses without confidence
    3. Expected log growth (Kelly-adjacent) — reward risk-adjusted returns
    4. Confidence weighting
    """
    pnl = hypothesis.shadow_pnl
    fills = max(hypothesis.shadow_fills, 1)
    pnl_per_fill = hypothesis.predicted_pnl_per_fill or (pnl / fills)
    confidence = hypothesis.confidence or 0.5
    wins = int(hypothesis.shadow_win_rate * fills)

    # Estimate average entry price from description or use 0.50 default.
    avg_price = 0.50
    desc = hypothesis.description or ""
    for token in desc.split():
        try:
            val = float(token.strip("(),$≤≥"))
            if 0.01 < val < 1.0:
                avg_price = val
                break
        except (ValueError, TypeError):
            pass

    # Component 1: Raw PnL improvement weighted by confidence.
    base = hypothesis.predicted_improvement * confidence

    # Component 2: PnL quality per fill (net of break-even).
    be_wr = break_even_win_rate(avg_price, fee_rate_bps)
    actual_wr = hypothesis.shadow_win_rate
    wr_edge = actual_wr - be_wr  # Positive = above break-even
    quality = max(pnl_per_fill, 0) * fills * 0.5

    # Component 3: Bayesian P(EV>0) gating.
    p_positive = bayesian_p_ev_positive(wins, fills, avg_price, fee_rate_bps)
    # Gate: multiply score by P(EV>0). This heavily penalizes uncertain hypotheses.
    bayesian_gate = max(0.0, p_positive - 0.5) * 2  # Maps [0.5, 1.0] → [0.0, 1.0]

    # Component 4: Log growth bonus (Kelly-adjacent).
    if wr_edge > 0 and avg_price > 0 and avg_price < 1:
        b = (1.0 - avg_price) / avg_price
        kelly_f = max(0, (actual_wr * b - (1 - actual_wr)) / b)
        log_growth = kelly_f * wr_edge * 10  # Scale factor
    else:
        log_growth = 0.0

    raw_score = base + quality + log_growth
    return round(raw_score * max(bayesian_gate, 0.1), 2)  # Floor gate at 0.1 to avoid zeroing


# ---------------------------------------------------------------------------
# Hypothesis outcome tracking & graduated promotion pipeline
# ---------------------------------------------------------------------------

def _load_tracking() -> dict:
    if TRACKING_PATH.exists():
        try:
            return json.loads(TRACKING_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"hypotheses": {}, "cycle_count": 0, "history": []}


def _save_tracking(tracking: dict) -> None:
    TRACKING_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACKING_PATH.write_text(json.dumps(tracking, indent=2))


def _compute_pnl_since(since_iso: str) -> float:
    conn = _db_connect()
    result = conn.execute("""
        SELECT COALESCE(SUM(pnl_usd), 0)
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
    """, (since_iso,)).fetchone()
    conn.close()
    return round(float(result[0]), 2) if result else 0.0


def _compute_fills_since(since_iso: str) -> int:
    conn = _db_connect()
    result = conn.execute("""
        SELECT COUNT(*)
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
    """, (since_iso,)).fetchone()
    conn.close()
    return int(result[0]) if result else 0


def _compute_win_rate_since(since_iso: str) -> float:
    conn = _db_connect()
    result = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END), 0)
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
    """, (since_iso,)).fetchone()
    conn.close()
    total, wins = int(result[0]), int(result[1])
    return round(wins / total, 3) if total > 0 else 0.0


def promote_hypothesis(hypothesis: Hypothesis) -> None:
    """Write hypothesis params to override file for the bot to read."""
    override = {
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_id": hypothesis.hypothesis_id,
        "params": hypothesis.params,
        "predicted_improvement": hypothesis.predicted_improvement,
        "predicted_pnl_per_fill": hypothesis.predicted_pnl_per_fill,
        "confidence": hypothesis.confidence,
        "promotion_stage": "trial",
        "description": hypothesis.description,
    }
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(override, indent=2))
    logger.info(
        "PROMOTED to trial: %s (predicted: $%.2f, confidence: %.0f%%)",
        hypothesis.hypothesis_id, hypothesis.predicted_improvement,
        hypothesis.confidence * 100,
    )

    tracking = _load_tracking()
    tracking["hypotheses"][hypothesis.hypothesis_id] = {
        "promoted_at": override["promoted_at"],
        "promotion_stage": "trial",
        "predicted_improvement": hypothesis.predicted_improvement,
        "predicted_pnl_per_fill": hypothesis.predicted_pnl_per_fill,
        "pnl_at_promotion": _compute_pnl_since(
            (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        ),
        "fills_at_promotion": _compute_fills_since(override["promoted_at"]),
        "params": hypothesis.params,
    }
    _save_tracking(tracking)


def advance_promotion_pipeline() -> list[str]:
    """Advance or demote tracked hypotheses using risk-adjusted metrics."""
    tracking = _load_tracking()
    actions: list[str] = []
    now = datetime.now(timezone.utc)

    for h_id, record in list(tracking.get("hypotheses", {}).items()):
        stage = record.get("promotion_stage", "trial")
        promoted_at = record.get("promoted_at", "")
        if not promoted_at or stage not in ("trial", "validated"):
            continue

        try:
            promoted_dt = datetime.fromisoformat(promoted_at)
            if promoted_dt.tzinfo is None:
                promoted_dt = promoted_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        hours_live = (now - promoted_dt).total_seconds() / 3600
        live_pnl = _compute_pnl_since(promoted_at)
        live_fills = _compute_fills_since(promoted_at)
        live_wr = _compute_win_rate_since(promoted_at)
        pnl_per_fill = round(live_pnl / live_fills, 4) if live_fills > 0 else 0.0

        if stage == "trial" and hours_live >= TRIAL_HOURS:
            predicted = record.get("predicted_improvement", 0)
            predicted_ppf = record.get("predicted_pnl_per_fill", 0)

            # Validate on multiple criteria:
            # 1. PnL is not deeply negative
            # 2. Win rate is acceptable (>= 50%)
            # 3. PnL/fill is positive
            if live_pnl >= predicted * 0.3 and live_wr >= 0.45 and pnl_per_fill >= 0:
                record["promotion_stage"] = "validated"
                record["validated_at"] = now.isoformat()
                record["actual_improvement"] = live_pnl
                record["actual_fills"] = live_fills
                record["actual_win_rate"] = live_wr
                record["actual_pnl_per_fill"] = pnl_per_fill
                _update_override_stage("validated")
                actions.append(
                    f"VALIDATED: {h_id} "
                    f"(PnL: ${live_pnl:.2f}, fills: {live_fills}, "
                    f"wr: {live_wr:.0%}, $/fill: {pnl_per_fill:.2f})"
                )
            elif live_pnl < -3.0 or (live_fills >= 5 and live_wr < 0.30):
                record["promotion_stage"] = "killed"
                record["killed_at"] = now.isoformat()
                record["actual_improvement"] = live_pnl
                record["actual_fills"] = live_fills
                record["actual_win_rate"] = live_wr
                _remove_override(h_id)
                actions.append(
                    f"KILLED: {h_id} "
                    f"(PnL: ${live_pnl:.2f}, fills: {live_fills}, wr: {live_wr:.0%})"
                )
            else:
                actions.append(
                    f"HOLD trial: {h_id} ({hours_live:.0f}h, "
                    f"PnL: ${live_pnl:.2f}, fills: {live_fills}, wr: {live_wr:.0%})"
                )

        elif stage == "validated" and hours_live >= VALIDATED_ARCHIVE_HOURS:
            record["promotion_stage"] = "archived"
            record["archived_at"] = now.isoformat()
            record["final_improvement"] = live_pnl
            record["final_fills"] = live_fills
            record["final_win_rate"] = live_wr
            # Log to history for long-term learning.
            tracking.setdefault("history", []).append({
                "hypothesis_id": h_id,
                "params": record.get("params", {}),
                "predicted": record.get("predicted_improvement", 0),
                "actual": live_pnl,
                "fills": live_fills,
                "win_rate": live_wr,
                "hours": round(hours_live),
                "archived_at": now.isoformat(),
            })
            actions.append(
                f"ARCHIVED: {h_id} ({hours_live:.0f}h, "
                f"PnL: ${live_pnl:.2f}, fills: {live_fills}, wr: {live_wr:.0%})"
            )

    _save_tracking(tracking)
    return actions


def _update_override_stage(stage: str) -> None:
    if not OVERRIDES_PATH.exists():
        return
    try:
        data = json.loads(OVERRIDES_PATH.read_text())
        data["promotion_stage"] = stage
        OVERRIDES_PATH.write_text(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError):
        pass


def _remove_override(hypothesis_id: str) -> None:
    if not OVERRIDES_PATH.exists():
        return
    try:
        data = json.loads(OVERRIDES_PATH.read_text())
        if data.get("hypothesis_id") == hypothesis_id:
            OVERRIDES_PATH.unlink()
            logger.info("Removed override for killed hypothesis: %s", hypothesis_id)
    except (json.JSONDecodeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _delta_bucket_label(abs_delta: float) -> str:
    if abs_delta < 0.0003:
        return "<0.03%"
    elif abs_delta < 0.0005:
        return "0.03-0.05%"
    elif abs_delta < 0.001:
        return "0.05-0.10%"
    elif abs_delta < 0.002:
        return "0.10-0.20%"
    else:
        return ">0.20%"


def _sharpe(pnl_list: list[float]) -> float:
    """Simple Sharpe ratio from a list of PnL values."""
    if len(pnl_list) < 2:
        return 0.0
    mean = sum(pnl_list) / len(pnl_list)
    var = sum((x - mean) ** 2 for x in pnl_list) / (len(pnl_list) - 1)
    std = math.sqrt(var) if var > 0 else 1e-9
    return round(mean / std, 3)


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------

def _is_expansive_hypothesis(hypothesis: Hypothesis) -> bool:
    """Classify a hypothesis as expansive (fill-seeking) vs restrictive.

    Baseline-aware: compares proposed params against current effective config
    instead of using hardcoded thresholds.
    """
    params = hypothesis.params
    baseline = _load_current_baseline()

    for key, value in params.items():
        if not isinstance(value, (int, float)):
            continue

        # MAX_BUY_PRICE: raising = expansive, lowering = restrictive.
        if "MAX_BUY_PRICE" in key:
            baseline_val = baseline.get(key)
            if baseline_val is not None and value > baseline_val:
                return True

        # MAX_ABS_DELTA: raising = expansive.
        if key == "BTC5_MAX_ABS_DELTA":
            baseline_val = baseline.get(key)
            if baseline_val is not None and value > baseline_val:
                return True

        # MIN_DELTA: lowering = expansive (more fills pass).
        if "MIN_DELTA" in key:
            baseline_val = baseline.get(key)
            if baseline_val is not None and value < baseline_val:
                return True

        # MIN_BUY_PRICE: lowering = expansive.
        if key == "BTC5_MIN_BUY_PRICE":
            baseline_val = baseline.get(key)
            if baseline_val is not None and value < baseline_val:
                return True

    return False


def _load_current_baseline() -> dict[str, float]:
    """Load the current effective baseline from env/config for comparison."""
    import os
    return {
        "BTC5_UP_MAX_BUY_PRICE": float(os.environ.get("BTC5_UP_MAX_BUY_PRICE", "0.52")),
        "BTC5_DOWN_MAX_BUY_PRICE": float(os.environ.get("BTC5_DOWN_MAX_BUY_PRICE", "0.53")),
        "BTC5_MAX_BUY_PRICE": float(os.environ.get("BTC5_MAX_BUY_PRICE", "0.95")),
        "BTC5_MAX_ABS_DELTA": float(os.environ.get("BTC5_MAX_ABS_DELTA", "0.004")),
        "BTC5_MIN_DELTA": float(os.environ.get("BTC5_MIN_DELTA", "0.0003")),
        "BTC5_UP_MIN_DELTA": float(os.environ.get("BTC5_UP_MIN_DELTA", "0.0006")),
        "BTC5_DOWN_MIN_DELTA": float(os.environ.get("BTC5_DOWN_MIN_DELTA", "0.0003")),
        "BTC5_MIN_BUY_PRICE": float(os.environ.get("BTC5_MIN_BUY_PRICE", "0.42")),
    }


BASELINE_SNAPSHOT_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/baseline_snapshot.json")


def _read_live_bot_environ() -> dict[str, str]:
    """Read the actual live bot process environment from /proc/<pid>/environ.

    This is the AUTHORITATIVE source — not os.environ of the research process.
    """
    import subprocess

    live_env: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["pgrep", "-f", "btc_5min_maker.py"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return live_env
        pid = pids[0]
        env_path = Path(f"/proc/{pid}/environ")
        if env_path.exists():
            raw = env_path.read_bytes()
            for entry in raw.split(b"\x00"):
                try:
                    decoded = entry.decode("utf-8", errors="replace")
                    if "=" in decoded:
                        k, v = decoded.split("=", 1)
                        if k.startswith("BTC5_") or k in {
                            "POLY_SIGNATURE_TYPE", "JJ_RUNTIME_PROFILE",
                        }:
                            live_env[k] = v
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("Failed to read live bot environ: %s", exc)
    return live_env


def build_baseline_snapshot() -> dict:
    """Capture the full effective baseline from the LIVE BOT PID.

    Reads /proc/<pid>/environ for the actual live bot process, not os.environ
    of this research process. This is the authoritative baseline.

    Includes: live bot env vars, overrides, strategy_fingerprint, git_sha,
    service unit hash, legacy contamination check.
    """
    import subprocess

    # Read actual live bot environment (authoritative).
    live_env = _read_live_bot_environ()

    # Autoresearch overrides (Python-level).
    overrides = {}
    if OVERRIDES_PATH.exists():
        try:
            overrides = json.loads(OVERRIDES_PATH.read_text())
        except Exception:
            pass

    # Git SHA.
    git_sha = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd="/home/ubuntu/polymarket-trading-bot",
        )
        if result.returncode == 0:
            git_sha = result.stdout.strip()
    except Exception:
        pass

    # Strategy fingerprint from most recent window.
    fingerprint = None
    try:
        conn = _db_connect()
        row = conn.execute(
            "SELECT strategy_fingerprint FROM window_trades ORDER BY window_start_ts DESC LIMIT 1"
        ).fetchone()
        if row:
            fingerprint = row[0]
        conn.close()
    except Exception:
        pass

    # Service unit hash (detect if deployed unit differs from repo).
    service_hash = None
    deployed_service = Path("/etc/systemd/system/btc-5min-maker.service")
    repo_service = Path("/home/ubuntu/polymarket-trading-bot/deploy/btc-5min-maker.service")
    try:
        if deployed_service.exists() and repo_service.exists():
            import hashlib
            deployed_h = hashlib.sha256(deployed_service.read_bytes()).hexdigest()[:12]
            repo_h = hashlib.sha256(repo_service.read_bytes()).hexdigest()[:12]
            service_hash = {
                "deployed": deployed_h,
                "repo": repo_h,
                "in_sync": deployed_h == repo_h,
            }
    except Exception:
        pass

    # Check for legacy env contamination.
    legacy_env_path = Path("/home/ubuntu/polymarket-trading-bot/state/btc5_autoresearch.env")
    legacy_env_loaded = False
    if legacy_env_path.exists():
        try:
            if deployed_service.exists():
                content = deployed_service.read_text()
                legacy_env_loaded = False
                for _line in content.splitlines():
                    _stripped = _line.strip()
                    if not _stripped or _stripped.startswith("#"):
                        continue
                    if _stripped.startswith("EnvironmentFile") and "btc5_autoresearch.env" in _stripped:
                        legacy_env_loaded = True
                        break
        except Exception:
            pass

    # Live PID metadata.
    live_pid = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "btc_5min_maker.py"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if pids:
            live_pid = int(pids[0])
    except Exception:
        pass

    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "live_pid" if live_env else "fallback_os_environ",
        "live_pid": live_pid,
        "git_sha": git_sha,
        "strategy_fingerprint": fingerprint,
        "live_bot_env": live_env,
        "autoresearch_overrides": overrides,
        "service_unit": service_hash,
        "legacy_env_contamination": legacy_env_loaded,
    }

    BASELINE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
    logger.info("Baseline snapshot written to %s (source=%s, pid=%s)",
                BASELINE_SNAPSHOT_PATH, snapshot["source"], live_pid)
    return snapshot


def _clear_stale_trials() -> list[str]:
    """Kill trials that have been live for 24h+ with zero fills — they had no effect."""
    tracking = _load_tracking()
    actions: list[str] = []
    now = datetime.now(timezone.utc)

    for h_id, record in list(tracking.get("hypotheses", {}).items()):
        if record.get("promotion_stage") != "trial":
            continue
        promoted_at = record.get("promoted_at", "")
        if not promoted_at:
            continue
        try:
            promoted_dt = datetime.fromisoformat(promoted_at)
            if promoted_dt.tzinfo is None:
                promoted_dt = promoted_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        hours_live = (now - promoted_dt).total_seconds() / 3600
        if hours_live >= TRIAL_HOURS:
            fills = _compute_fills_since(promoted_at)
            if fills == 0:
                record["promotion_stage"] = "killed"
                record["killed_at"] = now.isoformat()
                record["kill_reason"] = "zero_fills_stale"
                _remove_override(h_id)
                actions.append(
                    f"STALE-KILLED: {h_id} ({hours_live:.0f}h, 0 fills — no effect)"
                )

    if actions:
        _save_tracking(tracking)
    return actions


def run_cycle() -> dict:
    """Full autoresearch cycle: observe → hypothesize → backtest → rank → promote."""
    logger.info("=== Autoresearch v3 cycle start ===")

    # Step 0: Capture baseline snapshot for auditability.
    baseline_snapshot = build_baseline_snapshot()
    if baseline_snapshot.get("legacy_env_contamination"):
        logger.warning("LEGACY ENV CONTAMINATION DETECTED: state/btc5_autoresearch.env is still loaded by live service")

    # Step 0a: Advance existing promoted hypotheses.
    pipeline_actions = advance_promotion_pipeline()
    for action in pipeline_actions:
        logger.info("  Pipeline: %s", action)

    # Step 0b: Kill stale trials that had zero fills (no effect).
    stale_actions = _clear_stale_trials()
    for action in stale_actions:
        logger.info("  Pipeline: %s", action)
    pipeline_actions.extend(stale_actions)

    # Step 1: Observe performance with adaptive lookback.
    # Use 24h, but if fills < 5, extend to 48h for better hypothesis generation.
    obs = observe_recent_performance(hours=24)
    if obs["total_fills"] < MIN_FILLS_FOR_HYPOTHESIS:
        obs_extended = observe_recent_performance(hours=48)
        if obs_extended["total_fills"] > obs["total_fills"]:
            logger.info(
                "Sparse data: extending lookback to 48h (%d → %d fills)",
                obs["total_fills"], obs_extended["total_fills"],
            )
            obs = obs_extended
    velocity = observe_capital_velocity(hours=24)
    fill_ev = compute_fill_ev(obs)

    logger.info(
        "Observed: %d fills, $%.2f PnL, %.1f%% wr, $%.4f/fill, sharpe=%.2f | "
        "Velocity: %d/%d (%.1f%%), top blocker: %s",
        obs["total_fills"], obs["total_pnl"], obs["win_rate"] * 100,
        obs.get("pnl_per_fill", 0), obs.get("sharpe", 0),
        velocity["fills"], velocity["total_windows"],
        velocity["fill_rate"] * 100,
        velocity.get("top_blocker", "none"),
    )

    # Step 2: Generate ALL hypotheses (performance + velocity + decay).
    # Lower minimum fill threshold — generate velocity hypotheses always.
    hypotheses = generate_hypotheses(obs, velocity)
    decay_h = detect_performance_decay(obs)
    if decay_h:
        hypotheses.append(decay_h)

    if not hypotheses:
        logger.info("No hypotheses generated (insufficient data)")
        tracking = _load_tracking()
        tracking["cycle_count"] = tracking.get("cycle_count", 0) + 1
        _save_tracking(tracking)
        return {
            "cycle_time": datetime.now(timezone.utc).isoformat(),
            "observation": obs, "velocity": velocity,
            "hypotheses": [], "pipeline_actions": pipeline_actions,
        }

    logger.info("Generated %d hypotheses", len(hypotheses))

    # Step 3: Full-cascade backtest each hypothesis.
    backtest_details: dict[str, dict] = {}
    for h in hypotheses:
        bt = backtest_hypothesis(h)
        h.shadow_pnl = bt["shadow_pnl"]
        h.shadow_fills = bt["shadow_fills"]
        h.shadow_win_rate = bt["shadow_win_rate"]
        h.changed_decision_count = bt.get("changed_decision_count", 0)
        if h.predicted_pnl_per_fill == 0:
            h.predicted_pnl_per_fill = bt.get("shadow_pnl_per_fill", 0)
        backtest_details[h.hypothesis_id] = bt

    # Step 4: Score and rank.
    # Gate: skip hypotheses that change zero decisions (inert/cosmetic).
    scored = []
    for h in hypotheses:
        if h.changed_decision_count == 0:
            h.status = "inert"
            logger.info(
                "  %s: INERT (changed_decision_count=0, family=%s)",
                h.hypothesis_id, h.policy_family or "none",
            )
            continue

        s = score_hypothesis(h)
        bt = backtest_details.get(h.hypothesis_id, {})
        decomp = bt.get("decomposition", {})
        logger.info(
            "  %s [%s]: score=%.2f, shadow_pnl=$%.2f, fills=%d, "
            "wr=%.0f%%, changed=%d, +fills=%d, -fills=%d",
            h.hypothesis_id, h.policy_family or "?", s,
            h.shadow_pnl, h.shadow_fills,
            h.shadow_win_rate * 100, h.changed_decision_count,
            bt.get("estimated_new_fills", 0), bt.get("removed_fills", 0),
        )
        if decomp:
            logger.info(
                "    WHY: +profitable(UP=%d,DOWN=%d) +unprofitable(UP=%d,DOWN=%d) "
                "-winning(UP=%d,DOWN=%d) -losing(UP=%d,DOWN=%d) "
                "avg_added_px=%.2f avg_removed_px=%.2f",
                decomp.get("added_profitable_UP", 0), decomp.get("added_profitable_DOWN", 0),
                decomp.get("added_unprofitable_UP", 0), decomp.get("added_unprofitable_DOWN", 0),
                decomp.get("removed_winning_UP", 0), decomp.get("removed_winning_DOWN", 0),
                decomp.get("removed_losing_UP", 0), decomp.get("removed_losing_DOWN", 0),
                decomp.get("avg_added_entry_price", 0), decomp.get("avg_removed_entry_price", 0),
            )
        if s > 0 and h.shadow_pnl >= 0:
            h.status = "shadow"
            scored.append((s, h))
        elif h.shadow_pnl < -2.0:
            h.status = "killed"
            logger.info("    KILLED (negative shadow PnL)")
        else:
            h.status = "inconclusive"

    scored.sort(key=lambda x: x[0], reverse=True)

    # De-duplicate by policy_family: keep only best arm per family.
    seen_families: set[str] = set()
    deduped_scored: list[tuple[float, Hypothesis]] = []
    for s, h in scored:
        fam = h.policy_family or h.hypothesis_id
        if fam in seen_families:
            logger.info(
                "    REDUNDANT: %s (family=%s already has better arm)",
                h.hypothesis_id, fam,
            )
            h.status = "redundant"
            continue
        seen_families.add(fam)
        deduped_scored.append((s, h))
    scored = deduped_scored

    # Step 5: Auto-promote best hypothesis if no active trial/validated.
    # SAFETY: Only auto-promote restrictive hypotheses. Expansive hypotheses
    # (that seek more fills by widening caps/deltas) remain shadow-only until
    # exact counterfactual replay is operational.
    promoted_id = None
    if scored:
        tracking = _load_tracking()
        active = [
            h_id for h_id, rec in tracking.get("hypotheses", {}).items()
            if rec.get("promotion_stage") in ("trial", "validated")
        ]
        if not active:
            # Find best restrictive hypothesis.
            best_restrictive = None
            best_expansive = None
            for s, h in scored:
                is_expansive = _is_expansive_hypothesis(h)
                if not is_expansive and best_restrictive is None:
                    best_restrictive = (s, h)
                if is_expansive and best_expansive is None:
                    best_expansive = (s, h)

            if best_restrictive:
                best_score, best_h = best_restrictive
                promote_hypothesis(best_h)
                best_h.status = "trial"
                promoted_id = best_h.hypothesis_id
                logger.info(
                    "AUTO-PROMOTED (restrictive): %s (score=%.2f, improvement=$%.2f)",
                    best_h.hypothesis_id, best_score, best_h.predicted_improvement,
                )
            elif best_expansive:
                logger.info(
                    "SHADOW-ONLY (expansive): %s blocked from auto-promote "
                    "(score=%.2f) — requires exact replay validation",
                    best_expansive[1].hypothesis_id, best_expansive[0],
                )
            else:
                logger.info("No promotable hypotheses found")
        else:
            logger.info("SKIP promotion: active hypothesis (%s)", ", ".join(active))

    # Step 5b: Multi-arm shadow evaluation with challenger quotas.
    # Maintain: top 1 per family, top 3 restrictive, top 3 expansive.
    shadow_eval = {}
    shadow_challengers: dict[str, list] = {
        "by_family": {},    # Best arm per family
        "restrictive": [],  # Top 3 restrictive
        "expansive": [],    # Top 3 expansive
    }
    if hypotheses:
        # Select quota-limited challengers for shadow evaluation.
        eval_candidates: list[Hypothesis] = []
        family_best: dict[str, tuple[float, Hypothesis]] = {}
        restrictive_top: list[tuple[float, Hypothesis]] = []
        expansive_top: list[tuple[float, Hypothesis]] = []

        for s, h in scored:
            fam = h.policy_family or h.hypothesis_id
            is_exp = _is_expansive_hypothesis(h)

            # Top 1 per family.
            if fam not in family_best or s > family_best[fam][0]:
                family_best[fam] = (s, h)

            # Top 3 restrictive/expansive.
            if is_exp:
                expansive_top.append((s, h))
            else:
                restrictive_top.append((s, h))

        # Collect unique candidates.
        seen_ids: set[str] = set()
        for fam, (s, h) in family_best.items():
            if h.hypothesis_id not in seen_ids:
                eval_candidates.append(h)
                seen_ids.add(h.hypothesis_id)
                shadow_challengers["by_family"][fam] = h.hypothesis_id

        for s, h in restrictive_top[:3]:
            if h.hypothesis_id not in seen_ids:
                eval_candidates.append(h)
                seen_ids.add(h.hypothesis_id)
            shadow_challengers["restrictive"].append(h.hypothesis_id)

        for s, h in expansive_top[:3]:
            if h.hypothesis_id not in seen_ids:
                eval_candidates.append(h)
                seen_ids.add(h.hypothesis_id)
            shadow_challengers["expansive"].append(h.hypothesis_id)

        logger.info(
            "Shadow quotas: %d families, %d restrictive, %d expansive, %d total candidates",
            len(family_best), min(3, len(restrictive_top)),
            min(3, len(expansive_top)), len(eval_candidates),
        )

        try:
            shadow_eval = evaluate_shadow_arms(eval_candidates)
            logger.info(
                "Shadow arms: %d arms × %d windows evaluated",
                shadow_eval.get("arms_evaluated", 0),
                shadow_eval.get("windows_evaluated", 0),
            )
            for h_id, arm in shadow_eval.get("arms", {}).items():
                logger.info(
                    "  %s: fills=%d, wr=%.0f%%, pnl=$%.2f, $/fill=$%.4f",
                    h_id, arm["fills"], arm["win_rate"] * 100,
                    arm["pnl"], arm["pnl_per_fill"],
                )
        except Exception as e:
            logger.warning("Shadow evaluation failed: %s", e)

    # Step 6: Write results.
    tracking = _load_tracking()
    tracking["cycle_count"] = tracking.get("cycle_count", 0) + 1
    _save_tracking(tracking)

    # Step 7: Build 4-question live policy report.
    live_report = build_live_policy_report()
    if live_report:
        logger.info("=== LIVE POLICY REPORT ===")
        logger.info("  Q1 (live policy): %s", live_report.get("live_policy_summary", "none"))
        logger.info("  Q2 (changed decisions): %d", live_report.get("changed_decision_count", 0))
        logger.info("  Q3 (realized PnL from changes): $%.2f", live_report.get("changed_decisions_pnl", 0))
        logger.info("  Q4 (best challenger): %s", live_report.get("best_challenger_summary", "none"))

    # Step 8: Build EV-based blocker ranking.
    blocker_ev_ranking = build_blocker_ev_ranking()

    # Step 9: Build and persist expansion frontier (cycle-scoped snapshots).
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    frontier = build_expansion_frontier()
    if frontier:
        persist_expansion_frontier(frontier, cycle_id=cycle_id)
        logger.info("Expansion frontier: %d cells, top: %s",
                     len(frontier),
                     f"{frontier[0]['skip_reason']}/{frontier[0]['direction']}"
                     f"/px={frontier[0]['price_bucket']} cf=${frontier[0].get('upper_bound_pnl_usd_std5', 0):.2f}"
                     if frontier else "none")

    # Step 10: Build EV-conditioned observation table.
    ev_table = build_ev_observation_table()

    # Step 11: Build execution failure report + funnel.
    exec_report = build_execution_failure_report()
    exec_funnel = build_execution_funnel()
    if exec_funnel:
        f = exec_funnel.get("funnel", {})
        r = exec_funnel.get("rates", {})
        p = exec_funnel.get("pnl", {})
        logger.info(
            "EXEC FUNNEL: %d windows → %d attempted (%.1f%%) → %d accepted (%.1f%%) "
            "→ %d filled (%.1f%% overall) | %d failed | PnL=$%.4f | "
            "exec_failure_cf=$%.4f (%d)",
            f.get("total_windows", 0), f.get("attempted", 0), r.get("attempt_rate", 0) * 100,
            f.get("accepted", 0), r.get("accept_rate", 0) * 100,
            f.get("filled", 0), r.get("overall_fill_rate", 0) * 100,
            f.get("failed", 0), p.get("realized_pnl", 0),
            p.get("exec_failure_cf_pnl", 0), p.get("exec_failure_cf_count", 0),
        )

    # Step 12: Generate and persist allowlist rules from frontier.
    allowlist_rules: list[AllowlistRule] = []
    if frontier:
        allowlist_rules = generate_allowlist_rules(frontier)
        if allowlist_rules:
            persist_allowlist_rules(allowlist_rules)
            for r in allowlist_rules:
                logger.info(
                    "  ALLOWLIST: %s — support=%d, cf/fill=$%.4f, "
                    "P(EV>0)=%.0f%%, edge=%+.1f%%",
                    r.rule_id, r.support, r.exact_cf_per_fill,
                    r.p_ev_positive * 100, r.wr_edge * 100,
                )

    # Step 13: EV consistency audit + h_dir_down diagnosis.
    ev_audit = build_ev_consistency_audit(frontier) if frontier else {"status": "no_frontier"}
    h_dir_down_diag = build_h_dir_down_diagnosis()

    # Step 14: UP salvage analysis.
    up_salvage = _analyze_up_salvage_cells()
    if up_salvage:
        logger.info("UP salvage: %d cells analyzed, %d measurable, %d positive-EV",
                     up_salvage.get("total_cells", 0),
                     up_salvage.get("measurable_cells", 0),
                     up_salvage.get("positive_ev_cells", 0))

    output = {
        "cycle_time": datetime.now(timezone.utc).isoformat(),
        "baseline_snapshot": baseline_snapshot,
        "observation": obs,
        "velocity": velocity,
        "fill_ev": fill_ev,
        "hypotheses": [asdict(h) for h in hypotheses],
        "scored_ranking": [(s, h.hypothesis_id) for s, h in scored],
        "backtest_details": {h_id: bt for h_id, bt in backtest_details.items()},
        "shadow_arms": shadow_eval.get("arms", {}),
        "shadow_challengers": shadow_challengers,
        "pipeline_actions": pipeline_actions,
        "promoted": promoted_id,
        "live_policy_report": live_report,
        "blocker_ev_ranking": blocker_ev_ranking,
        "expansion_frontier_actionable": [c for c in (frontier or []) if c.get("actionable")][:20],
        "expansion_frontier_signal_only": [c for c in (frontier or []) if not c.get("actionable")][:20],
        "ev_observation_table": ev_table,
        "execution_failures": exec_report,
        "execution_funnel": exec_funnel,
        "allowlist_rules": [asdict(r) for r in allowlist_rules],
        "ev_consistency_audit": ev_audit,
        "h_dir_down_diagnosis": h_dir_down_diag,
        "up_salvage": up_salvage,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2, default=str))
    logger.info("Results written to %s", RESULTS_PATH)
    logger.info("=== Autoresearch v3 cycle complete ===")
    return output


# ---------------------------------------------------------------------------
# Multi-arm shadow evaluation
# ---------------------------------------------------------------------------

SHADOW_DB_TABLE = "shadow_arm_evaluations"


def _init_shadow_table(conn: sqlite3.Connection) -> None:
    """Create shadow evaluation table if it doesn't exist."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SHADOW_DB_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL,
            hypothesis_id TEXT NOT NULL,
            would_trade INTEGER NOT NULL,
            direction TEXT,
            hyp_order_price REAL,
            hyp_shares REAL,
            resolved_outcome TEXT,
            counterfactual_pnl_usd REAL,
            created_at TEXT NOT NULL,
            UNIQUE(window_start_ts, hypothesis_id)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_shadow_arm_hypothesis
            ON {SHADOW_DB_TABLE}(hypothesis_id)
    """)


def evaluate_shadow_arms(hypotheses: list[Hypothesis], lookback_hours: int = 24) -> dict:
    """Evaluate top hypotheses against recent resolved windows.

    For each window that has been resolved (has resolved_outcome), check
    whether each hypothesis would have traded, and compute the counterfactual PnL.
    """
    conn = _db_connect()
    _init_shadow_table(conn)

    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    now_iso = datetime.now(timezone.utc).isoformat()

    # Get all resolved windows in lookback period.
    windows = conn.execute("""
        SELECT window_start_ts, direction, order_price, best_ask, best_bid,
               delta, order_status, resolved_outcome, counterfactual_pnl_usd,
               filled, pnl_usd
        FROM window_trades
        WHERE window_start_ts > ?
          AND resolved_outcome IS NOT NULL
        ORDER BY window_start_ts ASC
    """, (cutoff_ts,)).fetchall()

    if not windows:
        conn.close()
        return {"arms_evaluated": 0, "windows_evaluated": 0}

    arm_results: dict[str, dict] = {}
    rows_inserted = 0

    for h in hypotheses[:10]:  # Cap at 10 arms
        h_id = h.hypothesis_id
        arm = {"fills": 0, "wins": 0, "pnl": 0.0, "skips": 0}

        for row in windows:
            wts, direction, order_price, best_ask, best_bid, delta, status, resolved, cf_pnl, filled, actual_pnl = row

            if not direction or not resolved:
                continue

            # Check if hypothesis would trade this window.
            would_trade = _fill_passes_hypothesis(
                direction, order_price, None, None, None, delta, h.params
            )

            # Determine hypothetical PnL.
            hyp_pnl = None
            if would_trade:
                arm["fills"] += 1
                if status.startswith("skip_"):
                    # Window was skipped but hypothesis would have traded.
                    hyp_price = order_price if order_price and order_price > 0 else best_ask
                    if hyp_price and hyp_price > 0:
                        hyp_shares = max(5.0, round(5.0 / hyp_price, 2))
                        if direction == resolved:
                            hyp_pnl = round(hyp_shares * (1.0 - hyp_price), 6)
                            arm["wins"] += 1
                        else:
                            hyp_pnl = round(-hyp_shares * hyp_price, 6)
                elif filled == 1:
                    # Window was filled under current policy.
                    hyp_pnl = actual_pnl
                    if direction == resolved:
                        arm["wins"] += 1
                if hyp_pnl is not None:
                    arm["pnl"] += hyp_pnl
            else:
                arm["skips"] += 1

            # Persist shadow evaluation.
            try:
                conn.execute(f"""
                    INSERT INTO {SHADOW_DB_TABLE}
                        (window_start_ts, hypothesis_id, would_trade, direction,
                         hyp_order_price, resolved_outcome, counterfactual_pnl_usd, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(window_start_ts, hypothesis_id) DO UPDATE SET
                        would_trade=excluded.would_trade,
                        resolved_outcome=excluded.resolved_outcome,
                        counterfactual_pnl_usd=excluded.counterfactual_pnl_usd
                """, (
                    wts, h_id, 1 if would_trade else 0, direction,
                    order_price, resolved, hyp_pnl, now_iso,
                ))
                rows_inserted += 1
            except sqlite3.Error:
                pass

        arm["win_rate"] = round(arm["wins"] / arm["fills"], 3) if arm["fills"] > 0 else 0.0
        arm["pnl_per_fill"] = round(arm["pnl"] / arm["fills"], 4) if arm["fills"] > 0 else 0.0
        arm["pnl"] = round(arm["pnl"], 2)
        arm_results[h_id] = arm

    conn.commit()
    conn.close()

    return {
        "arms_evaluated": len(arm_results),
        "windows_evaluated": len(windows),
        "arms": arm_results,
    }


def get_shadow_arm_rankings() -> list[tuple[str, dict]]:
    """Return shadow arms ranked by PnL, for reporting."""
    conn = _db_connect()
    try:
        _init_shadow_table(conn)
        rows = conn.execute(f"""
            SELECT hypothesis_id,
                   COUNT(*) as windows,
                   SUM(CASE WHEN would_trade = 1 THEN 1 ELSE 0 END) as fills,
                   SUM(CASE WHEN would_trade = 1 AND counterfactual_pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                   COALESCE(SUM(CASE WHEN would_trade = 1 THEN counterfactual_pnl_usd ELSE 0 END), 0) as total_pnl
            FROM {SHADOW_DB_TABLE}
            GROUP BY hypothesis_id
            ORDER BY total_pnl DESC
        """).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
    conn.close()

    rankings = []
    for h_id, windows, fills, wins, pnl in rows:
        rankings.append((h_id, {
            "windows": windows,
            "fills": fills,
            "wins": wins,
            "pnl": round(pnl, 2),
            "win_rate": round(wins / fills, 3) if fills > 0 else 0.0,
            "pnl_per_fill": round(pnl / fills, 4) if fills > 0 else 0.0,
        }))
    return rankings


# ---------------------------------------------------------------------------
# 4-question live policy report
# ---------------------------------------------------------------------------

def build_live_policy_report() -> dict:
    """Answer the 4 key questions about the current live policy.

    Q1: What policy is live right now?
    Q2: How many decisions did it actually change?
    Q3: What exact realized PnL did those changed decisions produce?
    Q4: What is the best shadow challenger right now?
    """
    # Q1: Current live policy.
    live_policy: dict = {"hypothesis_id": None, "params": {}, "stage": "none"}
    if OVERRIDES_PATH.exists():
        try:
            data = json.loads(OVERRIDES_PATH.read_text())
            live_policy = {
                "hypothesis_id": data.get("hypothesis_id"),
                "params": data.get("params", {}),
                "stage": data.get("promotion_stage", "unknown"),
                "promoted_at": data.get("promoted_at"),
                "description": data.get("description"),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # Q2 + Q3: Changed decisions and their realized PnL.
    changed_count = 0
    changed_pnl = 0.0
    h_id = live_policy.get("hypothesis_id")
    promoted_at = live_policy.get("promoted_at")

    if h_id and promoted_at:
        conn = _db_connect()
        try:
            # Count windows tagged with this hypothesis that wouldn't exist without it.
            rows = conn.execute("""
                SELECT order_status, pnl_usd, direction, counterfactual_pnl_usd,
                       override_hypothesis_id
                FROM window_trades
                WHERE created_at > ?
                  AND override_hypothesis_id = ?
            """, (promoted_at, h_id)).fetchall()
            changed_count = len(rows)
            changed_pnl = sum(r[1] or 0 for r in rows if r[0] == "live_filled")

            # Also count windows where this policy caused a skip (directional_mode).
            skip_rows = conn.execute("""
                SELECT COUNT(*), direction
                FROM window_trades
                WHERE created_at > ?
                  AND order_status = 'skip_directional_mode'
                GROUP BY direction
            """, (promoted_at,)).fetchall()
            for cnt, d in skip_rows:
                changed_count += cnt
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    # Q4: Best shadow challenger.
    rankings = get_shadow_arm_rankings()
    best_challenger: dict = {}
    if rankings:
        best_id, best_stats = rankings[0]
        if best_id != h_id:
            best_challenger = {"hypothesis_id": best_id, **best_stats}

    summary = live_policy.get("description") or str(live_policy.get("params", {}))
    challenger_summary = (
        f"{best_challenger.get('hypothesis_id', 'none')} "
        f"(pnl=${best_challenger.get('pnl', 0):.2f}, "
        f"wr={best_challenger.get('win_rate', 0):.0%}, "
        f"fills={best_challenger.get('fills', 0)})"
        if best_challenger else "none"
    )

    return {
        "live_policy": live_policy,
        "live_policy_summary": summary,
        "changed_decision_count": changed_count,
        "changed_decisions_pnl": round(changed_pnl, 2),
        "best_challenger": best_challenger,
        "best_challenger_summary": challenger_summary,
    }


# ---------------------------------------------------------------------------
# EV-based blocker ranking
# ---------------------------------------------------------------------------

BLOCKER_CLASSES = {
    "skip_bad_book": "structural",
    "skip_missing_price": "structural",
    "live_order_failed": "execution_failure",
    "live_cancelled_unfilled": "execution_failure",
    "live_cancel_unknown": "execution_failure",
    "skip_delta_too_small": "policy_guardrail",
    "skip_delta_too_large": "policy_guardrail",
    "skip_direction_delta_too_small": "policy_guardrail",
    "skip_price_outside_guardrails": "policy_guardrail",
    "skip_price_bucket_floor": "policy_guardrail",
    "skip_directional_mode": "policy_guardrail",
    "skip_suppressed_hour": "policy_guardrail",
    "skip_toxic_order_flow": "intentional_shadow_only",
    "skip_shadow_only_direction": "intentional_shadow_only",
    "skip_midpoint_kill_zone": "intentional_shadow_only",
    "skip_size_too_small": "policy_guardrail",
}


def build_blocker_ev_ranking(hours: int = 48) -> list[dict]:
    """Rank blockers by EV/day, not by frequency.

    For each skip reason × direction × price bucket, compute:
    - count, wins, actual_wr, break_even_wr, wr_edge
    - exact counterfactual PnL where available
    - estimated EV/day if unblocked
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, direction, best_ask, order_price,
               resolved_outcome, counterfactual_pnl_usd
        FROM window_trades
        WHERE order_status LIKE 'skip_%'
          AND window_start_ts > ?
          AND resolved_outcome IS NOT NULL
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return []

    # Group by (skip_reason, direction, price_bucket).
    cells: dict[tuple, dict] = {}
    for status, direction, best_ask, order_price, resolved, cf_pnl in rows:
        entry_px = best_ask or order_price or 0
        price_bucket = f"{round(entry_px * 10) / 10:.1f}" if entry_px > 0 else "unknown"
        key = (status, direction or "?", price_bucket)
        if key not in cells:
            cells[key] = {
                "skip_reason": status,
                "blocker_class": BLOCKER_CLASSES.get(status, "unknown"),
                "direction": direction or "?",
                "price_bucket": price_bucket,
                "count": 0, "wins": 0, "losses": 0,
                "cf_pnl_sum": 0.0, "cf_count": 0,
            }
        c = cells[key]
        c["count"] += 1
        if direction and resolved and direction == resolved:
            c["wins"] += 1
        elif direction and resolved:
            c["losses"] += 1
        if cf_pnl is not None:
            c["cf_pnl_sum"] += cf_pnl
            c["cf_count"] += 1

    # Compute EV metrics for each cell.
    results = []
    for key, c in cells.items():
        n = c["count"]
        if n == 0:
            continue

        try:
            entry_px = float(c["price_bucket"])
        except (ValueError, TypeError):
            entry_px = 0.50

        actual_wr = c["wins"] / n if n > 0 else 0.0
        be_wr = break_even_win_rate(entry_px) if entry_px > 0 else 0.50
        wr_edge = actual_wr - be_wr

        # EV per trade from exact counterfactual.
        if c["cf_count"] > 0:
            ev_per_trade = c["cf_pnl_sum"] / c["cf_count"]
        elif entry_px > 0:
            # Estimate from win rate and price — but only if we have price.
            ev_per_trade = actual_wr * (1 - entry_px) - (1 - actual_wr) * entry_px
        else:
            # No price data and no counterfactual — mark as unmeasurable.
            ev_per_trade = None

        # EV per day: (trades/day) * EV/trade.
        trades_per_day = n / max(hours / 24, 1)
        ev_per_day = (trades_per_day * ev_per_trade) if ev_per_trade is not None else None

        results.append({
            "skip_reason": c["skip_reason"],
            "blocker_class": c["blocker_class"],
            "direction": c["direction"],
            "price_bucket": c["price_bucket"],
            "count": n,
            "wins": c["wins"],
            "losses": c["losses"],
            "actual_wr": round(actual_wr, 3),
            "break_even_wr": round(be_wr, 3),
            "wr_edge": round(wr_edge, 3),
            "exact_cf_pnl": round(c["cf_pnl_sum"], 2) if c["cf_count"] > 0 else None,
            "exact_cf_count": c["cf_count"],
            "ev_per_trade": round(ev_per_trade, 4) if ev_per_trade is not None else None,
            "ev_per_day": round(ev_per_day, 2) if ev_per_day is not None else None,
            "trades_per_day": round(trades_per_day, 1),
            "measurable": ev_per_trade is not None,
        })

    # Sort: measurable cells first by EV/day, then unmeasurable by count.
    results.sort(
        key=lambda x: (
            x["measurable"],
            x["ev_per_day"] if x["ev_per_day"] is not None else -9999,
        ),
        reverse=True,
    )

    # Log top results.
    for i, r in enumerate(results[:10]):
        ev_trade = f"${r['ev_per_trade']:.4f}" if r["ev_per_trade"] is not None else "N/A"
        ev_day = f"${r['ev_per_day']:.2f}" if r["ev_per_day"] is not None else "N/A"
        logger.info(
            "  Blocker EV #%d: %s/%s/px=%s n=%d wr=%.0f%% be=%.0f%% "
            "edge=%.1f%% EV/trade=%s EV/day=%s [%s]",
            i + 1, r["skip_reason"], r["direction"], r["price_bucket"],
            r["count"], r["actual_wr"] * 100, r["break_even_wr"] * 100,
            r["wr_edge"] * 100, ev_trade, ev_day,
            r["blocker_class"],
        )

    return results


# ---------------------------------------------------------------------------
# Expansion frontier builder
# ---------------------------------------------------------------------------

def build_expansion_frontier(hours: int = 48) -> list[dict]:
    """Build a measured expansion frontier from resolved skip windows.

    Groups by skip_reason × direction × price_bucket × delta_bucket × hour_bucket
    × edge_tier × strategy_fingerprint × counterfactual_quality.

    Produces TWO outputs via the `actionable` flag:
    - exact_actionable_frontier: only CQ_EXACT, eligible for allowlists
    - signal_only_frontier: CQ_MISSING_PRICE/HEURISTIC/NONE, for instrumentation only
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, direction, best_ask, best_bid, order_price, delta,
               resolved_outcome, counterfactual_pnl_usd, strategy_fingerprint,
               edge_tier, window_start_ts, filled
        FROM window_trades
        WHERE order_status LIKE 'skip_%'
          AND window_start_ts > ?
          AND resolved_outcome IS NOT NULL
          AND direction IS NOT NULL
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return []

    cells: dict[tuple, dict] = {}
    for (status, direction, best_ask, best_bid, order_price, delta,
         resolved, cf_pnl, fingerprint, edge_tier, wts, filled) in rows:
        entry_px = best_ask or order_price or 0
        price_bucket = f"{round(entry_px * 10) / 10:.1f}" if entry_px > 0 else "unknown"
        delta_bucket = _delta_bucket_label(abs(delta or 0))

        # Hour bucket from window_start_ts.
        try:
            hour_bucket = f"{datetime.fromtimestamp(wts, tz=timezone.utc).hour:02d}"
        except (ValueError, TypeError, OSError):
            hour_bucket = "unknown"

        et = edge_tier or "unknown"
        fp_str = fingerprint or "unknown"

        # Classify CQ for this observation.
        cq = classify_counterfactual_quality(
            best_ask=best_ask, order_price=order_price,
            resolved_outcome=resolved, counterfactual_pnl=cf_pnl,
            is_live_fill=(filled == 1),
        )

        # Key includes all dimensions — no merging incompatible regimes.
        key = (status, direction, price_bucket, delta_bucket, hour_bucket, et, fp_str, cq)

        if key not in cells:
            cells[key] = {
                "skip_reason": status,
                "blocker_class": BLOCKER_CLASSES.get(status, "unknown"),
                "direction": direction,
                "price_bucket": price_bucket,
                "delta_bucket": delta_bucket,
                "hour_bucket": hour_bucket,
                "edge_tier": et,
                "strategy_fingerprint": fp_str,
                "counterfactual_quality": cq,
                "n": 0, "wins": 0, "losses": 0,
                "cf_pnl_values": [],
                "entry_prices": [],
                "fill_probs": [],
                "sample_wts": [],
                "quality_counts": {t: 0 for t in ALL_CQ_TIERS},
            }
        c = cells[key]
        c["n"] += 1
        if direction == resolved:
            c["wins"] += 1
        else:
            c["losses"] += 1
        if cf_pnl is not None:
            c["cf_pnl_values"].append(cf_pnl)
        if entry_px > 0:
            c["entry_prices"].append(entry_px)
        c["quality_counts"][cq] += 1
        # Estimate fill probability.
        fp = estimate_fill_probability(
            order_price=order_price or entry_px,
            best_ask=best_ask,
            best_bid=best_bid,
        )
        c["fill_probs"].append(fp)
        c["sample_wts"].append(wts)

    results = []
    for key, c in cells.items():
        n = c["n"]
        if n < 2:
            continue

        qc = c["quality_counts"]
        cq_tier = c["counterfactual_quality"]

        # Actionable = exact-price tier only.
        actionable = cq_tier == CQ_EXACT

        has_price_data = bool(c["entry_prices"])
        avg_entry = (sum(c["entry_prices"]) / len(c["entry_prices"])) if has_price_data else None

        actual_wr = c["wins"] / n

        if avg_entry is not None and avg_entry > 0:
            be_wr = break_even_win_rate(avg_entry)
            wr_edge = actual_wr - be_wr
        else:
            be_wr = None
            wr_edge = None

        # Standardized counterfactual PnL (upper bound, pre-fillability).
        cf_values = c["cf_pnl_values"]
        upper_bound_pnl_usd_std5 = round(sum(cf_values), 2) if cf_values else None
        cf_per_fill = round(sum(cf_values) / len(cf_values), 4) if cf_values else None

        # Bootstrap lower confidence bound.
        bootstrap_lcb = None
        if len(cf_values) >= 5:
            import random
            rng = random.Random(42)
            means = sorted(
                sum(rng.choice(cf_values) for _ in range(len(cf_values))) / len(cf_values)
                for _ in range(1000)
            )
            bootstrap_lcb = round(means[int(len(means) * 0.10)], 4)

        # P(EV>0) — only with price data.
        p_positive = bayesian_p_ev_positive(c["wins"], n, avg_entry) if (avg_entry and avg_entry > 0) else None

        # Fillability adjustment.
        fill_probs = c["fill_probs"]
        avg_fill_prob = (sum(fill_probs) / len(fill_probs)) if fill_probs else 0.30
        fillability_adjusted_pnl_usd_std5 = None
        fillability_adjusted_per_fill = None
        if cf_values and cf_per_fill is not None:
            fillability_adjusted_per_fill = round(cf_per_fill * avg_fill_prob, 4)
            fillability_adjusted_pnl_usd_std5 = round(upper_bound_pnl_usd_std5 * avg_fill_prob, 2) if upper_bound_pnl_usd_std5 else None

        # Sample window timestamps for audit traceability.
        sample_ids = sorted(c["sample_wts"])[:5]

        results.append({
            "skip_reason": c["skip_reason"],
            "blocker_class": c["blocker_class"],
            "direction": c["direction"],
            "price_bucket": c["price_bucket"],
            "delta_bucket": c["delta_bucket"],
            "hour_bucket": c["hour_bucket"],
            "edge_tier": c["edge_tier"],
            "strategy_fingerprint": c["strategy_fingerprint"],
            "counterfactual_quality": cq_tier,
            "actionable": actionable,
            "quality_counts": dict(qc),
            "n": n,
            "wins": c["wins"],
            "losses": c["losses"],
            "avg_entry_price": round(avg_entry, 4) if avg_entry is not None else None,
            "actual_wr": round(actual_wr, 3),
            "break_even_wr": round(be_wr, 3) if be_wr is not None else None,
            "wr_edge": round(wr_edge, 3) if wr_edge is not None else None,
            # PnL units: explicit labels (#10).
            "upper_bound_pnl_usd_std5": upper_bound_pnl_usd_std5,
            "counterfactual_pnl_usd_std5_per_fill": cf_per_fill,
            "avg_fill_probability": round(avg_fill_prob, 3),
            "fillability_adjusted_pnl_usd_std5": fillability_adjusted_pnl_usd_std5,
            "fillability_adjusted_per_fill": fillability_adjusted_per_fill,
            "fillability_model_version": FILLABILITY_MODEL_VERSION,
            "bootstrap_lcb_per_fill": bootstrap_lcb,
            "p_ev_positive": round(p_positive, 3) if p_positive is not None else None,
            "sample_window_start_ts": sample_ids,
        })

    # Internal consistency audit: flag cells where wr_edge < 0 but cf_per_fill > 0.
    for r in results:
        we = r.get("wr_edge")
        cf = r.get("counterfactual_pnl_usd_std5_per_fill")
        if we is not None and cf is not None and we < 0 and cf > 0:
            r["consistency_flag"] = "wr_edge_negative_but_cf_positive"
            logger.warning(
                "CONSISTENCY FLAG: %s/%s/%s — wr_edge=%.3f but cf_per_fill=$%.4f",
                r["skip_reason"], r["direction"], r["price_bucket"],
                we, cf,
            )

    # Sort: actionable first, then by fillability-adjusted PnL.
    results.sort(
        key=lambda x: (
            1 if x.get("actionable") else 0,
            x.get("fillability_adjusted_pnl_usd_std5") or x.get("upper_bound_pnl_usd_std5") or -9999,
        ),
        reverse=True,
    )
    return results


def persist_expansion_frontier(frontier: list[dict], cycle_id: str | None = None) -> int:
    """Persist expansion frontier cells as cycle-scoped snapshots.

    Does NOT drop the table. Uses cycle_id to scope each snapshot.
    Old snapshots are preserved for cross-cycle comparison.
    """
    if not frontier:
        return 0

    conn = _db_connect()
    # Create table with cycle-scoped snapshots (no destructive DROP).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expansion_frontier_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            skip_reason TEXT NOT NULL,
            blocker_class TEXT,
            direction TEXT NOT NULL,
            price_bucket TEXT NOT NULL DEFAULT 'unknown',
            delta_bucket TEXT NOT NULL DEFAULT 'unknown',
            hour_bucket TEXT NOT NULL DEFAULT 'unknown',
            edge_tier TEXT NOT NULL DEFAULT 'unknown',
            strategy_fingerprint TEXT NOT NULL DEFAULT 'unknown',
            counterfactual_quality TEXT NOT NULL DEFAULT 'no_counterfactual',
            actionable INTEGER NOT NULL DEFAULT 0,
            n INTEGER NOT NULL,
            wins INTEGER,
            losses INTEGER,
            avg_entry_price REAL,
            actual_wr REAL,
            break_even_wr REAL,
            wr_edge REAL,
            upper_bound_pnl_usd_std5 REAL,
            counterfactual_pnl_usd_std5_per_fill REAL,
            avg_fill_probability REAL,
            fillability_adjusted_pnl_usd_std5 REAL,
            fillability_adjusted_per_fill REAL,
            fillability_model_version TEXT,
            bootstrap_lcb_per_fill REAL,
            p_ev_positive REAL,
            consistency_flag TEXT,
            sample_window_start_ts TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(cycle_id, skip_reason, direction, price_bucket, delta_bucket,
                   hour_bucket, edge_tier, strategy_fingerprint, counterfactual_quality)
        )
    """)

    now_iso = datetime.now(timezone.utc).isoformat()
    cid = cycle_id or now_iso
    count = 0
    error_count = 0

    for cell in frontier:
        # Normalize ALL key dimensions — no NULLs.
        pb = cell.get("price_bucket") or "unknown"
        db = cell.get("delta_bucket") or "unknown"
        hb = cell.get("hour_bucket") or "unknown"
        et = cell.get("edge_tier") or "unknown"
        fp = cell.get("strategy_fingerprint") or "unknown"
        cq = cell.get("counterfactual_quality") or CQ_NONE
        act = 1 if cell.get("actionable") else 0

        try:
            conn.execute("""
                INSERT INTO expansion_frontier_snapshots
                    (cycle_id, skip_reason, blocker_class, direction,
                     price_bucket, delta_bucket, hour_bucket, edge_tier,
                     strategy_fingerprint, counterfactual_quality, actionable,
                     n, wins, losses, avg_entry_price, actual_wr, break_even_wr,
                     wr_edge, upper_bound_pnl_usd_std5,
                     counterfactual_pnl_usd_std5_per_fill,
                     avg_fill_probability, fillability_adjusted_pnl_usd_std5,
                     fillability_adjusted_per_fill, fillability_model_version,
                     bootstrap_lcb_per_fill, p_ev_positive,
                     consistency_flag, sample_window_start_ts, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cycle_id, skip_reason, direction, price_bucket, delta_bucket,
                            hour_bucket, edge_tier, strategy_fingerprint, counterfactual_quality)
                DO UPDATE SET
                    blocker_class=excluded.blocker_class,
                    actionable=excluded.actionable,
                    n=excluded.n, wins=excluded.wins, losses=excluded.losses,
                    avg_entry_price=excluded.avg_entry_price,
                    actual_wr=excluded.actual_wr, break_even_wr=excluded.break_even_wr,
                    wr_edge=excluded.wr_edge,
                    upper_bound_pnl_usd_std5=excluded.upper_bound_pnl_usd_std5,
                    counterfactual_pnl_usd_std5_per_fill=excluded.counterfactual_pnl_usd_std5_per_fill,
                    avg_fill_probability=excluded.avg_fill_probability,
                    fillability_adjusted_pnl_usd_std5=excluded.fillability_adjusted_pnl_usd_std5,
                    fillability_adjusted_per_fill=excluded.fillability_adjusted_per_fill,
                    fillability_model_version=excluded.fillability_model_version,
                    bootstrap_lcb_per_fill=excluded.bootstrap_lcb_per_fill,
                    p_ev_positive=excluded.p_ev_positive,
                    consistency_flag=excluded.consistency_flag,
                    sample_window_start_ts=excluded.sample_window_start_ts,
                    created_at=excluded.created_at
            """, (
                cid, cell["skip_reason"], cell.get("blocker_class"),
                cell["direction"], pb, db, hb, et, fp, cq, act,
                cell["n"], cell.get("wins"), cell.get("losses"),
                cell.get("avg_entry_price"), cell.get("actual_wr"),
                cell.get("break_even_wr"), cell.get("wr_edge"),
                cell.get("upper_bound_pnl_usd_std5"),
                cell.get("counterfactual_pnl_usd_std5_per_fill"),
                cell.get("avg_fill_probability"),
                cell.get("fillability_adjusted_pnl_usd_std5"),
                cell.get("fillability_adjusted_per_fill"),
                cell.get("fillability_model_version", FILLABILITY_MODEL_VERSION),
                cell.get("bootstrap_lcb_per_fill"), cell.get("p_ev_positive"),
                cell.get("consistency_flag"),
                json.dumps(cell.get("sample_window_start_ts", [])),
                now_iso,
            ))
            count += 1
        except sqlite3.Error as exc:
            error_count += 1
            logger.error(
                "Failed to persist frontier cell %s/%s/%s: %s | payload=%s",
                cell.get("skip_reason"), cell.get("direction"), pb, exc,
                json.dumps({k: v for k, v in cell.items()
                            if k not in {"cf_pnl_values", "entry_prices", "fill_probs", "sample_wts"}},
                           default=str),
            )

    if error_count > 0:
        logger.error("Frontier persistence: %d errors out of %d cells", error_count, len(frontier))

    conn.commit()
    conn.close()
    logger.info("Persisted %d expansion frontier cells (cycle=%s, errors=%d)", count, cid, error_count)
    return count


# ---------------------------------------------------------------------------
# EV-conditioned observation tables
# ---------------------------------------------------------------------------

def build_ev_observation_table(hours: int = 48) -> dict:
    """Build EV-conditioned observation table for all windows.

    Replaces raw correctness tables. For each skip_reason × direction × price_bucket:
    - Count, win rate, avg entry price, break-even wr, net EV/trade, EV/day,
      loss clustering stats.

    This is the main ranking surface for autoresearch decisions.
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, direction, best_ask, order_price, delta,
               resolved_outcome, counterfactual_pnl_usd, pnl_usd, won, filled
        FROM window_trades
        WHERE window_start_ts > ?
          AND resolved_outcome IS NOT NULL
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return {"cells": [], "summary": {}}

    cells: dict[tuple, dict] = {}
    for status, direction, best_ask, order_price, delta, resolved, cf_pnl, pnl, won, filled in rows:
        entry_px = best_ask or order_price or 0
        price_bucket = f"{round(entry_px * 10) / 10:.1f}" if entry_px > 0 else "unknown"
        key = (status, direction or "?", price_bucket)

        if key not in cells:
            cells[key] = {
                "order_status": status,
                "direction": direction or "?",
                "price_bucket": price_bucket,
                "blocker_class": BLOCKER_CLASSES.get(status, "fill" if status == "live_filled" else "other"),
                "n": 0, "wins": 0, "losses": 0,
                "pnl_values": [], "cf_pnl_values": [],
                "entry_prices": [],
                "loss_streak_max": 0, "_current_loss_streak": 0,
            }
        c = cells[key]
        c["n"] += 1
        if direction and resolved and direction == resolved:
            c["wins"] += 1
            c["_current_loss_streak"] = 0
        elif direction and resolved:
            c["losses"] += 1
            c["_current_loss_streak"] += 1
            c["loss_streak_max"] = max(c["loss_streak_max"], c["_current_loss_streak"])

        if pnl is not None and filled:
            c["pnl_values"].append(pnl)
        if cf_pnl is not None:
            c["cf_pnl_values"].append(cf_pnl)
        if entry_px > 0:
            c["entry_prices"].append(entry_px)

    results = []
    total_ev_per_day = 0.0
    for key, c in cells.items():
        n = c["n"]
        if n == 0:
            continue

        has_price = bool(c["entry_prices"])
        avg_entry = (sum(c["entry_prices"]) / len(c["entry_prices"])) if has_price else None
        actual_wr = c["wins"] / n

        if avg_entry is not None and avg_entry > 0:
            be_wr = break_even_win_rate(avg_entry)
            wr_edge = actual_wr - be_wr
        else:
            be_wr = None
            wr_edge = None

        # EV/trade: prefer exact data. Never compute from actual_wr alone without price.
        if c["pnl_values"]:  # Live fills — always exact
            ev_per_trade = sum(c["pnl_values"]) / len(c["pnl_values"])
        elif c["cf_pnl_values"]:  # Skip with exact counterfactual
            ev_per_trade = sum(c["cf_pnl_values"]) / len(c["cf_pnl_values"])
        elif avg_entry is not None and avg_entry > 0:
            ev_per_trade = actual_wr * (1 - avg_entry) - (1 - actual_wr) * avg_entry
        else:
            ev_per_trade = None  # Unknown price → no EV computation

        trades_per_day = n / max(hours / 24, 1)
        ev_per_day = (trades_per_day * ev_per_trade) if ev_per_trade is not None else None
        if ev_per_day is not None:
            total_ev_per_day += ev_per_day

        # Downside stats.
        all_values = c["pnl_values"] or c["cf_pnl_values"]
        downside_deviation = 0.0
        if all_values:
            losses_only = [v for v in all_values if v < 0]
            if losses_only:
                mean_loss = sum(losses_only) / len(losses_only)
                downside_deviation = round(
                    (sum((v - mean_loss) ** 2 for v in losses_only) / len(losses_only)) ** 0.5, 4
                )

        # Classify data quality for this cell.
        has_exact_pnl = bool(c["pnl_values"]) or bool(c["cf_pnl_values"])
        cell_actionable = has_price and has_exact_pnl

        row = {
            "order_status": c["order_status"],
            "direction": c["direction"],
            "price_bucket": c["price_bucket"],
            "blocker_class": c["blocker_class"],
            "actionable": cell_actionable,
            "n": n,
            "wins": c["wins"],
            "losses": c["losses"],
            "avg_entry_price": round(avg_entry, 4) if avg_entry is not None else None,
            "actual_wr": round(actual_wr, 3),
            "break_even_wr": round(be_wr, 3) if be_wr is not None else None,
            "wr_edge": round(wr_edge, 3) if wr_edge is not None else None,
            "ev_per_trade": round(ev_per_trade, 4) if ev_per_trade is not None else None,
            "ev_per_day": round(ev_per_day, 2) if ev_per_day is not None else None,
            "trades_per_day": round(trades_per_day, 1),
            "max_loss_streak": c["loss_streak_max"],
            "downside_deviation": downside_deviation,
            "exact_data_count": len(c["pnl_values"]) + len(c["cf_pnl_values"]),
        }
        # Clean up internal fields.
        results.append(row)

    # Sort by EV/day.
    results.sort(
        key=lambda x: x["ev_per_day"] if x["ev_per_day"] is not None else -9999,
        reverse=True,
    )

    return {
        "cells": results,
        "summary": {
            "total_cells": len(results),
            "positive_ev_cells": sum(1 for r in results if (r["ev_per_day"] or 0) > 0),
            "negative_ev_cells": sum(1 for r in results if (r["ev_per_day"] or 0) < 0),
            "total_ev_per_day": round(total_ev_per_day, 2),
        },
    }


# ---------------------------------------------------------------------------
# Execution failure taxonomy
# ---------------------------------------------------------------------------

def build_execution_failure_report(hours: int = 72) -> dict:
    """Build execution failure taxonomy and counterfactual PnL report."""
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, direction, reason, resolved_outcome,
               counterfactual_pnl_usd, best_ask, order_price, delta
        FROM window_trades
        WHERE order_status IN ('live_order_failed', 'live_cancelled_unfilled', 'live_cancel_unknown')
          AND window_start_ts > ?
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return {"total_failures": 0, "by_error": {}, "by_direction": {}}

    by_error: dict[str, dict] = {}
    by_direction: dict[str, dict] = {}
    total_cf_pnl = 0.0
    cf_count = 0

    for status, direction, reason, resolved, cf_pnl, best_ask, order_price, delta in rows:
        # Normalize error.
        error_key = status
        if reason:
            if "invalid signature" in reason.lower():
                error_key = "invalid_signature"
            elif "post only" in reason.lower() or "cross" in reason.lower():
                error_key = "post_only_cross"
            elif "nonce" in reason.lower():
                error_key = "nonce_error"
            elif "timeout" in reason.lower():
                error_key = "timeout"

        if error_key not in by_error:
            by_error[error_key] = {"count": 0, "cf_pnl": 0.0, "cf_count": 0, "retryable": False}
        by_error[error_key]["count"] += 1
        by_error[error_key]["retryable"] = error_key in {"invalid_signature", "nonce_error", "post_only_cross"}

        d = direction or "UNKNOWN"
        if d not in by_direction:
            by_direction[d] = {"count": 0, "cf_pnl": 0.0, "cf_count": 0}
        by_direction[d]["count"] += 1

        if cf_pnl is not None:
            by_error[error_key]["cf_pnl"] += cf_pnl
            by_error[error_key]["cf_count"] += 1
            by_direction[d]["cf_pnl"] += cf_pnl
            by_direction[d]["cf_count"] += 1
            total_cf_pnl += cf_pnl
            cf_count += 1

    # Round values.
    for v in by_error.values():
        v["cf_pnl"] = round(v["cf_pnl"], 2)
    for v in by_direction.values():
        v["cf_pnl"] = round(v["cf_pnl"], 2)

    return {
        "total_failures": len(rows),
        "total_cf_pnl": round(total_cf_pnl, 2),
        "by_error": by_error,
        "by_direction": by_direction,
    }


def build_execution_funnel(hours: int = 72) -> dict:
    """Build the full execution funnel: eligible → attempted → accepted → filled → resolved.

    Shows where volume is lost at each stage. This is the single most important
    diagnostic for execution quality.
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    # Total windows (policy-eligible = all windows that reached _process_window).
    total = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ?", (cutoff_ts,)
    ).fetchone()[0]

    # Skipped (policy or structural).
    skipped = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status LIKE 'skip_%'",
        (cutoff_ts,),
    ).fetchone()[0]

    # Attempted (order was placed or attempted).
    attempted = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status LIKE 'live_%'",
        (cutoff_ts,),
    ).fetchone()[0]

    # Accepted (order placed, got an order_id).
    accepted = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status LIKE 'live_%' AND order_id IS NOT NULL",
        (cutoff_ts,),
    ).fetchone()[0]

    # Filled.
    filled = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND filled = 1",
        (cutoff_ts,),
    ).fetchone()[0]

    # Failed (attempted but no order_id).
    failed = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status = 'live_order_failed'",
        (cutoff_ts,),
    ).fetchone()[0]

    # Unfilled (accepted but not filled).
    unfilled = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status IN ('live_cancelled_unfilled', 'live_cancel_unknown')",
        (cutoff_ts,),
    ).fetchone()[0]

    # Resolved (filled + has outcome).
    resolved = conn.execute(
        "SELECT COUNT(*) FROM window_trades WHERE window_start_ts > ? AND filled = 1 AND resolved_outcome IS NOT NULL",
        (cutoff_ts,),
    ).fetchone()[0]

    # PnL from fills.
    pnl_row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0), COUNT(*) FROM window_trades WHERE window_start_ts > ? AND filled = 1 AND pnl_usd IS NOT NULL",
        (cutoff_ts,),
    ).fetchone()
    realized_pnl = round(float(pnl_row[0]), 4)
    pnl_count = pnl_row[1]

    # Counterfactual PnL from execution failures.
    cf_row = conn.execute(
        "SELECT COALESCE(SUM(counterfactual_pnl_usd), 0), COUNT(*) FROM window_trades WHERE window_start_ts > ? AND order_status = 'live_order_failed' AND counterfactual_pnl_usd IS NOT NULL",
        (cutoff_ts,),
    ).fetchone()
    exec_failure_cf_pnl = round(float(cf_row[0]), 4)
    exec_failure_cf_count = cf_row[1]

    # Skip breakdown by category.
    skip_rows = conn.execute("""
        SELECT order_status, COUNT(*) FROM window_trades
        WHERE window_start_ts > ? AND order_status LIKE 'skip_%'
        GROUP BY order_status ORDER BY COUNT(*) DESC
    """, (cutoff_ts,)).fetchall()
    conn.close()

    skip_breakdown = {row[0]: row[1] for row in skip_rows}

    # Compute conversion rates.
    attempt_rate = attempted / total if total > 0 else 0.0
    accept_rate = accepted / attempted if attempted > 0 else 0.0
    fill_rate = filled / accepted if accepted > 0 else 0.0
    overall_fill_rate = filled / total if total > 0 else 0.0

    return {
        "hours": hours,
        "funnel": {
            "total_windows": total,
            "skipped": skipped,
            "attempted": attempted,
            "accepted": accepted,
            "filled": filled,
            "unfilled": unfilled,
            "failed": failed,
            "resolved": resolved,
        },
        "rates": {
            "attempt_rate": round(attempt_rate, 4),
            "accept_rate": round(accept_rate, 4),
            "fill_rate_of_accepted": round(fill_rate, 4),
            "overall_fill_rate": round(overall_fill_rate, 4),
        },
        "pnl": {
            "realized_pnl": realized_pnl,
            "realized_fills": pnl_count,
            "exec_failure_cf_pnl": exec_failure_cf_pnl,
            "exec_failure_cf_count": exec_failure_cf_count,
        },
        "skip_breakdown": skip_breakdown,
    }


# ---------------------------------------------------------------------------
# Cell-level allowlist rules
# ---------------------------------------------------------------------------

ALLOWLIST_PATH = Path("/home/ubuntu/polymarket-trading-bot/config/expansion_allowlist.json")

# Safety constraints for allowlist generation.
MAX_ALLOWLIST_AVG_ENTRY = 0.85  # No rules targeting entry > 0.85 unless bootstrap proves it.
MIN_ALLOWLIST_SUPPORT = 5       # Minimum observations.
MIN_ALLOWLIST_P_POSITIVE = 0.70  # P(EV>0) threshold.
MIN_ALLOWLIST_WR_EDGE = 0.0     # Must be at or above break-even.

# These skip reasons may never be relaxed via allowlist.
NEVER_RELAX = {
    "skip_toxic_order_flow",
    "skip_shadow_only_direction",
    "skip_bad_book",
    "skip_missing_price",
    "skip_midpoint_kill_zone",  # Investigate-only until consistency audit is clean.
}


@dataclass
class AllowlistRule:
    """A precise predicate for selectively relaxing a guardrail."""
    rule_id: str
    skip_reason: str
    direction: str
    price_min: float | None = None
    price_max: float | None = None
    delta_min: float | None = None
    delta_max: float | None = None
    excluded_hours_utc: list[int] = field(default_factory=list)
    # Evidence.
    support: int = 0
    exact_cf_per_fill: float = 0.0
    bootstrap_lcb: float | None = None
    p_ev_positive: float = 0.0
    wr_edge: float = 0.0
    # Metadata.
    source_cell: str = ""
    created_at: str = ""
    # Enriched metadata (#13 shadow-only, #14 fillability).
    strategy_fingerprint: str = ""
    counterfactual_quality: str = ""
    fillability_model_version: str = FILLABILITY_MODEL_VERSION
    canary_pct: float = 0.0
    daily_notional_cap: float = 0.0
    daily_fill_cap: int = 0
    daily_drawdown_stop: float = 0.0
    status: str = "shadow_only"  # ALWAYS shadow_only until graduation criteria met.

    def matches(self, *, skip_reason: str, direction: str,
                entry_price: float | None, abs_delta: float | None,
                hour_utc: int | None) -> bool:
        """Check if a window matches this allowlist rule."""
        if skip_reason != self.skip_reason:
            return False
        if direction != self.direction:
            return False
        if entry_price is not None:
            if self.price_min is not None and entry_price < self.price_min:
                return False
            if self.price_max is not None and entry_price > self.price_max:
                return False
        if abs_delta is not None:
            if self.delta_min is not None and abs_delta < self.delta_min:
                return False
            if self.delta_max is not None and abs_delta > self.delta_max:
                return False
        if hour_utc is not None and hour_utc in self.excluded_hours_utc:
            return False
        return True


def generate_allowlist_rules(frontier: list[dict]) -> list[AllowlistRule]:
    """Generate precise allowlist rules from positive-EV frontier cells.

    Only generates rules for cells that pass all safety constraints.
    Never generates rules for toxic_flow, shadow_only, or structural blockers.
    """
    rules: list[AllowlistRule] = []
    now = datetime.now(timezone.utc).isoformat()

    for cell in frontier:
        skip_reason = cell["skip_reason"]

        # Hard block: never relax these.
        if skip_reason in NEVER_RELAX:
            continue

        # QUALITY GATE: only exact-price cells are actionable for allowlist.
        if not cell.get("actionable", False):
            continue

        # Must have enough support.
        if cell["n"] < MIN_ALLOWLIST_SUPPORT:
            continue

        # Must have positive EV evidence.
        p_pos = cell.get("p_ev_positive", 0)
        if p_pos < MIN_ALLOWLIST_P_POSITIVE:
            continue

        # Must be at or above break-even.
        wr_edge = cell.get("wr_edge", 0)
        if wr_edge < MIN_ALLOWLIST_WR_EDGE:
            continue

        # Must have positive EV after fillability adjustment (conservative).
        cf_per_fill = cell.get("fillability_adjusted_per_fill") or cell.get("counterfactual_pnl_usd_std5_per_fill")
        if cf_per_fill is None or cf_per_fill <= 0:
            continue

        # Must not have consistency flag.
        if cell.get("consistency_flag"):
            continue

        avg_entry = cell.get("avg_entry_price", 0.50)

        # Safety: high-price entries need bootstrap LCB proof.
        if avg_entry > MAX_ALLOWLIST_AVG_ENTRY:
            lcb = cell.get("bootstrap_lcb_per_fill")
            if lcb is None or lcb <= 0:
                continue

        # Build the rule predicate from the cell dimensions.
        direction = cell["direction"]
        price_bucket = cell.get("price_bucket", "unknown")
        delta_bucket = cell.get("delta_bucket", "")

        # Convert price bucket to range.
        price_min, price_max = None, None
        try:
            pb = float(price_bucket)
            price_min = round(pb - 0.05, 2)
            price_max = round(pb + 0.05, 2)
        except (ValueError, TypeError):
            pass  # Unknown price — skip price constraint.

        # Convert delta bucket to range.
        delta_min, delta_max = _delta_bucket_to_range(delta_bucket)

        rule_id = f"allow_{skip_reason}_{direction}_{price_bucket}_{delta_bucket}".replace(
            " ", "_"
        ).replace("%", "pct")

        rules.append(AllowlistRule(
            rule_id=rule_id,
            skip_reason=skip_reason,
            direction=direction,
            price_min=price_min,
            price_max=price_max,
            delta_min=delta_min,
            delta_max=delta_max,
            support=cell["n"],
            exact_cf_per_fill=cf_per_fill,
            bootstrap_lcb=cell.get("bootstrap_lcb_per_fill"),
            p_ev_positive=p_pos,
            wr_edge=wr_edge,
            source_cell=f"{skip_reason}/{direction}/{price_bucket}/{delta_bucket}",
            created_at=now,
            strategy_fingerprint=cell.get("strategy_fingerprint", ""),
            counterfactual_quality=cell.get("counterfactual_quality", ""),
            fillability_model_version=FILLABILITY_MODEL_VERSION,
            status="shadow_only",  # NEVER auto-graduate (#13).
        ))

    logger.info("Generated %d allowlist rules from %d frontier cells", len(rules), len(frontier))
    return rules


def _delta_bucket_to_range(bucket: str) -> tuple[float | None, float | None]:
    """Convert a delta bucket label to (min, max) range."""
    if bucket == "<0.03%":
        return (0.0, 0.0003)
    elif bucket == "0.03-0.05%":
        return (0.0003, 0.0005)
    elif bucket == "0.05-0.10%":
        return (0.0005, 0.001)
    elif bucket == "0.10-0.20%":
        return (0.001, 0.002)
    elif bucket == ">0.20%":
        return (0.002, None)
    return (None, None)


def persist_allowlist_rules(rules: list[AllowlistRule]) -> None:
    """Write allowlist rules to JSON file for the bot to read."""
    data = [asdict(r) for r in rules]
    ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALLOWLIST_PATH.write_text(json.dumps(data, indent=2))
    logger.info("Wrote %d allowlist rules to %s", len(rules), ALLOWLIST_PATH)


# ---------------------------------------------------------------------------
# EV consistency audit artifact (#11)
# ---------------------------------------------------------------------------

EV_AUDIT_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/ev_consistency_audit.json")


def build_ev_consistency_audit(frontier: list[dict]) -> dict:
    """Build EV consistency audit for exact-price cells.

    Flags cells where wr_edge < 0 but counterfactual_pnl_usd_std5_per_fill > 0.
    Includes sample window timestamps for traceability.
    """
    exact_cells = [c for c in frontier if c.get("counterfactual_quality") == CQ_EXACT]

    flagged = []
    clean = []
    for c in exact_cells:
        we = c.get("wr_edge")
        cf = c.get("counterfactual_pnl_usd_std5_per_fill")

        entry = {
            "skip_reason": c["skip_reason"],
            "direction": c["direction"],
            "price_bucket": c["price_bucket"],
            "delta_bucket": c.get("delta_bucket"),
            "hour_bucket": c.get("hour_bucket"),
            "n": c["n"],
            "avg_entry_price": c.get("avg_entry_price"),
            "actual_wr": c.get("actual_wr"),
            "break_even_wr": c.get("break_even_wr"),
            "wr_edge": we,
            "counterfactual_pnl_usd_std5_per_fill": cf,
            "fillability_adjusted_per_fill": c.get("fillability_adjusted_per_fill"),
            "fee_assumption": "0 bps (maker rebate assumed)",
            "sample_window_start_ts": c.get("sample_window_start_ts", []),
        }

        if we is not None and cf is not None and we < 0 and cf > 0:
            entry["flag"] = "wr_edge_negative_but_cf_positive"
            entry["explanation"] = (
                f"Win rate ({c.get('actual_wr', 0):.0%}) is below break-even "
                f"({c.get('break_even_wr', 0):.0%}) at entry price "
                f"${c.get('avg_entry_price', 0):.2f}, but standardized $5 "
                f"counterfactual shows +${cf:.4f}/fill. This happens when "
                f"wins at high prices yield small gains but losses cost more. "
                f"The counterfactual ignores break-even dynamics."
            )
            flagged.append(entry)
        else:
            clean.append(entry)

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_exact_cells": len(exact_cells),
        "flagged_cells": len(flagged),
        "clean_cells": len(clean),
        "status": "INVESTIGATE" if flagged else "CLEAN",
        "flagged": flagged,
        "clean_sample": clean[:10],
    }

    EV_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EV_AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    logger.info("EV consistency audit: %d exact cells, %d flagged → %s",
                len(exact_cells), len(flagged), EV_AUDIT_PATH)
    return audit


# ---------------------------------------------------------------------------
# h_dir_down diagnosis artifact (#16)
# ---------------------------------------------------------------------------

H_DIR_DOWN_DIAG_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/h_dir_down_diagnosis.json")


def build_h_dir_down_diagnosis(hours: int = 48) -> dict:
    """Diagnose h_dir_down negative shadow PnL.

    Analyzes DOWN windows across quality tiers to determine whether the
    negative shadow is a measurement artifact or real thin-edge warning.
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT direction, order_price, best_ask, resolved_outcome,
               counterfactual_pnl_usd, pnl_usd, filled, order_status,
               strategy_fingerprint
        FROM window_trades
        WHERE direction = 'DOWN'
          AND window_start_ts > ?
          AND resolved_outcome IS NOT NULL
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return {"status": "no_data", "n": 0}

    # Separate live vs replay.
    live_fills = []
    skip_exact = []
    skip_missing_price = []

    for (d, opx, bask, resolved, cf_pnl, pnl, filled, status, fp) in rows:
        entry_px = bask or opx or 0
        has_price = entry_px > 0

        if filled == 1:
            live_fills.append({
                "entry_price": entry_px,
                "pnl_usd": pnl,
                "won": 1 if d == resolved else 0,
            })
        elif status and status.startswith("skip_"):
            if has_price and cf_pnl is not None:
                skip_exact.append({
                    "entry_price": entry_px,
                    "cf_pnl": cf_pnl,
                    "won": 1 if d == resolved else 0,
                })
            elif not has_price:
                skip_missing_price.append({
                    "won": 1 if d == resolved else 0,
                })

    def _summarize(items, pnl_key="pnl_usd"):
        if not items:
            return {"n": 0}
        n = len(items)
        wins = sum(1 for i in items if i.get("won"))
        pnl_values = [i.get(pnl_key, 0) or 0 for i in items]
        prices = [i["entry_price"] for i in items if i.get("entry_price", 0) > 0]
        avg_price = sum(prices) / len(prices) if prices else None
        return {
            "n": n,
            "wins": wins,
            "win_rate": round(wins / n, 3) if n else 0,
            "total_pnl": round(sum(pnl_values), 4),
            "pnl_per_fill": round(sum(pnl_values) / n, 4) if n else 0,
            "avg_entry_price": round(avg_price, 4) if avg_price else None,
            "break_even_wr": round(break_even_win_rate(avg_price), 3) if avg_price and avg_price > 0 else None,
        }

    live_summary = _summarize(live_fills, "pnl_usd")
    exact_summary = _summarize(skip_exact, "cf_pnl")
    missing_summary = {
        "n": len(skip_missing_price),
        "wins": sum(1 for i in skip_missing_price if i.get("won")),
        "win_rate": round(sum(1 for i in skip_missing_price if i.get("won")) / len(skip_missing_price), 3) if skip_missing_price else 0,
    }

    # Key diagnostic: does the negative shadow survive exact-only cut?
    exact_only_negative = exact_summary.get("total_pnl", 0) < 0
    mixed_negative = (exact_summary.get("total_pnl", 0) + live_summary.get("total_pnl", 0)) < 0

    diagnosis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_down_windows": len(rows),
        "live_actual": live_summary,
        "exact_price_counterfactual": exact_summary,
        "missing_price_counterfactual": missing_summary,
        "diagnostics": {
            "exact_only_negative_shadow": exact_only_negative,
            "mixed_quality_negative_shadow": mixed_negative,
            "live_fills_positive": live_summary.get("total_pnl", 0) > 0,
            "explanation": (
                "If live fills are positive but exact counterfactual is negative, "
                "the system is correctly filtering for high-quality fills. "
                "If exact-only is also negative, the thin-edge warning is real: "
                "high entry prices require very high win rates to break even."
            ),
        },
        "recommendation": (
            "REAL_WARNING" if exact_only_negative
            else "MEASUREMENT_ARTIFACT" if not mixed_negative
            else "INCONCLUSIVE"
        ),
    }

    H_DIR_DOWN_DIAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    H_DIR_DOWN_DIAG_PATH.write_text(json.dumps(diagnosis, indent=2))
    logger.info("h_dir_down diagnosis: %s → %s", diagnosis["recommendation"], H_DIR_DOWN_DIAG_PATH)
    return diagnosis


def _analyze_up_salvage_cells(hours: int = 48) -> dict:
    """Analyze UP windows blocked by directional_mode or shadow_only.

    Identifies potential UP salvage cells. Since these windows often lack
    price data (directional check fires before book fetch), we flag them
    as unmeasurable until the bot captures book data for directional skips.
    """
    conn = _db_connect()
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute("""
        SELECT order_status, best_ask, order_price, delta,
               resolved_outcome, counterfactual_pnl_usd
        FROM window_trades
        WHERE order_status IN ('skip_directional_mode', 'skip_shadow_only_direction')
          AND direction = 'UP'
          AND resolved_outcome IS NOT NULL
          AND window_start_ts > ?
    """, (cutoff_ts,)).fetchall()
    conn.close()

    if not rows:
        return {"total_cells": 0, "measurable_cells": 0, "positive_ev_cells": 0}

    # Group by delta bucket (since we don't have price data for most).
    cells: dict[str, dict] = {}
    for status, best_ask, order_price, delta, resolved, cf_pnl in rows:
        delta_bucket = _delta_bucket_label(abs(delta or 0))
        has_price = (best_ask and best_ask > 0) or (order_price and order_price > 0)
        key = f"{status}/{delta_bucket}"

        if key not in cells:
            cells[key] = {
                "skip_reason": status,
                "delta_bucket": delta_bucket,
                "n": 0, "wins": 0, "with_price": 0,
                "cf_values": [],
            }
        c = cells[key]
        c["n"] += 1
        if resolved == "UP":
            c["wins"] += 1
        if has_price:
            c["with_price"] += 1
        if cf_pnl is not None:
            c["cf_values"].append(cf_pnl)

    results = []
    for key, c in cells.items():
        n = c["n"]
        wr = c["wins"] / n if n > 0 else 0
        measurable = len(c["cf_values"]) > 0
        cf_total = sum(c["cf_values"]) if c["cf_values"] else None

        results.append({
            "cell": key,
            "n": n,
            "wins": c["wins"],
            "win_rate": round(wr, 3),
            "with_price_data": c["with_price"],
            "measurable": measurable,
            "cf_total_pnl": round(cf_total, 2) if cf_total is not None else None,
            "recommendation": (
                "NEEDS_PRICE_DATA" if not measurable
                else ("CANDIDATE" if cf_total and cf_total > 0 else "NEGATIVE_EV")
            ),
        })

    measurable_count = sum(1 for r in results if r["measurable"])
    positive_count = sum(1 for r in results if r.get("cf_total_pnl") and r["cf_total_pnl"] > 0)

    return {
        "total_cells": len(results),
        "measurable_cells": measurable_count,
        "positive_ev_cells": positive_count,
        "cells": results,
        "note": ("Most UP salvage cells lack price data because directional_mode check "
                 "fires before book fetch. To enable UP salvage, the bot should log "
                 "book data even for directional skips."),
    }


def load_allowlist_rules() -> list[AllowlistRule]:
    """Load allowlist rules from JSON file."""
    if not ALLOWLIST_PATH.exists():
        return []
    try:
        data = json.loads(ALLOWLIST_PATH.read_text())
        rules = []
        for d in data:
            rules.append(AllowlistRule(
                rule_id=d.get("rule_id", ""),
                skip_reason=d.get("skip_reason", ""),
                direction=d.get("direction", ""),
                price_min=d.get("price_min"),
                price_max=d.get("price_max"),
                delta_min=d.get("delta_min"),
                delta_max=d.get("delta_max"),
                excluded_hours_utc=d.get("excluded_hours_utc", []),
                support=d.get("support", 0),
                exact_cf_per_fill=d.get("exact_cf_per_fill", 0),
                bootstrap_lcb=d.get("bootstrap_lcb"),
                p_ev_positive=d.get("p_ev_positive", 0),
                wr_edge=d.get("wr_edge", 0),
                source_cell=d.get("source_cell", ""),
                created_at=d.get("created_at", ""),
            ))
        return rules
    except (json.JSONDecodeError, OSError):
        return []


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_cycle()
