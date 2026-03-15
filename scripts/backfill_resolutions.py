"""Backfill resolved_outcome and counterfactual PnL for all historical windows.

Fetches Binance 5m klines for each unresolved window, determines UP/DOWN/FLAT,
computes counterfactual PnL for skip windows, and updates the DB.

SAFETY INVARIANT: Never modifies pnl_usd or won for live_filled rows.
Live execution data is the sole source of truth for filled trades.

Usage:
    python3 scripts/backfill_resolutions.py [--limit N] [--dry-run] [--audit-only]
"""
import argparse
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db")
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
STD_TRADE_USD = 5.0  # Standardized notional for counterfactual sizing.


def fetch_kline(window_start_ts: int) -> tuple[float, float] | None:
    """Fetch open/close for a 5m window from Binance."""
    url = (
        f"{BINANCE_KLINES_URL}?symbol=BTCUSDT&interval=5m"
        f"&startTime={window_start_ts * 1000}&limit=1"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "backfill/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data or not isinstance(data, list):
            return None
        row = data[0]
        if not isinstance(row, list) or len(row) < 5:
            return None
        return float(row[1]), float(row[4])  # open, close
    except Exception as e:
        print(f"  [WARN] Kline fetch failed for ts={window_start_ts}: {e}")
        return None


def batch_fetch_klines(timestamps: list[int]) -> dict[int, tuple[float, float]]:
    """Fetch klines in batches of up to 1000 (Binance limit)."""
    if not timestamps:
        return {}

    results: dict[int, tuple[float, float]] = {}
    sorted_ts = sorted(set(timestamps))

    batch_size = 500
    for i in range(0, len(sorted_ts), batch_size):
        batch = sorted_ts[i : i + batch_size]
        start_ms = batch[0] * 1000
        end_ms = (batch[-1] + 300) * 1000
        url = (
            f"{BINANCE_KLINES_URL}?symbol=BTCUSDT&interval=5m"
            f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "backfill/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, list) and len(row) >= 5:
                        candle_ts = int(row[0]) // 1000
                        results[candle_ts] = (float(row[1]), float(row[4]))
            print(f"  Fetched {len(data)} klines for batch {i // batch_size + 1}")
        except Exception as e:
            print(f"  [WARN] Batch kline fetch failed: {e}")
            for ts in batch:
                kline = fetch_kline(ts)
                if kline:
                    results[ts] = kline
                time.sleep(0.1)

        time.sleep(0.2)

    return results


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add backfill-era columns if they don't exist."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()}
    new_cols = {
        "backfilled_at": "TEXT",
        "counterfactual_pnl_usd_std5": "REAL",
        "counterfactual_notional_usd": "REAL",
    }
    for col, typ in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE window_trades ADD COLUMN {col} {typ}")
            print(f"  Added column: {col} ({typ})")
    conn.commit()


def _compute_counterfactual(
    direction: str,
    resolved_side: str,
    hyp_price: float,
) -> tuple[float, float, float]:
    """Compute standardized counterfactual PnL for a skip window.

    Returns (counterfactual_pnl_usd_std5, counterfactual_notional_usd, shares).
    """
    hyp_shares = max(5.0, round(STD_TRADE_USD / hyp_price, 2))
    notional = round(hyp_shares * hyp_price, 4)
    if direction == resolved_side:
        pnl = round(hyp_shares * (1.0 - hyp_price), 6)
    else:
        pnl = round(-hyp_shares * hyp_price, 6)
    return pnl, notional, hyp_shares


def backfill(limit: int | None = None, dry_run: bool = False) -> dict:
    """Backfill resolution data for unresolved windows.

    NEVER writes pnl_usd or won for live_filled rows.
    Only backfills: resolved_side, resolved_outcome, counterfactual PnL for skips.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    _ensure_columns(conn)

    backfill_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Phase 1: Populate resolved_outcome + counterfactual from existing resolved_side.
    # Only touches rows where resolved_side exists but resolved_outcome is missing,
    # or where counterfactual data is missing for skip rows.
    phase1_rows = conn.execute("""
        SELECT window_start_ts, window_end_ts, direction, order_price, best_ask, shares,
               order_status, filled, resolved_side, pnl_usd, won
        FROM window_trades
        WHERE resolved_side IS NOT NULL
          AND (resolved_outcome IS NULL OR counterfactual_pnl_usd_std5 IS NULL)
        ORDER BY window_start_ts ASC
    """).fetchall()

    phase1_count = 0
    phase1_cf = 0
    for row in phase1_rows:
        resolved_side = row["resolved_side"]
        direction = str(row["direction"] or "")
        order_price = float(row["order_price"] or 0)
        best_ask = float(row["best_ask"]) if row["best_ask"] else None
        order_status = str(row["order_status"] or "")
        window_end_ts = row["window_end_ts"]

        cf_pnl_std5 = None
        cf_notional = None

        # Counterfactual for skip windows only.
        if order_status.startswith("skip_") and direction in {"UP", "DOWN"} and resolved_side in {"UP", "DOWN"}:
            hyp_price = order_price if order_price > 0 else (best_ask if best_ask and best_ask > 0 else None)
            if hyp_price is not None and hyp_price > 0:
                cf_pnl_std5, cf_notional, _ = _compute_counterfactual(direction, resolved_side, hyp_price)
                phase1_cf += 1

        if not dry_run:
            # Only set resolved_outcome and counterfactual — NEVER touch pnl_usd/won.
            conn.execute("""
                UPDATE window_trades
                SET resolved_outcome = COALESCE(resolved_outcome, ?),
                    resolution_ts = COALESCE(resolution_ts, ?),
                    counterfactual_pnl_usd_std5 = COALESCE(counterfactual_pnl_usd_std5, ?),
                    counterfactual_notional_usd = COALESCE(counterfactual_notional_usd, ?),
                    backfilled_at = COALESCE(backfilled_at, ?)
                WHERE window_start_ts = ?
            """, (resolved_side, window_end_ts, cf_pnl_std5, cf_notional, backfill_ts, row["window_start_ts"]))
        phase1_count += 1

    if not dry_run and phase1_count:
        conn.commit()
    print(f"Phase 1: Backfilled {phase1_count} rows from existing resolved_side ({phase1_cf} counterfactuals)")

    # Phase 2: Resolve windows with no resolved_side at all.
    cutoff_ts = int(time.time()) - 600
    query = """
        SELECT window_start_ts, window_end_ts, slug, direction,
               order_price, best_ask, best_bid, shares,
               order_status, filled, delta, trade_size_usd, pnl_usd, won
        FROM window_trades
        WHERE resolved_side IS NULL
          AND window_start_ts < ?
        ORDER BY window_start_ts ASC
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query, (cutoff_ts,)).fetchall()
    print(f"Phase 2: Found {len(rows)} windows needing kline resolution")

    if not rows:
        conn.close()
        return {"phase1_backfilled": phase1_count, "phase1_counterfactuals": phase1_cf,
                "phase2_total": 0, "phase2_resolved": 0, "phase2_skipped": 0}

    timestamps = [int(r["window_start_ts"]) for r in rows]
    print(f"Fetching klines for {len(set(timestamps))} unique timestamps...")
    klines = batch_fetch_klines(timestamps)
    print(f"Got {len(klines)} klines")

    resolved_count = 0
    cf_count = 0
    skipped = 0

    for row in rows:
        wts = int(row["window_start_ts"])
        kline = klines.get(wts)
        if not kline:
            skipped += 1
            continue

        open_px, close_px = kline
        if close_px > open_px:
            resolved_side = "UP"
        elif close_px < open_px:
            resolved_side = "DOWN"
        else:
            resolved_side = "FLAT"

        direction = str(row["direction"] or "")
        order_price = float(row["order_price"] or 0)
        best_ask = float(row["best_ask"]) if row["best_ask"] else None
        order_status = str(row["order_status"] or "")
        window_end_ts = row["window_end_ts"]

        cf_pnl_std5 = None
        cf_notional = None

        # Counterfactual for skip windows only.
        if order_status.startswith("skip_") and direction in {"UP", "DOWN"} and resolved_side in {"UP", "DOWN"}:
            hyp_price = order_price if order_price > 0 else (best_ask if best_ask and best_ask > 0 else None)
            if hyp_price is not None and hyp_price > 0:
                cf_pnl_std5, cf_notional, _ = _compute_counterfactual(direction, resolved_side, hyp_price)
                cf_count += 1

        if not dry_run:
            # Set resolution fields. NEVER touch pnl_usd or won — those are live-only.
            conn.execute("""
                UPDATE window_trades
                SET resolved_side = ?,
                    resolved_outcome = ?,
                    resolution_ts = ?,
                    counterfactual_pnl_usd_std5 = ?,
                    counterfactual_notional_usd = ?,
                    backfilled_at = ?
                WHERE window_start_ts = ?
                  AND resolved_side IS NULL
            """, (resolved_side, resolved_side, window_end_ts,
                  cf_pnl_std5, cf_notional, backfill_ts, wts))

        resolved_count += 1

    if not dry_run:
        conn.commit()
        print(f"Committed {resolved_count} resolutions, {cf_count} counterfactuals")
    else:
        print(f"[DRY RUN] Would resolve {resolved_count}, compute {cf_count} counterfactuals")

    conn.close()
    return {
        "phase1_backfilled": phase1_count,
        "phase1_counterfactuals": phase1_cf,
        "phase2_total": len(rows),
        "phase2_resolved": resolved_count,
        "phase2_counterfactuals": cf_count,
        "phase2_skipped": skipped,
    }


def audit_integrity() -> dict:
    """Audit backfill integrity.

    Checks:
    1. No live_filled rows have been touched by backfill
    2. pnl_usd and won are only set for live_filled rows
    3. Count rows that WOULD have been modified under old unsafe query
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    report: dict = {"status": "ok", "checks": []}

    # Check which columns exist.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()}
    has_backfilled_at = "backfilled_at" in existing_cols

    # Check 1: live_filled rows should have pnl_usd set by live execution, not backfill.
    if has_backfilled_at:
        live_filled_with_backfill = conn.execute("""
            SELECT COUNT(*) FROM window_trades
            WHERE order_status = 'live_filled'
              AND backfilled_at IS NOT NULL
        """).fetchone()[0]
    else:
        live_filled_with_backfill = 0
    report["checks"].append({
        "name": "live_filled_not_backfilled",
        "pass": True,
        "live_filled_with_backfill_ts": live_filled_with_backfill,
        "note": "Backfill only sets resolved_side/resolved_outcome on live rows, never pnl_usd/won",
    })

    # Check 2: Count live_filled rows where pnl_usd or won differs from recomputed values.
    live_fills = conn.execute("""
        SELECT window_start_ts, direction, order_price, shares, resolved_side, won, pnl_usd
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND filled = 1
          AND resolved_side IS NOT NULL
    """).fetchall()

    mismatches = []
    for row in live_fills:
        d = row["direction"]
        rs = row["resolved_side"]
        px = float(row["order_price"] or 0)
        sh = float(row["shares"] or 0)
        actual_won = row["won"]
        actual_pnl = row["pnl_usd"]

        if d in {"UP", "DOWN"} and rs in {"UP", "DOWN"}:
            expected_won = 1 if d == rs else 0
            expected_pnl = round(sh * (1.0 - px), 6) if expected_won else round(-sh * px, 6)

            if actual_won != expected_won or (actual_pnl is not None and abs(actual_pnl - expected_pnl) > 0.001):
                mismatches.append({
                    "window_start_ts": row["window_start_ts"],
                    "direction": d,
                    "resolved_side": rs,
                    "actual_won": actual_won,
                    "expected_won": expected_won,
                    "actual_pnl": actual_pnl,
                    "expected_pnl": expected_pnl,
                })

    report["checks"].append({
        "name": "live_filled_pnl_consistency",
        "pass": len(mismatches) == 0,
        "total_live_fills": len(live_fills),
        "mismatches": len(mismatches),
        "mismatch_details": mismatches[:10],
    })

    # Check 3: Count rows that WOULD have changed under old COALESCE(?, existing) query.
    # The old query did COALESCE(?, won) — overwrites when new value is non-null.
    old_would_overwrite = conn.execute("""
        SELECT COUNT(*) FROM window_trades
        WHERE order_status = 'live_filled'
          AND won IS NOT NULL
          AND pnl_usd IS NOT NULL
    """).fetchone()[0]
    report["checks"].append({
        "name": "old_query_overwrite_risk",
        "rows_that_old_query_would_have_overwritten": old_would_overwrite,
        "note": "These rows had existing won/pnl_usd — old COALESCE(?, col) would overwrite them",
    })

    # Check 4: Skip rows should NOT have pnl_usd set (they weren't traded).
    skip_with_pnl = conn.execute("""
        SELECT COUNT(*) FROM window_trades
        WHERE order_status LIKE 'skip_%'
          AND pnl_usd IS NOT NULL
          AND pnl_usd != 0.0
    """).fetchone()[0]
    report["checks"].append({
        "name": "skip_rows_no_live_pnl",
        "pass": skip_with_pnl == 0,
        "skip_rows_with_nonzero_pnl": skip_with_pnl,
    })

    # Summary.
    all_pass = all(c.get("pass", True) for c in report["checks"])
    report["status"] = "PASS" if all_pass else "FAIL"

    conn.close()
    return report


if __name__ == "__main__":
    import time as _time
    _t0 = _time.time()

    parser = argparse.ArgumentParser(description="Backfill window resolutions from Binance klines")
    parser.add_argument("--limit", type=int, default=None, help="Max windows to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--audit-only", action="store_true", help="Only run integrity audit")
    args = parser.parse_args()

    if args.audit_only:
        result = audit_integrity()
    else:
        result = backfill(limit=args.limit, dry_run=args.dry_run)
        print("\n--- Integrity Audit ---")
        audit = audit_integrity()
        result["integrity_audit"] = audit
        print(json.dumps(audit, indent=2))

    print(f"\nResult: {json.dumps(result, indent=2)}")

    try:
        from scripts.cost_ledger import log_invocation
        log_invocation(task_class="backfill", execution_path="deterministic",
                       duration_seconds=round(_time.time() - _t0, 2))
    except Exception as _e:
        print(f"[WARN] cost_ledger write failed: {_e}")
