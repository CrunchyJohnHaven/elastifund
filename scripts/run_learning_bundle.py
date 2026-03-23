#!/usr/bin/env python3
"""
Learning Bundle: Unified Instance 5 (new plan) — Learning Layer.

Combines research_os + architecture_alpha outputs and uses Kimi/Moonshot as the
breadth engine for failure clustering, candidate compression, and triage.
Produces the authoritative `learning_bundle` artifact that feeds the kernel's
learning stage.

Produces:
  reports/learning_bundle/latest.json            — current learning bundle
  reports/learning_bundle/history.jsonl          — append-only run ledger
  reports/autoresearch/providers/moonshot/history.jsonl — Kimi usage ledger

Inputs:
  reports/autoresearch/research_os/latest.json      — research OS outputs
  reports/architecture_alpha/latest.json             — architecture candidates
  reports/autoresearch/btc5_market/latest.json       — recent discard history
  reports/autoresearch/command_node/latest.json      — command node state

Kernel role: learning_bundle
  - May mutate: compact lane packets, ranking logic, strategy constitution
  - May NOT: submit orders, bypass promotion gates, trade directly
  - Kimi is a breadth engine, not a decision authority

Env vars required for Kimi (optional — degrades gracefully without):
  MOONSHOT_API_KEY    — Kimi/Moonshot API key (from .env)

Usage:
  python3 scripts/run_learning_bundle.py [--dry-run] [--no-kimi]

Schedule: every 2 hours (cadence: 7200s)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS = REPO_ROOT / "reports"
OUT_DIR = REPORTS / "learning_bundle"
KIMI_USAGE_DIR = REPORTS / "autoresearch" / "providers" / "moonshot"

INPUT_RESEARCH_OS = REPORTS / "autoresearch" / "research_os" / "latest.json"
INPUT_ARCH_ALPHA = REPORTS / "architecture_alpha" / "latest.json"
INPUT_MARKET_LANE = REPORTS / "autoresearch" / "btc5_market" / "latest.json"
INPUT_CN_LANE = REPORTS / "autoresearch" / "command_node" / "latest.json"

KIMI_MODEL = "moonshot-v1-8k"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_API_KEY_ENV = "MOONSHOT_API_KEY"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [learning_bundle] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("learning_bundle")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class FailureCluster:
    cluster_id: str
    label: str
    description: str
    mutation_types: list[str]
    count: int
    recommendation: str
    source: str  # "kimi" | "heuristic"


@dataclass
class RankedCandidate:
    candidate_id: str
    title: str
    impact: str
    lane: str
    triage_rank: int
    triage_rationale: str
    hash: str


@dataclass
class LearningMutation:
    mutation_id: str
    target: str  # "market_lane" | "policy_lane" | "command_node" | "constitution"
    mutation_type: str
    description: str
    expected_improvement: str
    priority: int  # 1 = highest
    blocked_by: list[str]


@dataclass
class KimiUsageRecord:
    timestamp: str
    model: str
    task: str  # "failure_clustering" | "candidate_triage" | "architecture_insight"
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    success: bool
    output_summary: str


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, label: str = "") -> dict[str, Any] | None:
    if not path.exists():
        log.info("Missing: %s%s", path.name, f" ({label})" if label else "")
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return None


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Kimi/Moonshot client (Instance 6 — real utilization)
# ---------------------------------------------------------------------------
def _call_kimi(
    prompt: str,
    task_label: str,
    api_key: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> tuple[str, KimiUsageRecord]:
    """
    Call Kimi/Moonshot API via OpenAI-compatible endpoint.
    Returns (response_text, usage_record).
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package required: pip install openai")

    client = OpenAI(api_key=api_key, base_url=KIMI_BASE_URL)
    t0 = time.monotonic()

    response = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )

    elapsed_ms = (time.monotonic() - t0) * 1000
    content = response.choices[0].message.content or ""
    usage = response.usage

    # Cost estimate: moonshot-v1-8k = $0.0001/1k tokens
    cost_per_1k = 0.0001
    total_tokens = (usage.prompt_tokens + usage.completion_tokens) if usage else 0
    cost_usd = round(total_tokens * cost_per_1k / 1000, 6)

    record = KimiUsageRecord(
        timestamp=_now_utc(),
        model=KIMI_MODEL,
        task=task_label,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        cost_usd=cost_usd,
        success=True,
        output_summary=content[:200].replace("\n", " "),
    )

    log.info(
        "Kimi %s: %d tokens, $%.6f, %.0fms",
        task_label, total_tokens, cost_usd, elapsed_ms
    )
    return content, record


