#!/usr/bin/env python3
"""
Canonical Truth Writer

Reconciles Polymarket wallet API truth with local runtime artifacts to produce
a single authoritative operator packet. Resolves the mode/exposure/posture
question without requiring SSH to the VPS.

Usage:
    python3 scripts/canonical_truth_writer.py              # write canonical packet
    python3 scripts/canonical_truth_writer.py --check-only # print without writing
    python3 scripts/canonical_truth_writer.py --wallet 0x...  # override wallet

Outputs:
    reports/canonical_operator_truth.json   — authoritative operator packet
    reports/wallet_truth_snapshot_latest.json — typed wallet truth contract
    data/finance_imports/account_polymarket.csv  — refreshed balance row

The March 22 wallet export and all subsequent exports are automatically
discovered from data/finance_imports/ and included in the packet as the
latest_csv_import field, making this the canonical truth workflow rather
than a manual after-the-fact check.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.proof_types import build_wallet_truth_snapshot
from scripts.report_envelope import write_report

POLYMARKET_DATA_API = "https://data-api.polymarket.com"
INITIAL_DEPOSIT_USD = 247.51  # Canonical from CLAUDE.md; override via --initial-deposit

# Output paths
CANONICAL_TRUTH_PATH = REPO_ROOT / "reports" / "canonical_operator_truth.json"
WALLET_TRUTH_SNAPSHOT_PATH = REPO_ROOT / "reports" / "wallet_truth_snapshot_latest.json"
ACCOUNT_CSV_PATH = REPO_ROOT / "data" / "finance_imports" / "account_polymarket.csv"
RUNTIME_TRUTH_PATH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
FINANCE_PATH = REPO_ROOT / "reports" / "finance" / "latest.json"
BTC5_STAGE_ENV_PATH = REPO_ROOT / "state" / "btc5_capital_stage.env"
FINANCE_IMPORTS_DIR = REPO_ROOT / "data" / "finance_imports"


# ---------------------------------------------------------------------------
# Wallet address resolution
# ---------------------------------------------------------------------------


def _get_proxy_wallet() -> str:
    """Read proxy wallet from .env; fall back to authoritative hardcoded value."""
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("POLY_DATA_API_ADDRESS="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("0xYour"):
                    return val
    # Authoritative proxy wallet documented in CLAUDE.md and wallet reconciliation
    return "0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5"


# ---------------------------------------------------------------------------
# Polymarket data API helpers (stdlib only — no httpx/requests dependency)
# ---------------------------------------------------------------------------


def _fetch_json(url: str, timeout: int = 20) -> Any:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "elastifund-truth/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"_fetch_error": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"_fetch_error": str(exc)}


def _fetch_paginated(base_url: str, params: dict[str, str], limit: int = 200) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    for _ in range(20):
        p = dict(params)
        p["limit"] = str(limit)
        p["offset"] = str(offset)
        url = base_url + "?" + urllib.parse.urlencode(p)
        data = _fetch_json(url)
        if isinstance(data, dict) and "_fetch_error" in data:
            break
        if not isinstance(data, list) or not data:
            break
        rows.extend(r for r in data if isinstance(r, dict))
        if len(data) < limit:
            break
        offset += len(data)
    return rows


def fetch_open_positions(wallet: str) -> tuple[list[dict], str | None]:
    """Returns (positions, error_str_or_None)."""
    rows = _fetch_paginated(
        f"{POLYMARKET_DATA_API}/positions",
        {"trader": wallet},
    )
    if not rows:
        # Try alternate param name
        rows = _fetch_paginated(
            f"{POLYMARKET_DATA_API}/positions",
            {"user": wallet},
        )
    return rows, None


def fetch_closed_positions(wallet: str) -> tuple[list[dict], str | None]:
    rows = _fetch_paginated(
        f"{POLYMARKET_DATA_API}/closed-positions",
        {"trader": wallet},
    )
    if not rows:
        rows = _fetch_paginated(
            f"{POLYMARKET_DATA_API}/closed-positions",
            {"user": wallet},
        )
    return rows, None


# ---------------------------------------------------------------------------
# P&L computation
# ---------------------------------------------------------------------------


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_open_pnl(positions: list[dict]) -> tuple[float, float]:
    """Return (cost_basis_usd, current_mark_usd) across all open positions."""
    cost = 0.0
    mark = 0.0
    for pos in positions:
        size = _safe_float(pos.get("size") or pos.get("shares"))
        avg_price = _safe_float(
            pos.get("avgPrice") or pos.get("avg_price") or pos.get("averagePrice")
        )
        cur_price = _safe_float(
            pos.get("curPrice")
            or pos.get("cur_price")
            or pos.get("price")
            or pos.get("currentPrice")
        )
        cost += size * avg_price
        mark += size * cur_price
    return round(cost, 4), round(mark, 4)


def compute_closed_pnl(closed: list[dict]) -> float:
    """Sum realized cashflow across all closed positions."""
    total = 0.0
    for pos in closed:
        total += _safe_float(
            pos.get("cashflow")
            or pos.get("pnl")
            or pos.get("profit")
            or pos.get("netCashflow")
            or pos.get("realizedPnl")
        )
    return round(total, 4)


# ---------------------------------------------------------------------------
# Local artifact readers
# ---------------------------------------------------------------------------


def _load_json_file(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _runtime_truth_age_seconds(rt: dict) -> float | None:
    ts = (
        rt.get("checked_at")
        or rt.get("generated_at")
        or rt.get("written_at")
        or rt.get("timestamp")
    )
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
    except Exception:
        return None


def _read_btc5_deploy_mode() -> str:
    if BTC5_STAGE_ENV_PATH.exists():
        for line in BTC5_STAGE_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("BTC5_DEPLOY_MODE="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Also check environment
    return os.environ.get("BTC5_DEPLOY_MODE", "")


def _latest_csv_export() -> str | None:
    """Find the most recently-named Polymarket wallet export CSV."""
    candidates = []
    for p in FINANCE_IMPORTS_DIR.glob("*.csv"):
        name = p.name.lower()
        if "polymarket" in name or "history" in name:
            candidates.append(p.name)
    # Also check repo root for dated exports
    for p in REPO_ROOT.glob("Polymarket-History-*.csv"):
        candidates.append(p.name)
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _classify_control_posture(
    btc5_deploy_mode: str,
    agent_run_mode: str,
    execution_mode: str,
    finance_verdict: str,
    allow_order_submission: bool | None,
) -> str:
    live_modes = {"live", "live_stage1", "stage1_live"}
    shadow_modes = {"shadow", "paper", "probe", "shadow_probe"}

    if allow_order_submission is False:
        return "blocked"
    if finance_verdict in {"blocked", "expansion_blocked"}:
        return "blocked"
    if btc5_deploy_mode.lower() in shadow_modes or str(execution_mode).lower() in shadow_modes:
        return "shadow"
    if btc5_deploy_mode.lower() in live_modes:
        return "live"
    if str(agent_run_mode).lower() == "live" and str(execution_mode).lower() in {
        "live",
        "micro_live",
    }:
        return "live"
    return "shadow"


def _extract_remote_wallet_counts(runtime_truth: dict[str, Any]) -> dict[str, Any]:
    accounting = runtime_truth.get("accounting_reconciliation")
    if isinstance(accounting, dict):
        remote_wallet = accounting.get("remote_wallet_counts")
        if isinstance(remote_wallet, dict):
            return remote_wallet
    wallet_block = runtime_truth.get("polymarket_wallet")
    if isinstance(wallet_block, dict):
        return wallet_block
    return {}


def _build_truth_mismatches(
    runtime_truth: dict[str, Any],
    *,
    positions: list[dict],
    closed: list[dict],
) -> list[str]:
    mismatches: list[str] = []
    trade_proof = runtime_truth.get("trade_proof") if isinstance(runtime_truth.get("trade_proof"), dict) else {}
    proof_status = str(trade_proof.get("proof_status") or "").strip().lower()
    latest_filled_trade_at = str(trade_proof.get("latest_filled_trade_at") or "").strip()

    if latest_filled_trade_at and proof_status == "no_fill_yet":
        mismatches.append("trade_proof_latest_fill_conflicts_with_no_fill_yet")

    reported_open_positions = runtime_truth.get("open_positions_count")
    if reported_open_positions is not None:
        try:
            if int(reported_open_positions) != len(positions):
                mismatches.append("runtime_truth_open_positions_mismatch")
        except (TypeError, ValueError):
            mismatches.append("runtime_truth_open_positions_unparseable")

    reported_closed_positions = runtime_truth.get("closed_positions_count")
    if reported_closed_positions is not None:
        try:
            if int(reported_closed_positions) != len(closed):
                mismatches.append("runtime_truth_closed_positions_mismatch")
        except (TypeError, ValueError):
            mismatches.append("runtime_truth_closed_positions_unparseable")

    return mismatches


# ---------------------------------------------------------------------------
# Main packet builder
# ---------------------------------------------------------------------------


def build_canonical_truth(
    wallet: str,
    positions: list[dict],
    closed: list[dict],
    runtime_truth: dict,
    finance_gate: dict,
    initial_deposit: float,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    open_cost, open_mark = compute_open_pnl(positions)
    closed_pnl = compute_closed_pnl(closed)
    unrealized_pnl = round(open_mark - open_cost, 4)
    reconstructed_total = round(initial_deposit + closed_pnl + unrealized_pnl, 4)
    remote_wallet = _extract_remote_wallet_counts(runtime_truth)
    remote_total_value = _safe_float(remote_wallet.get("total_wallet_value_usd"))
    remote_free_collateral = _safe_float(remote_wallet.get("free_collateral_usd"))
    estimated_total = round(remote_total_value or reconstructed_total, 4)
    available_cash = round(remote_free_collateral or open_mark, 4)

    agent_run_mode = str(
        runtime_truth.get("agent_run_mode") or runtime_truth.get("mode") or "unknown"
    )
    execution_mode = str(runtime_truth.get("execution_mode") or "unknown")
    btc5_deploy_mode = _read_btc5_deploy_mode() or str(
        runtime_truth.get("btc5_deploy_mode", "unknown")
    )
    finance_btc5 = finance_gate.get("btc5_baseline") or finance_gate.get("btc5", {}) or {}
    finance_verdict = str(finance_btc5.get("verdict", "unknown"))
    trade_proof = runtime_truth.get("trade_proof") if isinstance(runtime_truth.get("trade_proof"), dict) else {}
    allow_order_submission = runtime_truth.get("allow_order_submission")
    if isinstance(allow_order_submission, str):
        allow_order_submission = allow_order_submission.strip().lower() in {"1", "true", "yes", "on"}

    posture = _classify_control_posture(
        btc5_deploy_mode,
        agent_run_mode,
        execution_mode,
        finance_verdict,
        allow_order_submission,
    )

    rt_age = _runtime_truth_age_seconds(runtime_truth)
    truth_mismatches = _build_truth_mismatches(runtime_truth, positions=positions, closed=closed)
    blockers = list(
        runtime_truth.get("blockers")
        or runtime_truth.get("hard_blockers")
        or []
    )
    if rt_age is None:
        blockers.append("runtime_truth_age_unavailable")
    elif rt_age > 600:
        blockers.append("runtime_truth_stale")
    if posture == "blocked":
        blockers.append("control_posture_blocked")
    if finance_verdict in {"blocked", "expansion_blocked"}:
        blockers.append("finance_gate_blocked")
    if truth_mismatches:
        blockers.extend(truth_mismatches)

    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item).strip()))
    if blockers:
        status = "blocked"
    elif rt_age is not None and rt_age > 600:
        status = "stale"
    else:
        status = "fresh"

    truth_status = "green"
    if blockers:
        truth_status = "blocked"
    elif rt_age is None or rt_age > 600:
        truth_status = "degraded"

    return {
        "schema": "canonical_operator_truth_v1",
        "checked_at": now,
        "wallet_address": wallet,
        # ── Capital ──────────────────────────────────────────────────────────
        "initial_deposit_usd": initial_deposit,
        "open_cost_basis_usd": open_cost,
        "open_mark_usd": open_mark,
        "unrealized_pnl_usd": unrealized_pnl,
        "closed_pnl_usd": closed_pnl,
        "available_cash_usd": available_cash,
        "estimated_total_value_usd": estimated_total,
        "estimated_total_value_method": "remote_wallet_counts" if remote_total_value > 0 else "pnl_reconstruction",
        "remote_wallet_total_value_usd": round(remote_total_value, 4),
        "remote_wallet_free_collateral_usd": round(remote_free_collateral, 4),
        # ── Position counts ───────────────────────────────────────────────────
        "open_positions_count": len(positions),
        "closed_positions_count": len(closed),
        # ── Mode & posture ────────────────────────────────────────────────────
        "btc5_deploy_mode": btc5_deploy_mode,
        "agent_run_mode": agent_run_mode,
        "execution_mode": execution_mode,
        "control_posture": posture,
        "capital_live": posture == "live" and truth_status == "green",
        "truth_status": truth_status,
        "truth_mismatches": truth_mismatches,
        "trade_proof": {
            "proof_status": trade_proof.get("proof_status"),
            "fill_confirmed": bool(trade_proof.get("fill_confirmed")),
            "latest_filled_trade_at": trade_proof.get("latest_filled_trade_at"),
            "source_of_truth": trade_proof.get("source_of_truth"),
        },
        # ── Finance gate ──────────────────────────────────────────────────────
        "finance_gate_btc5_verdict": finance_verdict,
        # ── Evidence quality ──────────────────────────────────────────────────
        "runtime_truth_age_seconds": rt_age,
        "latest_csv_export": _latest_csv_export(),
        # ── Blockers ──────────────────────────────────────────────────────────
        "blockers": blockers,
        "status": status,
    }


# ---------------------------------------------------------------------------
# CSV update
# ---------------------------------------------------------------------------


def update_account_csv(truth: dict) -> None:
    ACCOUNT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "account_key",
        "name",
        "account_type",
        "institution",
        "currency",
        "balance_usd",
        "available_cash_usd",
        "source",
    ]
    row = {
        "account_key": "polymarket",
        "name": "Polymarket Runtime",
        "account_type": "trading",
        "institution": "Polymarket",
        "currency": "USD",
        "balance_usd": truth["estimated_total_value_usd"],
        "available_cash_usd": truth["available_cash_usd"],
        "source": f"canonical_truth_{truth.get('estimated_total_value_method', 'api')}",
    }
    with ACCOUNT_CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def build_wallet_truth_snapshot_payload(truth: dict[str, Any]) -> dict[str, Any]:
    source_of_truth = {
        "runtime_truth": "reports/runtime_truth_latest.json",
        "canonical_truth": "reports/canonical_operator_truth.json",
        "finance_gate": "reports/finance/latest.json",
        "positions_api": "https://data-api.polymarket.com/positions",
    }
    metadata = {
        "btc5_deploy_mode": truth.get("btc5_deploy_mode"),
        "execution_mode": truth.get("execution_mode"),
        "agent_run_mode": truth.get("agent_run_mode"),
        "estimated_total_value_method": truth.get("estimated_total_value_method"),
        "remote_wallet_total_value_usd": truth.get("remote_wallet_total_value_usd"),
        "remote_wallet_free_collateral_usd": truth.get("remote_wallet_free_collateral_usd"),
        "latest_csv_export": truth.get("latest_csv_export"),
        "runtime_truth_age_seconds": truth.get("runtime_truth_age_seconds"),
    }
    snapshot = build_wallet_truth_snapshot(
        generated_at=str(truth.get("checked_at") or datetime.now(timezone.utc).isoformat()),
        wallet_address=str(truth.get("wallet_address") or ""),
        control_posture=str(truth.get("control_posture") or "blocked"),
        truth_status=str(truth.get("truth_status") or "blocked"),
        open_positions_count=int(truth.get("open_positions_count") or 0),
        closed_positions_count=int(truth.get("closed_positions_count") or 0),
        estimated_total_value_usd=float(truth.get("estimated_total_value_usd") or 0.0),
        available_cash_usd=float(truth.get("available_cash_usd") or 0.0),
        capital_live=bool(truth.get("capital_live")),
        source_of_truth=source_of_truth,
        blockers=list(truth.get("blockers") or []),
        mismatches=list(truth.get("truth_mismatches") or []),
        metadata=metadata,
    )
    return snapshot.to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Print truth packet to stdout without writing any files",
    )
    parser.add_argument(
        "--wallet",
        default=None,
        help="Override proxy wallet address (default: read from .env POLY_DATA_API_ADDRESS)",
    )
    parser.add_argument(
        "--initial-deposit",
        type=float,
        default=INITIAL_DEPOSIT_USD,
        help=f"Initial deposit in USD (default: {INITIAL_DEPOSIT_USD})",
    )
    return parser.parse_args(argv)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    wallet = args.wallet or _get_proxy_wallet()

    print(f"[{_ts()}] [canonical-truth] wallet={wallet}")

    print(f"[{_ts()}] [canonical-truth] fetching open positions…")
    positions, _ = fetch_open_positions(wallet)

    print(f"[{_ts()}] [canonical-truth] fetching closed positions…")
    closed, _ = fetch_closed_positions(wallet)

    print(
        f"[{_ts()}] [canonical-truth] api_open={len(positions)} api_closed={len(closed)}"
    )

    runtime_truth = _load_json_file(RUNTIME_TRUTH_PATH)
    finance_gate = _load_json_file(FINANCE_PATH)

    rt_age = _runtime_truth_age_seconds(runtime_truth)
    if rt_age is not None:
        print(f"[{_ts()}] [canonical-truth] runtime_truth age={rt_age:.0f}s")

    truth = build_canonical_truth(
        wallet, positions, closed, runtime_truth, finance_gate, args.initial_deposit
    )

    print(
        f"[{_ts()}] [canonical-truth] posture={truth['control_posture']}"
        f" btc5_mode={truth['btc5_deploy_mode']}"
        f" capital_live={truth['capital_live']}"
    )
    print(
        f"[{_ts()}] [canonical-truth]"
        f" closed_pnl={truth['closed_pnl_usd']:+.2f}"
        f" unrealized={truth['unrealized_pnl_usd']:+.2f}"
        f" total={truth['estimated_total_value_usd']:.2f}"
        f" (deposit={truth['initial_deposit_usd']:.2f})"
    )
    print(
        f"[{_ts()}] [canonical-truth]"
        f" blockers={len(truth['blockers'])}"
        f" csv={truth['latest_csv_export']}"
    )

    if args.check_only:
        print(json.dumps(truth, indent=2))
        return 0

    write_report(
        CANONICAL_TRUTH_PATH,
        artifact="canonical_operator_truth",
        payload=truth,
        status=truth["status"],
        source_of_truth=(
            "reports/runtime_truth_latest.json; reports/finance/latest.json; "
            "data/finance_imports/*; Polymarket data-api"
        ),
        freshness_sla_seconds=600,
        blockers=truth["blockers"],
        summary=(
            f"control_posture={truth['control_posture']} "
            f"open_positions={truth['open_positions_count']} "
            f"closed_pnl_usd={truth['closed_pnl_usd']:+.2f}"
        ),
    )
    print(f"[{_ts()}] [canonical-truth] wrote {CANONICAL_TRUTH_PATH.relative_to(REPO_ROOT)}")

    write_report(
        REPO_ROOT / "reports" / "wallet_live_snapshot_latest.json",
        artifact="wallet_live_snapshot",
        payload={
            "wallet_address": wallet,
            "open_position_count": truth["open_positions_count"],
            "closed_position_count": truth["closed_positions_count"],
            "open_cost_basis_usd": truth["open_cost_basis_usd"],
            "open_mark_usd": truth["open_mark_usd"],
            "unrealized_pnl_usd": truth["unrealized_pnl_usd"],
            "closed_pnl_usd": truth["closed_pnl_usd"],
            "estimated_total_value_usd": truth["estimated_total_value_usd"],
            "btc5_deploy_mode": truth["btc5_deploy_mode"],
            "control_posture": truth["control_posture"],
            "capital_live": truth["capital_live"],
            "runtime_truth_age_seconds": truth["runtime_truth_age_seconds"],
            "latest_csv_export": truth["latest_csv_export"],
            "blockers": truth["blockers"],
        },
        status="blocked"
        if truth["blockers"]
        else ("stale" if (rt_age is not None and rt_age > 3600) else "fresh"),
        source_of_truth=(
            "reports/runtime_truth_latest.json; reports/finance/latest.json; "
            "data/finance_imports/*; Polymarket data-api"
        ),
        freshness_sla_seconds=3600,
        blockers=truth["blockers"],
        summary=(
            f"control_posture={truth['control_posture']} "
            f"open_positions={truth['open_positions_count']} "
            f"closed_pnl_usd={truth['closed_pnl_usd']:+.2f}"
        ),
    )
    wallet_truth_snapshot_payload = build_wallet_truth_snapshot_payload(truth)
    write_report(
        WALLET_TRUTH_SNAPSHOT_PATH,
        artifact="wallet_truth_snapshot",
        payload=wallet_truth_snapshot_payload,
        status="blocked"
        if truth["blockers"]
        else ("stale" if (rt_age is not None and rt_age > 3600) else "fresh"),
        source_of_truth=(
            "reports/runtime_truth_latest.json; reports/canonical_operator_truth.json; "
            "reports/finance/latest.json; Polymarket data-api"
        ),
        freshness_sla_seconds=3600,
        blockers=truth["blockers"],
        summary=(
            f"truth_status={truth['truth_status']} "
            f"control_posture={truth['control_posture']} "
            f"capital_live={truth['capital_live']}"
        ),
    )

    update_account_csv(truth)
    print(f"[{_ts()}] [canonical-truth] updated {ACCOUNT_CSV_PATH.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
