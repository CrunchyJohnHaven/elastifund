#!/usr/bin/env python3
"""
P2.3 — render_btc5_truth_bundle.py

Produces reports/btc5_truth_bundle_latest.json — the single source of truth
for BTC5 performance.

After writing the bundle, also invokes render_btc5_health_snapshot.py.

Usage:
  python scripts/render_btc5_truth_bundle.py
"""

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DB_CANDIDATES = [
    REPO_ROOT / "data" / "btc_5min_maker.db",
    REPO_ROOT / "bot" / "data" / "btc_5min_maker.db",
]

EFFECTIVE_ENV = REPO_ROOT / "state" / "btc5_effective.env"
FALLBACK_ENV = REPO_ROOT / "config" / "btc5_strategy.env"
MUTATION_FILE = REPO_ROOT / "state" / "btc5_active_mutation.json"
RUNTIME_CONTRACT = REPO_ROOT / "reports" / "btc5_runtime_contract.json"
OUTPUT = REPO_ROOT / "reports" / "btc5_truth_bundle_latest.json"

# Price bucket boundaries (DOWN direction; price = buy price on DOWN)
PRICE_BUCKETS = [
    ("<=0.44", None, 0.44),
    ("0.44-0.46", 0.44, 0.46),
    ("0.46-0.48", 0.46, 0.48),
    ("0.48-0.50", 0.48, 0.50),
    (">0.50", 0.50, None),
]

# ET offset from UTC (UTC-5 in standard, UTC-4 in daylight; use UTC-5 as approximation)
ET_OFFSET_HOURS = -5

ONE_WEEK_S = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_db() -> Path | None:
    for candidate in DB_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def parse_env_file(path: Path) -> dict:
    result = {}
    if not path.exists():
        return result
    try:
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if "#" in value and not (value.startswith('"') or value.startswith("'")):
                value = value.split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    except Exception as exc:
        print(f"WARNING: could not parse {path}: {exc}", file=sys.stderr)
    return result


def config_hash_from_params(params: dict) -> str:
    payload = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_effective_params() -> dict:
    env_path = EFFECTIVE_ENV if EFFECTIVE_ENV.exists() else FALLBACK_ENV
    raw = parse_env_file(env_path)
    return {k: v for k, v in raw.items() if k.startswith("BTC5_")}


def load_mutation_id() -> str | None:
    if not MUTATION_FILE.exists():
        return None
    try:
        data = json.loads(MUTATION_FILE.read_text())
        return data.get("mutation_id") or data.get("id") or None
    except Exception:
        return None