# ---------------------------------------------------------------------------
# Failure clustering (heuristic fallback + Kimi when available)
# ---------------------------------------------------------------------------
def _extract_discard_summaries(market_raw: dict | None) -> list[str]:
    if not market_raw:
        return []
    summaries = []
    context = market_raw.get("latest_proposal", {}).get("context", {})
    for disc in context.get("recent_discards", []):
        mtype = disc.get("mutation_type", "unknown")
        reason = disc.get("decision_reason", "")
        loss = disc.get("loss", "?")
        summaries.append(f"{mtype} → {reason} (loss={loss})")
    # Also get from selection
    sel = market_raw.get("latest_proposal", {}).get("selection", {})
    consec = sel.get("consecutive_discards", 0)
    if consec:
        summaries.append(f"consecutive_discards={consec}")
    return summaries


def _heuristic_failure_clusters(
    market_raw: dict | None,
    cn_raw: dict | None,
) -> list[FailureCluster]:
    clusters: list[FailureCluster] = []

    # Market lane: below-frontier cluster
    if market_raw:
        sel = market_raw.get("latest_proposal", {}).get("selection", {})
        consec = sel.get("consecutive_discards", 0)
        hours = sel.get("hours_without_keep", 0)
        budget_reason = sel.get("budget_reason", "")
        mutation_type = market_raw.get("latest_proposal", {}).get("mutation_type", "unknown")

        clusters.append(FailureCluster(
            cluster_id="FC-MKT-001",
            label="below_frontier_plateau",
            description=(
                f"Market model stuck at {consec} consecutive discards over {hours:.1f}h. "
                f"Most recent mutation type: {mutation_type}."
            ),
            mutation_types=["session_focus_jitter", "ranked_hierarchy_jitter",
                            "fill_aware_pnl_jitter", "conservative_backoff_jitter",
                            "price_delta_focus_jitter"],
            count=consec,
            recommendation=(
                "Epoch renewal is the highest-probability unlock. "
                "Current epoch (Mar 10-11) is exhausted. "
                "Alternatively: try warmup_prior_shift with DOWN bias."
            ),
            source="heuristic",
        ))

        if budget_reason == "daily_budget_exhausted":
            clusters.append(FailureCluster(
                cluster_id="FC-MKT-002",
                label="budget_exhausted_noop",
                description=(
                    "Daily budget exhausted ($10/day). "
                    "System falls back to budget_fallback tier which does not use LLM. "
                    "Experiments continue but without expensive model proposals."
                ),
                mutation_types=["budget_exhausted_noop"],
                count=1,
                recommendation=(
                    "Increase daily_budget_usd or implement a 'rest' mode "
                    "that pauses expensive lanes when budget is exhausted "
                    "rather than running budget_fallback indefinitely."
                ),
                source="heuristic",
            ))

    # Command node: task penalty cluster
    if cn_raw:
        penalties = cn_raw.get("latest_proposal", {}).get("mutation_summary", {}).get("task_penalties", {})
        if penalties:
            top_penalty_tasks = sorted(penalties.items(), key=lambda x: x[1], reverse=True)
            clusters.append(FailureCluster(
                cluster_id="FC-CN-001",
                label="high_penalty_tasks",
                description=(
                    f"Command node has {len(penalties)} high-penalty tasks. "
                    f"Top: {top_penalty_tasks[0][0]} (penalty={top_penalty_tasks[0][1]:.1f})."
                ),
                mutation_types=["budget_exhausted_noop"],
                count=len(penalties),
                recommendation=(
                    "Target the highest-penalty task with targeted_task_repair mutation. "
                    f"Priority tasks: {', '.join(t for t, _ in top_penalty_tasks[:3])}."
                ),
                source="heuristic",
            ))

    return clusters


