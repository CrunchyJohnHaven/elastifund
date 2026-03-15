from __future__ import annotations

from scripts import render_repo_manifest


def test_extract_task_routing_includes_live_trading_lane() -> None:
    text = """
## Task Routing

- Live trading logic: `bot/`, `execution/`, `strategies/`
- Documentation and publishing: `docs/`, `research/`
"""
    rows = render_repo_manifest._extract_task_routing(text)
    assert rows[0]["lane"] == "Live trading logic"
    assert "bot/" in rows[0]["paths"]


def test_extract_directory_map_roles_reads_table_paths() -> None:
    text = """
## Directory Map

| Path | Purpose | Notes |
|---|---|---|
| `bot/` | live trading loop | high risk |
| `docs/`, `research/` | docs lane | durable docs |
"""
    roles = render_repo_manifest._extract_directory_map_roles(text)
    assert roles["bot/"]["package_role"] == "live trading loop"
    assert roles["docs/"]["notes"] == "durable docs"
    assert roles["research/"]["package_role"] == "docs lane"


def test_build_payload_contains_required_machine_routing_fields() -> None:
    payload = render_repo_manifest.build_payload()
    assert payload["entrypoints"]["machine_entrypoint"] == "AGENTS.md"
    assert payload["refresh_commands"]["check"] == "make repo-manifest-check"
    assert "reports/runtime_truth_latest.json" in payload["machine_contract_artifacts"]

    by_path = {row["path"]: row for row in payload["subsystems"]}
    assert by_path["bot/"]["narrow_test_command"] == "pytest -q bot/tests"
    assert by_path["archive/"]["flags"]["archive"] is True
    assert by_path["reports/"]["flags"]["generated"] is True
    assert "nontrading/finance/main.py" in {
        row["path"] for row in payload["nontrading_package_map_rows"]
    }
