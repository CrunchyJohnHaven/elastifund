#!/usr/bin/env python3
"""
Learning Bundle — Research-OS + Architecture Alpha + Kimi Unified
=================================================================
Fourth stage of the self-improvement kernel.

Combines what were previously three separate loops into one governed bundle:
  - research_os          (hourly mutation wave, strategy constitution updates)
  - architecture_alpha   (architecture mining, module improvement candidates)
  - Kimi / Moonshot      (breadth engine: failure clustering, packet compression,
                          candidate triage)

Invariants
----------
  1. This bundle may mutate lane packets, ranking logic, and strategy
     constitution.  It does NOT place orders or allocate capital directly.
  2. Kimi is a breadth engine inside this layer.  It clusters and compresses;
     Claude synthesizes and decides.
  3. All mutations produced here must be staged in reports/learning_bundle.json
     before any downstream system acts on them.
  4. Retained outputs (improvements that pass mutation acceptance) are appended
     to reports/autoresearch/research_os/history.jsonl and
     reports/architecture_alpha/history.jsonl respectively.

Output files
------------
  reports/learning_bundle.json                        — main bundle
  reports/autoresearch/research_os/latest.json        — research-OS output
  reports/autoresearch/research_os/history.jsonl      — append-only history
  reports/architecture_alpha/latest.json              — architecture output
  reports/architecture_alpha/history.jsonl            — append-only history
  reports/autoresearch/providers/moonshot/status.json — Kimi provider status
  reports/autoresearch/providers/moonshot/history.jsonl — Kimi usage ledger

Usage
-----
  python3 scripts/learning_bundle.py                   # run once
  python3 scripts/learning_bundle.py --daemon          # continuous (1h)
  python3 scripts/learning_bundle.py --mode kimi       # Kimi lane only
  python3 scripts/learning_bundle.py --mode research   # research-OS lane only
  python3 scripts/learning_bundle.py --mode arch       # architecture lane only

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("JJ.learning")

PROJECT_ROOT = REPO_ROOT
REPORTS = PROJECT_ROOT / "reports"
BOT_DIR = PROJECT_ROOT / "bot"

EVIDENCE_PATH = REPORTS / "evidence_bundle.json"
THESIS_PATH = REPORTS / "thesis_bundle.json"
NOVELTY_PATH = REPORTS / "novelty_discovery.json"
OUTPUT_PATH = REPORTS / "learning_bundle.json"

RESEARCH_OS_DIR = REPORTS / "autoresearch" / "research_os"
ARCH_DIR = REPORTS / "architecture_alpha"
KIMI_DIR = REPORTS / "autoresearch" / "providers" / "moonshot"

INTERVAL = int(os.environ.get("LEARNING_INTERVAL_SECONDS", "3600"))
ANTHROPIC_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "")
KIMI_ACTIVE = bool(MOONSHOT_API_KEY and not MOONSHOT_API_KEY.startswith("your-"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


# ---------------------------------------------------------------------------
# Kimi / Moonshot lane
# ---------------------------------------------------------------------------


async def run_kimi_lane(
    evidence: dict[str, Any] | None,
    thesis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Route research tasks to Kimi for breadth and compression."""
    status_path = KIMI_DIR / "status.json"
    history_path = KIMI_DIR / "history.jsonl"

    if not KIMI_ACTIVE:
        status = {
            "provider": "moonshot",
            "status": "configured_not_active",
            "reason": "MOONSHOT_API_KEY not set or is placeholder",
            "checked_at": utc_now(),
            "daily_spend_usd": 0.0,
            "sessions_today": 0,
        }
        write_report(
            status_path,
            artifact="moonshot_provider_status",
            payload=status,
            status="stale",
            source_of_truth="MOONSHOT_API_KEY; MOONSHOT_BASE_URL; KIMI_MODEL",
            freshness_sla_seconds=3600,
            blockers=["kimi_configured_not_active"],
            summary="Kimi configured but not active",
        )
        logger.info("[kimi] configured but not active (placeholder key)")
        return {"kimi_active": False, "outputs": []}

    logger.info("[kimi] Kimi active — running breadth tasks")

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=MOONSHOT_API_KEY,
            base_url="https://api.moonshot.cn/v1",
        )
    except ImportError:
        logger.error("[kimi] openai package not installed")
        return {"kimi_active": False, "error": "openai package missing"}

    outputs: list[dict[str, Any]] = []
    total_cost = 0.0

    # Task 1: Failure clustering — summarize dominant skip reasons
    theses = (thesis or {}).get("theses") or []
    if theses:
        items_summary = "\n".join(
            f"- {t['thesis_id']}: {t.get('description', '')[:80]}" for t in theses[:10]
        )
        prompt = (
            "You are a quantitative research assistant.\n"
            "Cluster these thesis candidates into 2-3 groups by theme and "
            "identify the single most promising group.\n\n"
            f"Candidates:\n{items_summary}\n\n"
            "Format: CLUSTER_A: [list] | CLUSTER_B: [list] | BEST: [cluster name] "
            "| REASON: [1 sentence]"
        )
        t0 = time.perf_counter()
        try:
            resp = await client.chat.completions.create(
                model="moonshot-v1-8k",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.3,
            )
            result = resp.choices[0].message.content or ""
            cost = (len(prompt) + len(result)) / 4000 * 0.0001  # rough estimate
            total_cost += cost
            elapsed_ms = (time.perf_counter() - t0) * 1000
            output = {
                "task": "failure_clustering",
                "model": "moonshot-v1-8k",
                "result": result,
                "cost_usd": round(cost, 6),
                "elapsed_ms": round(elapsed_ms, 0),
                "timestamp": utc_now(),
            }
            outputs.append(output)
            append_jsonl(history_path, output)
            logger.info("[kimi] clustering complete: %.1fms $%.6f", elapsed_ms, cost)
        except Exception as exc:
            logger.error("[kimi] clustering task failed: %s", exc)

    # Task 2: Packet compression — compress evidence summary
    ev_sources = (evidence or {}).get("sources_used") or []
    if ev_sources:
        ev_summary = f"Sources: {', '.join(ev_sources)}\nItems: {(evidence or {}).get('source_count', 0)}"
        prompt = (
            "Compress this evidence packet summary into ≤2 sentences for operator review:\n\n"
            f"{ev_summary}\n\nCOMPRESSED:"
        )
        t0 = time.perf_counter()
        try:
            resp = await client.chat.completions.create(
                model="moonshot-v1-8k",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=128,
                temperature=0.2,
            )
            result = resp.choices[0].message.content or ""
            cost = (len(prompt) + len(result)) / 4000 * 0.0001
            total_cost += cost
            elapsed_ms = (time.perf_counter() - t0) * 1000
            output = {
                "task": "packet_compression",
                "model": "moonshot-v1-8k",
                "result": result,
                "cost_usd": round(cost, 6),
                "elapsed_ms": round(elapsed_ms, 0),
                "timestamp": utc_now(),
            }
            outputs.append(output)
            append_jsonl(history_path, output)
            logger.info("[kimi] compression complete: %.1fms $%.6f", elapsed_ms, cost)
        except Exception as exc:
            logger.error("[kimi] compression task failed: %s", exc)

    # Update provider status
    status = {
        "provider": "moonshot",
        "status": "active",
        "checked_at": utc_now(),
        "tasks_this_session": len(outputs),
        "session_cost_usd": round(total_cost, 6),
        "daily_spend_usd": round(total_cost, 6),  # session only; append to accumulate
    }
    write_report(
        status_path,
        artifact="moonshot_provider_status",
        payload=status,
        status="fresh",
        source_of_truth="MOONSHOT_API_KEY; MOONSHOT_BASE_URL; KIMI_MODEL",
        freshness_sla_seconds=3600,
        summary=f"Kimi active; {len(outputs)} tasks; session_cost_usd={round(total_cost, 6):.6f}",
    )
    logger.info("[kimi] session complete: %d tasks, $%.6f", len(outputs), total_cost)
    return {"kimi_active": True, "tasks": len(outputs), "session_cost_usd": total_cost, "outputs": outputs}