def _kimi_failure_clustering(
    discard_summaries: list[str],
    api_key: str,
) -> tuple[list[FailureCluster], KimiUsageRecord | None]:
    """Use Kimi to cluster failure modes from discard summaries."""
    if not discard_summaries:
        return [], None

    sample = discard_summaries[:50]  # Limit for token budget
    summary_text = "\n".join(f"- {s}" for s in sample)

    prompt = f"""You are analyzing a self-improving trading system's mutation history.
Below are {len(sample)} recent discard summaries from the BTC5 market model autoresearch loop.
Each entry shows: mutation_type → decision_reason (loss=value).

Discard summaries:
{summary_text}

Task: Identify 2-4 distinct failure clusters. For each cluster:
1. Give it a short label (snake_case)
2. Describe what's failing and why
3. Recommend one concrete next action

Format each cluster as:
CLUSTER: <label>
DESCRIPTION: <what's failing>
MUTATION_TYPES: <comma-separated types in this cluster>
RECOMMENDATION: <one concrete action>
---"""

    try:
        response_text, usage_record = _call_kimi(prompt, "failure_clustering", api_key)
    except Exception as exc:
        log.warning("Kimi failure clustering failed: %s", exc)
        return [], None

    # Parse Kimi's response
    clusters: list[FailureCluster] = []
    blocks = response_text.split("---")
    for i, block in enumerate(blocks):
        if "CLUSTER:" not in block:
            continue
        try:
            label = _extract_field(block, "CLUSTER").strip().replace(" ", "_").lower()
            desc = _extract_field(block, "DESCRIPTION").strip()
            mtypes_raw = _extract_field(block, "MUTATION_TYPES")
            mtypes = [m.strip() for m in mtypes_raw.split(",") if m.strip()]
            rec = _extract_field(block, "RECOMMENDATION").strip()

            if label and desc:
                clusters.append(FailureCluster(
                    cluster_id=f"FC-KIMI-{i+1:03d}",
                    label=label,
                    description=desc,
                    mutation_types=mtypes,
                    count=len([s for s in sample if any(m in s for m in mtypes)]),
                    recommendation=rec,
                    source="kimi",
                ))
        except Exception:
            continue

    log.info("Kimi produced %d failure clusters from %d discards", len(clusters), len(sample))
    return clusters, usage_record


def _extract_field(text: str, field: str) -> str:
    import re
    pattern = rf"^{re.escape(field)}:\s*(.+?)$"
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Candidate triage (heuristic + Kimi)
# ---------------------------------------------------------------------------
def _heuristic_triage(
    research_os: dict | None,
    arch_alpha: dict | None,
) -> list[RankedCandidate]:
    """Merge and rank candidates from research_os and arch_alpha."""
    ranked: list[RankedCandidate] = []
    _priority = {"critical": 1, "high": 2, "medium": 3, "low": 4}

    # From research_os opportunity_exchange
    if research_os:
        for i, opp in enumerate(research_os.get("opportunity_exchange", [])):
            ranked.append(RankedCandidate(
                candidate_id=opp.get("opp_id", f"OS-{i}"),
                title=opp.get("description", "")[:80],
                impact=opp.get("estimated_priority", "medium"),
                lane=opp.get("lane", "unknown"),
                triage_rank=_priority.get(opp.get("estimated_priority", "medium"), 99),
                triage_rationale=opp.get("rationale", ""),
                hash=opp.get("hash", ""),
            ))

    # From arch_alpha design_candidates
    if arch_alpha:
        for cand in arch_alpha.get("design_candidates", []):
            ranked.append(RankedCandidate(
                candidate_id=cand.get("candidate_id", "DC-?"),
                title=cand.get("title", "")[:80],
                impact=cand.get("impact", "medium"),
                lane="architecture",
                triage_rank=_priority.get(cand.get("impact", "medium"), 99),
                triage_rationale=cand.get("rationale", ""),
                hash=cand.get("hash", ""),
            ))

    # Sort by priority, then by ID
    ranked.sort(key=lambda c: (c.triage_rank, c.candidate_id))

    # Assign final ranks
    for i, cand in enumerate(ranked):
        cand.triage_rank = i + 1

    return ranked


