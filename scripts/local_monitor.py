#!/usr/bin/env python3
"""
Elastifund Local Monitor — Terminal dashboard for fund health.

Pulls live data from:
  - Polymarket Data API (positions, closed trades, recent activity)
  - Dublin VPS via SSH (BTC5 maker DB, skip reasons, service status)

Refreshes every 60 seconds.  Saves state to data/local_monitor_state.json.

Usage:
    python3 scripts/local_monitor.py              # continuous dashboard
    python3 scripts/local_monitor.py --once        # single snapshot then exit
    python3 scripts/local_monitor.py --no-ssh      # skip VPS queries
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "local_monitor_state.json"

PROXY_WALLET = "0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5"
BASE_URL = "https://data-api.polymarket.com"
DEFAULT_DEPOSIT = 1331.28
VPS_BTC5_DB = "/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db"
VPS_TIMEOUT = 10  # seconds


def _load_repo_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


_REPO_ENV = _load_repo_env(PROJECT_ROOT / ".env")
_VPS_USER = str(os.environ.get("VPS_USER") or _REPO_ENV.get("VPS_USER") or "ubuntu").strip()
_VPS_IP = str(os.environ.get("VPS_IP") or _REPO_ENV.get("VPS_IP") or "34.244.34.108").strip()
VPS_HOST = f"{_VPS_USER}@{_VPS_IP}"
VPS_KEY = os.path.expanduser(
    str(
        os.environ.get("LIGHTSAIL_KEY")
        or _REPO_ENV.get("LIGHTSAIL_KEY")
        or "~/Downloads/LightsailDefaultKey-eu-west-1.pem"
    ).strip()
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Position:
    market: str
    outcome: str
    size: float
    avg_price: float
    cur_price: float
    unrealized_pnl: float
    condition_id: str = ""


@dataclass
class ClosedTrade:
    market: str
    outcome: str
    size: float
    avg_price: float
    payout: float
    pnl: float
    is_btc5: bool = False


@dataclass
class RecentTrade:
    timestamp: str
    market: str
    side: str
    size: float
    price: float
    outcome: str = ""


@dataclass
class VPSStatus:
    service_active: bool = False
    service_status: str = "unknown"
    last_20_entries: list[dict[str, Any]] = field(default_factory=list)
    skip_breakdown: dict[str, int] = field(default_factory=dict)
    total_rows: int = 0
    error: str = ""


@dataclass
class MonitorState:
    timestamp: str = ""
    total_deposits: float = DEFAULT_DEPOSIT
    wallet_value: float = 0.0
    free_collateral: float = 0.0
    position_value: float = 0.0
    true_pnl: float = 0.0
    true_pnl_pct: float = 0.0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_count: int = 0
    btc5_closed_count: int = 0
    btc5_win_rate: float = 0.0
    btc5_wins: int = 0
    btc5_losses: int = 0
    btc5_pnl: float = 0.0
    recent_trades: list[dict[str, Any]] = field(default_factory=list)
    vps: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Polymarket API helpers
# ---------------------------------------------------------------------------


async def fetch_json(client: Any, url: str, params: dict | None = None) -> Any:
    """GET JSON from Polymarket data API with error handling."""
    import httpx

    try:
        resp = await client.get(url, params=params or {}, timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        print(f"  [API ERROR] {url} -> {exc.response.status_code}")
        return []
    except Exception as exc:
        print(f"  [NETWORK ERROR] {url} -> {exc}")
        return []


async def fetch_positions(client: Any) -> list[dict]:
    url = f"{BASE_URL}/positions"
    return await fetch_json(client, url, {"user": PROXY_WALLET})


async def fetch_closed_positions(client: Any) -> list[dict]:
    url = f"{BASE_URL}/closed-positions"
    return await fetch_json(client, url, {"user": PROXY_WALLET})


async def fetch_recent_trades(client: Any, limit: int = 50) -> list[dict]:
    url = f"{BASE_URL}/trades"
    return await fetch_json(client, url, {"user": PROXY_WALLET, "limit": str(limit)})


# ---------------------------------------------------------------------------
# VPS SSH helpers
# ---------------------------------------------------------------------------


def _ssh_cmd(command: str) -> str:
    """Run a command on the VPS via SSH.  Returns stdout or raises."""
    args = [
        "ssh",
        "-i", VPS_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=8",
        "-o", "BatchMode=yes",
        VPS_HOST,
        command,
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=VPS_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ssh exit {result.returncode}")
    return result.stdout.strip()


def fetch_vps_status() -> VPSStatus:
    """Pull BTC5 DB stats and service status from VPS."""
    status = VPSStatus()

    if not Path(VPS_KEY).exists():
        status.error = f"SSH key not found: {VPS_KEY}"
        return status

    # Service status
    try:
        raw = _ssh_cmd("systemctl is-active btc-5min-maker.service 2>/dev/null || echo inactive")
        status.service_status = raw.strip()
        status.service_active = status.service_status == "active"
    except Exception as exc:
        status.error = f"SSH service check failed: {exc}"
        return status

    # Total rows
    try:
        raw = _ssh_cmd(f"sqlite3 {VPS_BTC5_DB} 'SELECT COUNT(*) FROM decisions;'")
        status.total_rows = int(raw.strip())
    except Exception:
        pass

    # Last 20 entries
    try:
        raw = _ssh_cmd(
            f"sqlite3 -json {VPS_BTC5_DB} "
            f"\"SELECT timestamp, market_slug, decision, skip_reason, edge, confidence "
            f"FROM decisions ORDER BY rowid DESC LIMIT 20;\""
        )
        if raw:
            status.last_20_entries = json.loads(raw)
    except Exception:
        # Fallback to CSV if -json not available
        try:
            raw = _ssh_cmd(
                f"sqlite3 -csv -header {VPS_BTC5_DB} "
                f"\"SELECT timestamp, market_slug, decision, skip_reason, edge, confidence "
                f"FROM decisions ORDER BY rowid DESC LIMIT 20;\""
            )
            if raw:
                lines = raw.strip().split("\n")
                if len(lines) > 1:
                    headers = [h.strip() for h in lines[0].split(",")]
                    for line in lines[1:]:
                        vals = [v.strip() for v in line.split(",")]
                        status.last_20_entries.append(dict(zip(headers, vals)))
        except Exception:
            pass

    # Skip reason breakdown
    try:
        raw = _ssh_cmd(
            f"sqlite3 -csv {VPS_BTC5_DB} "
            f"\"SELECT skip_reason, COUNT(*) FROM decisions "
            f"WHERE skip_reason IS NOT NULL AND skip_reason != '' "
            f"GROUP BY skip_reason ORDER BY COUNT(*) DESC;\""
        )
        if raw:
            for line in raw.strip().split("\n"):
                parts = line.split(",")
                if len(parts) == 2:
                    status.skip_breakdown[parts[0].strip('"')] = int(parts[1])
    except Exception:
        pass

    return status


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def parse_positions(raw: list[dict]) -> list[Position]:
    positions = []
    for p in raw:
        try:
            size = float(p.get("size", 0))
            avg_price = float(p.get("avgPrice", p.get("avg_price", 0)))
            cur_price = float(p.get("curPrice", p.get("cur_price", avg_price)))
            unrealized = size * (cur_price - avg_price)
            positions.append(Position(
                market=p.get("title", p.get("market", ""))[:60],
                outcome=p.get("outcome", p.get("side", "")),
                size=size,
                avg_price=avg_price,
                cur_price=cur_price,
                unrealized_pnl=round(unrealized, 4),
                condition_id=p.get("conditionId", p.get("condition_id", "")),
            ))
        except (ValueError, TypeError):
            continue
    return positions


def parse_closed(raw: list[dict]) -> list[ClosedTrade]:
    trades = []
    for c in raw:
        try:
            size = float(c.get("size", 0))
            avg_price = float(c.get("avgPrice", c.get("avg_price", 0)))
            payout = float(c.get("payout", 0))
            cost = size * avg_price
            pnl = payout - cost
            title = c.get("title", c.get("market", ""))
            is_btc5 = any(kw in title.lower() for kw in ["btc", "bitcoin", "5-min", "5 min"])
            trades.append(ClosedTrade(
                market=title[:60],
                outcome=c.get("outcome", c.get("side", "")),
                size=size,
                avg_price=avg_price,
                payout=payout,
                pnl=round(pnl, 4),
                is_btc5=is_btc5,
            ))
        except (ValueError, TypeError):
            continue
    return trades


def parse_recent_trades(raw: list[dict]) -> list[RecentTrade]:
    trades = []
    for t in raw:
        try:
            trades.append(RecentTrade(
                timestamp=t.get("timestamp", t.get("createdAt", ""))[:19],
                market=t.get("title", t.get("market", ""))[:50],
                side=t.get("side", t.get("outcome", "")),
                size=float(t.get("size", 0)),
                price=float(t.get("price", 0)),
                outcome=t.get("outcome", ""),
            ))
        except (ValueError, TypeError):
            continue
    return trades[:20]  # cap display at 20


def compute_state(
    positions: list[Position],
    closed: list[ClosedTrade],
    recent: list[RecentTrade],
    vps: VPSStatus,
    deposits: float,
) -> MonitorState:
    position_value = sum(p.size * p.cur_price for p in positions)
    # Free collateral is hard to get without auth; estimate from deposits - invested
    invested = sum(p.size * p.avg_price for p in positions)
    realized = sum(c.pnl for c in closed)
    free_est = deposits + realized - invested
    wallet_value = position_value + max(free_est, 0)

    btc5 = [c for c in closed if c.is_btc5]
    btc5_wins = sum(1 for c in btc5 if c.pnl > 0)
    btc5_losses = sum(1 for c in btc5 if c.pnl <= 0)
    btc5_total = btc5_wins + btc5_losses

    return MonitorState(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        total_deposits=deposits,
        wallet_value=round(wallet_value, 2),
        free_collateral=round(max(free_est, 0), 2),
        position_value=round(position_value, 2),
        true_pnl=round(wallet_value - deposits, 2),
        true_pnl_pct=round((wallet_value - deposits) / deposits * 100, 2) if deposits else 0.0,
        open_positions=[asdict(p) for p in positions],
        closed_count=len(closed),
        btc5_closed_count=btc5_total,
        btc5_win_rate=round(btc5_wins / btc5_total * 100, 1) if btc5_total else 0.0,
        btc5_wins=btc5_wins,
        btc5_losses=btc5_losses,
        btc5_pnl=round(sum(c.pnl for c in btc5), 2),
        recent_trades=[asdict(t) for t in recent],
        vps=asdict(vps),
    )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def _pnl_color(val: float) -> str:
    if val > 0:
        return GREEN
    elif val < 0:
        return RED
    return DIM


def _bar(width: int = 0) -> str:
    cols = shutil.get_terminal_size((100, 40)).columns
    return "─" * (width or cols)


def render_dashboard(state: MonitorState) -> str:
    lines: list[str] = []
    w = shutil.get_terminal_size((100, 40)).columns

    lines.append("")
    lines.append(f"{BOLD}{CYAN}  ELASTIFUND LOCAL MONITOR{RESET}  {DIM}{state.timestamp}{RESET}")
    lines.append(f"  {_bar(w - 4)}")

    # ── Fund Summary ──
    pc = _pnl_color(state.true_pnl)
    lines.append(f"  {BOLD}FUND SUMMARY{RESET}")
    lines.append(f"    Deposits:         ${state.total_deposits:>10,.2f}")
    lines.append(f"    Wallet Value:     ${state.wallet_value:>10,.2f}")
    lines.append(f"    Free Collateral:  ${state.free_collateral:>10,.2f}")
    lines.append(f"    Position Value:   ${state.position_value:>10,.2f}")
    lines.append(f"    {BOLD}True P&L:         {pc}${state.true_pnl:>+10,.2f}  ({state.true_pnl_pct:+.1f}%){RESET}")
    lines.append("")

    # ── BTC5 Stats ──
    lines.append(f"  {BOLD}BTC5 CLOSED TRADES{RESET}")
    wr_color = GREEN if state.btc5_win_rate > 52 else (YELLOW if state.btc5_win_rate > 50 else RED)
    lines.append(f"    Total: {state.btc5_closed_count}   "
                 f"W: {state.btc5_wins}  L: {state.btc5_losses}   "
                 f"WR: {wr_color}{state.btc5_win_rate:.1f}%{RESET}   "
                 f"PnL: {_pnl_color(state.btc5_pnl)}${state.btc5_pnl:+.2f}{RESET}")
    lines.append(f"    All Closed: {state.closed_count}")
    lines.append("")

    # ── Open Positions ──
    lines.append(f"  {BOLD}OPEN POSITIONS ({len(state.open_positions)}){RESET}")
    if state.open_positions:
        lines.append(f"    {'Market':<42} {'Side':<6} {'Size':>6} {'Avg':>6} {'Cur':>6} {'uPnL':>8}")
        lines.append(f"    {'─'*42} {'─'*6} {'─'*6} {'─'*6} {'─'*6} {'─'*8}")
        for p in state.open_positions:
            upnl = p["unrealized_pnl"]
            c = _pnl_color(upnl)
            lines.append(
                f"    {p['market']:<42} {p['outcome']:<6} "
                f"{p['size']:>6.1f} {p['avg_price']:>6.3f} {p['cur_price']:>6.3f} "
                f"{c}${upnl:>+7.2f}{RESET}"
            )
    else:
        lines.append(f"    {DIM}(none){RESET}")
    lines.append("")

    # ── Recent Trades ──
    lines.append(f"  {BOLD}RECENT TRADES (last {len(state.recent_trades)}){RESET}")
    if state.recent_trades:
        lines.append(f"    {'Time':<20} {'Market':<35} {'Side':<5} {'Size':>6} {'Price':>6}")
        lines.append(f"    {'─'*20} {'─'*35} {'─'*5} {'─'*6} {'─'*6}")
        for t in state.recent_trades[:15]:
            lines.append(
                f"    {t['timestamp']:<20} {t['market']:<35} "
                f"{t['side']:<5} {t['size']:>6.1f} {t['price']:>6.3f}"
            )
    else:
        lines.append(f"    {DIM}(none){RESET}")
    lines.append("")

    # ── VPS Status ──
    vps = state.vps
    lines.append(f"  {BOLD}VPS (BTC5 MAKER){RESET}")
    if vps.get("error"):
        lines.append(f"    {RED}Error: {vps['error']}{RESET}")
    else:
        svc_color = GREEN if vps.get("service_active") else RED
        lines.append(f"    Service: {svc_color}{vps.get('service_status', 'unknown')}{RESET}   "
                     f"DB rows: {vps.get('total_rows', '?')}")

        skip = vps.get("skip_breakdown", {})
        if skip:
            lines.append(f"    {BOLD}Skip Reasons:{RESET}")
            total_skips = sum(skip.values())
            for reason, count in sorted(skip.items(), key=lambda x: -x[1]):
                pct = count / total_skips * 100 if total_skips else 0
                lines.append(f"      {reason:<35} {count:>5}  ({pct:>5.1f}%)")

        entries = vps.get("last_20_entries", [])
        if entries:
            lines.append(f"    {BOLD}Last {len(entries)} DB entries:{RESET}")
            for e in entries[:10]:
                ts = str(e.get("timestamp", ""))[:19]
                slug = str(e.get("market_slug", ""))[:30]
                decision = e.get("decision", "")
                skip_r = e.get("skip_reason", "")
                label = skip_r if skip_r else decision
                color = GREEN if decision == "trade" else DIM
                lines.append(f"      {ts}  {slug:<30}  {color}{label}{RESET}")

    lines.append("")
    lines.append(f"  {DIM}State saved to {STATE_FILE.relative_to(PROJECT_ROOT)}{RESET}")
    lines.append(f"  {_bar(w - 4)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_state(state: MonitorState) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(asdict(state), f, indent=2, default=str)
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_cycle(deposits: float, skip_ssh: bool) -> MonitorState:
    import httpx

    async with httpx.AsyncClient() as client:
        raw_positions, raw_closed, raw_trades = await asyncio.gather(
            fetch_positions(client),
            fetch_closed_positions(client),
            fetch_recent_trades(client),
        )

    positions = parse_positions(raw_positions)
    closed = parse_closed(raw_closed)
    recent = parse_recent_trades(raw_trades)

    if skip_ssh:
        vps = VPSStatus(error="SSH disabled (--no-ssh)")
    else:
        # Run SSH in thread to avoid blocking event loop
        loop = asyncio.get_running_loop()
        vps = await loop.run_in_executor(None, fetch_vps_status)

    state = compute_state(positions, closed, recent, vps, deposits)
    save_state(state)
    return state


async def main_loop(args: argparse.Namespace) -> int:
    deposits = args.deposits
    interval = args.interval
    skip_ssh = args.no_ssh

    # Handle SIGINT gracefully
    stop = asyncio.Event()

    def _sigint(*_: Any) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    while True:
        try:
            state = await run_cycle(deposits, skip_ssh)
        except Exception as exc:
            print(f"\n{RED}  Cycle error: {exc}{RESET}\n")
            if args.once:
                return 1
            await asyncio.sleep(interval)
            continue

        # Clear screen and render
        if not args.once:
            os.system("clear")
        print(render_dashboard(state))

        if args.once:
            return 0

        # Wait for interval or stop signal
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            print(f"\n{DIM}  Monitor stopped.{RESET}\n")
            return 0
        except asyncio.TimeoutError:
            pass  # next cycle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Elastifund local monitoring dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single snapshot and exit",
    )
    parser.add_argument(
        "--no-ssh", action="store_true",
        help="Skip VPS SSH queries",
    )
    parser.add_argument(
        "--deposits", type=float, default=DEFAULT_DEPOSIT,
        help=f"Total deposits in USD (default: ${DEFAULT_DEPOSIT})",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Refresh interval in seconds (default: 60)",
    )
    args = parser.parse_args()
    return asyncio.run(main_loop(args))


if __name__ == "__main__":
    sys.exit(main())