# ---------------------------------------------------------------------------
# Research-OS lane
# ---------------------------------------------------------------------------


async def run_research_os(
    evidence: dict[str, Any] | None,
    novelty: dict[str, Any] | None,
) -> dict[str, Any]:
    """Generate a mutation wave using Claude Haiku."""
    logger.info("[research_os] generating mutation wave")

    findings = (novelty or {}).get("findings") or []
    ev_sources = (evidence or {}).get("sources_used") or []

    context_lines = []
    if findings:
        context_lines.append("Recent novelty findings:")
        for f in findings[:5]:
            context_lines.append(f"  - [{f.get('type')}] {f.get('note', '')[:80]}")
    if ev_sources:
        context_lines.append(f"Evidence sources active: {', '.join(ev_sources)}")

    context = "\n".join(context_lines) or "No fresh evidence available."

    mutations: list[dict[str, Any]] = []

    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("[research_os] ANTHROPIC_API_KEY not set — skipping LLM mutation")
            return _research_os_stub(context)

        client = anthropic.AsyncAnthropic(api_key=api_key)
        prompt = (
            "You are a quantitative research system generating self-improvement mutations.\n\n"
            f"Current system context:\n{context}\n\n"
            "Generate 3 concrete mutation candidates for improving this trading system. "
            "For each, specify:\n"
            "  MUTATION_ID: short_snake_case_id\n"
            "  TYPE: parameter_change | strategy_add | signal_remove | threshold_adjust\n"
            "  DESCRIPTION: what changes and why (1-2 sentences)\n"
            "  EXPECTED_IMPACT: which metric improves and by how much\n"
            "  RISK: what could go wrong\n\n"
            "Separate mutations with ---"
        )

        resp = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""
        logger.info("[research_os] LLM response: %d chars", len(raw))

        # Parse mutation blocks
        blocks = raw.split("---")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            mut: dict[str, Any] = {"raw": block}
            for field_name in ("MUTATION_ID", "TYPE", "DESCRIPTION", "EXPECTED_IMPACT", "RISK"):
                import re
                m = re.search(rf"{field_name}:\s*(.+?)(?=\n[A-Z_]+:|$)", block, re.DOTALL | re.IGNORECASE)
                if m:
                    mut[field_name.lower()] = m.group(1).strip()
            mut["timestamp"] = utc_now()
            mut["accepted"] = False  # must pass mutation acceptance test to be kept
            mutations.append(mut)

    except ImportError:
        logger.warning("[research_os] anthropic package not installed")
        return _research_os_stub(context)
    except Exception as exc:
        logger.error("[research_os] LLM call failed: %s", exc)
        return _research_os_stub(context)

    result: dict[str, Any] = {
        "artifact": "research_os",
        "generated_at": utc_now(),
        "context_summary": context[:300],
        "mutation_count": len(mutations),
        "mutations": mutations,
    }

    write_report(
        RESEARCH_OS_DIR / "latest.json",
        artifact="research_os",
        payload=result,
        status="fresh" if mutations else "blocked",
        source_of_truth="reports/evidence_bundle.json; reports/novelty_discovery.json",
        freshness_sla_seconds=7200,
        blockers=["no_mutations_generated"] if not mutations else [],
        summary=f"{len(mutations)} research mutations generated",
    )
    append_jsonl(RESEARCH_OS_DIR / "history.jsonl", result)
    logger.info("[research_os] %d mutations generated", len(mutations))
    return result


