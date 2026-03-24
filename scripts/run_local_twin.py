#!/usr/bin/env python3
"""
Local Twin Control Plane

Orchestrates local lanes against live APIs. Venue execution stays paper/shadow
unless the operator explicitly enables local live submission for a venue.
Mirrors the Lightsail artifact paths so the same supervisor and foundry code can
consume outputs from either host.

Usage:
    python3 scripts/run_local_twin.py                     # all lanes, once
    python3 scripts/run_local_twin.py --lane btc5         # BTC5 improvement search only
    python3 scripts/run_local_twin.py --lane alpaca       # Alpaca crypto lane
    python3 scripts/run_local_twin.py --lane kalshi       # Kalshi execution lane
    python3 scripts/run_local_twin.py --lane polymarket   # BTC5 / Polymarket execution lane
    python3 scripts/run_local_twin.py --lane weather      # weather shadow lane only
    python3 scripts/run_local_twin.py --lane strike_desk  # strike desk shadow lane only
    python3 scripts/run_local_twin.py --lane monitor      # fund health snapshot only
    python3 scripts/run_local_twin.py --lane truth        # canonical truth reconciliation only
    python3 scripts/run_local_twin.py --lane structural_profit  # structural alpha cycle
    python3 scripts/run_local_twin.py --daemon            # continuous loop (alpaca+kernel+weather+truth+strike desk)
    python3 scripts/run_local_twin.py --daemon --lane btc5   # daemon on one lane
    python3 scripts/run_local_twin.py --daemon --daemon-profile heavy_local
                                                       # continuous heavy local research/shadow loop
    python3 scripts/run_local_twin.py --local-live-venues alpaca,kalshi,polymarket
    python3 scripts/run_local_twin.py --no-ssh            # skip VPS SSH in monitor lane
    python3 scripts/run_local_twin.py --interval-seconds 600 --daemon  # custom loop interval

Artifact outputs (mirror Lightsail artifact paths):
    reports/autoresearch/btc5_market/latest.json         (btc5 lane)
    reports/autoresearch/command_node/latest.json        (btc5 lane)
    reports/parallel/alpaca_crypto_lane.json             (alpaca lane)
    reports/alpaca_first_trade/latest.json               (alpaca lane)
    reports/parallel/instance04_weather_divergence_shadow.json  (weather lane)
    data/kalshi_weather_decisions.jsonl                   (kalshi lane)
    reports/local_live_status.json                        (venue live control plane)
    reports/local_feedback_loop.json                      (cross-venue feedback compiler)
    reports/strike_desk/latest.json                      (strike desk lane)
    reports/canonical_operator_truth.json               (truth lane)
    data/local_monitor_state.json                       (monitor lane)

Safety:
    BTC5_DEPLOY_MODE is forced to 'shadow' for btc5 lane — no live orders locally.
    Weather divergence stays shadow-only; the separate kalshi lane owns order submission.
    Venue live submission requires explicit inclusion in --local-live-venues (or LOCAL_LIVE_VENUES).
    Polymarket live additionally requires the canonical BTC5 launch contract to be green.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = REPO_ROOT / "logs"
PYTHON = sys.executable
LOCAL_LIVE_VENUES = {"alpaca", "kalshi", "polymarket"}


def _load_repo_env(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from the repo .env without overriding the parent shell."""
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


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _local_live_status_path() -> Path:
    return REPO_ROOT / "reports" / "local_live_status.json"


def _local_polymarket_db_path() -> Path:
    return REPO_ROOT / "data" / "local_btc_5min_maker.db"


def _repo_env() -> dict[str, str]:
    return _load_repo_env(REPO_ROOT / ".env")