def _kimi_candidate_triage(
    candidates: list[RankedCandidate],
    api_key: str,
) -> tuple[list[RankedCandidate], KimiUsageRecord | None]:
    """Use Kimi to compress and re-rank candidates with cross-domain insight."""
    if not candidates:
        return candidates, None

    # Format top candidates for Kimi
    top = candidates[:15]
    cand_text = "\n".join(
        f"{i+1}. [{c.impact.upper()}] {c.candidate_id}: {c.title}"
        for i, c in enumerate(top)
    )

    prompt = f"""You are the learning engine for an AI-run trading fund (Elastifund).
The system is a self-improving prediction market trader. Below are the top {len(top)}
improvement candidates ranked by heuristic priority.

Candidates:
{cand_text}

Context:
- The system currently has ZERO live fills (BTC5 delta threshold too tight)
- Time-of-day filter and direction filter are untested improvements
- Kimi (you) needs to start generating real value vs sitting idle
- SSH key fix unblocks VPS deploys

Task: Compress these into the TOP 5 that would produce the most compound value.
Consider: what unblocks what? What is the minimum set of changes that unlocks a cascade?

For each of your top 5, format as:
RANK: <1-5>
CANDIDATE_ID: <original ID>
REASON: <one sentence on why this is the highest-leverage action>
---"""

    try:
        response_text, usage_record = _call_kimi(prompt, "candidate_triage", api_key, max_tokens=800)
    except Exception as exc:
        log.warning("Kimi candidate triage failed: %s", exc)
        return candidates, None

    # Parse Kimi's response
    kimi_ranked: dict[str, tuple[int, str]] = {}
    blocks = response_text.split("---")
    for block in blocks:
        if "RANK:" not in block:
            continue
        try:
            rank = int(_extract_field(block, "RANK").strip())
            cid = _extract_field(block, "CANDIDATE_ID").strip()
            reason = _extract_field(block, "REASON").strip()
            if rank and cid:
                kimi_ranked[cid] = (rank, reason)
        except Exception:
            continue

    if kimi_ranked:
        # Re-rank based on Kimi's ordering
        for cand in candidates:
            if cand.candidate_id in kimi_ranked:
                kimi_rank, kimi_reason = kimi_ranked[cand.candidate_id]
                cand.triage_rank = kimi_rank
                cand.triage_rationale = f"[Kimi] {kimi_reason}"
        candidates.sort(key=lambda c: (c.triage_rank, c.candidate_id))
        # Re-assign clean sequential ranks
        for i, cand in enumerate(candidates):
            cand.triage_rank = i + 1

    log.info("Kimi re-ranked %d of %d candidates", len(kimi_ranked), len(candidates))
    return candidates, usage_record


# ---------------------------------------------------------------------------
# Learning mutations (what the bundle authorizes the lanes to try)
# ---------------------------------------------------------------------------
def _build_learning_mutations(ranked: list[RankedCandidate]) -> list[LearningMutation]:
    """Convert top ranked candidates into concrete learning mutations."""
    mutations: list[LearningMutation] = []

    # Build from top 5 critical/high candidates
    priority_counter = 1
    for cand in ranked:
        if cand.triage_rank > 8:
            break
        if cand.impact not in ("critical", "high"):
            continue

        # Map candidate to mutation target
        target = "market_lane"
        if "policy" in cand.lane.lower() or "POL-" in cand.candidate_id:
            target = "policy_lane"
        elif "command_node" in cand.lane.lower() or "CN-" in cand.candidate_id:
            target = "command_node"
        elif "architecture" in cand.lane.lower() or "DC-" in cand.candidate_id:
            target = "constitution"

        mutations.append(LearningMutation(
            mutation_id=f"LM-{priority_counter:03d}",
            target=target,
            mutation_type=_infer_mutation_type(cand),
            description=cand.title,
            expected_improvement=f"Impact: {cand.impact}",
            priority=priority_counter,
            blocked_by=[],
        ))
        priority_counter += 1
        if priority_counter > 5:
            break

    return mutations


