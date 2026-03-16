"""
Autoresearch closed loop for BTC5 maker.

Cycle (runs every 6 hours via cron):
1. OBSERVE: Pull last 24h of fills, segment by price/direction/hour
2. HYPOTHESIZE: Generate parameter variations that might improve PnL
3. SHADOW TEST: Run each hypothesis against historical data
4. RANK: Mark as shadow (promote candidate), killed, or inconclusive
5. Write results for auto_promote.py to act on

Mutable surface (what changes): price floor, direction bias, time filter
Immutable surface (what never changes): daily loss limit, max position, kill rules

Part of the recursive self-improvement loop (DISPATCH 108).

March 14, 2026 — Elastifund Autoresearch
"""
import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot.pricing_evolution import evolve_and_maybe_promote

logger = logging.getLogger("AutoresearchLoop")

BOT_DIR = Path(os.environ.get("POLYMARKET_BOT_DIR", "/home/ubuntu/polymarket-trading-bot"))
DB_PATH = Path(os.environ.get("BTC5_DB_PATH", str(BOT_DIR / "data" / "btc_5min_maker.db")))
RESULTS_PATH = Path(
    os.environ.get("BTC5_AUTORESEARCH_RESULTS_PATH", str(BOT_DIR / "data" / "autoresearch_results.json"))
)
KELLY_RECOMMENDATION_PATH = Path(
    os.environ.get(
        "BTC5_AUTORESEARCH_KELLY_PATH",
        str(BOT_DIR / "data" / "autoresearch_kelly_recommendation.json"),
    )
)
AUTORESEARCH_OVERRIDES_PATH = Path(
    os.environ.get("BTC5_AUTORESEARCH_OVERRIDES_PATH", str(BOT_DIR / "config" / "autoresearch_overrides.json"))
)
PRICE_FLOOR_SWEEP = (0.85, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92)
PRICE_CAP_SWEEP = (0.93, 0.94, 0.95)


@dataclass
class Hypothesis:
    hypothesis_id: str
    description: str
    params: dict = field(default_factory=dict)
    predicted_improvement: float = 0.0
    status: str = "generated"
    shadow_pnl: float = 0.0
    live_pnl_at_generation: float = 0.0
    created_at: str = ""
    resolved_at: str = ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _generate_price_floor_hypotheses(*, now: str, observation: dict[str, Any]) -> list[Hypothesis]:
    """Generate MIN_BUY / MAX_BUY sweeps for replay validation."""
    hypotheses: list[Hypothesis] = []
    total_pnl = float(observation.get("total_pnl") or 0.0)
    for min_buy in PRICE_FLOOR_SWEEP:
        for cap in PRICE_CAP_SWEEP:
            if min_buy > cap:
                continue
            suffix = f"{min_buy:.2f}_{cap:.2f}".replace(".", "")
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=f"h_price_{suffix}_{now[:10]}",
                    description=f"Set MIN_BUY={min_buy:.2f}, MAX_BUY={cap:.2f}",
                    params={
                        "BTC5_MIN_BUY_PRICE": round(min_buy, 2),
                        "BTC5_DOWN_MAX_BUY_PRICE": round(cap, 2),
                        "BTC5_UP_MAX_BUY_PRICE": round(cap, 2),
                    },
                    predicted_improvement=max(0.0, total_pnl),
                    live_pnl_at_generation=total_pnl,
                    created_at=now,
                )
            )
    return hypotheses


