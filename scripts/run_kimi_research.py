#!/usr/bin/env python3
"""
Kimi (Moonshot AI) Research — Instance 6 learning-layer breadth engine.

Activates Kimi from "configured" to "active" status by making real API calls,
logging usage history, and producing measurable learning artifacts.

Roles:
  1. Failure clustering  — group similar failed hypotheses from research_os
  2. Candidate triage    — score backlog items by novelty

Inputs (all optional):
  reports/autoresearch/research_os/latest.json        — mutation wave priorities
  reports/parallel/novelty_discovery.json             — novel patterns to cluster

Outputs:
  reports/autoresearch/providers/moonshot/history.jsonl  — append-only usage log
  reports/autoresearch/providers/moonshot/latest.json    — current output

If MOONSHOT_API_KEY is not set, writes a "configured_not_active" status record
to latest.json with a clear diagnostic message — never silently no-ops.

Usage:
  python3 scripts/run_kimi_research.py [--dry-run]

API: https://api.moonshot.cn/v1/chat/completions (OpenAI-compatible, Bearer auth)
Transport: stdlib urllib only — no httpx/requests.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).resolve().parents[1]
REPORTS  = ROOT / "reports"
PARALLEL = REPORTS / "parallel"

RESEARCH_OS_PATH       = REPORTS / "autoresearch" / "research_os" / "latest.json"
NOVELTY_DISCOVERY_PATH = PARALLEL / "novelty_discovery.json"

MOONSHOT_DIR     = REPORTS / "autoresearch" / "providers" / "moonshot"
OUT_HISTORY      = MOONSHOT_DIR / "history.jsonl"
OUT_LATEST       = MOONSHOT_DIR / "latest.json"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
KIMI_API_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_MODEL   = "moonshot-v1-8k"       # cost-effective; switch to moonshot-v1-32k for large contexts
KIMI_TIMEOUT = 45                     # seconds

# Approximate cost per 1k tokens (blended input+output) — matches llm_tournament.py
COST_PER_1K_TOKENS = 0.0001

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [kimi_research] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("kimi_research")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _load_json(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        log.debug("optional input not found: %s (%s)", path, label)
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            log.warning("%s: expected dict, got %s — skipping", label, type(data).__name__)
            return None
        log.info("loaded %s (%d keys)", label, len(data))
        return data
    except Exception as exc:
        log.warning("could not load %s: %s", label, exc)
        return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    total_k = (prompt_tokens + completion_tokens) / 1000.0
    return round(total_k * COST_PER_1K_TOKENS, 6)


def _write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def _atomic_write_json(path: Path, data: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(tmp_fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def _extract_failed_hypotheses(research_os: dict[str, Any] | None) -> list[str]:
    """Pull failed/killed hypothesis summaries from research_os."""
    if not research_os:
        return []
    items: list[str] = []

    # mutation_waves may have failed entries
    waves = research_os.get("mutation_waves") or []
    for wave in waves:
        if not isinstance(wave, dict):
            continue
        status = str(wave.get("status") or wave.get("state") or "").lower()
        if any(k in status for k in ("fail", "kill", "reject", "dead")):
            desc = wave.get("description") or wave.get("name") or str(wave)
            items.append(str(desc)[:200])

    # lane_health / task penalties can also indicate failures
    health = research_os.get("lane_health") or {}
    for lane, info in health.items():
        if not isinstance(info, dict):
            continue
        if float(info.get("score") or info.get("health") or 1.0) < 0.4:
            items.append(f"Low-health lane: {lane} (score={info.get('score', '?')})")

    return items[:12]


def _extract_candidate_backlog(research_os: dict[str, Any] | None) -> list[str]:
    """Pull candidate hypotheses awaiting triage."""
    if not research_os:
        return []
    items: list[str] = []

    # opportunity_exchange is the canonical list
    opps = research_os.get("opportunity_exchange") or []
    for opp in opps:
        if not isinstance(opp, dict):
            continue
        desc = opp.get("description") or opp.get("opp_id") or str(opp)
        priority = opp.get("estimated_priority") or "medium"
        items.append(f"[{priority}] {str(desc)[:180]}")

    return items[:10]


def _extract_novel_patterns(novelty_discovery: dict[str, Any] | None) -> list[str]:
    """Pull top discovery descriptions for clustering context."""
    if not novelty_discovery:
        return []
    discs = novelty_discovery.get("discoveries") or []
    return [
        f"[{d.get('type', '?')}] {str(d.get('description', ''))[:180]}"
        for d in discs[:8]
        if isinstance(d, dict)
    ]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a systematic research analyst for an AI-run quantitative trading fund (Elastifund).
The fund trades prediction markets (Polymarket, Kalshi) using validated statistical edges.
Your job:
1. Group similar failed hypotheses into failure clusters so the team avoids repeating known mistakes.
2. Score backlog candidates by novelty — how different is each from previously explored territory.
Be concise. Output structured JSON only. No prose outside the JSON object.
"""

