#!/usr/bin/env python3
"""
btc5_start_validation_cohort.py — Stamp the validation cohort start time.

Run this AFTER verify_btc5_mutation.py returns exit code 0 (MUTATION_VERIFY_OK)
on the VPS. Marks the cohort as active and records the start timestamp so that
render_btc5_validation_cohort.py knows which fills to count.

Exit codes:
  0 — cohort activated successfully
  1 — error (already active, missing files, or unexpected exception)

Usage:
    python3 scripts/btc5_start_validation_cohort.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COHORT_PATH = _REPO_ROOT / "state" / "btc5_validation_cohort.json"
_MUTATION_PATH = _REPO_ROOT / "state" / "btc5_active_mutation.json"
_CONTRACT_PATH = _REPO_ROOT / "reports" / "btc5_runtime_contract.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with path.open() as f:
        return json.load(f)


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.rename(path)


def main() -> int:
    try:
        cohort = _load_json(_COHORT_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if cohort.get("cohort_status") != "awaiting_deploy":
        current = cohort.get("cohort_status")
        print(
            f"ERROR: cohort_status is '{current}', expected 'awaiting_deploy'. "
            "Refusing to re-activate an already-active or completed cohort.",
            file=sys.stderr,
        )
        return 1

    # Load mutation ID from active mutation state
    mutation_id: str | None = None
    try:
        mutation = _load_json(_MUTATION_PATH)
        mutation_id = mutation.get("mutation_id")
    except FileNotFoundError:
        print("WARNING: state/btc5_active_mutation.json not found; mutation_id will be null", file=sys.stderr)

    # Load config hash from runtime contract
    config_hash: str | None = None
    try:
        contract = _load_json(_CONTRACT_PATH)
        config_hash = contract.get("config_hash")
    except FileNotFoundError:
        print("WARNING: reports/btc5_runtime_contract.json not found; config_hash will be null", file=sys.stderr)

    now_ts = int(time.time())
    now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()

    cohort["cohort_status"] = "active"
    cohort["cohort_start_ts"] = now_ts
    cohort["cohort_activated_at"] = now_iso
    cohort["validation_mutation_id"] = mutation_id
    cohort["validation_config_hash"] = config_hash

    try:
        _write_atomic(_COHORT_PATH, cohort)
    except Exception as e:
        print(f"ERROR: failed to write cohort contract: {e}", file=sys.stderr)
        return 1

    hash_preview = f"{config_hash[:16]}..." if config_hash else "null"
    print(
        f"COHORT_ACTIVATED cohort_id={cohort['cohort_id']} "
        f"start_ts={now_ts} "
        f"mutation_id={mutation_id} "
        f"config_hash={hash_preview}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
