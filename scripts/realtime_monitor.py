"""Real-time trading monitor — runs every 5 minutes via systemd timer.

Computes rolling metrics from btc_5min_maker.db, checks alert thresholds,
and sends Telegram summaries every 30 minutes (6 windows).
Runs in log-only mode if TELEGRAM_BOT_TOKEN is not configured.

Usage:
    python3 scripts/realtime_monitor.py [--force-summary] [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db")
STATE_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/monitor_state.json")
REPORT_PATH = Path("/home/ubuntu/polymarket-trading-bot/reports/realtime_monitor.json")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ALERT_NO_FILLS_WINDOWS = 12       # Alert if 0 fills in last N windows (1 hour)
ALERT_WIN_RATE_MIN_SAMPLE = 10    # Min fills required before alerting on WR
ALERT_CONSECUTIVE_LOSSES = 3      # Alert on streak
ALERT_DRAWDOWN_PCT = 0.05         # Alert if balance drops > 5% from HWM
ALERT_STALE_WINDOW_SECS = 900     # Alert if last window > 15 min ago
ALERT_UNRESOLVED_BACKLOG = 5      # Alert if >= N live fills have no resolution
SUMMARY_EVERY_N_WINDOWS = 6       # Telegram summary cadence (30 min)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _telegram_send(text: str, *, dry_run: bool = False) -> bool:
    """Send Telegram message. Returns True on success. Silently fails if not configured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or "your-bot-token" in token:
        print(f"[TELEGRAM-STUB] {text[:200]}")
        return False
    if dry_run:
        print(f"[DRY-RUN] Telegram: {text[:200]}")
        return True
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"[WARN] Telegram send failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, params).fetchall()