def observe_recent_performance(hours: int = 24) -> dict:
    """Pull fills from last N hours and compute performance by segment."""
    conn = sqlite3.connect(str(DB_PATH))
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
        return {"total_fills": 0, "total_pnl": 0.0, "win_rate": 0.0, "segments": {}}

    total_pnl = sum(f[2] or 0 for f in fills)
    total_wins = sum(1 for f in fills if f[3])

    # Segment by price bucket
    price_buckets: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        bucket = f"{int((price or 0) * 10) / 10:.1f}"
        if bucket not in price_buckets:
            price_buckets[bucket] = {"fills": 0, "wins": 0, "pnl": 0.0}
        price_buckets[bucket]["fills"] += 1
        price_buckets[bucket]["wins"] += 1 if won else 0
        price_buckets[bucket]["pnl"] += pnl or 0

    # Segment by direction
    dir_stats: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        if d not in dir_stats:
            dir_stats[d] = {"fills": 0, "wins": 0, "pnl": 0.0}
        dir_stats[d]["fills"] += 1
        dir_stats[d]["wins"] += 1 if won else 0
        dir_stats[d]["pnl"] += pnl or 0

    # Segment by hour
    hour_stats: dict[str, dict] = {}
    for d, price, pnl, won, ts, tier, delta in fills:
        try:
            hour = datetime.fromisoformat(ts).hour
            h_key = f"{hour:02d}"
        except (ValueError, TypeError):
            h_key = "unknown"
        if h_key not in hour_stats:
            hour_stats[h_key] = {"fills": 0, "wins": 0, "pnl": 0.0}
        hour_stats[h_key]["fills"] += 1
        hour_stats[h_key]["wins"] += 1 if won else 0
        hour_stats[h_key]["pnl"] += pnl or 0

    return {
        "total_fills": len(fills),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(total_wins / len(fills), 3) if fills else 0.0,
        "segments": {
            "by_price_bucket": price_buckets,
            "by_direction": dir_stats,
            "by_hour": hour_stats,
        },
    }


def generate_hypotheses(observation: dict) -> list[Hypothesis]:
    """Generate parameter variation hypotheses from performance data."""
    hypotheses = []
    now = datetime.now(timezone.utc).isoformat()
    segments = observation.get("segments", {})
    hypotheses.extend(_generate_price_floor_hypotheses(now=now, observation=observation))

    # Hypothesis: find best price floor from data
    price_data = segments.get("by_price_bucket", {})
    profitable_buckets = {k: v for k, v in price_data.items() if v["pnl"] > 0}
    if profitable_buckets:
        best_bucket = max(profitable_buckets, key=lambda k: profitable_buckets[k]["pnl"])
        hypotheses.append(Hypothesis(
            hypothesis_id=f"h_floor_{best_bucket}_{now[:10]}",
            description=f"Set min buy price to {best_bucket} (best performing bucket)",
            params={"BTC5_MIN_BUY_PRICE": float(best_bucket)},
            predicted_improvement=profitable_buckets[best_bucket]["pnl"],
            live_pnl_at_generation=observation["total_pnl"],
            created_at=now,
        ))

    # Hypothesis: direction bias
    dir_data = segments.get("by_direction", {})
    for direction, stats in dir_data.items():
        if stats["fills"] >= 3 and stats["pnl"] > 0:
            other_pnl = sum(s["pnl"] for d, s in dir_data.items() if d != direction)
            if stats["pnl"] > other_pnl + 1.0:
                hypotheses.append(Hypothesis(
                    hypothesis_id=f"h_dir_{direction.lower()}_{now[:10]}",
                    description=(
                        f"{direction}-only mode "
                        f"({direction} PnL: ${stats['pnl']:.2f} vs rest: ${other_pnl:.2f})"
                    ),
                    params={"BTC5_DIRECTIONAL_MODE": f"{direction.lower()}_only"},
                    predicted_improvement=stats["pnl"] - other_pnl,
                    live_pnl_at_generation=observation["total_pnl"],
                    created_at=now,
                ))

    # Hypothesis: suppress losing hours
    hour_data = segments.get("by_hour", {})
    losing_hours = [h for h, s in hour_data.items() if s["pnl"] < -1.0 and s["fills"] >= 2]
    if losing_hours:
        saved = sum(abs(hour_data[h]["pnl"]) for h in losing_hours)
        hypotheses.append(Hypothesis(
            hypothesis_id=f"h_suppress_hours_{now[:10]}",
            description=f"Suppress trading during losing hours: {', '.join(losing_hours)} UTC",
            params={"BTC5_SUPPRESS_HOURS_UTC": ",".join(losing_hours)},
            predicted_improvement=saved,
            live_pnl_at_generation=observation["total_pnl"],
            created_at=now,
        ))

    return hypotheses


