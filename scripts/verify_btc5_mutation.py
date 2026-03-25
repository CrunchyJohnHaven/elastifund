#!/usr/bin/env python3
"""
verify_btc5_mutation.py — Post-deploy mutation verification gate.

Run after each deployment to confirm the promoted BTC5 mutation is the
config that is actually live on the VPS. Compares config_hash in the
active mutation state file against the hash recorded in the BTC5 runtime
contract snapshot.

Exit codes:
  0 — MUTATION_VERIFY_OK   (hashes match)
  1 — MUTATION_VERIFY_FAIL (hash mismatch or unexpected error)
  2 — MUTATION_VERIFY_UNKNOWN (state or contract file missing)

Usage:
    python scripts/verify_btc5_mutation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MUTATION_STATE = _REPO_ROOT / "state" / "btc5_active_mutation.json"
_RUNTIME_CONTRACT = _REPO_ROOT / "reports" / "btc5_runtime_contract.json"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def main() -> None:
    mutation = _load_json(_MUTATION_STATE)
    contract = _load_json(_RUNTIME_CONTRACT)

    if mutation is None or contract is None:
        missing = []
        if mutation is None:
            missing.append(str(_MUTATION_STATE))
        if contract is None:
            missing.append(str(_RUNTIME_CONTRACT))
        print(f"MUTATION_VERIFY_UNKNOWN — missing files: {', '.join(missing)}")
        sys.exit(2)

    mutation_hash = mutation.get("config_hash")
    contract_hash = contract.get("config_hash")

    if not mutation_hash or not contract_hash:
        print(
            "MUTATION_VERIFY_UNKNOWN — config_hash absent "
            f"(mutation={mutation_hash!r}, contract={contract_hash!r})"
        )
        sys.exit(2)

    if mutation_hash != contract_hash:
        print(
            f"MUTATION_VERIFY_FAIL config_hash_mismatch — "
            f"mutation={mutation_hash[:16]}... contract={contract_hash[:16]}..."
        )
        sys.exit(1)

    mutation_id = mutation.get("mutation_id", "unknown")
    print(f"MUTATION_VERIFY_OK mutation_id={mutation_id}")
    sys.exit(0)


if __name__ == "__main__":
    main()