_USER_TEMPLATE = """\
## Failed Hypotheses (to cluster)
{failed_block}

## Backlog Candidates (to score by novelty)
{backlog_block}

## Novel Patterns Observed (for context)
{patterns_block}

## Task
Return EXACTLY the following JSON structure (no extra keys, no markdown fences):

{{
  "failure_clusters": [
    {{
      "cluster_id": "FC-01",
      "label": "<short name>",
      "members": ["<hyp summary>", ...],
      "root_cause": "<1 sentence>",
      "avoid_rule": "<concrete rule to prevent repeating>"
    }}
  ],
  "candidate_triage": [
    {{
      "candidate": "<candidate description>",
      "novelty_score": 0.0,
      "novelty_rationale": "<why novel or not>",
      "recommendation": "prioritise|defer|discard"
    }}
  ],
  "learning_summary": "<2-3 sentence synthesis of what these failures and candidates reveal>"
}}

Produce at most 5 failure clusters and score all {backlog_count} candidates.
"""


def _build_prompt(
    failed: list[str],
    backlog: list[str],
    patterns: list[str],
) -> str:
    failed_block   = "\n".join(f"- {h}" for h in failed)  if failed   else "(none available)"
    backlog_block  = "\n".join(f"- {c}" for c in backlog) if backlog  else "(none available)"
    patterns_block = "\n".join(f"- {p}" for p in patterns) if patterns else "(none available)"

    return _USER_TEMPLATE.format(
        failed_block=failed_block,
        backlog_block=backlog_block,
        patterns_block=patterns_block,
        backlog_count=len(backlog),
    )


# ---------------------------------------------------------------------------
# Kimi API call
# ---------------------------------------------------------------------------

