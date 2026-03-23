#!/usr/bin/env python3
"""
Local Twin Control Plane

Orchestrates shadow-mode lanes against live APIs without submitting real orders.
Mirrors the Lightsail artifact paths so the same supervisor and foundry code can
consume outputs from either host.

Usage:
    python3 scripts/run_local_twin.py                     # all lanes, once
    python3 scripts/run_local_twin.py --lane btc5         # BTC5 improvement search only
    python3 scripts/run_local_twin.py --lane weather      # weather shadow lane only
    python3 scripts/run_local_twin.py --lane strike_desk  # strike desk shadow lane only
    python3 scripts/run_local_twin.py --lane monitor      # fund health snapshot only
    python3 scripts/run_local_twin.py --lane truth        # canonical truth reconciliation only
    python3 scripts/run_local_twin.py --daemon            # continuous loop (btc5+weather+truth+strike desk)
    python3 scripts/run_local_twin.py --daemon --lane btc5   # daemon on one lane
    python3 scripts/run_local_twin.py --no-ssh            # skip VPS SSH in monitor lane
    python3 scripts/run_local_twin.py --interval-seconds 600 --daemon  # custom loop interval

Artifact outputs (mirror Lightsail artifact paths):
    reports/autoresearch/btc5_market/latest.json         (btc5 lane)
    reports/autoresearch/command_node/latest.json        (btc5 lane)
    reports/parallel/instance04_weather_divergence_shadow.json  (weather lane)
    reports/strike_desk/latest.json                      (strike desk lane)
    reports/canonical_operator_truth.json               (truth lane)
    data/local_monitor_state.json                       (monitor lane)

Safety:
    BTC5_DEPLOY_MODE is forced to 'shadow' for btc5 lane — no live orders locally.
    KALSHI_WEATHER_MODE is forced to 'paper' for weather lane.
"""

from __future__ import annotations

import argparse
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
) -> int:
    """Run a repo script as a subprocess, returning its exit code."""
    script_path = REPO_ROOT / relpath
    if not script_path.exists():
        _log(f"MISSING {relpath} — skipping")
        return 1
    cmd = [PYTHON, str(script_path)] + (extra_args or [])
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    _log(f"→ {relpath} {' '.join(extra_args or [])}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
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


# ---------------------------------------------------------------------------
# Lane registry
# ---------------------------------------------------------------------------

LANE_RUNNERS: dict[str, Any] = {
    "btc5": run_btc5,
    "weather": run_weather,
    "strike_desk": run_strike_desk,
    "monitor": run_monitor,
    "truth": run_truth,
    "sensorium": run_sensorium,
    "kernel": run_kernel,
    "novelty": run_novelty,
    "architecture_alpha": run_architecture_alpha,
    "promotion": run_promotion,
    "kimi": run_kimi,
    "harness": run_harness,
    "strike_factory": run_strike_factory,
}

# Lanes suitable for continuous daemon operation
DAEMON_LANE_KEYS = ["kernel", "weather", "truth", "strike_desk", "kimi"]

LANE_DESCRIPTIONS = {
    "btc5": "BTC5 local improvement search (shadow)",
    "weather": "NWS/Kalshi weather divergence shadow",
    "strike_desk": "Strike desk execution queue and tape writer",
    "monitor": "Polymarket fund health snapshot",
    "truth": "Canonical wallet+runtime truth reconciliation",
    "sensorium": "Evidence layer aggregator",
    "kernel": "Self-improvement kernel cycle (shadow)",
    "novelty": "Novelty discovery from sensorium observations",
    "architecture_alpha": "Architecture constitution candidate generator",
    "promotion": "Promotion bundle writer",
    "kimi": "Kimi/Moonshot learning layer (failure clustering, candidate triage)",
    "harness": "End-to-end intelligence harness (acceptance gate)",
    "strike_factory": "Revenue-first strike desk orchestrator",
}


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def run_once(args: argparse.Namespace, lanes: list[str]) -> dict[str, int]:
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
        description="Local Twin Control Plane — shadow-mode orchestration for live-data testing",
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
        help="Run continuously, looping daemon-compatible lanes (btc5, weather, truth, strike_desk, kimi)",
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
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override repo root path (default: auto-detected from script location)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global REPO_ROOT
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    args = parse_args(argv)

    # Allow repo-root override
    if args.repo_root != str(REPO_ROOT):
        REPO_ROOT = Path(args.repo_root).resolve()
        _log(f"repo-root overridden to {REPO_ROOT}")

    # Determine which lanes to run
    if args.lane:
        lanes = [args.lane]
    elif args.daemon:
        # Daemon mode defaults to the continuous-safe subset
        lanes = DAEMON_LANE_KEYS
    else:
        # One-shot: all lanes
        lanes = list(LANE_RUNNERS.keys())

    _log(f"{'daemon' if args.daemon else 'one-shot'} | lanes={','.join(lanes)}")

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
