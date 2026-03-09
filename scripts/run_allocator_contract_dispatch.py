"""Generate allocator contract and closed-trade flywheel artifacts for Instance #5."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.candidate_contract import (
    build_allocator_contract_snapshot,
    load_candidate_records,
    simulate_closed_trade_flywheel,
)


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_reports(
    *,
    reports_dir: Path,
    polymarket_input: Path | None,
    kalshi_input: Path | None,
    horizon_hours: int,
    seed: int,
) -> tuple[Path, Path]:
    candidates, diagnostics = load_candidate_records(
        reports_dir=reports_dir,
        polymarket_path=polymarket_input,
        kalshi_path=kalshi_input,
    )
    contract_payload = build_allocator_contract_snapshot(candidates, diagnostics=diagnostics)
    flywheel_payload = simulate_closed_trade_flywheel(
        candidates,
        horizon_hours=horizon_hours,
        seed=seed,
    )
    flywheel_payload["input_diagnostics"] = diagnostics
    flywheel_payload["assumptions"] = {
        "launch_posture_default": "blocked",
        "shadow_envelope_usd": {
            "max_position": 5,
            "daily_loss": 5,
            "max_open_positions": 5,
        },
    }

    stamp = _timestamp()
    contract_path = reports_dir / f"allocator_contract_{stamp}.json"
    flywheel_path = reports_dir / f"closed_trade_flywheel_{stamp}.json"
    _write_json(contract_path, contract_payload)
    _write_json(flywheel_path, flywheel_payload)
    return contract_path, flywheel_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build canonical allocator contract and 24h closed-trade flywheel artifacts.",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Reports directory containing venue candidate exports (default: reports).",
    )
    parser.add_argument(
        "--polymarket-input",
        default=None,
        help="Optional explicit Polymarket candidate json path.",
    )
    parser.add_argument(
        "--kalshi-input",
        default=None,
        help="Optional explicit Kalshi candidate json path.",
    )
    parser.add_argument(
        "--horizon-hours",
        type=int,
        default=24,
        help="Simulation horizon in hours (default: 24).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic simulation (default: 42).",
    )
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir).resolve()
    polymarket_input = Path(args.polymarket_input).resolve() if args.polymarket_input else None
    kalshi_input = Path(args.kalshi_input).resolve() if args.kalshi_input else None

    contract_path, flywheel_path = build_reports(
        reports_dir=reports_dir,
        polymarket_input=polymarket_input,
        kalshi_input=kalshi_input,
        horizon_hours=max(1, int(args.horizon_hours)),
        seed=int(args.seed),
    )
    print(contract_path)
    print(flywheel_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