def load_metrics(hours_1: int = 1, hours_6: int = 6) -> dict:
    """Load rolling metrics from DB."""
    conn = sqlite3.connect(str(DB_PATH))
    now_ts = int(time.time())
    cutoff_1h = now_ts - hours_1 * 3600
    cutoff_6h = now_ts - hours_6 * 3600

    def _window_stats(cutoff_ts: int) -> dict:
        rows = _query(conn, """
            SELECT order_status, direction, best_ask, pnl_usd, won,
                   resolved_outcome, window_start_ts, counterfactual_pnl_usd_std5
            FROM window_trades
            WHERE window_start_ts > ?
            ORDER BY window_start_ts ASC
        """, (cutoff_ts,))

        total = len(rows)
        fills = [r for r in rows if r["order_status"] == "live_filled"]
        order_failures = sum(1 for r in rows if r["order_status"] == "live_order_failed")
        skip_counts: dict[str, int] = {}
        for r in rows:
            s = r["order_status"]
            if s.startswith("skip_"):
                skip_counts[s] = skip_counts.get(s, 0) + 1

        # Per-direction fill stats (live_pnl_usd_actual only).
        dir_stats: dict[str, dict] = {}
        for r in fills:
            d = r["direction"] or "?"
            if d not in dir_stats:
                dir_stats[d] = {"fills": 0, "wins": 0, "live_pnl_usd_actual": 0.0,
                                 "counterfactual_pnl_usd_std5": 0.0, "prices": [],
                                 "resolved": 0}
            dir_stats[d]["fills"] += 1
            dir_stats[d]["wins"] += r["won"] or 0
            dir_stats[d]["live_pnl_usd_actual"] += r["pnl_usd"] or 0
            dir_stats[d]["counterfactual_pnl_usd_std5"] += r["counterfactual_pnl_usd_std5"] or 0
            dir_stats[d]["resolved"] += 1 if r["resolved_outcome"] is not None else 0
            if r["best_ask"]:
                dir_stats[d]["prices"].append(float(r["best_ask"]))
        for d, s in dir_stats.items():
            n = s["fills"]
            s["win_rate"] = round(s["wins"] / n, 3) if n else 0
            s["live_pnl_per_fill"] = round(s["live_pnl_usd_actual"] / n, 4) if n else 0
            avg_px = sum(s["prices"]) / len(s["prices"]) if s["prices"] else 0.5
            s["avg_entry_price"] = round(avg_px, 3)
            s["break_even_wr"] = round(avg_px / 1.0, 3)
            s["wr_edge"] = round(s["win_rate"] - s["break_even_wr"], 3)
            s["live_pnl_usd_actual"] = round(s["live_pnl_usd_actual"], 4)
            s["counterfactual_pnl_usd_std5"] = round(s["counterfactual_pnl_usd_std5"], 4)
            del s["prices"]

        # Total PnL — LIVE actual only (not blended with counterfactual).
        live_pnl = sum(r["pnl_usd"] or 0 for r in fills)

        # Consecutive losses at end of fills.
        consec_losses = 0
        for r in reversed(fills):
            if not r["won"]:
                consec_losses += 1
            else:
                break

        # Unresolved fills (live_filled but no resolved_outcome yet).
        unresolved_fills = sum(
            1 for r in fills if r["resolved_outcome"] is None
        )

        return {
            "total_windows": total,
            "fills": len(fills),
            "fill_rate": round(len(fills) / total, 4) if total else 0.0,
            "live_pnl_usd_actual": round(live_pnl, 4),
            "live_pnl_per_fill": round(live_pnl / len(fills), 4) if fills else 0.0,
            "win_rate": round(sum(r["won"] or 0 for r in fills) / len(fills), 3) if fills else 0.0,
            "by_direction": dir_stats,
            "skip_breakdown": skip_counts,
            "consecutive_losses_at_end": consec_losses,
            "order_failures": order_failures,
            "unresolved_fills": unresolved_fills,
        }

    stats_1h = _window_stats(cutoff_1h)
    stats_6h = _window_stats(cutoff_6h)

    # Health metrics.
    last_window_age_secs = None
    unresolved_backlog = 0
    try:
        row = conn.execute(
            "SELECT window_start_ts FROM window_trades ORDER BY window_start_ts DESC LIMIT 1"
        ).fetchone()
        if row:
            last_window_age_secs = now_ts - row[0]
        # Fills with no resolution (entire history, not just recent).
        unresolved_backlog = conn.execute(
            "SELECT COUNT(*) FROM window_trades WHERE order_status='live_filled' AND resolved_outcome IS NULL"
        ).fetchone()[0]
    except Exception:
        pass

    # Balance from CLOB healthcheck logs.
    balance = None
    try:
        import subprocess
        r = subprocess.run(
            ["journalctl", "-u", "btc-5min-maker", "--since", "1 hour ago", "--no-pager", "-n", "200"],
            capture_output=True, text=True, timeout=5,
        )
        for line in reversed(r.stdout.splitlines()):
            if "CLOB healthcheck OK" in line and "balance=" in line:
                part = line.split("balance=")[1]
                balance = float(part.strip("$").split()[0])
                break
    except Exception:
        pass

    conn.close()
    return {
        "ts": now_ts,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "balance_usd": balance,
        "last_window_age_secs": last_window_age_secs,
        "unresolved_backlog": unresolved_backlog,
        "stats_1h": stats_1h,
        "stats_6h": stats_6h,
    }


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {
        "last_summary_window_count": 0,
        "total_windows_ever": 0,
        "starting_balance": None,
        "balance_hwm": None,          # High-water mark for drawdown calculation.
        "alerts_sent": [],
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Config drift detector
# ---------------------------------------------------------------------------

def check_config_drift() -> list[dict]:
    """Compare running bot environ to env files. Alert on mismatches."""
    import subprocess

    alerts = []

    try:
        result = subprocess.run(
            ["pgrep", "-f", "btc_5min_maker.py"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return [{"type": "config_drift", "severity": "WARN",
                     "message": "Config drift check: bot process not found"}]
        pid = pids[0]
        env_path = Path(f"/proc/{pid}/environ")
        if not env_path.exists():
            return []

        raw = env_path.read_bytes()
        live_env = {}
        for entry in raw.split(b"\x00"):
            try:
                decoded = entry.decode("utf-8", errors="replace")
                if "=" in decoded:
                    k, v = decoded.split("=", 1)
                    if k.startswith("BTC5_"):
                        live_env[k] = v
            except Exception:
                pass
    except Exception as exc:
        return [{"type": "config_drift", "severity": "WARN",
                 "message": f"Config drift check failed: {exc}"}]

    file_env = {}
    env_files = [
        Path("/home/ubuntu/polymarket-trading-bot/.env"),
        Path("/home/ubuntu/polymarket-trading-bot/config/btc5_strategy.env"),
        Path("/home/ubuntu/polymarket-trading-bot/state/btc5_capital_stage.env"),
    ]
    for ef in env_files:
        if not ef.exists():
            continue
        for line in ef.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith("BTC5_"):
                    file_env[k] = v.strip()

    critical_keys = [
        "BTC5_MIN_BUY_PRICE", "BTC5_DOWN_MAX_BUY_PRICE", "BTC5_UP_MAX_BUY_PRICE",
        "BTC5_MIN_DELTA", "BTC5_MAX_ABS_DELTA", "BTC5_DIRECTIONAL_MODE",
        "BTC5_PAPER_TRADING", "BTC5_BANKROLL_USD", "BTC5_RISK_FRACTION",
        "BTC5_MAX_TRADE_USD", "BTC5_DAILY_LOSS_LIMIT_USD",
        "BTC5_PROBE_RECENT_MIN_PNL_USD", "BTC5_CAPITAL_STAGE",
    ]

    mismatches = []
    for key in critical_keys:
        live_val = live_env.get(key)
        file_val = file_env.get(key)
        if live_val is not None and file_val is not None and live_val != file_val:
            mismatches.append(f"{key}: live={live_val} file={file_val}")

    if mismatches:
        alerts.append({
            "type": "config_drift",
            "severity": "ALERT",
            "message": (
                f"CONFIG DRIFT DETECTED ({len(mismatches)} params): "
                + "; ".join(mismatches[:3])
                + (f" (+{len(mismatches)-3} more)" if len(mismatches) > 3 else "")
            ),
        })

    return alerts


# ---------------------------------------------------------------------------
# Alert checks
# ---------------------------------------------------------------------------

def check_alerts(metrics: dict, state: dict) -> list[dict]:
    """Return list of alert dicts that should be sent."""
    alerts = []
    s1h = metrics["stats_1h"]
    s6h = metrics["stats_6h"]

    # Alert 1: No fills in 1h with enough windows.
    if s1h["total_windows"] >= ALERT_NO_FILLS_WINDOWS and s1h["fills"] == 0:
        alerts.append({
            "type": "no_fills",
            "severity": "WARN",
            "message": (
                f"⚠️ No fills in last {s1h['total_windows']} windows "
                f"({s1h['total_windows'] // 12}h). "
                f"Top skip: {max(s1h['skip_breakdown'], key=s1h['skip_breakdown'].get, default='none')}"
            ),
        })

    # Alert 2: DOWN win rate below break-even (6h, min ALERT_WIN_RATE_MIN_SAMPLE fills).
    down_6h = s6h.get("by_direction", {}).get("DOWN", {})
    if down_6h.get("fills", 0) >= ALERT_WIN_RATE_MIN_SAMPLE:
        if down_6h.get("wr_edge", 0) < -0.05:  # More than 5% below break-even.
            alerts.append({
                "type": "win_rate_below_breakeven",
                "severity": "WARN",
                "message": (
                    f"⚠️ DOWN win rate {down_6h['win_rate']:.0%} is {abs(down_6h['wr_edge']):.0%} "
                    f"below break-even {down_6h['break_even_wr']:.0%} "
                    f"(n={down_6h['fills']} fills, 6h)"
                ),
            })

    # Alert 3: Consecutive losses.
    if s1h["consecutive_losses_at_end"] >= ALERT_CONSECUTIVE_LOSSES:
        alerts.append({
            "type": "loss_streak",
            "severity": "WARN",
            "message": (
                f"⚠️ {s1h['consecutive_losses_at_end']} consecutive losses. "
                f"6h PnL: ${s6h['total_pnl']:.2f}"
            ),
        })

    # Alert 4: Drawdown from high-water mark (not starting balance).
    balance = metrics.get("balance_usd")
    hwm = state.get("balance_hwm")
    if balance and hwm and hwm > 0:
        drawdown = (hwm - balance) / hwm
        if drawdown >= ALERT_DRAWDOWN_PCT:
            alerts.append({
                "type": "drawdown",
                "severity": "ALERT",
                "message": (
                    f"🚨 Drawdown {drawdown:.1%} from HWM: balance ${balance:.2f} "
                    f"vs HWM ${hwm:.2f}"
                ),
            })

    # Alert 5: Stale windows (last window processed > threshold).
    age = metrics.get("last_window_age_secs")
    if age is not None and age > ALERT_STALE_WINDOW_SECS:
        alerts.append({
            "type": "stale_windows",
            "severity": "WARN",
            "message": f"⚠️ Last window processed {age // 60}m ago — bot may be down",
        })

    # Alert 6: High unresolved backlog.
    backlog = metrics.get("unresolved_backlog", 0)
    if backlog >= ALERT_UNRESOLVED_BACKLOG:
        alerts.append({
            "type": "unresolved_backlog",
            "severity": "WARN",
            "message": f"⚠️ {backlog} live fills awaiting resolution (backfill may be stalled)",
        })

    return alerts


# ---------------------------------------------------------------------------
# Summary message
# ---------------------------------------------------------------------------

def format_summary(metrics: dict, state: dict) -> str:
    s1h = metrics["stats_1h"]
    s6h = metrics["stats_6h"]
    balance = metrics.get("balance_usd")
    hwm = state.get("balance_hwm")
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    lines = [f"<b>📊 Elastifund Monitor — {now}</b>"]

    if balance:
        hwm_str = f" (HWM ${hwm:.2f})" if hwm and hwm > balance else ""
        lines.append(f"💰 Balance: <b>${balance:.2f}</b>{hwm_str}")

    # Health indicators.
    age = metrics.get("last_window_age_secs")
    backlog = metrics.get("unresolved_backlog", 0)
    health_parts = []
    if age is not None:
        health_parts.append(f"last window {age // 60}m ago")
    if backlog:
        health_parts.append(f"backlog={backlog}")
    if s1h.get("order_failures", 0):
        health_parts.append(f"failures={s1h['order_failures']}")
    if health_parts:
        lines.append(f"🏥 Health: {', '.join(health_parts)}")

    lines.append(f"\n<b>Last 1h ({s1h['total_windows']} windows):</b>")
    lines.append(f"  Fills: {s1h['fills']} ({s1h['fill_rate']:.1%} rate)")
    if s1h["fills"] > 0:
        lines.append(
            f"  WR: {s1h['win_rate']:.0%} | live_pnl_actual: ${s1h['live_pnl_usd_actual']:.2f}"
        )

    lines.append(f"\n<b>Last 6h ({s6h['total_windows']} windows):</b>")
    lines.append(f"  Fills: {s6h['fills']} ({s6h['fill_rate']:.1%} rate)")
    if s6h["fills"] > 0:
        lines.append(
            f"  WR: {s6h['win_rate']:.0%} | live_pnl_actual: ${s6h['live_pnl_usd_actual']:.2f}"
        )

    # Direction breakdown.
    for d, ds in s6h.get("by_direction", {}).items():
        if ds["fills"] > 0:
            edge = ds.get("wr_edge", 0)
            edge_str = f"+{edge:.0%}" if edge >= 0 else f"{edge:.0%}"
            lines.append(
                f"  {d}: {ds['fills']} fills, WR {ds['win_rate']:.0%} "
                f"(edge {edge_str}), live=${ds['live_pnl_usd_actual']:.2f}"
            )

    # Top skip in last 1h.
    if s1h["skip_breakdown"]:
        top_skip = max(s1h["skip_breakdown"], key=s1h["skip_breakdown"].get)
        top_n = s1h["skip_breakdown"][top_skip]
        lines.append(f"\nTop skip (1h): {top_skip} ×{top_n}")

    if s1h.get("consecutive_losses_at_end", 0) > 0:
        lines.append(f"⚠️ Streak: {s1h['consecutive_losses_at_end']} losses")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(force_summary: bool = False, dry_run: bool = False) -> dict:
    _t0 = time.time()
    metrics = load_metrics()
    state = load_state()

    # Initialize and update balance tracking.
    balance = metrics.get("balance_usd")
    if balance:
        if state.get("starting_balance") is None:
            state["starting_balance"] = balance
            print(f"Starting balance set: ${balance:.2f}")
        # Update HWM.
        if state.get("balance_hwm") is None or balance > state["balance_hwm"]:
            state["balance_hwm"] = balance

    # Track window count for summary cadence.
    current_total = metrics["stats_6h"]["total_windows"]
    windows_since_last = current_total - state.get("last_summary_window_count", 0)

    # Check alerts.
    alerts = check_alerts(metrics, state)
    # Config drift check.
    drift_alerts = check_config_drift()
    alerts.extend(drift_alerts)
    for alert in alerts:
        severity = alert["severity"]
        msg = alert["message"]
        print(f"[{severity}] {msg}")
        _telegram_send(msg, dry_run=dry_run)
        state.setdefault("alerts_sent", []).append({
            "ts": metrics["ts"],
            "type": alert["type"],
            "severity": severity,
        })
        # Keep only last 50 alerts.
        state["alerts_sent"] = state["alerts_sent"][-50:]

    # Send summary every N windows or when forced.
    should_summary = force_summary or windows_since_last >= SUMMARY_EVERY_N_WINDOWS
    if should_summary:
        summary = format_summary(metrics, state)
        print(f"\n--- SUMMARY ---\n{summary}\n---")
        _telegram_send(summary, dry_run=dry_run)
        state["last_summary_window_count"] = current_total

    # Save metrics to report file.
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "metrics": metrics,
        "alerts_this_run": alerts,
        "summary_sent": should_summary,
    }
    REPORT_PATH.write_text(json.dumps(output, indent=2))

    save_state(state)
    duration = time.time() - _t0
    print(f"Monitor run complete: {metrics['stats_1h']['total_windows']} windows (1h), "
          f"{metrics['stats_1h']['fills']} fills, {len(alerts)} alerts")

    # Log to cost ledger.
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.cost_ledger import log_invocation
        log_invocation(task_class="monitor", execution_path="deterministic",
                       duration_seconds=duration)
    except Exception as _e:
        print(f"[WARN] cost_ledger write failed: {_e}")

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time trading monitor")
    parser.add_argument("--force-summary", action="store_true", help="Force Telegram summary")
    parser.add_argument("--dry-run", action="store_true", help="Don't send Telegram")
    args = parser.parse_args()

    # Load env from .env file if not already set.
    env_file = Path("/home/ubuntu/polymarket-trading-bot/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

    result = run(force_summary=args.force_summary, dry_run=args.dry_run)
    print(json.dumps({"status": "ok", "alerts": len(result["alerts_this_run"])}, indent=2))