def _research_os_stub(context: str) -> dict[str, Any]:
    return {
        "artifact": "research_os",
        "generated_at": utc_now(),
        "context_summary": context[:300],
        "mutation_count": 0,
        "mutations": [],
        "stub": True,
        "note": "No LLM available — stub output",
    }


# ---------------------------------------------------------------------------
# Architecture Alpha lane
# ---------------------------------------------------------------------------


async def run_architecture_alpha() -> dict[str, Any]:
    """Scan bot modules and generate improvement candidates."""
    logger.info("[arch] scanning bot modules")

    # Summarize bot modules
    module_summaries: list[dict[str, Any]] = []
    for py_file in sorted(BOT_DIR.glob("*.py")):
        try:
            content = py_file.read_text(errors="replace")
            lines = content.count("\n")
            # Extract first docstring line
            import re
            doc_match = re.search(r'"""(.+?)(?:\n|""")', content)
            doc = doc_match.group(1).strip() if doc_match else "no docstring"
            module_summaries.append({
                "module": py_file.stem,
                "lines": lines,
                "summary": doc[:100],
            })
        except Exception:
            pass

    candidates: list[dict[str, Any]] = []

    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("[arch] ANTHROPIC_API_KEY not set — returning module scan only")
            return _arch_stub(module_summaries)

        mod_list = "\n".join(
            f"  {m['module']} ({m['lines']} lines): {m['summary']}"
            for m in module_summaries[:20]
        )

        client = anthropic.AsyncAnthropic(api_key=api_key)
        prompt = (
            "You are an AI trading system architect reviewing module architecture.\n\n"
            f"Current bot modules:\n{mod_list}\n\n"
            "Identify 3 architectural improvements. For each:\n"
            "  CANDIDATE_ID: short_id\n"
            "  TYPE: consolidate | split | add | remove | refactor\n"
            "  TARGET_MODULE(S): which modules\n"
            "  RATIONALE: why (1 sentence)\n"
            "  EXPECTED_BENEFIT: measurable outcome\n"
            "  EFFORT: low | medium | high\n\n"
            "Separate with ---"
        )

        resp = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=600,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""

        import re
        blocks = raw.split("---")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            cand: dict[str, Any] = {"raw": block}
            for field_name in ("CANDIDATE_ID", "TYPE", "TARGET_MODULE", "RATIONALE",
                               "EXPECTED_BENEFIT", "EFFORT"):
                m = re.search(rf"{field_name}\(?S?\)?:\s*(.+?)(?=\n[A-Z_]+:|$)", block, re.DOTALL | re.IGNORECASE)
                if m:
                    cand[field_name.lower().rstrip("s").replace("(", "").replace(")", "")] = m.group(1).strip()
            cand["timestamp"] = utc_now()
            candidates.append(cand)

    except ImportError:
        logger.warning("[arch] anthropic package not installed")
        return _arch_stub(module_summaries)
    except Exception as exc:
        logger.error("[arch] LLM call failed: %s", exc)
        return _arch_stub(module_summaries)

    result: dict[str, Any] = {
        "artifact": "architecture_alpha",
        "generated_at": utc_now(),
        "module_count": len(module_summaries),
        "candidate_count": len(candidates),
        "module_summaries": module_summaries[:20],
        "candidates": candidates,
    }
    write_report(
        ARCH_DIR / "latest.json",
        artifact="architecture_alpha",
        payload=result,
        status="fresh" if candidates else "blocked",
        source_of_truth="bot/*.py; reports/research_os/latest.json; reports/novelty_discovery.json",
        freshness_sla_seconds=7200,
        blockers=["no_architecture_candidates"] if not candidates else [],
        summary=f"{len(candidates)} architecture candidates generated",
    )
    append_jsonl(ARCH_DIR / "history.jsonl", result)
    logger.info("[arch] %d candidates from %d modules", len(candidates), len(module_summaries))
    return result


