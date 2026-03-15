# BTC5 Command Node

This file is the only mutable surface for the BTC5 command-node autoresearch lane.
The task suite, scorer, chart renderer, and append-only results ledger are frozen within each benchmark epoch.

```json
{
  "task_suite_id": "command_node_btc5_v4",
  "candidate_label": "headroom-command-node-v4-proposal_0005-proposal_0006-proposal_0007-proposal_0001-proposal_0002-proposal_0003-proposal_0001",
  "responses": [
    {
      "task_id": "agent_lane_headroom_rebenchmark",
      "objective": "Execute BTC5 command-node mutation loop with v4 headroom, temp-workspace proposals, and keep-only overwrite with baseline below ninety five; keep-only overwrite; proposer metadata; temp workspace proposal while preserving the frozen command_node_btc5_v4 benchmark contract.",
      "owner_model": "Codex GPT-5 Extra High",
      "read_first": [
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/command_node/champion.json",
        "reports/autoresearch/command_node/results.jsonl",
        "benchmarks/command_node_btc5/v4/README.md",
        "benchmarks/command_node_btc5/v4/manifest.json",
        "benchmarks/command_node_btc5/v4/tasks.jsonl",
        "btc5_command_node.md",
        "scripts/run_btc5_command_node_autoresearch.py",
        "scripts/run_btc5_command_node_mutation_cycle.py",
        "research/btc5_command_node_progress.svg",
        "tests/test_btc5_command_node_benchmark.py",
        "tests/test_run_btc5_command_node_autoresearch.py"
      ],
      "files_to_edit": [
        "benchmarks/command_node_btc5/v4/README.md",
        "benchmarks/command_node_btc5/v4/manifest.json",
        "benchmarks/command_node_btc5/v4/tasks.jsonl",
        "btc5_command_node.md",
        "scripts/run_btc5_command_node_autoresearch.py",
        "scripts/run_btc5_command_node_mutation_cycle.py",
        "tests/test_btc5_command_node_benchmark.py",
        "tests/test_run_btc5_command_node_autoresearch.py"
      ],
      "output_files": [
        "instance02_agent_mutation_loop.md",
        "reports/autoresearch/command_node/champion.json",
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/command_node/results.jsonl",
        "research/btc5_command_node_progress.svg"
      ],
      "dependencies": [
        "load_champion_and_recent_failures",
        "freeze_v4_manifest_and_measure_current_baseline",
        "choose_proposer_tier_and_budget_window",
        "generate_candidate_in_temp_workspace",
        "benchmark_candidate_against_frozen_v4",
        "keep_only_when_frontier_improves",
        "prove_temp_workspace_candidate_cannot_overwrite_on_discard",
        "persist_proposer_metadata_and_lane_artifacts",
        "rerun_targeted_command_node_suite",
        "emit_handoff"
      ],
      "verification_commands": [
        "verify pytest",
        "verify mutation loop",
        "verify baseline < 95",
        "verify perfect synthetic packet = 100",
        "verify proposer metadata",
        "verify keep-only overwrite",
        "verify temp workspace"
      ],
      "checklist": [
        "v1 through v3 remain frozen and runnable",
        "v4 baseline is below saturation",
        "Perfect synthetic packet still reaches 100",
        "The command-node lane can hill-climb without overwriting on discards",
        "Karpathy-style command-node chart remains unchanged",
        "Temp-workspace proposal artifacts stay separate from the canonical mutable surface"
      ],
      "notes": "Use machine-truth lane artifacts first, keep one owner per path, and preserve baseline below ninety five; keep-only overwrite; proposer metadata; temp workspace proposal. Mutation strategy: targeted_task_repair. Recent failure focus: none."
    },
    {
      "task_id": "overnight_closeout_lane_artifact",
      "objective": "Execute BTC5 command-node frontier artifacts with explicit no_better_candidate and overnight closeout truth with no_better_candidate; suite-specific champion lineage; machine-readable frontier; overnight closeout truth while preserving the frozen command_node_btc5_v4 benchmark contract.",
      "owner_model": "Codex GPT-5 Extra High",
      "read_first": [
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/command_node/champion.json",
        "reports/autoresearch/command_node/results.jsonl",
        "reports/autoresearch/overnight_closeout/latest.json",
        "research/btc5_command_node_progress.svg",
        "scripts/render_btc5_command_node_progress.py",
        "scripts/run_btc5_command_node_autoresearch.py",
        "tests/test_btc5_dual_autoresearch_ops.py",
        "tests/test_run_btc5_command_node_autoresearch.py"
      ],
      "files_to_edit": [
        "btc5_command_node.md",
        "instance02_agent_mutation_loop.md",
        "scripts/run_btc5_command_node_autoresearch.py",
        "scripts/render_btc5_command_node_progress.py",
        "tests/test_btc5_dual_autoresearch_ops.py",
        "tests/test_run_btc5_command_node_autoresearch.py"
      ],
      "output_files": [
        "instance02_agent_mutation_loop.md",
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/command_node/champion.json",
        "reports/autoresearch/overnight_closeout/latest.json",
        "research/btc5_command_node_progress.svg"
      ],
      "dependencies": [
        "load_current_frontier_and_chart_contract",
        "classify_keep_discard_or_no_better_candidate",
        "preserve_suite_specific_champion_lineage",
        "surface_no_better_candidate_for_overnight_closeout",
        "write_latest_summary_and_champion_registry",
        "preserve_karpathy_chart_contract",
        "emit_handoff"
      ],
      "verification_commands": [
        "verify pytest",
        "verify no_better_candidate",
        "verify command-node chart",
        "verify suite-specific champion",
        "verify latest summary",
        "verify overnight closeout"
      ],
      "checklist": [
        "Legacy v1 through v3 champions do not block v4 keeps",
        "Latest summary reports keep discard and no_better_candidate cleanly",
        "Champion lineage stays suite-specific and machine-readable",
        "Karpathy-style command-node chart remains unchanged",
        "Overnight closeout surfaces no_better_candidate without inventing a keep"
      ],
      "notes": "Use machine-truth lane artifacts first, keep one owner per path, and preserve no_better_candidate; suite-specific champion lineage; machine-readable frontier; overnight closeout truth. Mutation strategy: targeted_task_repair. Recent failure focus: none."
    },
    {
      "task_id": "vps_burnin_supervised_lane_run",
      "objective": "Execute BTC5 follow-on handoff for AWS mutation-loop burn-in readiness with exact mutation-cycle entrypoints with mutation loops; proposer plus evaluator activity; explicit no_better_candidate; mutation-cycle entrypoints while preserving the frozen command_node_btc5_v4 benchmark contract.",
      "owner_model": "Claude Code | Sonnet 4.5",
      "read_first": [
        "deploy/btc5-command-node-autoresearch.service",
        "deploy/btc5-market-model-autoresearch.service",
        "deploy/btc5-autoresearch.service",
        "docs/ops/REMOTE_DEV_CYCLE_STANDARD.md",
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/btc5_market/latest.json",
        "scripts/run_btc5_command_node_mutation_cycle.py",
        "scripts/run_btc5_market_model_mutation_cycle.py"
      ],
      "files_to_edit": [
        "deploy/btc5-command-node-autoresearch.service",
        "deploy/btc5-market-model-autoresearch.service",
        "deploy/btc5-autoresearch.service",
        "deploy/btc5-autoresearch.timer",
        "docs/ops/REMOTE_DEV_CYCLE_STANDARD.md",
        "scripts/btc5_dual_autoresearch_ops.py"
      ],
      "output_files": [
        "instance05_aws_burnin.md",
        "reports/autoresearch/command_node/latest.json",
        "reports/autoresearch/btc5_market/latest.json",
        "reports/autoresearch/overnight_closeout/latest.json"
      ],
      "dependencies": [
        "point_services_at_mutation_cycle_runners",
        "name_exact_mutation_cycle_entrypoints",
        "verify_proposer_plus_evaluator_audit_growth",
        "require_explicit_no_better_candidate_or_improved_champion",
        "confirm_fresh_market_and_command_node_artifacts",
        "leave_final_burnin_decision_to_follow_on_instance",
        "emit_handoff"
      ],
      "verification_commands": [
        "verify systemd",
        "verify proposer",
        "verify evaluator",
        "verify no_better_candidate",
        "verify 8 hours",
        "verify mutation-cycle runner"
      ],
      "checklist": [
        "Follow-on burn-in explicitly targets mutation loops not evaluator-only runs",
        "Audit trail expects repeated proposer plus evaluator activity",
        "Final closeout can accept improved champion or explicit no_better_candidate",
        "Handoff names the exact artifact paths the burn-in must refresh",
        "Handoff names the exact command-node and market mutation-cycle entrypoints"
      ],
      "notes": "Use machine-truth lane artifacts first, keep one owner per path, and preserve mutation loops; proposer plus evaluator activity; explicit no_better_candidate; mutation-cycle entrypoints. Mutation strategy: targeted_task_repair. Recent failure focus: none."
    }
  ]
}
```

## Review Gate

Before keeping a new command-node candidate, confirm that the proposal was generated in a temp workspace, benchmarked on frozen v4, preserves suite-specific champion lineage, and overwrites the mutable surface only when the frontier improves.