def load_contract_hash() -> str | None:
    if not RUNTIME_CONTRACT.exists():
        return None
    try:
        data = json.loads(RUNTIME_CONTRACT.read_text())
        return data.get("config_hash")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def query_all(db_path: Path, now_ts: int) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # db_summary
    # -----------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) as n FROM window_trades")
    total_windows = cur.fetchone()["n"]

    # "fills" = rows that reached an execution attempt (not pure skips)
    skip_prefix_like_statuses = (
        "skip_%",
        "pending_%",
        "cap_breach_%",
    )
    # Count non-skip rows as fills
    cur.execute(
        """
        SELECT COUNT(*) as n FROM window_trades
        WHERE order_status NOT LIKE 'skip_%'
          AND order_status NOT LIKE 'pending_%'
          AND order_status NOT LIKE 'cap_breach_%'
        """
    )
    total_fills = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE wallet_copy = 1 OR order_status = 'paper_filled'"
    )
    total_paper_fills = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE order_status = 'live_filled'"
    )
    total_live_fills = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE resolved_side IS NOT NULL"
    )
    resolved_fills = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE won = 1"
    )
    wins = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE won = 0 AND resolved_side IS NOT NULL"
    )
    losses = cur.fetchone()["n"]

    win_rate = round(wins / resolved_fills, 4) if resolved_fills > 0 else 0.0

    cur.execute(
        "SELECT COALESCE(SUM(trade_size_usd), 0) as s FROM window_trades WHERE trade_size_usd IS NOT NULL"
    )
    total_trade_size_usd = round(cur.fetchone()["s"], 4)

    cur.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) as s FROM window_trades WHERE pnl_usd IS NOT NULL"
    )
    total_pnl_usd = round(cur.fetchone()["s"], 4)

    db_summary = {
        "total_windows": total_windows,
        "total_fills": total_fills,
        "total_paper_fills": total_paper_fills,
        "total_live_fills": total_live_fills,
        "resolved_fills": resolved_fills,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_trade_size_usd": total_trade_size_usd,
        "total_pnl_usd_if_resolved": total_pnl_usd,
    }

    # -----------------------------------------------------------------------
    # last_50_resolved
    # -----------------------------------------------------------------------
    cur.execute(
        """
        SELECT won, trade_size_usd
        FROM window_trades
        WHERE resolved_side IS NOT NULL
        ORDER BY decision_ts DESC
        LIMIT 50
        """
    )
    rows_50 = cur.fetchall()
    w50_wins = sum(1 for r in rows_50 if r["won"] == 1)
    w50_losses = sum(1 for r in rows_50 if r["won"] == 0)
    w50_total = w50_wins + w50_losses
    w50_wr = round(w50_wins / w50_total, 4) if w50_total > 0 else 0.0
    sizes = [r["trade_size_usd"] for r in rows_50 if r["trade_size_usd"] is not None]
    avg_size = round(sum(sizes) / len(sizes), 4) if sizes else 0.0

    last_50_resolved = {
        "win_rate": w50_wr,
        "wins": w50_wins,
        "losses": w50_losses,
        "avg_trade_size_usd": avg_size,
    }

    # -----------------------------------------------------------------------
    # direction_slice
    # -----------------------------------------------------------------------
    direction_slice = {}
    for direction in ("UP", "DOWN"):
        cur.execute(
            """
            SELECT COUNT(*) as fills,
                   SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) as wins,
                   COALESCE(SUM(trade_size_usd), 0) as total_usd
            FROM window_trades
            WHERE direction = ? AND resolved_side IS NOT NULL
            """,
            (direction,),
        )
        r = cur.fetchone()
        fills = r["fills"] or 0
        dir_wins = r["wins"] or 0
        total_usd = round(r["total_usd"] or 0.0, 4)
        direction_slice[direction] = {
            "fills": fills,
            "wins": dir_wins,
            "win_rate": round(dir_wins / fills, 4) if fills > 0 else 0.0,
            "total_usd": total_usd,
        }

    # -----------------------------------------------------------------------
    # hour_slice_et  (0-23)
    # -----------------------------------------------------------------------
    # decision_ts is Unix epoch in seconds; convert to ET by subtracting ET offset
    cur.execute(
        """
        SELECT
          CAST((decision_ts + ?) / 3600 % 24 AS INTEGER) as hour_et,
          COUNT(*) as fills,
          SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) as wins,
          COALESCE(SUM(trade_size_usd), 0) as total_usd
        FROM window_trades
        WHERE resolved_side IS NOT NULL
        GROUP BY hour_et
        ORDER BY hour_et
        """,
        (ET_OFFSET_HOURS * 3600,),
    )
    hour_rows = cur.fetchall()
    # Build a full 24-hour list with 0s for missing hours
    hour_map = {r["hour_et"]: r for r in hour_rows}
    hour_slice_et = []
    for h in range(24):
        r = hour_map.get(h)
        if r:
            fills_h = r["fills"] or 0
            wins_h = r["wins"] or 0
            hour_slice_et.append({
                "hour_et": h,
                "fills": fills_h,
                "wins": wins_h,
                "win_rate": round(wins_h / fills_h, 4) if fills_h > 0 else 0.0,
                "total_usd": round(r["total_usd"] or 0.0, 4),
            })
        else:
            hour_slice_et.append({"hour_et": h, "fills": 0, "wins": 0, "win_rate": 0.0, "total_usd": 0.0})

    # -----------------------------------------------------------------------
    # price_bucket_slice
    # -----------------------------------------------------------------------
    price_bucket_slice = []
    for label, lo, hi in PRICE_BUCKETS:
        conditions = ["resolved_side IS NOT NULL", "order_price IS NOT NULL"]
        params: list = []
        if lo is not None:
            conditions.append("order_price > ?")
            params.append(lo)
        if hi is not None:
            conditions.append("order_price <= ?")
            params.append(hi)
        where = " AND ".join(conditions)
        cur.execute(
            f"""
            SELECT COUNT(*) as fills,
                   SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) as wins
            FROM window_trades
            WHERE {where}
            """,
            params,
        )
        r = cur.fetchone()
        fills_b = r["fills"] or 0
        wins_b = r["wins"] or 0
        price_bucket_slice.append({
            "bucket": label,
            "fills": fills_b,
            "wins": wins_b,
            "win_rate": round(wins_b / fills_b, 4) if fills_b > 0 else 0.0,
        })

    # -----------------------------------------------------------------------
    # cap_breach_events & pending_reservation_rows
    # -----------------------------------------------------------------------
    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE order_status LIKE 'cap_breach%'"
    )
    cap_breach_events = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) as n FROM window_trades WHERE order_status = 'pending_reservation'"
    )
    pending_reservation_rows = cur.fetchone()["n"]

    # -----------------------------------------------------------------------
    # UP fills with live orders in last week (for kill logic)
    # -----------------------------------------------------------------------
    one_week_ago = now_ts - ONE_WEEK_S
    cur.execute(
        """
        SELECT COUNT(*) as n FROM window_trades
        WHERE direction = 'UP'
          AND order_status = 'live_filled'
          AND decision_ts >= ?
        """,
        (one_week_ago,),
    )
    up_live_fills_last_week = cur.fetchone()["n"]

    conn.close()

    return {
        "db_summary": db_summary,
        "last_50_resolved": last_50_resolved,
        "direction_slice": direction_slice,
        "hour_slice_et": hour_slice_et,
        "price_bucket_slice": price_bucket_slice,
        "cap_breach_events": cap_breach_events,
        "pending_reservation_rows": pending_reservation_rows,
        "up_live_fills_last_week": up_live_fills_last_week,
    }


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

