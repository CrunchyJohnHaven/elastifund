"""Cost ledger — lightweight per-invocation cost tracker.

Appends one JSON line per invocation to data/cost_ledger.jsonl.
Used by all Elastifund scripts to track API spend vs deterministic paths.

Usage:
    from scripts.cost_ledger import log_invocation

    log_invocation(
        task_class="backfill",
        execution_path="deterministic",
        duration_seconds=1.4,
    )

    log_invocation(
        task_class="autoresearch",
        execution_path="api_sonnet",
        estimated_tokens=12000,
        estimated_cost_usd=0.036,
        cache_hit=False,
        duration_seconds=45.2,
    )

Query total cost:
    python3 scripts/cost_ledger.py --summary
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/cost_ledger.jsonl")

# Approximate cost per 1K tokens (Anthropic pricing as of 2026-03, input+output blended).
COST_PER_1K_TOKENS = {
    "api_haiku": 0.000375,    # claude-haiku-4-5: $0.25/1M in + $1.25/1M out (blended ~$0.375/1M)
    "api_sonnet": 0.015,      # claude-sonnet-4-6: $3/1M in + $15/1M out (blended ~$15/1M)
    "api_opus": 0.075,        # claude-opus-4-6 estimate
    "deterministic": 0.0,
    "cached": 0.0,
}


def log_invocation(
    task_class: str,
    execution_path: str,
    duration_seconds: float = 0.0,
    estimated_tokens: int = 0,
    estimated_cost_usd: float | None = None,
    cache_hit: bool = False,
    notes: str = "",
) -> None:
    """Append one cost record to the ledger.

    Args:
        task_class: One of: backfill, monitor, frontier, autoresearch, trading, promote
        execution_path: One of: deterministic, cached, api_haiku, api_sonnet, api_opus
        duration_seconds: Wall-clock seconds this invocation took.
        estimated_tokens: Total token count (input + output). 0 for deterministic.
        estimated_cost_usd: Override cost if known. Computed from tokens if None.
        cache_hit: True if LLM prompt cache was hit.
        notes: Free-text annotation.
    """
    if estimated_cost_usd is None:
        rate = COST_PER_1K_TOKENS.get(execution_path, 0.0)
        estimated_cost_usd = estimated_tokens * rate / 1000.0

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_class": task_class,
        "execution_path": execution_path,
        "cache_hit": cache_hit,
        "estimated_tokens": estimated_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "duration_seconds": round(duration_seconds, 2),
        "notes": notes,
    }

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def _load_records() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    records = []
    for line in LEDGER_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def summarize(days: int = 7) -> dict:
    """Summarize cost ledger for last N days."""
    records = _load_records()
    cutoff = time.time() - days * 86400

    recent = []
    for r in records:
        try:
            ts = datetime.fromisoformat(r["timestamp"]).timestamp()
            if ts >= cutoff:
                recent.append(r)
        except Exception:
            pass

    total_cost = sum(r.get("estimated_cost_usd", 0) for r in recent)
    total_tokens = sum(r.get("estimated_tokens", 0) for r in recent)
    by_path: dict[str, dict] = {}
    by_class: dict[str, dict] = {}

    for r in recent:
        path = r.get("execution_path", "unknown")
        cls = r.get("task_class", "unknown")
        for key, bucket in [(path, by_path), (cls, by_class)]:
            if key not in bucket:
                bucket[key] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            bucket[key]["calls"] += 1
            bucket[key]["cost_usd"] = round(bucket[key]["cost_usd"] + r.get("estimated_cost_usd", 0), 6)
            bucket[key]["tokens"] += r.get("estimated_tokens", 0)

    return {
        "period_days": days,
        "total_records": len(recent),
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        "by_execution_path": by_path,
        "by_task_class": by_class,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cost ledger query tool")
    parser.add_argument("--summary", action="store_true", help="Print cost summary")
    parser.add_argument("--days", type=int, default=7, help="Days to summarize (default: 7)")
    parser.add_argument("--total", action="store_true", help="Print total cost only (all time)")
    args = parser.parse_args()

    if args.total:
        records = _load_records()
        total = sum(r.get("estimated_cost_usd", 0) for r in records)
        print(f"Total cost (all time): ${total:.4f} ({len(records)} records)")
        sys.exit(0)

    if args.summary or True:  # Default to summary.
        s = summarize(days=args.days)
        print(f"\nCost summary — last {s['period_days']} days")
        print(f"  Records: {s['total_records']}")
        print(f"  Total cost: ${s['total_cost_usd']:.4f}")
        print(f"  Total tokens: {s['total_tokens']:,}")
        if s["by_execution_path"]:
            print("\n  By execution path:")
            for path, d in sorted(s["by_execution_path"].items(), key=lambda x: -x[1]["cost_usd"]):
                print(f"    {path:20s} {d['calls']:4d} calls  ${d['cost_usd']:.4f}  {d['tokens']:,} tokens")
        if s["by_task_class"]:
            print("\n  By task class:")
            for cls, d in sorted(s["by_task_class"].items(), key=lambda x: -x[1]["cost_usd"]):
                print(f"    {cls:20s} {d['calls']:4d} calls  ${d['cost_usd']:.4f}")
