#!/usr/bin/env python3
"""Retention policy helpers for timestamped report snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
RETENTION_POLICY_PATH = REPORTS / "retention_policy.json"


def _normalize(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def retention_days_for(path: str | Path, policy: dict[str, Any], explicit_days: int | None) -> int:
    """Resolve retention days using the longest matching override prefix."""
    if explicit_days is not None:
        return int(explicit_days)

    default_days = int(policy.get("default_policy", {}).get("retain_days", 0) or 0)
    overrides = policy.get("overrides", {})
    if not isinstance(overrides, dict):
        return default_days

    normalized_path = _normalize(path)
    best_days = default_days
    best_len = -1

    for prefix, config in overrides.items():
        if not isinstance(config, dict):
            continue
        normalized_prefix = _normalize(prefix)
        if not normalized_prefix:
            continue
        if normalized_path == normalized_prefix or normalized_path.startswith(f"{normalized_prefix}/"):
            if len(normalized_prefix) > best_len:
                best_len = len(normalized_prefix)
                best_days = int(config.get("retain_days", default_days) or default_days)
    return best_days


def load_policy(path: Path = RETENTION_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Report path to evaluate")
    parser.add_argument("--days", type=int, default=None, help="Explicit retention override")
    parser.add_argument("--policy", type=Path, default=RETENTION_POLICY_PATH, help="Path to retention policy JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.path:
        print(json.dumps({"error": "path argument required"}))
        return 2

    policy = load_policy(args.policy)
    print(
        json.dumps(
            {
                "path": args.path,
                "retain_days": retention_days_for(args.path, policy, explicit_days=args.days),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
