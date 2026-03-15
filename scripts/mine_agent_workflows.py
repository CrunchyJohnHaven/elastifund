#!/usr/bin/env python3
"""Mine local Claude/Codex Elastifund sessions into a workflow cleanup report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "agent_workflow_mining" / "summary.json"
DEFAULT_CODEX_ARCHIVED_DIR = Path.home() / ".codex" / "archived_sessions"
DEFAULT_CODEX_INDEX_PATH = Path.home() / ".codex" / "session_index.jsonl"
DEFAULT_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
SCHEMA_VERSION = "1.0"

ENTRY_DOCS = {
    "README.md",
    "AGENTS.md",
    "PROJECT_INSTRUCTIONS.md",
    "COMMAND_NODE.md",
    "docs/REPO_MAP.md",
    "docs/PARALLEL_AGENT_WORKFLOW.md",
    "CONTRIBUTING.md",
}
KNOWN_TOP_LEVEL_NAMES = {
    "README.md",
    "AGENTS.md",
    "PROJECT_INSTRUCTIONS.md",
    "COMMAND_NODE.md",
    "CONTRIBUTING.md",
    "CLAUDE.md",
    "FAST_TRADE_EDGE_ANALYSIS.md",
    "Makefile",
    "jj_state.json",
    "docs",
    "research",
    "bot",
    "execution",
    "strategies",
    "signals",
    "infra",
    "src",
    "backtest",
    "simulator",
    "data_layer",
    "hub",
    "orchestration",
    "nontrading",
    "inventory",
    "polymarket-bot",
    "deploy",
    "scripts",
    "tests",
    "reports",
    "state",
    "data",
    "logs",
    "archive",
    "codex_instances",
    "kalshi",
}
ROOT_FILE_PATTERN = re.compile(
    r"(?<![\w/.-])"
    r"(?:README\.md|AGENTS\.md|PROJECT_INSTRUCTIONS\.md|COMMAND_NODE\.md|CONTRIBUTING\.md|CLAUDE\.md|"
    r"FAST_TRADE_EDGE_ANALYSIS\.md|Makefile|jj_state\.json)"
    r"(?![\w/.-])"
)
RELATIVE_PATH_PATTERN = re.compile(
    r"(?<![\w/.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_.-]+)?"
)
TRAILING_PUNCTUATION = " \t\n\r`\"'()[]{}<>.,:;"
ACTIVITY_PRIORITY = ("dispatch", "recon", "reporting", "implementation", "verification", "automation")
ACTIVITY_LABELS = {
    "dispatch": "Dispatch",
    "recon": "Recon",
    "reporting": "Reporting",
    "implementation": "Implementation",
    "verification": "Verification",
    "automation": "Automation",
}
DOMAIN_LABELS = {
    "capital": "Capital",
    "finance": "Finance",
    "trading": "Trading",
    "operator": "Operator",
    "general": "General",
}


@dataclass(frozen=True)
class Evidence:
    session_key: str
    agent: str
    session_title: str
    source_type: str
    text: str
    file_refs: tuple[str, ...]
    commands: tuple[str, ...]
    domains: tuple[str, ...]
    activities: tuple[str, ...]
    workflow_key: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _load_codex_index(index_path: Path | None) -> dict[str, str]:
    if index_path is None or not index_path.exists():
        return {}
    titles: dict[str, str] = {}
    for row in _iter_jsonl(index_path):
        session_id = str(row.get("id") or "").strip()
        title = str(row.get("thread_name") or "").strip()
        if session_id and title:
            titles[session_id] = title
    return titles


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_repo_path(candidate: str, repo_root: Path) -> str | None:
    text = candidate.strip(TRAILING_PUNCTUATION)
    if not text:
        return None

    absolute_repo_root = repo_root.resolve()
    path = Path(text).expanduser()
    if path.is_absolute():
        try:
            relative = path.resolve().relative_to(absolute_repo_root)
        except (ValueError, OSError):
            return None
        return relative.as_posix()

    normalized = text.lstrip("./").replace("\\", "/").strip("/")
    if not normalized:
        return None
    top_level = normalized.split("/", 1)[0]
    if top_level not in KNOWN_TOP_LEVEL_NAMES:
        return None
    return normalized


def extract_file_refs(text: str, repo_root: Path) -> list[str]:
    if not text:
        return []

    matches: list[str] = []
    repo_root_text = str(repo_root.resolve()).replace("\\", "/")
    absolute_pattern = re.compile(re.escape(repo_root_text) + r"/[A-Za-z0-9_./-]+")
    matches.extend(absolute_pattern.findall(text))
    matches.extend(ROOT_FILE_PATTERN.findall(text))
    matches.extend(RELATIVE_PATH_PATTERN.findall(text))

    normalized: list[str] = []
    seen: set[str] = set()
    for match in matches:
        normalized_path = _normalize_repo_path(match, repo_root)
        if not normalized_path or normalized_path in seen:
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    return normalized


def _normalize_command(command: str) -> str:
    compact = _normalize_whitespace(command)
    return compact[:160]


def _contains_keyword(haystack: str, keyword: str) -> bool:
    if not keyword:
        return False
    if re.fullmatch(r"[a-z0-9_]+", keyword):
        return re.search(rf"\b{re.escape(keyword)}\b", haystack) is not None
    return keyword in haystack


def _command_prefix(command: str) -> str:
    compact = _normalize_whitespace(command)
    if not compact:
        return ""
    token = compact.split(" ", 1)[0]
    return token[:64]


def _classify_domains(text: str, file_refs: Sequence[str]) -> tuple[str, ...]:
    haystack = f"{text}\n" + "\n".join(file_refs)
    lowered = haystack.lower()
    domains: set[str] = set()

    finance_keywords = (
        "finance",
        "budget",
        "treasury",
        "subscription",
        "cash reserve",
        "allocator",
        "allocate",
        "capital policy",
        "burn",
        "expense",
        "tool spend",
        "cfo",
        "recurring commitment",
    )
    trading_keywords = (
        "trading",
        "trade",
        "polymarket",
        "kalshi",
        "btc5",
        "wallet flow",
        "order book",
        "signal",
        "maker",
        "arr",
        "jj-live",
        "runtime truth",
        "edge",
        "market",
    )

    if any(_contains_keyword(lowered, keyword) for keyword in finance_keywords):
        domains.add("finance")
    if any(_contains_keyword(lowered, keyword) for keyword in trading_keywords):
        domains.add("trading")

    if any(path.startswith("nontrading/finance/") or path.startswith("reports/finance/") for path in file_refs):
        domains.add("finance")
    if any(
        path.startswith(prefix)
        for path in file_refs
        for prefix in (
            "bot/",
            "execution/",
            "strategies/",
            "signals/",
            "polymarket-bot/",
            "reports/runtime_",
            "reports/btc5_",
            "research/btc5_",
            "scripts/run_btc5",
            "scripts/render_btc5",
        )
    ):
        domains.add("trading")

    operator_files = ENTRY_DOCS.intersection(file_refs)
    if len(operator_files) >= 2 or "prompt library" in lowered or "context manifest" in lowered:
        domains.add("operator")

    if "finance" in domains and "trading" in domains:
        ordered = ["capital", "finance", "trading", "operator"]
        return tuple(domain for domain in ordered if domain in {"capital", *domains})

    ordered = ["finance", "trading", "operator"]
    if domains:
        return tuple(domain for domain in ordered if domain in domains)
    return ("general",)


def _classify_activities(text: str, file_refs: Sequence[str], commands: Sequence[str], source_type: str) -> tuple[str, ...]:
    lowered = text.lower()
    activities: set[str] = set()

    if source_type in {"command", "bash"}:
        if any(token in lowered for token in ("pytest", "make test", "make hygiene", "make verify", "ruff", "mypy")):
            activities.add("verification")
        if any(token in lowered for token in ("render_", "report", "summary", "latest.json", "write_text", "tee ")):
            activities.add("reporting")
        if any(token in lowered for token in ("python", "apply_patch", "edit", "write", "patch")):
            activities.add("implementation")
        if any(token in lowered for token in ("sed -n", "rg ", "find ", "read ", "cat ", "ls ", "git status")):
            activities.add("recon")

    recon_terms = ("read ", "review ", "explore", "inspect", "audit", "understand", "check ")
    if any(term in lowered for term in recon_terms) or len(file_refs) >= 3:
        activities.add("recon")
    if any(term in lowered for term in ("dispatch", "handoff", "instance", "node ", "command node", "owner per path")):
        activities.add("dispatch")
    if any(term in lowered for term in ("report", "summary", "artifact", "scorecard", "render", "writeup")):
        activities.add("reporting")
    if any(term in lowered for term in ("implement", "build", "create", "add ", "edit ", "patch", "fix ", "wire ")) or source_type in {
        "edit_tool",
        "write_tool",
    }:
        activities.add("implementation")
    if any(term in lowered for term in ("test", "pytest", "verify", "validation", "smoke", "hygiene", "preflight")):
        activities.add("verification")
    if any(term in lowered for term in ("automation", "scheduled", "loop", "cron", "autopush", "recurring")):
        activities.add("automation")
    if source_type in {"read_tool", "grep_tool", "agent_prompt"}:
        activities.add("recon")

    if not activities:
        activities.add("recon")
    return tuple(activity for activity in ACTIVITY_PRIORITY if activity in activities)


def _primary_domain(domains: Sequence[str]) -> str:
    if "capital" in domains:
        return "capital"
    if "finance" in domains:
        return "finance"
    if "trading" in domains:
        return "trading"
    if "operator" in domains:
        return "operator"
    return "general"


def _workflow_key(domains: Sequence[str], activities: Sequence[str]) -> str:
    primary = _primary_domain(domains)
    chosen_activities = list(activities[:2]) or ["recon"]
    return "_".join([primary, *chosen_activities])


def _label_for_workflow(key: str) -> str:
    parts = key.split("_")
    if not parts:
        return "General Recon"
    domain = DOMAIN_LABELS.get(parts[0], parts[0].title())
    activities = " + ".join(ACTIVITY_LABELS.get(part, part.title()) for part in parts[1:]) or "Recon"
    return f"{domain} {activities}"


def _truncate(text: str, *, limit: int = 160) -> str:
    compact = _normalize_whitespace(text)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _build_evidence(
    *,
    session_key: str,
    agent: str,
    session_title: str,
    source_type: str,
    text: str,
    repo_root: Path,
    commands: Sequence[str] | None = None,
) -> Evidence | None:
    cleaned_text = str(text or "").strip()
    cleaned_commands = tuple(_normalize_command(command) for command in (commands or ()) if str(command).strip())
    file_refs = tuple(extract_file_refs(cleaned_text, repo_root))
    domains = _classify_domains(cleaned_text, file_refs)
    activities = _classify_activities(cleaned_text, file_refs, cleaned_commands, source_type)

    relevant = bool(file_refs or cleaned_commands or set(domains) & {"capital", "finance", "trading", "operator"})
    if not relevant:
        return None

    return Evidence(
        session_key=session_key,
        agent=agent,
        session_title=session_title,
        source_type=source_type,
        text=cleaned_text,
        file_refs=file_refs,
        commands=cleaned_commands,
        domains=domains,
        activities=activities,
        workflow_key=_workflow_key(domains, activities),
    )


def _extract_codex_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    fragments: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text", "text"}:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                fragments.append(text)
    return "\n".join(fragments).strip()


def _extract_codex_command(payload: Mapping[str, Any]) -> str | None:
    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError:
            decoded = {"raw": arguments}
    elif isinstance(arguments, Mapping):
        decoded = dict(arguments)
    else:
        decoded = {}
    for key in ("cmd", "command", "raw"):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _parse_codex_session(path: Path, repo_root: Path, titles: Mapping[str, str]) -> tuple[str | None, list[Evidence]]:
    session_id = path.stem
    session_title = path.stem
    cwd = ""
    evidence: list[Evidence] = []

    for row in _iter_jsonl(path):
        row_type = str(row.get("type") or "")
        if row_type == "session_meta":
            payload = row.get("payload")
            if isinstance(payload, Mapping):
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload.get("cwd") or cwd)
                session_title = titles.get(session_id, session_title)
        if row_type != "response_item":
            continue

        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue

        payload_type = str(payload.get("type") or "")
        if payload_type == "message" and str(payload.get("role") or "") == "user":
            text = _extract_codex_message_text(payload.get("content"))
            item = _build_evidence(
                session_key=f"codex:{session_id}",
                agent="codex",
                session_title=session_title,
                source_type="user_prompt",
                text=text,
                repo_root=repo_root,
            )
            if item is not None:
                evidence.append(item)
        elif payload_type in {"function_call", "custom_tool_call"}:
            command = _extract_codex_command(payload)
            if not command:
                continue
            item = _build_evidence(
                session_key=f"codex:{session_id}",
                agent="codex",
                session_title=session_title,
                source_type="command",
                text=command,
                commands=[command],
                repo_root=repo_root,
            )
            if item is not None:
                evidence.append(item)

    repo_root_text = str(repo_root.resolve())
    if cwd and repo_root_text != cwd and repo_root.name not in cwd:
        return None, []
    return session_id, evidence


def _extract_claude_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts).strip()


def _parse_claude_tool_use(item: Mapping[str, Any], *, session_key: str, session_title: str, repo_root: Path) -> Evidence | None:
    name = str(item.get("name") or "")
    tool_input = item.get("input")
    if not isinstance(tool_input, Mapping):
        return None

    if name == "Read":
        file_path = str(tool_input.get("file_path") or "")
        return _build_evidence(
            session_key=session_key,
            agent="claude",
            session_title=session_title,
            source_type="read_tool",
            text=file_path,
            repo_root=repo_root,
        )
    if name == "Bash":
        command = str(tool_input.get("command") or "")
        return _build_evidence(
            session_key=session_key,
            agent="claude",
            session_title=session_title,
            source_type="bash",
            text=command,
            commands=[command],
            repo_root=repo_root,
        )
    if name == "Grep":
        pattern = str(tool_input.get("pattern") or "")
        path = str(tool_input.get("path") or "")
        return _build_evidence(
            session_key=session_key,
            agent="claude",
            session_title=session_title,
            source_type="grep_tool",
            text=f"{pattern} {path}".strip(),
            repo_root=repo_root,
        )
    if name == "Agent":
        prompt = str(tool_input.get("prompt") or "")
        return _build_evidence(
            session_key=session_key,
            agent="claude",
            session_title=session_title,
            source_type="agent_prompt",
            text=prompt,
            repo_root=repo_root,
        )
    if name in {"Edit", "Write"}:
        file_path = str(tool_input.get("file_path") or "")
        return _build_evidence(
            session_key=session_key,
            agent="claude",
            session_title=session_title,
            source_type=f"{name.lower()}_tool",
            text=file_path,
            repo_root=repo_root,
        )
    return None


def _parse_claude_session(path: Path, repo_root: Path) -> tuple[str | None, list[Evidence]]:
    session_key = f"claude:{path.stem}"
    cwd_seen = False
    title = path.stem
    evidence: list[Evidence] = []
    repo_root_text = str(repo_root.resolve())

    for row in _iter_jsonl(path):
        cwd = str(row.get("cwd") or "")
        if cwd and (cwd == repo_root_text or repo_root.name in cwd):
            cwd_seen = True

        message = row.get("message")
        if not isinstance(message, Mapping):
            continue

        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "user":
            text = _extract_claude_message_text(content)
            if not text and isinstance(content, str):
                text = content
            if text and title == path.stem:
                title = _truncate(text, limit=80)
            item = _build_evidence(
                session_key=session_key,
                agent="claude",
                session_title=title,
                source_type="user_prompt",
                text=text,
                repo_root=repo_root,
            )
            if item is not None:
                evidence.append(item)
            continue

        if role != "assistant" or not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "tool_use":
                continue
            item = _parse_claude_tool_use(part, session_key=session_key, session_title=title, repo_root=repo_root)
            if item is not None:
                evidence.append(item)

    if not cwd_seen and not evidence:
        return None, []
    return path.stem, evidence


def _default_recommendation(workflow_key: str, session_count: int, top_files: Sequence[str]) -> dict[str, str]:
    if ENTRY_DOCS.intersection(top_files):
        return {
            "surface": "AGENTS.md addition",
            "name": "canonical-entrypoint-bundle",
            "summary": (
                "Codify the repeated entry-doc/status-artifact read bundle in AGENTS.md instead of repeating "
                "manual bootstrapping prompts."
            ),
        }

    if workflow_key.startswith(("trading_dispatch", "capital_dispatch", "finance_dispatch")):
        stem = workflow_key.replace("_", "-")
        return {
            "surface": "skill",
            "name": stem,
            "summary": "Promote this repeated dispatch-and-recon workflow into a reusable repo skill with fixed inputs and done conditions.",
        }

    if workflow_key.endswith("reporting") or workflow_key.endswith("automation") or "reports/" in " ".join(top_files):
        stem = workflow_key.replace("_", "-")
        return {
            "surface": "script",
            "name": stem,
            "summary": "Replace repeated manual report assembly with a stable script or renderer that emits the same contract every run.",
        }

    surface = "skill" if session_count >= 2 else "AGENTS.md addition"
    stem = workflow_key.replace("_", "-")
    return {
        "surface": surface,
        "name": stem,
        "summary": "Codify this repeated workflow so it stops consuming fresh context every time it appears.",
    }


def _sorted_counter_items(counter: Counter[str], limit: int) -> list[str]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [key for key, _ in items[:limit]]


def _build_inefficiency_signals(
    *,
    workflow_key: str,
    items: Sequence[Evidence],
    file_counter: Counter[str],
    command_counter: Counter[str],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    session_count = len({item.session_key for item in items})

    if file_counter:
        entry_hits = sum(count for path, count in file_counter.items() if path in ENTRY_DOCS)
        if entry_hits >= 3:
            signals.append(
                {
                    "signal": "manual_context_bundle",
                    "count": entry_hits,
                    "detail": "The same canonical docs are being pulled into sessions by hand instead of through one reusable bundle.",
                }
            )

    if "dispatch" in workflow_key and session_count >= 2:
        signals.append(
            {
                "signal": "repeat_dispatch_prompt",
                "count": session_count,
                "detail": "Multi-node dispatch planning is recurring often enough to deserve a dedicated prompt/skill surface.",
            }
        )

    read_like = sum(
        count
        for prefix, count in command_counter.items()
        if prefix in {"sed", "rg", "find", "cat", "ls", "git", "python3", "pytest", "make"}
    )
    if read_like >= 3:
        signals.append(
            {
                "signal": "manual_terminal_sampling",
                "count": read_like,
                "detail": "Terminal sampling is being repeated manually instead of through a smaller scripted report contract.",
            }
        )
    return signals


def _summarize_workflows(evidence: Sequence[Evidence], *, min_session_count: int = 2) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.workflow_key].append(item)

    repeated: list[dict[str, Any]] = []
    action_queue: list[dict[str, Any]] = []

    for workflow_key, items in sorted(grouped.items()):
        sessions = {item.session_key for item in items}
        if len(sessions) < min_session_count:
            continue

        file_counter: Counter[str] = Counter()
        command_counter: Counter[str] = Counter()
        title_counter: Counter[str] = Counter()
        agent_counter: Counter[str] = Counter()
        source_counter: Counter[str] = Counter()

        for item in items:
            file_counter.update(item.file_refs)
            command_counter.update(_command_prefix(command) for command in item.commands if _command_prefix(command))
            title_counter[item.session_title] += 1
            agent_counter[item.agent] += 1
            source_counter[item.source_type] += 1

        top_files = _sorted_counter_items(file_counter, limit=6)
        top_commands = _sorted_counter_items(command_counter, limit=6)
        primary_domain = _primary_domain(items[0].domains)
        if primary_domain == "general" and not ENTRY_DOCS.intersection(top_files):
            continue
        recommendation = _default_recommendation(workflow_key, len(sessions), top_files)
        record = {
            "workflow_key": workflow_key,
            "label": _label_for_workflow(workflow_key),
            "domain": primary_domain,
            "session_count": len(sessions),
            "evidence_count": len(items),
            "agents": _sorted_counter_items(agent_counter, limit=4),
            "source_types": _sorted_counter_items(source_counter, limit=6),
            "top_files": top_files,
            "top_command_prefixes": top_commands,
            "sample_titles": _sorted_counter_items(title_counter, limit=4),
            "sample_prompts": [_truncate(item.text, limit=140) for item in items[:3]],
            "inefficiency_signals": _build_inefficiency_signals(
                workflow_key=workflow_key,
                items=items,
                file_counter=file_counter,
                command_counter=command_counter,
            ),
            "recommended_surface": recommendation["surface"],
            "recommended_name": recommendation["name"],
            "recommended_change": recommendation["summary"],
            "node_1_handoff": {
                "cleanup_target": recommendation["surface"],
                "summary": recommendation["summary"],
            },
        }
        repeated.append(record)
        action_queue.append(
            {
                "priority": 0 if record["session_count"] >= 3 else 1,
                "surface": recommendation["surface"],
                "name": recommendation["name"],
                "workflow_key": workflow_key,
                "why": recommendation["summary"],
            }
        )

    repeated.sort(key=lambda row: (-int(row["session_count"]), row["workflow_key"]))
    return repeated, _dedupe_actions(action_queue)


def _dedupe_actions(actions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for action in actions:
        key = (str(action["surface"]), str(action["name"]))
        workflow_key = str(action["workflow_key"])
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = {
                "priority": int(action["priority"]),
                "surface": str(action["surface"]),
                "name": str(action["name"]),
                "why": str(action["why"]),
                "workflow_keys": [workflow_key],
            }
            continue
        existing["priority"] = min(int(existing["priority"]), int(action["priority"]))
        existing["workflow_keys"] = sorted({*existing["workflow_keys"], workflow_key})

    ordered = sorted(
        deduped.values(),
        key=lambda row: (int(row["priority"]), str(row["surface"]), str(row["name"])),
    )
    return ordered


def _cross_cutting_findings(evidence: Sequence[Evidence]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    entry_bundle_sessions = {
        item.session_key
        for item in evidence
        if len(ENTRY_DOCS.intersection(item.file_refs)) >= 3
    }
    if len(entry_bundle_sessions) >= 2:
        findings.append(
            {
                "finding_key": "manual_entry_context_bundle",
                "session_count": len(entry_bundle_sessions),
                "detail": "Entry docs are repeatedly attached by hand. Move the canonical bundle into AGENTS.md or a small repo skill.",
                "recommended_surface": "AGENTS.md addition",
            }
        )

    dispatch_sessions = {item.session_key for item in evidence if "dispatch" in item.activities}
    if len(dispatch_sessions) >= 2:
        findings.append(
            {
                "finding_key": "repeat_dispatch_planning",
                "session_count": len(dispatch_sessions),
                "detail": "Multi-node dispatch planning is recurring across sessions. Promote it into a skill with fixed inputs and outputs.",
                "recommended_surface": "skill",
            }
        )

    finance_sessions = {
        item.session_key
        for item in evidence
        if {"finance", "capital"} & set(item.domains)
    }
    if finance_sessions:
        findings.append(
            {
                "finding_key": "finance_workflow_ready_for_cleanup",
                "session_count": len(finance_sessions),
                "detail": "Finance workflows are present in local history and can feed the new finance control-plane prompt contract.",
                "recommended_surface": "skill",
            }
        )

    return findings


def mine_agent_workflows(
    *,
    repo_root: Path = PROJECT_ROOT,
    codex_archived_dir: Path | None = DEFAULT_CODEX_ARCHIVED_DIR,
    codex_index_path: Path | None = DEFAULT_CODEX_INDEX_PATH,
    claude_projects_dir: Path | None = DEFAULT_CLAUDE_PROJECTS_DIR,
    min_repeated_sessions: int = 2,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    codex_titles = _load_codex_index(codex_index_path)
    all_evidence: list[Evidence] = []
    gaps: list[dict[str, str]] = []

    source_summary = {
        "codex": {
            "sessions_scanned": 0,
            "sessions_matched": 0,
            "evidence_count": 0,
        },
        "claude": {
            "sessions_scanned": 0,
            "sessions_matched": 0,
            "evidence_count": 0,
        },
    }

    if codex_archived_dir is None or not codex_archived_dir.exists():
        gaps.append(
            {
                "source": "codex_archived_sessions",
                "status": "missing",
                "detail": "Codex archived session directory was not found, so Codex workflow history could not be mined.",
            }
        )
    else:
        for session_path in sorted(codex_archived_dir.glob("*.jsonl")):
            source_summary["codex"]["sessions_scanned"] += 1
            _, evidence = _parse_codex_session(session_path, repo_root, codex_titles)
            if not evidence:
                continue
            source_summary["codex"]["sessions_matched"] += 1
            source_summary["codex"]["evidence_count"] += len(evidence)
            all_evidence.extend(evidence)

    if claude_projects_dir is None or not claude_projects_dir.exists():
        gaps.append(
            {
                "source": "claude_projects",
                "status": "missing",
                "detail": "Claude projects directory was not found, so Claude workflow history could not be mined.",
            }
        )
    else:
        for session_path in sorted(claude_projects_dir.glob("**/*.jsonl")):
            if "subagents" in session_path.parts:
                continue
            source_summary["claude"]["sessions_scanned"] += 1
            _, evidence = _parse_claude_session(session_path, repo_root)
            if not evidence:
                continue
            source_summary["claude"]["sessions_matched"] += 1
            source_summary["claude"]["evidence_count"] += len(evidence)
            all_evidence.extend(evidence)

    repeated_workflows, recommended_actions = _summarize_workflows(
        all_evidence,
        min_session_count=min_repeated_sessions,
    )

    trading_sessions = {
        item.session_key
        for item in all_evidence
        if "trading" in item.domains or "capital" in item.domains
    }
    finance_sessions = {
        item.session_key
        for item in all_evidence
        if "finance" in item.domains or "capital" in item.domains
    }
    operator_sessions = {item.session_key for item in all_evidence if "operator" in item.domains}

    if not finance_sessions:
        gaps.append(
            {
                "source": "finance_workflows",
                "status": "missing",
                "detail": "No finance-tagged Elastifund sessions were found in the scanned local history.",
            }
        )
    if not trading_sessions:
        gaps.append(
            {
                "source": "trading_workflows",
                "status": "missing",
                "detail": "No trading-tagged Elastifund sessions were found in the scanned local history.",
            }
        )
    if not repeated_workflows:
        gaps.append(
            {
                "source": "workflow_clusters",
                "status": "insufficient_history",
                "detail": "The local history did not contain enough repeated Elastifund workflows to cross the clustering threshold.",
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "workspace": {
            "repo_name": repo_root.name,
            "repo_root": str(repo_root),
        },
        "inputs": {
            "min_repeated_sessions": min_repeated_sessions,
        },
        "source_summary": source_summary,
        "workflow_summary": {
            "evidence_count": len(all_evidence),
            "trading_session_count": len(trading_sessions),
            "finance_session_count": len(finance_sessions),
            "operator_session_count": len(operator_sessions),
            "repeated_workflow_count": len(repeated_workflows),
        },
        "repeated_workflows": repeated_workflows,
        "cross_cutting_findings": _cross_cutting_findings(all_evidence),
        "recommended_actions": recommended_actions,
        "node_1_cleanup_queue": recommended_actions,
        "machine_readable_gaps": gaps,
    }


def write_summary(payload: Mapping[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT, help="Workspace root to filter session history against.")
    parser.add_argument(
        "--codex-archived-dir",
        type=Path,
        default=DEFAULT_CODEX_ARCHIVED_DIR,
        help=f"Codex archived session directory (default: {DEFAULT_CODEX_ARCHIVED_DIR}).",
    )
    parser.add_argument(
        "--codex-index",
        type=Path,
        default=DEFAULT_CODEX_INDEX_PATH,
        help=f"Codex session index JSONL for thread titles (default: {DEFAULT_CODEX_INDEX_PATH}).",
    )
    parser.add_argument(
        "--claude-projects-dir",
        type=Path,
        default=DEFAULT_CLAUDE_PROJECTS_DIR,
        help=f"Claude project history directory (default: {DEFAULT_CLAUDE_PROJECTS_DIR}).",
    )
    parser.add_argument(
        "--min-repeated-sessions",
        type=int,
        default=2,
        help="Minimum unique sessions required before a workflow is promoted into the repeated-workflow set.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Where to write the machine-readable workflow summary (default: {DEFAULT_OUTPUT_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = mine_agent_workflows(
        repo_root=args.repo_root,
        codex_archived_dir=args.codex_archived_dir,
        codex_index_path=args.codex_index,
        claude_projects_dir=args.claude_projects_dir,
        min_repeated_sessions=args.min_repeated_sessions,
    )
    output_path = write_summary(summary, args.output)
    print(f"Wrote workflow mining summary to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
