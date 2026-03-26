#!/usr/bin/env python3
"""
P1.1 — render_btc5_effective_env.py

Reads the four BTC5 env layers in priority order and merges them into
a single authoritative state/btc5_effective.env. Also writes
reports/btc5_runtime_contract.json.

Priority order (later = higher priority, exactly like shell source order):
  1. config/btc5_strategy.env
  2. state/btc5_autoresearch.env    (may not exist)
  3. state/btc5_capital_stage.env   (may not exist)
  4. .env                            (filter to BTC5_ prefixed vars only)

Usage:
  python scripts/render_btc5_effective_env.py [--check-only]
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root — two levels up from scripts/
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent

ENV_LAYERS = [
    REPO_ROOT / "config" / "btc5_strategy.env",
    REPO_ROOT / "state" / "btc5_autoresearch.env",
    REPO_ROOT / "state" / "btc5_capital_stage.env",
    REPO_ROOT / ".env",
]

OUTPUT_ENV = REPO_ROOT / "state" / "btc5_effective.env"
OUTPUT_CONTRACT = REPO_ROOT / "reports" / "btc5_runtime_contract.json"
MUTATION_FILE = REPO_ROOT / "state" / "btc5_active_mutation.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_env_file(path: Path, btc5_only: bool = False) -> dict:
    """Parse a .env-style file into a dict.  Comments and blanks are skipped."""
    result = {}
    if not path.exists():
        return result
    try:
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip optional inline comment (after bare #, not inside quotes)
            if "#" in value and not (value.startswith('"') or value.startswith("'")):
                value = value.split("#", 1)[0].strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if btc5_only and not key.startswith("BTC5_"):
                continue
            result[key] = value
    except Exception as exc:
        print(f"WARNING: could not parse {path}: {exc}", file=sys.stderr)
    return result


def config_hash(params: dict) -> str:
    """SHA-256 of sorted key=value pairs."""
    payload = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_mutation_id() -> str | None:
    if not MUTATION_FILE.exists():
        return None
    try:
        data = json.loads(MUTATION_FILE.read_text())
        return data.get("mutation_id") or data.get("id") or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def run_safety_checks(params: dict) -> list:
    warnings = []

    up_live = params.get("BTC5_UP_LIVE_MODE", "")
    if up_live != "shadow_only":
        warnings.append(
            f"BTC5_UP_LIVE_MODE is '{up_live}' — expected 'shadow_only'. "
            "UP direction must stay in shadow mode (UP lost -$1,060 on $1,492 deployed)."
        )

    direction_mode = params.get("BTC5_DIRECTION_MODE", "")
    if direction_mode != "down_only":
        warnings.append(
            f"BTC5_DIRECTION_MODE is '{direction_mode}' — expected 'down_only'. "
            "UP direction is KILLED. System must run DOWN-only until further notice."
        )

    down_max_str = params.get("BTC5_DOWN_MAX_BUY_PRICE", "")
    try:
        down_max = float(down_max_str)
        if down_max > 0.48:
            warnings.append(
                f"BTC5_DOWN_MAX_BUY_PRICE is {down_max} — exceeds 0.48 safety ceiling. "
                "Prices above 0.48 on DOWN contracts carry unacceptable fee drag."
            )
    except (ValueError, TypeError):
        if down_max_str:
            warnings.append(
                f"BTC5_DOWN_MAX_BUY_PRICE could not be parsed as float: '{down_max_str}'."
            )

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_effective_params() -> tuple[dict, list[str], dict]:
    """Return (effective_params, sources_used, layer_map)."""
    merged: dict = {}
    sources_used: list[str] = []
    layer_map: dict = {}  # key -> source file that set it

    for path in ENV_LAYERS:
        btc5_only = (path.name == ".env")
        layer_vars = parse_env_file(path, btc5_only=btc5_only)
        if layer_vars:
            sources_used.append(str(path.relative_to(REPO_ROOT)))
            for k, v in layer_vars.items():
                merged[k] = v
                layer_map[k] = str(path.relative_to(REPO_ROOT))

    # Keep only BTC5_ vars in the final effective env
    effective = {k: v for k, v in merged.items() if k.startswith("BTC5_")}
    return effective, sources_used, layer_map


def render(check_only: bool = False) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()

    effective, sources_used, _layer_map = build_effective_params()
    chash = config_hash(effective)
    mutation_id = load_mutation_id()
    warnings = run_safety_checks(effective)

    if check_only:
        print("=== BTC5 Effective Parameters ===")
        for k, v in sorted(effective.items()):
            print(f"  {k}={v}")
        print(f"\nSources used: {', '.join(sources_used) or '(none)'}")
        print(f"Config hash:  {chash}")
        print(f"Mutation ID:  {mutation_id or '(none)'}")
        if warnings:
            print(f"\n[SAFETY WARNINGS — {len(warnings)} found]")
            for w in warnings:
                print(f"  * {w}")
        else:
            print("\n[Safety checks: PASS — no warnings]")
        print(f"\nWarnings: {len(warnings)}")
        return 1 if warnings else 0

    # Ensure output directories exist
    OUTPUT_ENV.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CONTRACT.parent.mkdir(parents=True, exist_ok=True)

    # Write state/btc5_effective.env
    header_lines = [
        f"# btc5_effective.env — auto-generated by render_btc5_effective_env.py",
        f"# generated_at={now_iso}",
        f"# config_hash={chash}",
        f"# sources={', '.join(sources_used) or '(none)'}",
        "",
    ]
    env_lines = [f"{k}={v}" for k, v in sorted(effective.items())]
    OUTPUT_ENV.write_text("\n".join(header_lines + env_lines) + "\n")
    print(f"Wrote {OUTPUT_ENV.relative_to(REPO_ROOT)}")

    # Write reports/btc5_runtime_contract.json
    contract = {
        "config_hash": chash,
        "generated_at": now_iso,
        "sources_used": sources_used,
        "effective_params": effective,
        "mutation_id": mutation_id,
        "service_loaded_at": None,
    }
    if warnings:
        contract["SAFETY_WARNINGS"] = warnings

    OUTPUT_CONTRACT.write_text(json.dumps(contract, indent=2))
    print(f"Wrote {OUTPUT_CONTRACT.relative_to(REPO_ROOT)}")

    # Sync config_hash back to the mutation file so verify_btc5_mutation.py can compare.
    # This is the only write render_effective_env makes to the mutation state.
    if MUTATION_FILE.exists():
        try:
            mutation_data = json.loads(MUTATION_FILE.read_text())
            mutation_data["config_hash"] = chash
            tmp = MUTATION_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(mutation_data, indent=2))
            tmp.replace(MUTATION_FILE)
            print(f"Synced config_hash → {MUTATION_FILE.relative_to(REPO_ROOT)}")
        except Exception as exc:
            print(f"WARNING: could not sync config_hash to mutation file: {exc}", file=sys.stderr)

    print(f"\nConfig hash:  {chash}")
    print(f"Sources used: {', '.join(sources_used) or '(none)'}")
    print(f"Warnings:     {len(warnings)}")
    if warnings:
        print("[SAFETY WARNINGS]")
        for w in warnings:
            print(f"  * {w}")

    return 1 if warnings else 0


def main():
    parser = argparse.ArgumentParser(
        description="Merge BTC5 env layers into state/btc5_effective.env and reports/btc5_runtime_contract.json"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Print effective params and warnings without writing files",
    )
    args = parser.parse_args()
    sys.exit(render(check_only=args.check_only))


if __name__ == "__main__":
    main()
