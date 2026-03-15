#!/usr/bin/env python3
"""Continuous wallet polling loop that keeps the local trade ledger in sync with
the live Polymarket wallet.  Wallet is authoritative — discrepancies are
auto-patched and logged."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Lazy imports so the module can be imported for testing without heavy deps
# ---------------------------------------------------------------------------

_reconciler_module = None


def _get_reconciler_module():
    global _reconciler_module
    if _reconciler_module is None:
        from bot import wallet_reconciliation as _mod
        _reconciler_module = _mod
    return _reconciler_module


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL_SECONDS = int(os.environ.get("WALLET_POLLER_INTERVAL_SECONDS", "60"))
DEFAULT_DB_PATH = Path(os.environ.get("JJ_DB_FILE", "data/jj_trades.db"))
DEFAULT_HEARTBEAT_PATH = Path(os.environ.get("WALLET_POLLER_HEARTBEAT_FILE", "data/wallet_poller_heartbeat.json"))
DEFAULT_SNAPSHOT_DIR = Path(os.environ.get("WALLET_POLLER_SNAPSHOT_DIR", "data/wallet_snapshots"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    value = dt or _utc_now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


logger = logging.getLogger("wallet_poller")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalletSnapshot:
    timestamp: str
    user_address: str
    open_position_count: int
    closed_position_count: int
    reconciliation_status: str
    recommendation: str
    matched_local_open: int
    matched_local_closed: int
    drift_open_delta: int
    drift_closed_delta: int
    phantom_count: int
    fixes_applied: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass
class PollerState:
    """Mutable state carried between poll cycles."""
    cycles_completed: int = 0
    consecutive_errors: int = 0
    last_snapshot: WalletSnapshot | None = None
    started_at: str = ""


# ---------------------------------------------------------------------------
# Heartbeat persistence
# ---------------------------------------------------------------------------


def _write_heartbeat(
    path: Path,
    *,
    state: PollerState,
    snapshot: WalletSnapshot | None,
    status: str = "running",
) -> None:
    payload: dict[str, Any] = {
        "service": "wallet-poller",
        "status": status,
        "started_at": state.started_at,
        "last_updated_at": _iso(),
        "cycles_completed": state.cycles_completed,
        "consecutive_errors": state.consecutive_errors,
        "poll_interval_seconds": DEFAULT_POLL_INTERVAL_SECONDS,
    }
    if snapshot is not None:
        payload["last_snapshot"] = asdict(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_snapshot(snapshot_dir: Path, snapshot: WalletSnapshot) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    ts = snapshot.timestamp.replace(":", "-").replace("+", "").replace("Z", "")
    path = snapshot_dir / f"snapshot_{ts}.json"
    path.write_text(json.dumps(asdict(snapshot), indent=2, sort_keys=True) + "\n")
    # Also write latest
    latest = snapshot_dir / "latest.json"
    latest.write_text(json.dumps(asdict(snapshot), indent=2, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------------------
# Core poll cycle
# ---------------------------------------------------------------------------


def run_single_poll(
    *,
    user_address: str,
    db_path: Path = DEFAULT_DB_PATH,
    apply_fixes: bool = True,
    purge_phantoms: bool = False,
    reconciler=None,
) -> WalletSnapshot:
    """Execute one poll cycle: fetch wallet state, reconcile, return snapshot."""
    mod = _get_reconciler_module()
    rec = reconciler or mod.PolymarketWalletReconciler()
    try:
        now_iso = _iso()
        summary = rec.reconcile_to_sqlite(
            user_address=user_address,
            db_path=db_path,
            apply_local_fixes=apply_fixes,
            purge_phantom_open_trades=purge_phantoms,
        )
        snapshot = WalletSnapshot(
            timestamp=now_iso,
            user_address=user_address,
            open_position_count=summary.open_positions_count,
            closed_position_count=summary.closed_positions_count,
            reconciliation_status=summary.status,
            recommendation=summary.recommendation,
            matched_local_open=summary.matched_local_open_trades,
            matched_local_closed=summary.matched_local_closed_trades,
            drift_open_delta=summary.unmatched_open_positions.get("delta_remote_minus_local", 0),
            drift_closed_delta=summary.unmatched_closed_positions.get("delta_remote_minus_local", 0),
            phantom_count=len(summary.phantom_local_open_trade_ids),
            fixes_applied=dict(summary.local_fixes),
        )
        if snapshot.reconciliation_status == "reconciled":
            logger.info(
                "poll_ok: open=%d closed=%d status=%s",
                snapshot.open_position_count,
                snapshot.closed_position_count,
                snapshot.reconciliation_status,
            )
        else:
            logger.warning(
                "poll_drift: open_delta=%+d closed_delta=%+d phantoms=%d rec=%s fixes=%s",
                snapshot.drift_open_delta,
                snapshot.drift_closed_delta,
                snapshot.phantom_count,
                snapshot.recommendation,
                json.dumps(snapshot.fixes_applied),
            )
        return snapshot
    except Exception as exc:
        logger.error("poll_error: %s", exc, exc_info=True)
        return WalletSnapshot(
            timestamp=_iso(),
            user_address=user_address,
            open_position_count=0,
            closed_position_count=0,
            reconciliation_status="error",
            recommendation="retry",
            matched_local_open=0,
            matched_local_closed=0,
            drift_open_delta=0,
            drift_closed_delta=0,
            phantom_count=0,
            error=str(exc)[:500],
        )
    finally:
        if reconciler is None:
            rec.close()


# ---------------------------------------------------------------------------
# Continuous loop
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("shutdown_signal_received: signal=%d", signum)


def run_continuous(
    *,
    user_address: str,
    db_path: Path = DEFAULT_DB_PATH,
    heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    apply_fixes: bool = True,
    purge_phantoms: bool = False,
    max_cycles: int = 0,
) -> PollerState:
    """Run the polling loop until shutdown signal or max_cycles reached."""
    global _shutdown_requested
    _shutdown_requested = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    state = PollerState(started_at=_iso())
    interval = max(10, int(poll_interval_seconds))

    logger.info(
        "wallet_poller_started: user=%s interval=%ds db=%s",
        user_address,
        interval,
        db_path,
    )
    _write_heartbeat(heartbeat_path, state=state, snapshot=None, status="starting")

    while not _shutdown_requested:
        if 0 < max_cycles <= state.cycles_completed:
            logger.info("max_cycles_reached: %d", max_cycles)
            break

        snapshot = run_single_poll(
            user_address=user_address,
            db_path=db_path,
            apply_fixes=apply_fixes,
            purge_phantoms=purge_phantoms,
        )
        state.last_snapshot = snapshot
        state.cycles_completed += 1

        if snapshot.error:
            state.consecutive_errors += 1
        else:
            state.consecutive_errors = 0

        _write_heartbeat(heartbeat_path, state=state, snapshot=snapshot)
        _write_snapshot(snapshot_dir, snapshot)

        if state.consecutive_errors >= 10:
            logger.error(
                "too_many_consecutive_errors: %d — backing off to 5x interval",
                state.consecutive_errors,
            )
            _sleep_interruptible(interval * 5)
        else:
            _sleep_interruptible(interval)

    _write_heartbeat(heartbeat_path, state=state, snapshot=state.last_snapshot, status="stopped")
    logger.info("wallet_poller_stopped: cycles=%d", state.cycles_completed)
    return state


def _sleep_interruptible(seconds: int) -> None:
    """Sleep in 1-second increments so SIGTERM is handled promptly."""
    for _ in range(max(1, seconds)):
        if _shutdown_requested:
            return
        time.sleep(1)


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


def show_status(heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH) -> dict[str, Any]:
    if not heartbeat_path.exists():
        return {"status": "not_running", "heartbeat_path": str(heartbeat_path)}
    try:
        payload = json.loads(heartbeat_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"status": "heartbeat_unreadable", "heartbeat_path": str(heartbeat_path)}
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_user_address() -> str:
    addr = os.environ.get("POLY_SAFE_ADDRESS") or os.environ.get("POLYMARKET_FUNDER") or ""
    if not addr or addr.startswith("0xYour"):
        raise SystemExit(
            "POLY_SAFE_ADDRESS or POLYMARKET_FUNDER must be set in .env"
        )
    return addr.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live wallet polling loop — keeps local ledger in sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Single poll cycle then exit")
    group.add_argument("--continuous", action="store_true", help="Run continuous polling loop")
    group.add_argument("--status", action="store_true", help="Show cached poller status")

    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--heartbeat-file", default=str(DEFAULT_HEARTBEAT_PATH))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--apply-fixes", action="store_true", default=True)
    parser.add_argument("--no-apply-fixes", dest="apply_fixes", action="store_false")
    parser.add_argument("--purge-phantoms", action="store_true", default=False)
    parser.add_argument("--max-cycles", type=int, default=0, help="Stop after N cycles (0=unlimited)")
    parser.add_argument("--live", action="store_true", help="Confirm live mode (no-op, for consistency)")
    args = parser.parse_args()

    # Set up logging
    try:
        from bot.log_config import setup_logging
        setup_logging(service_name="wallet-poller")
    except ImportError:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    if args.status:
        result = show_status(Path(args.heartbeat_file))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    user_address = _resolve_user_address()
    db_path = Path(args.db_path)

    if args.once:
        snapshot = run_single_poll(
            user_address=user_address,
            db_path=db_path,
            apply_fixes=args.apply_fixes,
            purge_phantoms=args.purge_phantoms,
        )
        print(json.dumps(asdict(snapshot), indent=2, sort_keys=True))
        return 0 if not snapshot.error else 1

    # --continuous
    run_continuous(
        user_address=user_address,
        db_path=db_path,
        heartbeat_path=Path(args.heartbeat_file),
        snapshot_dir=Path(args.snapshot_dir),
        poll_interval_seconds=args.interval,
        apply_fixes=args.apply_fixes,
        purge_phantoms=args.purge_phantoms,
        max_cycles=args.max_cycles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