def _call_kimi(api_key: str, prompt: str, dry_run: bool = False) -> dict[str, Any]:
    """
    Call the Kimi API and return a structured result dict.
    Uses urllib (stdlib) only.
    """
    payload = {
        "model":       KIMI_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }

    if dry_run:
        log.info("[dry-run] would POST to %s with model=%s", KIMI_API_URL, KIMI_MODEL)
        prompt_tokens = _estimate_tokens(_SYSTEM_PROMPT + prompt)
        return {
            "status":            "dry_run",
            "model":             KIMI_MODEL,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": 0,
            "cost_usd":          0.0,
            "raw_content":       None,
            "parsed":            None,
            "error":             None,
            "latency_ms":        0,
        }

    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        KIMI_API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=KIMI_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        return {
            "status":   "api_error",
            "error":    f"HTTP {exc.code}: {err_body}",
            "model":    KIMI_MODEL,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        return {
            "status":   "network_error",
            "error":    str(exc),
            "model":    KIMI_MODEL,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    latency_ms = int((time.monotonic() - t0) * 1000)

    try:
        resp_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "status":     "parse_error",
            "error":      str(exc),
            "raw":        raw[:500],
            "model":      KIMI_MODEL,
            "latency_ms": latency_ms,
        }

    # Extract usage
    usage            = resp_data.get("usage") or {}
    prompt_tokens    = int(usage.get("prompt_tokens")     or _estimate_tokens(_SYSTEM_PROMPT + prompt))
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cost_usd         = _estimate_cost_usd(prompt_tokens, completion_tokens)

    # Extract content
    choices     = resp_data.get("choices") or []
    raw_content = (choices[0].get("message") or {}).get("content") or "" if choices else ""

    # Attempt JSON parse of model output
    parsed: dict | None = None
    parse_error: str | None = None
    content_clean = raw_content.strip()
    # Strip markdown fences if model adds them despite instructions
    if content_clean.startswith("```"):
        content_clean = content_clean.split("```")[1]
        if content_clean.startswith("json"):
            content_clean = content_clean[4:]
    try:
        parsed = json.loads(content_clean)
    except json.JSONDecodeError as exc:
        parse_error = f"model output not valid JSON: {exc}"
        log.warning("Kimi response JSON parse error: %s", parse_error)
        log.debug("raw content: %s", raw_content[:400])

    return {
        "status":             "ok" if parsed else ("parse_error" if parse_error else "ok"),
        "model":              resp_data.get("model") or KIMI_MODEL,
        "prompt_tokens":      prompt_tokens,
        "completion_tokens":  completion_tokens,
        "cost_usd":           cost_usd,
        "raw_content":        raw_content[:2000] if raw_content else None,
        "parsed":             parsed,
        "error":              parse_error,
        "latency_ms":         latency_ms,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(*, dry_run: bool = False) -> dict[str, Any]:
    """Run Kimi research pass. Returns the latest.json artifact."""
    now = _now_iso()

    # Check for API key first — produce configured_not_active record if absent
    api_key = os.environ.get("MOONSHOT_API_KEY") or ""
    if not api_key and not dry_run:
        msg = (
            "MOONSHOT_API_KEY not set in environment. "
            "Kimi is configured (moonshot-v1-8k, cost table in llm_tournament.py) "
            "but not active. Set MOONSHOT_API_KEY to enable live calls."
        )
        log.warning(msg)
        result: dict[str, Any] = {
            "artifact":  "kimi_research_v1",
            "status":    "configured_not_active",
            "message":   msg,
            "model":     KIMI_MODEL,
            "generated_at": now,
            "failure_clusters":   [],
            "candidate_triage":   [],
            "learning_summary":   None,
            "usage": {
                "prompt_tokens":    0,
                "completion_tokens": 0,
                "cost_usd":         0.0,
                "latency_ms":       0,
            },
        }
        MOONSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(OUT_LATEST, result)
        _write_jsonl(OUT_HISTORY, {**result, "run_at": now})
        print(f"kimi latest   → {OUT_LATEST}  (status: configured_not_active)")
        print(f"kimi history  → {OUT_HISTORY}")
        return result

    # Load inputs
    research_os       = _load_json(RESEARCH_OS_PATH,       "research_os")
    novelty_discovery = _load_json(NOVELTY_DISCOVERY_PATH, "novelty_discovery")

    # Extract context
    failed   = _extract_failed_hypotheses(research_os)
    backlog  = _extract_candidate_backlog(research_os)
    patterns = _extract_novel_patterns(novelty_discovery)

    log.info(
        "context: %d failed hyps, %d backlog candidates, %d novel patterns",
        len(failed), len(backlog), len(patterns),
    )

    # Build prompt
    prompt = _build_prompt(failed, backlog, patterns)
    prompt_tokens_est = _estimate_tokens(_SYSTEM_PROMPT + prompt)
    log.info("estimated prompt tokens: %d", prompt_tokens_est)

    # Call API
    api_result = _call_kimi(api_key, prompt, dry_run=dry_run)

    # Unpack parsed output (may be None on parse error or dry run)
    parsed: dict[str, Any] = api_result.get("parsed") or {}

    result = {
        "artifact":    "kimi_research_v1",
        "status":      api_result.get("status") or "unknown",
        "model":       api_result.get("model") or KIMI_MODEL,
        "generated_at": now,
        "failure_clusters":  parsed.get("failure_clusters") or [],
        "candidate_triage":  parsed.get("candidate_triage") or [],
        "learning_summary":  parsed.get("learning_summary") or None,
        "raw_content_sample": (api_result.get("raw_content") or "")[:500] or None,
        "error":       api_result.get("error"),
        "usage": {
            "prompt_tokens":     api_result.get("prompt_tokens") or prompt_tokens_est,
            "completion_tokens": api_result.get("completion_tokens") or 0,
            "cost_usd":          api_result.get("cost_usd") or 0.0,
            "latency_ms":        api_result.get("latency_ms") or 0,
        },
    }

    # Persist
    MOONSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if dry_run:
        log.info("[dry-run] would write %s", OUT_LATEST)
        log.info("[dry-run] would append to %s", OUT_HISTORY)
        print(json.dumps(result, indent=2))
    else:
        _atomic_write_json(OUT_LATEST, result)
        _write_jsonl(OUT_HISTORY, {**result, "run_at": now})
        log.info(
            "wrote kimi output: status=%s  clusters=%d  triage=%d  cost=$%.5f  latency=%dms",
            result["status"],
            len(result["failure_clusters"]),
            len(result["candidate_triage"]),
            result["usage"]["cost_usd"],
            result["usage"]["latency_ms"],
        )
        print(f"kimi latest   → {OUT_LATEST}  (status: {result['status']})")
        print(f"kimi history  → {OUT_HISTORY}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run Kimi (Moonshot AI) as Instance 6 learning-layer breadth engine. "
            "Performs failure clustering and candidate triage."
        )
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompt and print result without making API call or writing files",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