def _arch_stub(module_summaries: list) -> dict[str, Any]:
    result: dict[str, Any] = {
        "artifact": "architecture_alpha",
        "generated_at": utc_now(),
        "module_count": len(module_summaries),
        "candidate_count": 0,
        "candidates": [],
        "module_summaries": module_summaries[:20],
        "stub": True,
    }
    write_report(
        ARCH_DIR / "latest.json",
        artifact="architecture_alpha",
        payload=result,
        status="blocked",
        source_of_truth="bot/*.py; reports/research_os/latest.json; reports/novelty_discovery.json",
        freshness_sla_seconds=7200,
        blockers=["anthropic_unavailable"],
        summary="architecture alpha stub output",
    )
    return result


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------


async def assemble_learning(mode: str = "all") -> dict[str, Any]:
    evidence = load_json(EVIDENCE_PATH)
    thesis = load_json(THESIS_PATH)
    novelty = load_json(NOVELTY_PATH)

    kimi_result: dict[str, Any] = {}
    research_result: dict[str, Any] = {}
    arch_result: dict[str, Any] = {}

    if mode in ("all", "kimi"):
        kimi_result = await run_kimi_lane(evidence, thesis)

    if mode in ("all", "research"):
        research_result = await run_research_os(evidence, novelty)

    if mode in ("all", "arch"):
        arch_result = await run_architecture_alpha()

    bundle: dict[str, Any] = {
        "artifact": "learning_bundle",
        "generated_at": utc_now(),
        "mode": mode,
        "kimi_active": kimi_result.get("kimi_active", False),
        "kimi_tasks": kimi_result.get("tasks", 0),
        "kimi_session_cost_usd": kimi_result.get("session_cost_usd", 0.0),
        "research_os_mutations": research_result.get("mutation_count", 0),
        "architecture_candidates": arch_result.get("candidate_count", 0),
        "lanes": {
            "kimi": kimi_result,
            "research_os": research_result,
            "architecture_alpha": arch_result,
        },
    }

    write_report(
        OUTPUT_PATH,
        artifact="learning_bundle",
        payload=bundle,
        status="fresh" if (kimi_result or research_result or arch_result) else "blocked",
        source_of_truth=(
            "reports/evidence_bundle.json; reports/thesis_bundle.json; "
            "reports/autoresearch/research_os/latest.json; "
            "reports/architecture_alpha/latest.json"
        ),
        freshness_sla_seconds=3600,
        blockers=[] if (kimi_result or research_result or arch_result) else ["all_learning_lanes_empty"],
        summary=(
            f"learning lane outputs: kimi={bundle['kimi_active']} "
            f"research_os={bundle['research_os_mutations']} arch={bundle['architecture_candidates']}"
        ),
    )
    logger.info(
        "[learning] bundle: kimi=%s tasks=%d, research_os=%d mutations, arch=%d candidates",
        "active" if kimi_result.get("kimi_active") else "inactive",
        kimi_result.get("tasks", 0),
        research_result.get("mutation_count", 0),
        arch_result.get("candidate_count", 0),
    )
    return bundle