def backtest_hypothesis(hypothesis: Hypothesis, lookback_hours: int = 48) -> float:
    """Simulate what PnL would have been with the hypothesis params applied."""
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    fills = conn.execute("""
        SELECT direction, order_price, pnl_usd, won, created_at
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
    """, (cutoff,)).fetchall()
    conn.close()

    shadow_pnl = 0.0
    for direction, price, pnl, won, ts in fills:
        params = hypothesis.params
        side = str(direction or "").strip().upper()

        if "BTC5_MIN_BUY_PRICE" in params:
            if (price or 0) < params["BTC5_MIN_BUY_PRICE"]:
                continue
        max_buy_price = None
        if "BTC5_MAX_BUY_PRICE" in params:
            max_buy_price = float(params["BTC5_MAX_BUY_PRICE"])
        elif side == "UP" and "BTC5_UP_MAX_BUY_PRICE" in params:
            max_buy_price = float(params["BTC5_UP_MAX_BUY_PRICE"])
        elif side == "DOWN" and "BTC5_DOWN_MAX_BUY_PRICE" in params:
            max_buy_price = float(params["BTC5_DOWN_MAX_BUY_PRICE"])
        if max_buy_price is not None and (price or 0) > max_buy_price:
            continue

        if "BTC5_DIRECTIONAL_MODE" in params:
            mode = params["BTC5_DIRECTIONAL_MODE"]
            if mode == "up_only" and direction != "UP":
                continue
            if mode == "down_only" and direction != "DOWN":
                continue

        if "BTC5_SUPPRESS_HOURS_UTC" in params:
            try:
                trade_hour = f"{datetime.fromisoformat(ts).hour:02d}"
                suppressed = params["BTC5_SUPPRESS_HOURS_UTC"].split(",")
                if trade_hour in suppressed:
                    continue
            except (ValueError, TypeError):
                pass

        shadow_pnl += pnl or 0

    return round(shadow_pnl, 2)


def _compute_kelly_fraction(*, win_rate: float, avg_entry: float) -> tuple[float, float]:
    """Return (full_kelly, quarter_kelly), both clamped to >= 0."""
    if not (0.0 < avg_entry < 1.0):
        return 0.0, 0.0
    p = max(0.0, min(1.0, float(win_rate)))
    q = 1.0 - p
    b = (1.0 - avg_entry) / avg_entry
    if b <= 0:
        return 0.0, 0.0
    full_kelly = max(0.0, ((p * b) - q) / b)
    quarter_kelly = max(0.0, full_kelly / 4.0)
    return round(full_kelly, 6), round(quarter_kelly, 6)