def _env_value(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value not in (None, ""):
        return str(value)
    return str(_repo_env().get(key, default))


def _bool_env_value(key: str, default: bool = False) -> bool:
    value = _env_value(key, "")
    if value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    placeholder_markers = (
        "your-",
        "placeholder",
        "changeme",
        "replace-me",
        "example",
        "dummy",
    )
    return any(marker in text for marker in placeholder_markers)


def _local_live_venues(args: argparse.Namespace) -> set[str]:
    raw = str(
        getattr(args, "local_live_venues", "")
        or os.environ.get("LOCAL_LIVE_VENUES", "")
        or ""
    ).strip()
    if not raw:
        return set()
    requested: set[str] = set()
    for piece in raw.split(","):
        venue = piece.strip().lower()
        if not venue:
            continue
        if venue in {"all", "*"}:
            requested.update(LOCAL_LIVE_VENUES)
            continue
        if venue in LOCAL_LIVE_VENUES:
            requested.add(venue)
    return requested


def _venue_live_requested(args: argparse.Namespace, venue: str) -> bool:
    return venue in _local_live_venues(args)


def _reset_local_live_status(args: argparse.Namespace, lanes: list[str]) -> None:
    current = _load_json(_local_live_status_path()) or {}
    current_venues = dict(current.get("venues") or {})
    refreshed_venues = {lane for lane in lanes if lane in LOCAL_LIVE_VENUES}
    if refreshed_venues:
        current_venues = {
            venue: payload
            for venue, payload in current_venues.items()
            if venue not in refreshed_venues
        }
    payload = {
        "artifact": "local_live_status.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "requested_live_venues": sorted(_local_live_venues(args)),
        "planned_lanes": list(lanes),
        "venues": current_venues,
    }
    _write_json(_local_live_status_path(), payload)


def _update_local_live_status(args: argparse.Namespace, venue: str, payload: dict[str, Any]) -> None:
    current = _load_json(_local_live_status_path()) or {
        "artifact": "local_live_status.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "requested_live_venues": sorted(_local_live_venues(args)),
        "planned_lanes": [],
        "venues": {},
    }
    current["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    current["requested_live_venues"] = sorted(_local_live_venues(args))
    venues = dict(current.get("venues") or {})
    venues[venue] = dict(payload)
    current["venues"] = venues
    _write_json(_local_live_status_path(), current)


def _alpaca_credentials_present(mode: str) -> bool:
    if mode == "live":
        key_id = _env_value("ALPACA_API_KEY_ID") or _env_value("APCA_API_KEY_ID")
        secret_key = _env_value("ALPACA_API_SECRET_KEY") or _env_value("APCA_API_SECRET_KEY")
    else:
        key_id = (
            _env_value("ALPACA_PAPER_API_KEY_ID")
            or _env_value("APCA_API_KEY_ID")
            or _env_value("ALPACA_API_KEY_ID")
        )
        secret_key = (
            _env_value("ALPACA_PAPER_API_SECRET_KEY")
            or _env_value("APCA_API_SECRET_KEY")
            or _env_value("ALPACA_API_SECRET_KEY")
        )
    return bool(key_id and secret_key and not _is_placeholder(key_id) and not _is_placeholder(secret_key))


def _alpaca_explicit_paper_credentials_present() -> bool:
    key_id = _env_value("ALPACA_PAPER_API_KEY_ID")
    secret_key = _env_value("ALPACA_PAPER_API_SECRET_KEY")
    return bool(key_id and secret_key and not _is_placeholder(key_id) and not _is_placeholder(secret_key))


def _resolve_alpaca_mode(args: argparse.Namespace) -> tuple[str, list[str], bool]:
    requested_mode = str(_env_value("ALPACA_TRADING_MODE", "paper")).strip().lower()
    if requested_mode not in {"shadow", "paper", "live"}:
        requested_mode = "paper"
    live_requested = _venue_live_requested(args, "alpaca")
    allow_live = _bool_env_value("ALPACA_ALLOW_LIVE", False)
    blockers: list[str] = []
    effective_mode = requested_mode
    if effective_mode == "live" and not live_requested:
        blockers.append("local_live_gate_disabled")
        effective_mode = "paper"
    if live_requested and requested_mode != "live":
        effective_mode = "live"
    if effective_mode == "live" and not allow_live:
        blockers.append("alpaca_allow_live_false")
        effective_mode = "paper"
    if not _alpaca_credentials_present(effective_mode):
        blockers.append(f"alpaca_{effective_mode}_credentials_missing")
    return effective_mode, blockers, live_requested


def _kalshi_auth_present() -> bool:
    key_id = _env_value("KALSHI_API_KEY_ID", "")
    key_path = _env_value("KALSHI_RSA_KEY_PATH", "")
    resolved_key = Path(key_path).expanduser() if key_path else REPO_ROOT / "bot" / "kalshi" / "kalshi_rsa_private.pem"
    return (
        bool(key_id)
        and not _is_placeholder(key_id)
        and resolved_key.exists()
    )


def _resolve_kalshi_mode(args: argparse.Namespace) -> tuple[str, list[str], bool]:
    live_requested = _venue_live_requested(args, "kalshi")
    requested_mode = str(_env_value("KALSHI_WEATHER_MODE", "paper")).strip().lower()
    if requested_mode not in {"paper", "live"}:
        requested_mode = "paper"
    blockers: list[str] = []
    effective_mode = requested_mode
    if live_requested:
        effective_mode = "live"
    elif requested_mode == "live":
        blockers.append("local_live_gate_disabled")
        effective_mode = "paper"
    if effective_mode == "live" and not _kalshi_auth_present():
        blockers.append("kalshi_auth_missing_or_placeholder")
        effective_mode = "paper"
    return effective_mode, blockers, live_requested


def _polymarket_credentials_present() -> bool:
    private_key = _env_value("POLY_PRIVATE_KEY") or _env_value("POLYMARKET_PK")
    safe_address = _env_value("POLY_SAFE_ADDRESS") or _env_value("POLYMARKET_FUNDER")
    return (
        bool(private_key)
        and bool(safe_address)
        and not _is_placeholder(private_key)
        and not _is_placeholder(safe_address)
    )


def _resolve_polymarket_mode(args: argparse.Namespace) -> tuple[str, list[str], bool]:
    live_requested = _venue_live_requested(args, "polymarket")
    blockers: list[str] = []
    effective_mode = "paper"
    if not live_requested:
        return effective_mode, blockers, False
    if not _polymarket_credentials_present():
        blockers.append("polymarket_credentials_missing")
        return effective_mode, blockers, True

    remote_cycle_status = _load_json(REPO_ROOT / "reports" / "remote_cycle_status.json") or {}
    launch_packet = _load_json(REPO_ROOT / "reports" / "launch_packet_latest.json") or {}
    try:
        from scripts.btc5_rollout import select_rollout_decision

        decision = select_rollout_decision(remote_cycle_status, launch_packet=launch_packet)
        if decision.deploy_mode == "live_stage1" and not decision.paper_trading:
            effective_mode = "live"
        else:
            blockers.extend(str(reason) for reason in decision.rationale if str(reason))
    except Exception as exc:
        blockers.append(f"btc5_rollout_decision_unavailable:{type(exc).__name__}")
    return effective_mode, blockers, True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [local-twin] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Lane runners
# ---------------------------------------------------------------------------


def _run_script(
    relpath: str,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
) -> int:
    """Run a repo script as a subprocess, returning its exit code."""
    script_path = REPO_ROOT / relpath
    if not script_path.exists():
        _log(f"MISSING {relpath} — skipping")
        return 1
    cmd = [PYTHON, str(script_path)] + (extra_args or [])
    env = os.environ.copy()
    for key, value in _load_repo_env(REPO_ROOT / ".env").items():
        env.setdefault(key, value)
    if env_overrides:
        env.update(env_overrides)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    _log(f"→ {relpath} {' '.join(extra_args or [])}")
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _log(f"TIMEOUT {relpath} after {timeout_seconds}s")
        return 124
    return result.returncode


def run_btc5(args: argparse.Namespace) -> int:
    """BTC5 local improvement search in shadow mode (no live orders)."""
    return _run_script(
        "scripts/run_btc5_local_improvement_search.py",
        ["--lanes", "market,command_node", "--repo-root", str(REPO_ROOT)],
        env_overrides={
            "BTC5_DEPLOY_MODE": "shadow",
            "BTC5_PAPER_TRADING": "true",
        },
    )


def run_weather(args: argparse.Namespace) -> int:
    """Instance 4 NWS/Kalshi weather divergence shadow lane."""
    return _run_script(
        "scripts/run_instance4_weather_shadow_lane.py",
        env_overrides={"KALSHI_WEATHER_MODE": "paper"},
    )


def run_alpaca(args: argparse.Namespace) -> int:
    """Alpaca crypto candidate -> queue -> execution lane."""
    mode, blockers, live_requested = _resolve_alpaca_mode(args)
    if mode != "live" and not _alpaca_explicit_paper_credentials_present():
        blockers = [*blockers, "alpaca_paper_credentials_missing"]
    status_payload = {
        "requested_live": live_requested,
        "requested_mode": str(_env_value("ALPACA_TRADING_MODE", "paper")).strip().lower() or "paper",
        "effective_mode": mode,
        "credentials_present": (
            _alpaca_credentials_present("live")
            if mode == "live"
            else _alpaca_explicit_paper_credentials_present()
        ),
        "feedback_loop_ready": True,
        "blockers": blockers,
        "execution_artifact": "reports/alpaca_first_trade/latest.json",
    }
    _update_local_live_status(args, "alpaca", status_payload)
    if mode != "live" and "alpaca_paper_credentials_missing" in blockers:
        _log("alpaca paper credentials missing — skipping lane until paper creds are configured or alpaca local live is enabled")
        return 0
    if not _alpaca_credentials_present(mode):
        _log(f"alpaca credentials missing for mode={mode} — skipping lane")
        return 0
    if blockers:
        _log(f"alpaca effective_mode={mode} blockers={','.join(blockers)}")
    return _run_script(
        "scripts/run_alpaca_first_trade.py",
        ["--mode", mode],
        env_overrides={"ALPACA_TRADING_MODE": mode},
    )


def run_kalshi(args: argparse.Namespace) -> int:
    """Kalshi weather execution lane with explicit local-live gating."""
    mode, blockers, live_requested = _resolve_kalshi_mode(args)
    status_payload = {
        "requested_live": live_requested,
        "requested_mode": str(_env_value("KALSHI_WEATHER_MODE", "paper")).strip().lower() or "paper",
        "effective_mode": mode,
        "credentials_present": _kalshi_auth_present(),
        "feedback_loop_ready": True,
        "blockers": blockers,
        "execution_artifacts": [
            "data/kalshi_weather_signals.jsonl",
            "data/kalshi_weather_orders.jsonl",
            "data/kalshi_weather_decisions.jsonl",
            "data/kalshi_weather_settlements.jsonl",
        ],
    }
    _update_local_live_status(args, "kalshi", status_payload)
    if blockers:
        _log(f"kalshi effective_mode={mode} blockers={','.join(blockers)}")
    extra_args = ["--mode", mode]
    if mode == "live":
        extra_args.append("--execute")
    return _run_script(
        "kalshi/weather_arb.py",
        extra_args,
        env_overrides={
            "KALSHI_WEATHER_MODE": mode,
            "KALSHI_WEATHER_PAPER_TRADING": "false" if mode == "live" else "true",
        },
    )


def run_polymarket(args: argparse.Namespace) -> int:
    """Polymarket BTC5 execution lane with canonical launch gating."""
    mode, blockers, live_requested = _resolve_polymarket_mode(args)
    status_payload = {
        "requested_live": live_requested,
        "effective_mode": mode,
        "credentials_present": _polymarket_credentials_present(),
        "feedback_loop_ready": True,
        "blockers": blockers,
        "execution_artifact": str(_local_polymarket_db_path().relative_to(REPO_ROOT)),
        "launch_packet_path": "reports/launch_packet_latest.json",
    }
    _update_local_live_status(args, "polymarket", status_payload)
    if blockers:
        _log(f"polymarket effective_mode={mode} blockers={','.join(blockers)}")
    return _run_script(
        "bot/btc_5min_maker.py",
        ["--run-now", "--live" if mode == "live" else "--paper"],
        env_overrides={
            "BTC5_DEPLOY_MODE": "live_stage1" if mode == "live" else "shadow_probe",
            "BTC5_PAPER_TRADING": "false" if mode == "live" else "true",
            "BTC5_DB_PATH": str(_local_polymarket_db_path()),
        },
    )


def run_strike_desk(args: argparse.Namespace) -> int:
    """Strike desk shadow lane — execution queue and event tape writer."""
    return _run_script(
        "scripts/run_strike_desk.py",
        ["--reports-dir", "reports/strike_desk", "--tape-db", "data/tape/strike_desk.db"],
    )


def run_monitor(args: argparse.Namespace) -> int:
    """Live fund health snapshot (Polymarket API + optional VPS SSH)."""
    extra: list[str] = ["--once"]
    if args.no_ssh:
        extra.append("--no-ssh")
    return _run_script("scripts/local_monitor.py", extra)


def run_truth(args: argparse.Namespace) -> int:
    """Canonical truth reconciliation — Polymarket API + runtime truth merge."""
    return _run_script("scripts/canonical_truth_writer.py")


def run_sensorium(args: argparse.Namespace) -> int:
    """Evidence layer aggregator — produces evidence_bundle and sensorium artifact."""
    return _run_script("scripts/run_sensorium.py")


def run_feedback(args: argparse.Namespace) -> int:
    """Cross-venue feedback compiler for local self-improvement."""
    return _run_script("scripts/build_local_feedback_loop.py")


def run_kernel(args: argparse.Namespace) -> int:
    """Kernel cycle — Evidence → Thesis → Promotion → Learning (shadow mode)."""
    return _run_script(
        "scripts/run_kernel_cycle.py",
        env_overrides={
            "BTC5_DEPLOY_MODE": "shadow",
            "KALSHI_WEATHER_MODE": "paper",
        },
    )


def run_novelty(args: argparse.Namespace) -> int:
    """Novelty discovery — converts sensorium observations into novel_edge artifacts."""
    return _run_script("scripts/run_novelty_discovery.py")


def run_architecture_alpha(args: argparse.Namespace) -> int:
    """Architecture alpha — mines constitution candidates from research artifacts."""
    return _run_script("scripts/run_architecture_alpha.py")


def run_promotion(args: argparse.Namespace) -> int:
    """Promotion bundle — merges opportunity_exchange + capital_lab + counterfactual."""
    return _run_script("scripts/run_promotion_bundle.py")


def run_kimi(args: argparse.Namespace) -> int:
    """Kimi/Moonshot learning — failure clustering and candidate triage."""
    return _run_script("scripts/run_kimi_research.py")


def run_harness(args: argparse.Namespace) -> int:
    """Intelligence harness — acceptance gate for self-improvement changes."""
    return _run_script("scripts/run_intelligence_harness.py")


def run_strike_factory(args: argparse.Namespace) -> int:
    """Strike factory — revenue-first desk scan, tape write, and promotion snapshot."""
    extra = ["--output", str(REPO_ROOT / "reports" / "strike_factory" / "latest.json")]
    return _run_script("scripts/run_strike_factory.py", extra)


def run_structural_profit(args: argparse.Namespace) -> int:
    """Full local structural cycle: truth -> evidence -> simulation -> promotion -> strike factory."""
    rc = _run_script("scripts/run_structural_profit_cycle.py", timeout_seconds=180)
    if rc == 0:
        return 0
    report = _load_json(REPO_ROOT / "reports" / "structural_alpha" / "local_cycle.json")
    if str((report or {}).get("status") or "").strip().lower() == "blocked":
        _log("structural_profit completed with blocked proof status — lane is healthy but not live-eligible")
        return 0
    return rc


# ---------------------------------------------------------------------------
# Lane registry
# ---------------------------------------------------------------------------

LANE_RUNNERS: dict[str, Any] = {
    "btc5": run_btc5,
    "alpaca": run_alpaca,
    "kalshi": run_kalshi,
    "polymarket": run_polymarket,
    "weather": run_weather,
    "strike_desk": run_strike_desk,
    "monitor": run_monitor,
    "truth": run_truth,
    "sensorium": run_sensorium,
    "feedback": run_feedback,
    "kernel": run_kernel,
    "novelty": run_novelty,
    "architecture_alpha": run_architecture_alpha,
    "promotion": run_promotion,
    "kimi": run_kimi,
    "harness": run_harness,
    "strike_factory": run_strike_factory,
    "structural_profit": run_structural_profit,
}

# Lanes suitable for continuous daemon operation
DAEMON_PROFILES: dict[str, list[str]] = {
    "default": ["alpaca", "kalshi", "polymarket", "feedback", "kernel", "weather", "truth", "strike_desk", "kimi", "structural_profit"],
    "heavy_local": [
        "alpaca",
        "btc5",
        "kalshi",
        "feedback",
        "kernel",
        "polymarket",
        "weather",
        "truth",
        "strike_desk",
        "kimi",
        "harness",
        "structural_profit",
    ],
}

LANE_DESCRIPTIONS = {
    "btc5": "BTC5 local improvement search (shadow)",
    "alpaca": "Alpaca crypto candidate scan and first-trade executor",
    "kalshi": "Kalshi weather execution lane",
    "polymarket": "Polymarket BTC5 execution lane",
    "weather": "NWS/Kalshi weather divergence shadow",
    "strike_desk": "Strike desk execution queue and tape writer",
    "monitor": "Polymarket fund health snapshot",
    "truth": "Canonical wallet+runtime truth reconciliation",
    "sensorium": "Evidence layer aggregator",
    "feedback": "Cross-venue local feedback compiler",
    "kernel": "Self-improvement kernel cycle (shadow)",
    "novelty": "Novelty discovery from sensorium observations",
    "architecture_alpha": "Architecture constitution candidate generator",
    "promotion": "Promotion bundle writer",
    "kimi": "Kimi/Moonshot learning layer (failure clustering, candidate triage)",
    "harness": "End-to-end intelligence harness (acceptance gate)",
    "strike_factory": "Revenue-first strike desk orchestrator",
    "structural_profit": "Full structural profit cycle (truth, simulation, promotion, strike factory)",
}


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def run_once(args: argparse.Namespace, lanes: list[str]) -> dict[str, int]:
    _reset_local_live_status(args, lanes)
    results: dict[str, int] = {}
    for lane in lanes:
        runner = LANE_RUNNERS[lane]
        _log(f"lane={lane} starting — {LANE_DESCRIPTIONS[lane]}")
        rc = runner(args)
        results[lane] = rc
        status = "OK" if rc == 0 else f"FAIL(exit={rc})"
        _log(f"lane={lane} {status}")
    return results


def run_daemon(
    args: argparse.Namespace,
    lanes: list[str],
    interval_seconds: int,
) -> None:
    _log(f"daemon mode | lanes={','.join(lanes)} | interval={interval_seconds}s")
    cycle = 0
    while True:
        cycle += 1
        _log(f"cycle={cycle} starting")
        results = run_once(args, lanes)
        failures = [k for k, v in results.items() if v != 0]
        if failures:
            _log(f"cycle={cycle} failures: {failures} — will retry next cycle")
        else:
            _log(f"cycle={cycle} all lanes OK")
        _log(f"sleeping {interval_seconds}s until next cycle")
        time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local Twin Control Plane — local orchestration for live-data testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--lane",
        choices=list(LANE_RUNNERS.keys()),
        default=None,
        help="Run a single named lane (default: all lanes)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously, looping daemon-compatible lanes (alpaca, kernel, weather, truth, strike_desk, kimi)",
    )
    parser.add_argument(
        "--daemon-profile",
        choices=sorted(DAEMON_PROFILES.keys()),
        default="default",
        help=(
            "Named daemon lane bundle. "
            "'default' is lighter-weight; 'heavy_local' adds BTC5 improvement search and the harness."
        ),
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        metavar="N",
        help="Seconds between daemon cycles (default: 300)",
    )
    parser.add_argument(
        "--no-ssh",
        action="store_true",
        help="Skip VPS SSH queries in the monitor lane",
    )
    parser.add_argument(
        "--local-live-venues",
        default=os.environ.get("LOCAL_LIVE_VENUES", ""),
        help=(
            "Comma-separated venue list allowed to submit real orders from local. "
            "Valid values: alpaca, kalshi, polymarket, all."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override repo root path (default: auto-detected from script location)",
    )
    return parser.parse_args(argv)


def _resolve_lanes(args: argparse.Namespace) -> list[str]:
    if args.lane:
        return [args.lane]
    if args.daemon:
        return list(DAEMON_PROFILES[args.daemon_profile])
    return list(LANE_RUNNERS.keys())


def main(argv: list[str] | None = None) -> int:
    global REPO_ROOT
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    args = parse_args(argv)

    # Allow repo-root override
    if args.repo_root != str(REPO_ROOT):
        REPO_ROOT = Path(args.repo_root).resolve()
        _log(f"repo-root overridden to {REPO_ROOT}")

    # Determine which lanes to run
    lanes = _resolve_lanes(args)

    mode_bits = ["daemon" if args.daemon else "one-shot"]
    if args.daemon:
        mode_bits.append(f"profile={args.daemon_profile}")
    _log(f"{' | '.join(mode_bits)} | lanes={','.join(lanes)}")

    if args.daemon:
        run_daemon(args, lanes, args.interval_seconds)
        return 0  # unreachable — daemon loops forever

    results = run_once(args, lanes)
    failures = sum(1 for rc in results.values() if rc != 0)
    total = len(results)
    _log(f"done — {total} lanes, {failures} failures")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
