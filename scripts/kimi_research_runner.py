#!/usr/bin/env python3
"""Kimi (Moonshot AI) Research Runner — learning-layer breadth engine.

Routes Kimi into three research lanes that benefit from cheap, high-throughput
inference:

  1. failure_clustering   — classify recent cycle failures by root-cause bucket
  2. packet_compression   — shorten tournament prompts without losing accuracy
  3. candidate_triage     — rank hypothesis candidates by novelty score

Each lane writes to:
  reports/autoresearch/providers/moonshot/history.jsonl   (append-only)
  reports/autoresearch/providers/moonshot/status.json     (latest activity)

The runner is safe to call with no MOONSHOT_API_KEY; it will exit cleanly with
a "configured_only" status and zero spend.

Usage:
  python -m scripts.kimi_research_runner [--lane all|failure_clustering|packet_compression|candidate_triage]
  python -m scripts.kimi_research_runner --lane failure_clustering
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_DIR = ROOT / "reports" / "autoresearch" / "providers" / "moonshot"
NOVELTY_LATEST = ROOT / "reports" / "autoresearch" / "novelty_discovery" / "latest.json"
NOVEL_EDGE_LATEST = ROOT / "reports" / "autoresearch" / "novel_edge" / "latest.json"
AUTORESEARCH_LATEST = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
CYCLE_CORE_LATEST = ROOT / "reports" / "btc5_autoresearch" / "latest.json"

MOONSHOT_MODEL = "moonshot-v1-8k"
MAX_TOKENS = 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_jsonl(path: Path, last_n: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:  # noqa: BLE001
        pass
    return rows[-last_n:]


def _write_usage(
    *,
    lane: str,
    model: str,
    prompt: str,
    response: str,
    cost_usd: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one usage record to the Moonshot history ledger."""
    record = {
        "ts": _now_utc().isoformat(),
        "epoch_s": time.time(),
        "provider": "moonshot",
        "model": model,
        "lane": lane,
        "prompt_chars": len(prompt),
        "response_chars": len(response),
        "tokens_estimate": int((len(prompt) + len(response)) / 4),
        "cost_usd": round(cost_usd, 8),
        **(metadata or {}),
    }
    PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    history_path = PROVIDER_DIR / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    status = {
        "provider": "moonshot",
        "status": "active",
        "last_used_at": record["ts"],
        "last_lane": lane,
        "last_model": model,
        "last_cost_usd": record["cost_usd"],
    }
    (PROVIDER_DIR / "status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )


def _estimate_cost(prompt: str, response: str, model: str = MOONSHOT_MODEL) -> float:
    cost_per_1k = {"moonshot-v1-8k": 0.0001, "moonshot-v1-32k": 0.0002}.get(model, 0.0001)
    tokens = (len(prompt) + len(response)) / 4.0
    return (tokens / 1000.0) * cost_per_1k


# ---------------------------------------------------------------------------
# OpenAI-compat client (lazy)
# ---------------------------------------------------------------------------


def _get_client() -> Any | None:
    """Return an AsyncOpenAI-compatible client for Moonshot, or None if no key."""
    api_key = os.environ.get("MOONSHOT_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    except ImportError:
        return None


async def _call_kimi(client: Any, prompt: str, *, model: str = MOONSHOT_MODEL) -> str:
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Lane 1: Failure Clustering
# ---------------------------------------------------------------------------


async def run_failure_clustering(client: Any) -> dict[str, Any]:
    """Classify recent autoresearch cycle failures into root-cause buckets."""
    # Gather recent failure data from cycle history
    cycles_jsonl = ROOT / "reports" / "btc5_autoresearch" / "cycles.jsonl"
    recent_cycles = _load_jsonl(cycles_jsonl, last_n=20)
    failures = [
        c for c in recent_cycles
        if str((c.get("decision") or {}).get("action") or "").lower() in {"hold", "error"}
    ]

    if not failures:
        return {
            "lane": "failure_clustering",
            "status": "skipped",
            "reason": "no_recent_failures_in_cycles_jsonl",
        }

    # Summarise failure context compactly for Kimi
    failure_snippets = []
    for c in failures[-10:]:
        decision = c.get("decision") or {}
        failure_snippets.append(
            f"- action={decision.get('action')} reason={decision.get('reason')} "
            f"missing_evidence={decision.get('package_missing_evidence', [])}"
        )
    failure_text = "\n".join(failure_snippets)

    prompt = f"""You are analyzing trading system autoresearch failures.
Classify these recent cycle outcomes into root-cause buckets.
Return 3-5 buckets with name, count, and one-sentence description.
Format: JSON array of {{"bucket": str, "count": int, "description": str}}.

Recent outcomes:
{failure_text}

Respond with only valid JSON."""

    response = await _call_kimi(client, prompt)
    cost = _estimate_cost(prompt, response)

    # Try to parse Kimi's JSON output
    clusters: list[dict] = []
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        clusters = json.loads(cleaned)
    except Exception:  # noqa: BLE001
        clusters = [{"bucket": "parse_error", "count": len(failures), "description": response[:200]}]

    _write_usage(
        lane="failure_clustering",
        model=MOONSHOT_MODEL,
        prompt=prompt,
        response=response,
        cost_usd=cost,
        metadata={"failure_count": len(failures), "cluster_count": len(clusters)},
    )

    # Write lane output
    output = {
        "generated_at": _now_utc().isoformat(),
        "lane": "failure_clustering",
        "failure_count": len(failures),
        "clusters": clusters,
        "cost_usd": cost,
    }
    lane_dir = PROVIDER_DIR / "lanes"
    lane_dir.mkdir(parents=True, exist_ok=True)
    (lane_dir / "failure_clustering_latest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    return output


# ---------------------------------------------------------------------------
# Lane 2: Packet Compression
# ---------------------------------------------------------------------------


async def run_packet_compression(client: Any) -> dict[str, Any]:
    """Suggest compressed tournament prompts based on novel_edge artifacts."""
    novel_edge = _load_json(NOVEL_EDGE_LATEST)
    if not novel_edge:
        return {
            "lane": "packet_compression",
            "status": "skipped",
            "reason": "novel_edge_artifact_missing",
        }

    top_edge = novel_edge.get("top_edge") or {}
    thesis_prompt = novel_edge.get("thesis_prompt", "")

    prompt = f"""You are optimizing LLM tournament prompts for a prediction market trading system.
The current thesis signal is:
"{thesis_prompt}"

Top edge: dimension={top_edge.get('dimension')} segment={top_edge.get('segment')}
win_rate={top_edge.get('win_rate')} pnl_usd={top_edge.get('pnl_usd')}

Produce a compressed (under 80 words) tournament question packet that:
1. Captures the core edge hypothesis
2. Eliminates anchoring (no market price)
3. Focuses on the specific time/direction segment
4. Is suitable for a 3-model ensemble

Return only the compressed packet text, no explanation."""

    response = await _call_kimi(client, prompt)
    cost = _estimate_cost(prompt, response)

    _write_usage(
        lane="packet_compression",
        model=MOONSHOT_MODEL,
        prompt=prompt,
        response=response,
        cost_usd=cost,
        metadata={
            "top_edge_dimension": top_edge.get("dimension"),
            "top_edge_segment": top_edge.get("segment"),
        },
    )

    output = {
        "generated_at": _now_utc().isoformat(),
        "lane": "packet_compression",
        "compressed_packet": response.strip(),
        "source_thesis_prompt": thesis_prompt,
        "cost_usd": cost,
    }
    lane_dir = PROVIDER_DIR / "lanes"
    lane_dir.mkdir(parents=True, exist_ok=True)
    (lane_dir / "packet_compression_latest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    return output


# ---------------------------------------------------------------------------
# Lane 3: Candidate Triage
# ---------------------------------------------------------------------------


async def run_candidate_triage(client: Any) -> dict[str, Any]:
    """Rank hypothesis candidates by novelty score using Kimi."""
    novelty = _load_json(NOVELTY_LATEST)
    autoresearch = _load_json(AUTORESEARCH_LATEST)

    segments = (novelty.get("segments") or {}).get("by_direction_x_session") or []
    edge_count = (novelty.get("obs_filled_count") or 0)

    # Build candidate list from autoresearch surface
    candidates_raw = []
    for key in ("global_best_candidate", "regime_best_candidate", "hypothesis_best_candidate"):
        c = autoresearch.get(key) or {}
        if c:
            candidates_raw.append({
                "source": key,
                "profile_name": c.get("profile_name") or c.get("name") or "unknown",
                "evidence_band": c.get("evidence_band") or "unknown",
                "validation_rows": c.get("validation_live_filled_rows") or 0,
            })

    if not candidates_raw:
        return {
            "lane": "candidate_triage",
            "status": "skipped",
            "reason": "no_candidates_in_autoresearch_latest",
        }

    candidate_text = "\n".join(
        f"- source={c['source']} profile={c['profile_name']} "
        f"evidence={c['evidence_band']} rows={c['validation_rows']}"
        for c in candidates_raw
    )
    segment_text = "\n".join(
        f"  {s.get('segment')}: fills={s.get('fills')} WR={s.get('win_rate')} PnL={s.get('pnl_usd')}"
        for s in segments[:5]
    )

    prompt = f"""You are triaging trading strategy candidates for a prediction market system.
Total observed fills: {edge_count}

Top performance segments:
{segment_text}

Candidates to rank (by expected novelty and evidence strength):
{candidate_text}

Rank these candidates from most to least promising.
Return JSON array: [{{"rank": int, "source": str, "rationale": str (max 20 words)}}]
Respond with only valid JSON."""

    response = await _call_kimi(client, prompt)
    cost = _estimate_cost(prompt, response)

    ranked: list[dict] = []
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        ranked = json.loads(cleaned)
    except Exception:  # noqa: BLE001
        ranked = [{"rank": 1, "source": c["source"], "rationale": "parse_error"} for c in candidates_raw]

    _write_usage(
        lane="candidate_triage",
        model=MOONSHOT_MODEL,
        prompt=prompt,
        response=response,
        cost_usd=cost,
        metadata={"candidate_count": len(candidates_raw), "ranked_count": len(ranked)},
    )

    output = {
        "generated_at": _now_utc().isoformat(),
        "lane": "candidate_triage",
        "candidate_count": len(candidates_raw),
        "ranked_candidates": ranked,
        "cost_usd": cost,
    }
    lane_dir = PROVIDER_DIR / "lanes"
    lane_dir.mkdir(parents=True, exist_ok=True)
    (lane_dir / "candidate_triage_latest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    return output


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _run_all_lanes(client: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for lane_fn, lane_name in [
        (run_failure_clustering, "failure_clustering"),
        (run_packet_compression, "packet_compression"),
        (run_candidate_triage, "candidate_triage"),
    ]:
        try:
            result = await lane_fn(client)
            results[lane_name] = result
        except Exception as exc:  # noqa: BLE001
            results[lane_name] = {"lane": lane_name, "status": "error", "error": str(exc)}
    return results


async def _run_one_lane(client: Any, lane: str) -> dict[str, Any]:
    dispatch = {
        "failure_clustering": run_failure_clustering,
        "packet_compression": run_packet_compression,
        "candidate_triage": run_candidate_triage,
    }
    fn = dispatch.get(lane)
    if fn is None:
        return {"error": f"unknown lane: {lane!r}"}
    return await fn(client)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Kimi research runner — breadth engine for learning layer"
    )
    p.add_argument(
        "--lane",
        default="all",
        choices=["all", "failure_clustering", "packet_compression", "candidate_triage"],
        help="Which research lane to run (default: all)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent but skip live API calls",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    api_key = os.environ.get("MOONSHOT_API_KEY", "")
    if not api_key:
        print("MOONSHOT_API_KEY not set — marking provider as configured_only and exiting.")
        PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
        status_path = PROVIDER_DIR / "status.json"
        if not status_path.exists():
            status_path.write_text(
                json.dumps(
                    {
                        "provider": "moonshot",
                        "status": "configured_only",
                        "last_used_at": None,
                        "last_lane": None,
                        "note": "Set MOONSHOT_API_KEY to activate. Endpoint: https://api.moonshot.cn/v1",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return 0

    if args.dry_run:
        print(f"[dry-run] Would run lane={args.lane} with model={MOONSHOT_MODEL}")
        print(f"[dry-run] Provider dir: {PROVIDER_DIR}")
        return 0

    client = _get_client()
    if client is None:
        print("openai package not installed — cannot create compat client.")
        return 1

    async def _main_async() -> dict[str, Any]:
        if args.lane == "all":
            return await _run_all_lanes(client)
        return {args.lane: await _run_one_lane(client, args.lane)}

    results = asyncio.run(_main_async())

    for lane_name, result in results.items():
        status = result.get("status", "ok")
        cost = result.get("cost_usd", 0.0)
        print(f"[{lane_name}] status={status}  cost=${cost:.6f}")

    total_cost = sum(
        float(r.get("cost_usd") or 0) for r in results.values()
    )
    print(f"Total spend this run: ${total_cost:.6f}")
    print(f"History → {PROVIDER_DIR / 'history.jsonl'}")
    print(f"Status  → {PROVIDER_DIR / 'status.json'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