def _infer_mutation_type(cand: RankedCandidate) -> str:
    title_lower = cand.title.lower()
    if "delta" in title_lower:
        return "parameter_shift"
    elif "time" in title_lower or "session" in title_lower:
        return "session_filter_update"
    elif "direction" in title_lower or "down" in title_lower:
        return "direction_filter_update"
    elif "kimi" in title_lower or "moonshot" in title_lower:
        return "provider_activation"
    elif "ssh" in title_lower:
        return "infrastructure_fix"
    elif "epoch" in title_lower:
        return "epoch_renewal"
    elif "wire" in title_lower or "wiring" in title_lower:
        return "module_wiring"
    return "targeted_improvement"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(dry_run: bool = False, no_kimi: bool = False) -> dict:
    generated_at = _now_utc()
    log.info("Learning Bundle starting. dry_run=%s no_kimi=%s", dry_run, no_kimi)

    # Load inputs
    research_os = _load_json(INPUT_RESEARCH_OS, "research_os")
    arch_alpha = _load_json(INPUT_ARCH_ALPHA, "architecture_alpha")
    market_raw = _load_json(INPUT_MARKET_LANE, "market_lane")
    cn_raw = _load_json(INPUT_CN_LANE, "command_node")

    inputs_loaded = {
        "research_os": research_os is not None,
        "architecture_alpha": arch_alpha is not None,
        "market_lane": market_raw is not None,
        "command_node": cn_raw is not None,
    }
    log.info("Inputs loaded: %s", inputs_loaded)

    # Failure clustering
    discard_summaries = _extract_discard_summaries(market_raw)
    failure_clusters = _heuristic_failure_clusters(market_raw, cn_raw)
    kimi_usage_records: list[KimiUsageRecord] = []

    # Kimi integration (Instance 6 — real utilization)
    api_key = os.getenv(KIMI_API_KEY_ENV, "")
    kimi_active = bool(api_key) and not no_kimi
    kimi_status = "configured" if api_key else "not_configured"

    if kimi_active:
        log.info("Kimi active: %s", KIMI_MODEL)
        # Failure clustering via Kimi
        if discard_summaries:
            kimi_clusters, usage_rec = _kimi_failure_clustering(discard_summaries, api_key)
            if kimi_clusters:
                failure_clusters = kimi_clusters + failure_clusters  # Kimi first
            if usage_rec:
                kimi_usage_records.append(usage_rec)
                kimi_status = "active"
    else:
        log.info("Kimi not active (no_kimi=%s, key_present=%s)", no_kimi, bool(api_key))

    # Candidate triage
    ranked_candidates = _heuristic_triage(research_os, arch_alpha)

    if kimi_active and ranked_candidates:
        ranked_candidates, triage_usage = _kimi_candidate_triage(ranked_candidates, api_key)
        if triage_usage:
            kimi_usage_records.append(triage_usage)

    # Learning mutations
    learning_mutations = _build_learning_mutations(ranked_candidates)

    # Kimi usage summary
    total_kimi_cost = sum(r.cost_usd for r in kimi_usage_records)
    total_kimi_tokens = sum(r.prompt_tokens + r.completion_tokens for r in kimi_usage_records)
    kimi_summary = {
        "status": kimi_status,
        "model": KIMI_MODEL,
        "calls_this_run": len(kimi_usage_records),
        "total_tokens_this_run": total_kimi_tokens,
        "total_cost_usd_this_run": round(total_kimi_cost, 6),
        "tasks_completed": [r.task for r in kimi_usage_records],
        "api_key_env": KIMI_API_KEY_ENV,
    }

    # Run hash
    run_hash = hashlib.sha256(
        f"{generated_at}:{len(failure_clusters)}:{len(ranked_candidates)}:{kimi_status}".encode()
    ).hexdigest()[:16]

    artifact = {
        "artifact": "learning_bundle",
        "schema_version": 1,
        "generated_at": generated_at,
        "run_hash": run_hash,
        "kernel_role": "learning_bundle",
        "kernel_permissions": {
            "may_mutate": ["compact_lane_packets", "ranking_logic", "strategy_constitution"],
            "may_not": ["submit_orders", "bypass_promotion_gates", "trade_directly"],
        },
        "inputs_loaded": inputs_loaded,
        "failure_clusters": [asdict(fc) for fc in failure_clusters],
        "ranked_candidates": [asdict(rc) for rc in ranked_candidates[:20]],
        "learning_mutations": [asdict(lm) for lm in learning_mutations],
        "kimi": kimi_summary,
        "research_os_summary": {
            "health": (research_os or {}).get("health", {}),
            "opportunity_count": len((research_os or {}).get("opportunity_exchange", [])),
            "constitution_rules": len((research_os or {}).get("strategy_constitution", [])),
        } if research_os else {"status": "not_loaded"},
        "arch_alpha_summary": {
            "module_count": (arch_alpha or {}).get("module_inventory", {}).get("total_modules", 0),
            "critical_candidates": [
                c["candidate_id"] for c in (arch_alpha or {}).get("design_candidates", [])
                if c.get("impact") == "critical"
            ],
        } if arch_alpha else {"status": "not_loaded"},
        "source_artifacts": [
            str(INPUT_RESEARCH_OS.relative_to(REPO_ROOT)),
            str(INPUT_ARCH_ALPHA.relative_to(REPO_ROOT)),
        ],
        "summary": (
            f"Learning Bundle. "
            f"Clusters: {len(failure_clusters)}. "
            f"Ranked candidates: {len(ranked_candidates)}. "
            f"Mutations: {len(learning_mutations)}. "
            f"Kimi: {kimi_status} "
            f"({'$' + str(round(total_kimi_cost, 6)) if kimi_active else 'not used'})."
        ),
    }

    log.info("Built artifact: %s", artifact["summary"])

    if not dry_run:
        _write_atomic(OUT_DIR / "latest.json", artifact)
        log.info("Wrote %s", OUT_DIR / "latest.json")

        ledger = {
            "generated_at": generated_at,
            "run_hash": run_hash,
            "kimi_status": kimi_status,
            "kimi_cost_usd": round(total_kimi_cost, 6),
            "kimi_tokens": total_kimi_tokens,
            "failure_cluster_count": len(failure_clusters),
            "ranked_candidate_count": len(ranked_candidates),
            "mutation_count": len(learning_mutations),
            "inputs_loaded": inputs_loaded,
        }
        _append_jsonl(OUT_DIR / "history.jsonl", ledger)
        log.info("Appended to learning_bundle/history.jsonl")

        # Write Kimi usage records (Instance 6 — usage history)
        for usage_rec in kimi_usage_records:
            _append_jsonl(KIMI_USAGE_DIR / "history.jsonl", asdict(usage_rec))
            log.info(
                "Kimi usage: task=%s tokens=%d cost=$%.6f",
                usage_rec.task, usage_rec.prompt_tokens + usage_rec.completion_tokens,
                usage_rec.cost_usd,
            )

        # Write Kimi latest status
        _write_atomic(KIMI_USAGE_DIR / "latest.json", {
            "artifact": "kimi_usage_status",
            "generated_at": generated_at,
            "status": kimi_status,
            "model": KIMI_MODEL,
            "api_key_env": KIMI_API_KEY_ENV,
            "last_run_cost_usd": round(total_kimi_cost, 6),
            "last_run_tokens": total_kimi_tokens,
            "last_run_tasks": [r.task for r in kimi_usage_records],
            "history_path": "reports/autoresearch/providers/moonshot/history.jsonl",
            "note": (
                "Kimi is the breadth engine for failure clustering and candidate triage. "
                "It may not make trading decisions or bypass promotion gates."
            ),
        })
        log.info("Wrote Kimi usage status to %s", KIMI_USAGE_DIR / "latest.json")
    else:
        log.info("[dry-run] Would write to %s", OUT_DIR / "latest.json")

    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Learning Bundle: unified learning layer with Kimi integration."
    )
    parser.add_argument("--dry-run", action="store_true", help="Build artifact, do not write.")
    parser.add_argument(
        "--no-kimi", action="store_true",
        help="Skip Kimi API calls (useful for offline testing)."
    )
    args = parser.parse_args()

    try:
        artifact = run(dry_run=args.dry_run, no_kimi=args.no_kimi)
        print(json.dumps({"status": "ok", "summary": artifact["summary"]}, indent=2))
        sys.exit(0)
    except Exception as exc:
        log.exception("Learning Bundle failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
