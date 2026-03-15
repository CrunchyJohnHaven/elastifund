from __future__ import annotations

import json
from pathlib import Path

from scripts.mine_agent_workflows import main, mine_agent_workflows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _codex_session_rows(repo_root: Path, session_id: str, prompt: str, commands: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "timestamp": "2026-03-10T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-03-10T00:00:00Z",
                "cwd": str(repo_root),
            },
        },
        {
            "timestamp": "2026-03-10T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        },
    ]
    for index, command in enumerate(commands, start=1):
        rows.append(
            {
                "timestamp": f"2026-03-10T00:00:{index + 1:02d}Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": command}),
                },
            }
        )
    return rows


def _claude_session_rows(repo_root: Path, prompt: str, tool_uses: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "type": "user",
            "cwd": str(repo_root),
            "message": {
                "role": "user",
                "content": prompt,
            },
        },
        {
            "cwd": str(repo_root),
            "message": {
                "role": "assistant",
                "content": tool_uses,
            },
        },
    ]
    return rows


def test_mine_agent_workflows_detects_repeated_trading_and_finance_workflows(tmp_path: Path) -> None:
    repo_root = tmp_path / "Elastifund"
    repo_root.mkdir()

    codex_archived_dir = tmp_path / "codex" / "archived_sessions"
    codex_index = tmp_path / "codex" / "session_index.jsonl"
    claude_projects_dir = tmp_path / "claude" / "projects" / "-tmp-Elastifund"

    _write_jsonl(
        codex_archived_dir / "trading-a.jsonl",
        _codex_session_rows(
            repo_root,
            "codex-trading-a",
            (
                "Review COMMAND_NODE.md, PROJECT_INSTRUCTIONS.md, README.md, docs/REPO_MAP.md, "
                "and bot/jj_live.py, then dispatch the next trading nodes for BTC5 ARR improvement."
            ),
            [
                "sed -n '1,220p' README.md",
                "pytest -q tests/test_btc5_hypothesis_lab.py",
            ],
        ),
    )
    _write_jsonl(
        codex_archived_dir / "finance-a.jsonl",
        _codex_session_rows(
            repo_root,
            "codex-finance-a",
            (
                "Audit subscription burn, cash reserve, and treasury allocation. Read nontrading/finance/main.py "
                "and reports/finance/latest.json, then report where the next dollar should go."
            ),
            [
                "sed -n '1,220p' nontrading/finance/main.py",
                "python3 scripts/render_finance_control_report.py",
            ],
        ),
    )
    _write_jsonl(
        codex_index,
        [
            {"id": "codex-trading-a", "thread_name": "Trading dispatch review"},
            {"id": "codex-finance-a", "thread_name": "Finance allocator review"},
        ],
    )

    _write_jsonl(
        claude_projects_dir / "claude-trading-a.jsonl",
        _claude_session_rows(
            repo_root,
            (
                "Command node trading review: read README.md, COMMAND_NODE.md, PROJECT_INSTRUCTIONS.md, "
                "reports/runtime_truth_latest.json, and bot/jj_live.py before dispatching the next BTC5 work."
            ),
            [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"file_path": str(repo_root / "bot" / "jj_live.py")},
                },
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "input": {
                        "prompt": (
                            "Explore the current trading runtime and return a node-by-node dispatch plan after "
                            "reading COMMAND_NODE.md, PROJECT_INSTRUCTIONS.md, and reports/runtime_truth_latest.json."
                        )
                    },
                },
            ],
        ),
    )
    _write_jsonl(
        claude_projects_dir / "claude-finance-a.jsonl",
        _claude_session_rows(
            repo_root,
            (
                "Finance control plane review: inspect nontrading/finance/main.py, reports/finance/latest.json, "
                "and reports/finance/allocation_plan.json, then summarize budget, treasury, and subscription cuts."
            ),
            [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"file_path": str(repo_root / "nontrading" / "finance" / "main.py")},
                },
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "python3 scripts/render_finance_control_report.py"},
                },
            ],
        ),
    )

    summary = mine_agent_workflows(
        repo_root=repo_root,
        codex_archived_dir=codex_archived_dir,
        codex_index_path=codex_index,
        claude_projects_dir=claude_projects_dir.parent,
    )

    assert summary["source_summary"]["codex"]["sessions_matched"] == 2
    assert summary["source_summary"]["claude"]["sessions_matched"] == 2
    assert summary["workflow_summary"]["trading_session_count"] >= 2
    assert summary["workflow_summary"]["finance_session_count"] >= 2
    assert not any(gap["source"] == "finance_workflows" for gap in summary["machine_readable_gaps"])

    trading_workflows = [row for row in summary["repeated_workflows"] if row["domain"] == "trading"]
    finance_workflows = [row for row in summary["repeated_workflows"] if row["domain"] == "finance"]
    assert trading_workflows
    assert finance_workflows
    assert trading_workflows[0]["recommended_surface"] in {"skill", "AGENTS.md addition"}
    assert any("nontrading/finance/main.py" in row["top_files"] for row in finance_workflows)
    assert summary["cross_cutting_findings"]


def test_mine_agent_workflows_emits_machine_readable_gaps_when_history_is_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "Elastifund"
    repo_root.mkdir()

    codex_archived_dir = tmp_path / "codex" / "archived_sessions"
    codex_index = tmp_path / "codex" / "session_index.jsonl"
    _write_jsonl(
        codex_archived_dir / "trading-a.jsonl",
        _codex_session_rows(
            repo_root,
            "codex-trading-a",
            "Review README.md, COMMAND_NODE.md, and bot/jj_live.py before dispatching the next trading node.",
            ["sed -n '1,220p' README.md"],
        ),
    )
    _write_jsonl(codex_index, [{"id": "codex-trading-a", "thread_name": "Trading dispatch review"}])

    summary = mine_agent_workflows(
        repo_root=repo_root,
        codex_archived_dir=codex_archived_dir,
        codex_index_path=codex_index,
        claude_projects_dir=tmp_path / "missing-claude",
    )

    gap_sources = {gap["source"] for gap in summary["machine_readable_gaps"]}
    assert "claude_projects" in gap_sources
    assert "finance_workflows" in gap_sources


def test_main_writes_summary_json(tmp_path: Path) -> None:
    repo_root = tmp_path / "Elastifund"
    repo_root.mkdir()
    codex_archived_dir = tmp_path / "codex" / "archived_sessions"
    codex_index = tmp_path / "codex" / "session_index.jsonl"
    claude_projects_dir = tmp_path / "claude" / "projects"
    output_path = tmp_path / "reports" / "agent_workflow_mining" / "summary.json"

    _write_jsonl(
        codex_archived_dir / "trading-a.jsonl",
        _codex_session_rows(
            repo_root,
            "codex-trading-a",
            "Review README.md, PROJECT_INSTRUCTIONS.md, and bot/jj_live.py, then dispatch the next trading node.",
            ["sed -n '1,220p' README.md"],
        ),
    )
    _write_jsonl(codex_index, [{"id": "codex-trading-a", "thread_name": "Trading dispatch review"}])
    claude_projects_dir.mkdir(parents=True, exist_ok=True)

    exit_code = main(
        [
            "--repo-root",
            str(repo_root),
            "--codex-archived-dir",
            str(codex_archived_dir),
            "--codex-index",
            str(codex_index),
            "--claude-projects-dir",
            str(claude_projects_dir),
            "--output",
            str(output_path),
            "--min-repeated-sessions",
            "1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["workspace"]["repo_name"] == "Elastifund"
