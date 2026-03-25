#!/usr/bin/env python3
"""
btc5_deploy_checklist.py — P0.4 pre-cohort deploy checklist.

Runs 10 pass/fail checks that must all pass before the validation cohort
can begin counting fills. Print a formatted table and exit 0 if all pass,
exit 1 if any fail.

Usage:
    python3 scripts/btc5_deploy_checklist.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MUTATION_PATH = _REPO_ROOT / "state" / "btc5_active_mutation.json"
_CONTRACT_PATH = _REPO_ROOT / "reports" / "btc5_runtime_contract.json"
_EFFECTIVE_ENV = _REPO_ROOT / "state" / "btc5_effective.env"
_COHORT_PATH = _REPO_ROOT / "state" / "btc5_validation_cohort.json"
_VERIFY_SCRIPT = _REPO_ROOT / "scripts" / "verify_btc5_mutation.py"

_MAX_ENV_AGE_SECONDS = 86400  # 24 hours


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file, ignoring comment lines."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _check_mutation_verify_ok() -> Tuple[bool, str]:
    """Run verify_btc5_mutation.py as a subprocess and check exit code 0."""
    if not _VERIFY_SCRIPT.exists():
        return False, f"script not found: {_VERIFY_SCRIPT}"
    try:
        result = subprocess.run(
            [sys.executable, str(_VERIFY_SCRIPT)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "exit code 0 (OK)"
        elif result.returncode == 1:
            return False, "exit code 1 (FAIL — hash mismatch)"
        else:
            return False, f"exit code {result.returncode} (UNKNOWN)"
    except subprocess.TimeoutExpired:
        return False, "timeout after 30s"
    except Exception as e:
        return False, f"exception: {e}"


def _check_runtime_contract_exists() -> Tuple[bool, str]:
    if not _CONTRACT_PATH.exists():
        return False, "file not found"
    try:
        data = _load_json(_CONTRACT_PATH)
        if not data.get("config_hash"):
            return False, "config_hash is null or missing"
        return True, f"config_hash={data['config_hash'][:16]}..."
    except Exception as e:
        return False, f"parse error: {e}"


def _check_active_mutation_not_reverted() -> Tuple[bool, str]:
    if not _MUTATION_PATH.exists():
        return False, "file not found"
    try:
        data = _load_json(_MUTATION_PATH)
        status = data.get("verification_status", "")
        reverted = data.get("auto_revert_triggered", False)
        if reverted:
            return False, f"auto_revert_triggered=true"
        if status == "reverted":
            return False, f"verification_status=reverted"
        return True, f"verification_status={status}"
    except Exception as e:
        return False, f"parse error: {e}"


def _check_config_hash_match() -> Tuple[bool, str]:
    if not _CONTRACT_PATH.exists() or not _MUTATION_PATH.exists():
        return False, "one or both files missing"
    try:
        contract = _load_json(_CONTRACT_PATH)
        mutation = _load_json(_MUTATION_PATH)
        contract_hash = contract.get("config_hash")
        mutation_hash = mutation.get("config_hash")
        if mutation_hash is None:
            # Mutation file doesn't carry config_hash — treat as soft pass
            return True, "mutation config_hash not set (pre-hash era — skipping match)"
        if contract_hash != mutation_hash:
            return False, f"mismatch: contract={contract_hash[:16]}... mutation={mutation_hash[:16]}..."
        return True, "hashes match"
    except Exception as e:
        return False, f"parse error: {e}"


def _check_effective_env_fresh() -> Tuple[bool, str]:
    if not _EFFECTIVE_ENV.exists():
        return False, "file not found"
    # Parse generated_at from header comment
    try:
        content = _EFFECTIVE_ENV.read_text()
        for line in content.splitlines():
            if "generated_at=" in line:
                ts_str = line.split("generated_at=", 1)[1].strip()
                # Parse ISO timestamp
                ts_str = ts_str.replace("Z", "+00:00")
                generated = datetime.fromisoformat(ts_str)
                now = datetime.now(tz=timezone.utc)
                if generated.tzinfo is None:
                    generated = generated.replace(tzinfo=timezone.utc)
                age_s = (now - generated).total_seconds()
                if age_s > _MAX_ENV_AGE_SECONDS:
                    return False, f"generated {age_s/3600:.1f}h ago (> 24h limit)"
                return True, f"generated {age_s/3600:.1f}h ago"
        # No timestamp found in header — fall back to file mtime
        import os
        mtime = _EFFECTIVE_ENV.stat().st_mtime
        now_ts = datetime.now(tz=timezone.utc).timestamp()
        age_s = now_ts - mtime
        if age_s > _MAX_ENV_AGE_SECONDS:
            return False, f"mtime {age_s/3600:.1f}h ago (> 24h limit)"
        return True, f"mtime {age_s/3600:.1f}h ago"
    except Exception as e:
        return False, f"parse error: {e}"


def _check_cohort_contract_defined() -> Tuple[bool, str]:
    if not _COHORT_PATH.exists():
        return False, "file not found"
    try:
        _load_json(_COHORT_PATH)
        return True, "exists"
    except Exception as e:
        return False, f"parse error: {e}"


def _check_up_live_mode_shadow() -> Tuple[bool, str]:
    env = _read_env_file(_EFFECTIVE_ENV)
    val = env.get("BTC5_UP_LIVE_MODE", "")
    if val == "shadow_only":
        return True, f"BTC5_UP_LIVE_MODE={val}"
    return False, f"BTC5_UP_LIVE_MODE={val!r} (expected 'shadow_only')"


def _check_direction_mode_down_only() -> Tuple[bool, str]:
    env = _read_env_file(_EFFECTIVE_ENV)
    val = env.get("BTC5_DIRECTION_MODE", "")
    if val == "down_only":
        return True, f"BTC5_DIRECTION_MODE={val}"
    return False, f"BTC5_DIRECTION_MODE={val!r} (expected 'down_only')"


def _check_down_price_cap() -> Tuple[bool, str]:
    env = _read_env_file(_EFFECTIVE_ENV)
    val = env.get("BTC5_DOWN_MAX_BUY_PRICE", "")
    try:
        price = float(val)
        if price <= 0.48:
            return True, f"BTC5_DOWN_MAX_BUY_PRICE={val}"
        return False, f"BTC5_DOWN_MAX_BUY_PRICE={val} (> 0.48)"
    except (ValueError, TypeError):
        return False, f"BTC5_DOWN_MAX_BUY_PRICE={val!r} (not a valid float)"


def _check_hour_filter_enabled() -> Tuple[bool, str]:
    env = _read_env_file(_EFFECTIVE_ENV)
    val = env.get("BTC5_HOUR_FILTER_ENABLED", "")
    if val.lower() == "true":
        return True, f"BTC5_HOUR_FILTER_ENABLED={val}"
    return False, f"BTC5_HOUR_FILTER_ENABLED={val!r} (expected 'true')"


def main() -> int:
    now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== BTC5 Deploy Checklist — {now_iso} ===\n")

    checks = [
        ("mutation_verify_ok", _check_mutation_verify_ok),
        ("runtime_contract_exists", _check_runtime_contract_exists),
        ("active_mutation_not_reverted", _check_active_mutation_not_reverted),
        ("config_hash_match", _check_config_hash_match),
        ("effective_env_fresh", _check_effective_env_fresh),
        ("cohort_contract_defined", _check_cohort_contract_defined),
        ("up_live_mode_shadow", _check_up_live_mode_shadow),
        ("direction_mode_down_only", _check_direction_mode_down_only),
        ("down_price_cap_at_048", _check_down_price_cap),
        ("hour_filter_enabled", _check_hour_filter_enabled),
    ]

    results = []
    for name, fn in checks:
        try:
            passed, detail = fn()
        except Exception as e:
            passed, detail = False, f"unexpected exception: {e}"
        results.append((name, passed, detail))

    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)

    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        if passed:
            print(f"PASS  {name}")
        else:
            print(f"FAIL  {name}: {detail}")

    print()
    if passed_count == total:
        print(f"{passed_count}/{total} checks passed. DEPLOY VALID — cohort may start.")
        return 0
    else:
        print(f"{passed_count}/{total} checks passed. DEPLOY INVALID — do not start cohort.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
