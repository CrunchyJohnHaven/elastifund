from __future__ import annotations

import json
from pathlib import Path

import scripts.run_btc5_local_improvement_search as runner


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_market_local_search_stops_on_quantified_improvement(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write_json(
        repo_root / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "champion": {
                "experiment_id": 1,
                "candidate_model_name": "baseline-market",
                "candidate_hash": "market-1",
                "loss": 10.0,
                "generated_at": "2026-03-11T20:00:00Z",
            },
            "latest_experiment": {
                "experiment_id": 1,
                "status": "keep",
                "decision_reason": "baseline_frontier",
                "proposal_id": "proposal_0001",
                "proposer_model": "seed",
                "estimated_llm_cost_usd": 0.35,
                "loss": 10.0,
                "keep": True,
            },
        },
    )
    _write_script(
        repo_root / "scripts" / "run_btc5_market_model_autoresearch.py",
        """#!/usr/bin/env python3
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
latest = root / "reports/autoresearch/btc5_market/latest.json"
payload = json.loads(latest.read_text())
payload["champion"] = {
    "experiment_id": 2,
    "candidate_model_name": "improved-market",
    "candidate_hash": "market-2",
    "loss": 8.0,
    "generated_at": "2026-03-11T21:00:00Z",
}
payload["latest_experiment"] = {
    "experiment_id": 2,
    "status": "keep",
    "decision_reason": "improved_frontier",
    "proposal_id": "proposal_0002",
    "proposer_model": "routine",
    "estimated_llm_cost_usd": 0.35,
    "loss": 8.0,
    "keep": True,
}
latest.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
""",
    )

    exit_code = runner.main(
        [
            "--repo-root",
            str(repo_root),
            "--lanes",
            "market",
            "--max-rounds",
            "3",
        ]
    )

    assert exit_code == 0
    latest_summary = json.loads(
        (repo_root / "reports" / "autoresearch" / "local_improvement_search" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest_summary["improvement_found"] is True
    assert latest_summary["winning_lane"] == "market"
    assert latest_summary["best_improvement"]["loss_improvement"] == 2.0
    assert latest_summary["best_improvement"]["loss_improvement_pct"] == 20.0


def test_aggressive_profile_forces_strongest_builtin_tier(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "run_btc5_market_model_autoresearch.py").write_text("", encoding="utf-8")
    (repo_root / "scripts" / "run_btc5_command_node_autoresearch.py").write_text("", encoding="utf-8")

    market_command = runner._lane_command_with_profile(repo_root, "market", "", "aggressive")
    command_node_command = runner._lane_command_with_profile(repo_root, "command_node", "", "aggressive")

    assert market_command[-2:] == ["--force-proposer-tier", "expensive"]
    assert command_node_command[-2:] == ["--force-proposer-tier", "escalated"]


def test_local_search_reports_frontier_seed_metadata(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write_json(
        repo_root / "reports" / "btc5_market_policy_frontier" / "latest.json",
        {
            "ranked_policies": [
                {
                    "policy_id": "active_profile",
                    "package_hash": "hash-active",
                    "policy_loss": -55389.7504,
                }
            ]
        },
    )
    seeds = runner._frontier_seed_pool(repo_root, "reports/btc5_market_policy_frontier/latest.json", 5)

    assert seeds == [
        {
            "policy_id": "active_profile",
            "package_hash": "hash-active",
            "policy_loss": -55389.7504,
        }
    ]


def test_command_node_local_search_quantifies_loss_and_score_delta(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write_json(
        repo_root / "reports" / "autoresearch" / "command_node" / "latest.json",
        {
            "champion": {
                "experiment_id": 5,
                "candidate_label": "baseline-command",
                "prompt_hash": "cmd-5",
                "loss": 10.0,
                "total_score": 90.0,
                "updated_at": "2026-03-11T20:00:00Z",
            },
            "latest_status": "keep",
            "latest_decision_reason": "baseline_frontier",
            "latest_loss": 10.0,
            "latest_total_score": 90.0,
            "latest_proposal_id": "proposal_0005",
            "latest_proposal": {
                "proposal_id": "proposal_0005",
                "proposer_model": "seed",
                "estimated_llm_cost_usd": 0.35,
            },
        },
    )
    _write_script(
        repo_root / "scripts" / "run_btc5_command_node_autoresearch.py",
        """#!/usr/bin/env python3
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
latest = root / "reports/autoresearch/command_node/latest.json"
payload = json.loads(latest.read_text())
payload["champion"] = {
    "experiment_id": 6,
    "candidate_label": "improved-command",
    "prompt_hash": "cmd-6",
    "loss": 7.5,
    "total_score": 94.5,
    "updated_at": "2026-03-11T21:00:00Z",
}
payload["latest_status"] = "keep"
payload["latest_decision_reason"] = "improved_frontier"
payload["latest_loss"] = 7.5
payload["latest_total_score"] = 94.5
payload["latest_proposal_id"] = "proposal_0006"
payload["latest_proposal"] = {
    "proposal_id": "proposal_0006",
    "proposer_model": "routine",
    "estimated_llm_cost_usd": 0.35,
}
latest.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
""",
    )

    exit_code = runner.main(
        [
            "--repo-root",
            str(repo_root),
            "--lanes",
            "command_node",
            "--max-rounds",
            "3",
        ]
    )

    assert exit_code == 0
    latest_summary = json.loads(
        (repo_root / "reports" / "autoresearch" / "local_improvement_search" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest_summary["improvement_found"] is True
    assert latest_summary["winning_lane"] == "command_node"
    assert latest_summary["best_improvement"]["loss_improvement"] == 2.5
    assert latest_summary["best_improvement"]["total_score_improvement"] == 4.5


def test_local_search_stops_cleanly_when_no_lane_improves(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write_json(
        repo_root / "reports" / "autoresearch" / "btc5_market" / "latest.json",
        {
            "champion": {
                "experiment_id": 1,
                "candidate_model_name": "baseline-market",
                "candidate_hash": "market-1",
                "loss": 10.0,
                "generated_at": "2026-03-11T20:00:00Z",
            },
            "latest_experiment": {
                "experiment_id": 1,
                "status": "keep",
                "decision_reason": "baseline_frontier",
                "proposal_id": "proposal_0001",
                "proposer_model": "seed",
                "estimated_llm_cost_usd": 0.35,
                "loss": 10.0,
                "keep": True,
            },
        },
    )
    _write_script(
        repo_root / "scripts" / "run_btc5_market_model_autoresearch.py",
        """#!/usr/bin/env python3
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
latest = root / "reports/autoresearch/btc5_market/latest.json"
payload = json.loads(latest.read_text())
payload["latest_experiment"] = {
    "experiment_id": 2,
    "status": "discard",
    "decision_reason": "below_frontier",
    "proposal_id": "proposal_0002",
    "proposer_model": "routine",
    "estimated_llm_cost_usd": 0.35,
    "loss": 10.4,
    "keep": False,
}
latest.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
""",
    )

    exit_code = runner.main(
        [
            "--repo-root",
            str(repo_root),
            "--lanes",
            "market",
            "--max-rounds",
            "2",
        ]
    )

    assert exit_code == 0
    latest_summary = json.loads(
        (repo_root / "reports" / "autoresearch" / "local_improvement_search" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest_summary["improvement_found"] is False
    assert latest_summary["stop_reason"] == "max_rounds_reached"
    assert latest_summary["lane_summaries"]["market"]["attempts"] == 2
