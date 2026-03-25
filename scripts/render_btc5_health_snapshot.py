#!/usr/bin/env python3
"""
P1.2 — render_btc5_health_snapshot.py

Answers the 5 operator questions about BTC5 and writes
reports/btc5_health_latest.json.

The 5 questions:
  1. Is the bot running?          (systemd check, graceful on non-VPS)
  2. When was the last fill?      (btc_5min_maker.db)
  3. Rolling win rate (last 50)?  (btc_5min_maker.db window_trades)
  4. What exact params deployed?  (state/btc5_effective.env or config/btc5_strategy.env)
  5. Does deployed config match the latest mutation?

Usage:
  python scripts/render_btc5_health_snapshot.py
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
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
OUTPUT = REPO_ROOT / "reports" / "btc5_health_latest.json"

# Statuses that are NOT real resolved fills
SKIP_STATUSES = frozenset([
    "pending_reservation",
    "cap_breach_blocked",
    "shadow_placed",
    "skip_direction_mode_suppressed",
    "skip_hour_filter_suppressed",
    "skip_already_processed",
])

ONE_HOUR = 3600
FOUR_HOURS = 4 * 3600


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


# ---------------------------------------------------------------------------
# Question 1: Is the bot running?
# ---------------------------------------------------------------------------

def check_bot_running() -> bool | None:
    """Return True/False/None. None means we can't determine (not on VPS)."""
    if not shutil.which("systemctl"):
        return None
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "btc-5min-maker.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Questions 2 & 3: Last fill + rolling win rate
# ---------------------------------------------------------------------------

def query_db(db_path: Path) -> dict:
    """Return dict with last_fill info and rolling win rate."""
    out = {
        "last_fill_ts": None,
        "last_fill_age_seconds": None,
        "last_fill_status": None,
        "rolling_win_rate_50": None,
        "rolling_win_count": 0,
        "rolling_loss_count": 0,
        "no_fills_found": True,
    }
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Question 2: last fill (exclude skip statuses)
        placeholders = ",".join("?" * len(SKIP_STATUSES))
        cur.execute(
            f"""
            SELECT decision_ts, order_status
            FROM window_trades
            WHERE order_status NOT IN ({placeholders})
            ORDER BY decision_ts DESC
            LIMIT 1
            """,
            list(SKIP_STATUSES),
        )
        row = cur.fetchone()
        if row:
            out["last_fill_ts"] = row["decision_ts"]
            out["last_fill_status"] = row["order_status"]
            out["no_fills_found"] = False
            now_ts = int(datetime.now(timezone.utc).timestamp())
            out["last_fill_age_seconds"] = now_ts - row["decision_ts"]

        # Question 3: rolling win rate over last 50 resolved fills
        cur.execute(
            """
            SELECT won
            FROM window_trades
            WHERE resolved_side IS NOT NULL
            ORDER BY decision_ts DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall()
        if rows:
            wins = sum(1 for r in rows if r["won"] == 1)
            losses = sum(1 for r in rows if r["won"] == 0)
            total = wins + losses
            out["rolling_win_count"] = wins
            out["rolling_loss_count"] = losses
            out["rolling_win_rate_50"] = round(wins / total, 4) if total > 0 else None

        conn.close()
    except Exception as exc:
        print(f"WARNING: DB query failed ({db_path}): {exc}", file=sys.stderr)

    return out


# ---------------------------------------------------------------------------
# Questions 4 & 5: Deployed params and mutation match
# ---------------------------------------------------------------------------

def load_effective_params() -> dict:
    env_path = EFFECTIVE_ENV if EFFECTIVE_ENV.exists() else FALLBACK_ENV
    raw = parse_env_file(env_path)
    return {k: v for k, v in raw.items() if k.startswith("BTC5_")}


def load_mutation() -> dict | None:
    if not MUTATION_FILE.exists():
        return None
    try:
        return json.loads(MUTATION_FILE.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_health_snapshot() -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()

    # Q1
    bot_running = check_bot_running()

    # Q2 & Q3
    db_path = find_db()
    db_info = {
        "last_fill_ts": None,
        "last_fill_age_seconds": None,
        "last_fill_status": None,
        "rolling_win_rate_50": None,
        "rolling_win_count": 0,
        "rolling_loss_count": 0,
        "no_fills_found": True,
    }
    if db_path:
        db_info = query_db(db_path)

    # Q4
    effective_params = load_effective_params()
    deployed_config_hash = config_hash_from_params(effective_params) if effective_params else None

    # Q5
    mutation = load_mutation()
    mutation_id = None
    config_hash_match = None
    if mutation:
        mutation_id = mutation.get("mutation_id") or mutation.get("id")
        mut_hash = mutation.get("config_hash")
        if deployed_config_hash and mut_hash:
            config_hash_match = deployed_config_hash == mut_hash

    # Build alert flags
    alert_flags = []
    if bot_running is False:
        alert_flags.append("service_down")
    age = db_info["last_fill_age_seconds"]
    if age is not None:
        if age > FOUR_HOURS:
            alert_flags.append("last_fill_stale_4h")
        elif age > ONE_HOUR:
            alert_flags.append("last_fill_stale_1h")
    if config_hash_match is False:
        alert_flags.append("config_hash_mismatch")
    wr = db_info["rolling_win_rate_50"]
    if wr is not None and wr < 0.35:
        alert_flags.append("win_rate_below_35pct")
    if db_info["no_fills_found"]:
        alert_flags.append("no_fills_found")

    snapshot = {
        "generated_at": now_iso,
        "bot_running": bot_running,
        "last_fill_ts": db_info["last_fill_ts"],
        "last_fill_age_seconds": db_info["last_fill_age_seconds"],
        "last_fill_status": db_info["last_fill_status"],
        "rolling_win_rate_50": db_info["rolling_win_rate_50"],
        "rolling_win_count": db_info["rolling_win_count"],
        "rolling_loss_count": db_info["rolling_loss_count"],
        "deployed_config_hash": deployed_config_hash,
        "mutation_id": mutation_id,
        "config_hash_match": config_hash_match,
        "effective_params": effective_params,
        "alert_flags": alert_flags,
        "db_path_used": str(db_path.relative_to(REPO_ROOT)) if db_path else None,
    }
    return snapshot


def main():
    snapshot = run_health_snapshot()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(snapshot, indent=2))
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")

    print(f"\nBot running:       {snapshot['bot_running']}")
    age = snapshot["last_fill_age_seconds"]
    if age is not None:
        hours, rem = divmod(age, 3600)
        mins = rem // 60
        print(f"Last fill:         {hours}h {mins}m ago  (status: {snapshot['last_fill_status']})")
    else:
        print(f"Last fill:         (none found)")
    wr = snapshot["rolling_win_rate_50"]
    print(
        f"Rolling WR (50):   {f'{wr:.1%}' if wr is not None else 'N/A'} "
        f"({snapshot['rolling_win_count']}W / {snapshot['rolling_loss_count']}L)"
    )
    print(f"Config hash:       {snapshot['deployed_config_hash'] or '(none)'}")
    print(f"Hash match:        {snapshot['config_hash_match']}")
    flags = snapshot["alert_flags"]
    if flags:
        print(f"\nALERT FLAGS ({len(flags)}): {', '.join(flags)}")
    else:
        print("\nAlert flags:       none")

    return 0


if __name__ == "__main__":
    sys.exit(main())