def compute_recommendation(db_data: dict) -> tuple[str, str]:
    summary = db_data["db_summary"]
    resolved = summary["resolved_fills"]
    wr = summary["win_rate"]
    cap_breach = db_data["cap_breach_events"]
    up_live_fills = db_data["up_live_fills_last_week"]

    if up_live_fills > 0:
        return (
            "kill",
            f"UP direction has {up_live_fills} live fill(s) in the last week. "
            "UP is KILLED per system mandate (lost -$1,060 on $1,492 deployed). "
            "Halt immediately and audit position limit enforcement.",
        )

    if cap_breach > 0:
        return (
            "kill",
            f"{cap_breach} cap_breach event(s) detected in the DB. "
            "Position limit enforcement is broken or has been bypassed. "
            "Do not deploy capital until limits are audited and fixed.",
        )

    if resolved > 100 and wr < 0.40:
        return (
            "kill",
            f"Win rate {wr:.1%} across {resolved} resolved fills is below 0.40 kill threshold. "
            "Strategy has no demonstrated edge at current parameters. "
            "Halt and redesign before further capital deployment.",
        )

    if resolved < 30:
        return (
            "hold",
            f"Only {resolved} resolved fills — insufficient sample for a reliable decision. "
            "Continue data collection; re-evaluate at 30+ fills.",
        )

    return (
        "continue",
        f"Win rate {wr:.1%} across {resolved} resolved fills is within acceptable range. "
        "No safety violations detected. Monitor closely.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_truth_bundle() -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = int(datetime.now(timezone.utc).timestamp())

    effective_params = load_effective_params()
    config_hash = config_hash_from_params(effective_params) if effective_params else None
    mutation_id = load_mutation_id()

    db_path = find_db()
    if db_path is None:
        print("WARNING: no btc_5min_maker.db found. Bundle will have empty DB stats.", file=sys.stderr)
        db_data = {
            "db_summary": {
                "total_windows": 0, "total_fills": 0, "total_paper_fills": 0,
                "total_live_fills": 0, "resolved_fills": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_trade_size_usd": 0.0, "total_pnl_usd_if_resolved": 0.0,
            },
            "last_50_resolved": {"win_rate": 0.0, "wins": 0, "losses": 0, "avg_trade_size_usd": 0.0},
            "direction_slice": {"UP": {"fills": 0, "wins": 0, "win_rate": 0.0, "total_usd": 0.0},
                                 "DOWN": {"fills": 0, "wins": 0, "win_rate": 0.0, "total_usd": 0.0}},
            "hour_slice_et": [{"hour_et": h, "fills": 0, "wins": 0, "win_rate": 0.0, "total_usd": 0.0}
                               for h in range(24)],
            "price_bucket_slice": [{"bucket": b[0], "fills": 0, "wins": 0, "win_rate": 0.0}
                                    for b in PRICE_BUCKETS],
            "cap_breach_events": 0,
            "pending_reservation_rows": 0,
            "up_live_fills_last_week": 0,
        }
    else:
        try:
            db_data = query_all(db_path, now_ts)
        except Exception as exc:
            print(f"ERROR querying DB: {exc}", file=sys.stderr)
            raise

    recommendation, reason = compute_recommendation(db_data)

    bundle = {
        "generated_at": now_iso,
        "mutation_id": mutation_id,
        "config_hash": config_hash,
        "db_summary": db_data["db_summary"],
        "last_50_resolved": db_data["last_50_resolved"],
        "direction_slice": db_data["direction_slice"],
        "hour_slice_et": db_data["hour_slice_et"],
        "price_bucket_slice": db_data["price_bucket_slice"],
        "cap_breach_events": db_data["cap_breach_events"],
        "pending_reservation_rows": db_data["pending_reservation_rows"],
        "recommendation": recommendation,
        "recommendation_reason": reason,
        "db_path_used": str(db_path.relative_to(REPO_ROOT)) if db_path else None,
    }
    return bundle


def invoke_health_snapshot():
    """Import and run the health snapshot script."""
    health_path = Path(__file__).parent / "render_btc5_health_snapshot.py"
    if not health_path.exists():
        print(f"WARNING: health snapshot script not found at {health_path}", file=sys.stderr)
        return
    try:
        spec = importlib.util.spec_from_file_location("render_btc5_health_snapshot", health_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    except Exception as exc:
        print(f"WARNING: health snapshot failed: {exc}", file=sys.stderr)


def main():
    bundle = run_truth_bundle()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(bundle, indent=2))
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")

    summary = bundle["db_summary"]
    print(f"\n=== BTC5 Truth Bundle ===")
    print(f"Total windows:    {summary['total_windows']}")
    print(f"Total fills:      {summary['total_fills']}  (live: {summary['total_live_fills']}, paper: {summary['total_paper_fills']})")
    print(f"Resolved fills:   {summary['resolved_fills']}")
    print(f"Win rate:         {summary['win_rate']:.1%}  ({summary['wins']}W / {summary['losses']}L)")
    print(f"Total deployed:   ${summary['total_trade_size_usd']:,.2f}")
    print(f"Total P&L:        ${summary['total_pnl_usd_if_resolved']:,.2f}")
    print(f"Cap breach events:{bundle['cap_breach_events']}")

    ds = bundle["direction_slice"]
    print(f"\nDirection slice:")
    for d in ("UP", "DOWN"):
        s = ds[d]
        print(f"  {d}: {s['fills']} fills, {s['win_rate']:.1%} WR, ${s['total_usd']:,.2f} deployed")

    print(f"\nRecommendation:   [{bundle['recommendation'].upper()}]")
    print(f"  {bundle['recommendation_reason']}")

    print(f"\n--- Running health snapshot ---")
    invoke_health_snapshot()

    return 0


if __name__ == "__main__":
    sys.exit(main())