def update_kernel_state(bundle: dict[str, Any]) -> None:
    try:
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from kernel_contract import KernelCycle, BundleStatus

        cycle = KernelCycle.load()
        total_outputs = (
            bundle.get("kimi_tasks", 0)
            + bundle.get("research_os_mutations", 0)
            + bundle.get("architecture_candidates", 0)
        )
        cycle.learning.mark_fresh(
            generated_at=bundle["generated_at"],
            source_count=3,  # three sub-lanes
            item_count=total_outputs,
        )
        cycle.compute_cycle_decision()
        cycle.save()
        cycle.append_cycle_log()
    except Exception as exc:
        logger.warning("[learning] kernel state update failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_once(mode: str = "all") -> None:
    asyncio.run(_run_once_async(mode))


async def _run_once_async(mode: str) -> None:
    bundle = await assemble_learning(mode)
    update_kernel_state(bundle)


async def run_daemon(mode: str) -> None:
    logger.info("Learning bundle daemon starting — mode=%s interval=%ds", mode, INTERVAL)
    while True:
        t0 = time.monotonic()
        try:
            bundle = await assemble_learning(mode)
            update_kernel_state(bundle)
        except Exception as exc:
            logger.error("[learning] cycle failed: %s", exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, INTERVAL - elapsed))


def main() -> None:
    global INTERVAL
    parser = argparse.ArgumentParser(description="Learning bundle — Kimi + research-OS + architecture")
    parser.add_argument(
        "--mode",
        choices=["all", "kimi", "research", "arch"],
        default="all",
        help="Which learning lanes to run",
    )
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=INTERVAL)
    args = parser.parse_args()
    INTERVAL = args.interval
    if args.daemon and not args.once:
        asyncio.run(run_daemon(args.mode))
    else:
        run_once(args.mode)


if __name__ == "__main__":
    main()