def build_kelly_recommendation(*, min_entry: float = 0.90, limit: int = 200) -> dict[str, Any]:
    """Build Kelly sizing recommendation from recent resolved live fills."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT won, order_price, pnl_usd, created_at
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND won IS NOT NULL
          AND order_price >= ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (float(min_entry), max(1, int(limit))),
    ).fetchall()
    conn.close()
    n = len(rows)
    wins = sum(1 for won, _, _, _ in rows if int(won) == 1)
    wr = (wins / n) if n else 0.0
    avg_entry = (sum(float(price or 0.0) for _, price, _, _ in rows) / n) if n else 0.0
    total_pnl = sum(float(pnl or 0.0) for _, _, pnl, _ in rows)
    full_kelly, quarter_kelly = _compute_kelly_fraction(win_rate=wr, avg_entry=avg_entry)
    capped_fraction = min(0.15, quarter_kelly)
    bankroll = float(os.environ.get("BTC5_BANKROLL_USD", "390"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "qualifying_min_entry": round(float(min_entry), 4),
        "lookback_limit": int(limit),
        "n_qualifying_fills": n,
        "win_rate": round(wr, 4),
        "avg_entry_price": round(avg_entry, 4),
        "total_pnl_usd": round(total_pnl, 4),
        "full_kelly_fraction": full_kelly,
        "recommended_kelly_fraction": round(capped_fraction, 6),
        "recommended_trade_size_usd": round(max(0.0, bankroll * capped_fraction), 2),
        "bankroll_usd": bankroll,
    }


def run_cycle() -> dict | None:
    """Full autoresearch cycle: observe -> hypothesize -> backtest -> rank."""
    logger.info("=== Autoresearch cycle start ===")
    kelly_recommendation = build_kelly_recommendation()
    _write_json(KELLY_RECOMMENDATION_PATH, kelly_recommendation)
    logger.info(
        "Kelly recommendation: n=%s wr=%.2f%% fraction=%.4f size=$%.2f",
        kelly_recommendation.get("n_qualifying_fills", 0),
        float(kelly_recommendation.get("win_rate", 0.0)) * 100.0,
        float(kelly_recommendation.get("recommended_kelly_fraction", 0.0)),
        float(kelly_recommendation.get("recommended_trade_size_usd", 0.0)),
    )

    obs = observe_recent_performance(hours=24)
    logger.info(
        f"Observed: {obs['total_fills']} fills, ${obs['total_pnl']} PnL, "
        f"{obs['win_rate']*100:.1f}% win rate"
    )
    if obs["total_fills"] < 5:
        pricing_evolution_result: dict[str, Any] = {"status": "not_run"}
        try:
            pricing_evolution_result = evolve_and_maybe_promote(
                db_path=DB_PATH,
                overrides_path=AUTORESEARCH_OVERRIDES_PATH,
                lookback_hours=24,
            )
            logger.info(
                "Pricing evolution status=%s generation=%s",
                pricing_evolution_result.get("status"),
                pricing_evolution_result.get("generation"),
            )
        except Exception:
            logger.exception("Pricing evolution failed at cycle end (low-fill path)")
        logger.info("Not enough fills for hypothesis generation. Waiting.")
        return None

    hypotheses = generate_hypotheses(obs)
    logger.info(f"Generated {len(hypotheses)} hypotheses")

    results = []
    for h in hypotheses:
        h.shadow_pnl = backtest_hypothesis(h)
        improvement = h.shadow_pnl - obs["total_pnl"]

        if h.shadow_pnl > 0 and improvement > 0.50:
            h.status = "shadow"
            logger.info(
                f"  PROMOTE to shadow: {h.hypothesis_id} "
                f"(shadow PnL: ${h.shadow_pnl}, improvement: ${improvement:.2f})"
            )
        elif h.shadow_pnl < -2.0:
            h.status = "killed"
            logger.info(f"  KILL: {h.hypothesis_id} (shadow PnL: ${h.shadow_pnl})")
        else:
            h.status = "inconclusive"
            logger.info(f"  INCONCLUSIVE: {h.hypothesis_id} (shadow PnL: ${h.shadow_pnl})")

        results.append(asdict(h))

    pricing_evolution_result = {"status": "not_run"}
    try:
        pricing_evolution_result = evolve_and_maybe_promote(
            db_path=DB_PATH,
            overrides_path=AUTORESEARCH_OVERRIDES_PATH,
            lookback_hours=24,
        )
        logger.info(
            "Pricing evolution status=%s generation=%s",
            pricing_evolution_result.get("status"),
            pricing_evolution_result.get("generation"),
        )
    except Exception:
        logger.exception("Pricing evolution failed at cycle end")
        pricing_evolution_result = {"status": "error", "reason": "exception_during_pricing_evolution"}

    output = {
        "cycle_time": datetime.now(timezone.utc).isoformat(),
        "observation": obs,
        "hypotheses": results,
        "kelly_recommendation": kelly_recommendation,
        "pricing_evolution": pricing_evolution_result,
    }
    _write_json(RESULTS_PATH, output)
    logger.info(f"Results written to {RESULTS_PATH}")
    logger.info("=== Autoresearch cycle complete ===")
    return output


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_cycle()
