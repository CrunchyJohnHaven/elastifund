from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from benchmarks.btc5_market.v1.benchmark import freeze_benchmark_from_rows, sha256_file
import scripts.run_btc5_market_model_autoresearch as runner


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_btc5_market_model_autoresearch.py"
BASE_CANDIDATE_SOURCE = (ROOT / "btc5_market_model_candidate.py").read_text(encoding="utf-8")


def _synthetic_rows(count: int = 320) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start_ts = 1_773_057_000
    for index in range(count):
        direction = "DOWN" if index % 4 != 0 else "UP"
        session_name = "open_et" if index % 3 else "late_et"
        price_bucket = "0.49_to_0.51" if session_name == "open_et" else "lt_0.49"
        delta_bucket = "le_0.00005" if direction == "DOWN" else "gt_0.00010"
        live_fill = session_name == "open_et"
        positive_regime = direction == "DOWN" and live_fill
        pnl_usd = 1.1 if positive_regime else (-1.0 if live_fill else 0.0)
        rows.append(
            {
                "id": index + 1,
                "window_start_ts": start_ts + (index * 300),
                "slug": f"btc-window-{index:04d}",
                "direction": direction,
                "delta": -0.00007 if direction == "DOWN" else 0.00012,
                "abs_delta": 0.00007 if direction == "DOWN" else 0.00012,
                "order_price": 0.50 if live_fill else 0.48,
                "price_bucket": price_bucket,
                "delta_bucket": delta_bucket,
                "trade_size_usd": 10.0 if live_fill else 0.0,
                "won": bool(positive_regime),
                "pnl_usd": pnl_usd,
                "realized_pnl_usd": pnl_usd,
                "order_status": "live_filled" if live_fill else "skip_price_outside_guardrails",
                "et_hour": 9 if session_name == "open_et" else 16,
                "session_name": session_name,
                "best_bid": 0.49,
                "best_ask": 0.51,
                "open_price": 84_000.0,
                "current_price": 84_012.0,
                "edge_tier": "high" if positive_regime else "medium",
                "session_policy_name": session_name,
                "effective_stage": 1,
                "loss_cluster_suppressed": 0,
                "source": "synthetic",
            }
        )
    return rows


def _candidate_source(surface: dict[str, object]) -> str:
    return runner._replace_mutation_surface(BASE_CANDIDATE_SOURCE, surface)


def _poor_surface() -> dict[str, object]:
    return {
        "model_name": "flat_baseline",
        "model_version": 1,
        "feature_levels": [[]],
        "target_priors": {"p_up": 0.5, "fill_rate": 0.5, "pnl_pct": 0.0},
        "target_smoothing": {"p_up": 18.0, "fill_rate": 18.0, "pnl_pct": 18.0},
        "global_backstop_weight_min": 0.25,
        "global_backstop_weight_max": 0.92,
        "pnl_fill_blend_base": 0.82,
        "pnl_fill_blend_scale": 0.18,
        "pnl_clamp_abs": 0.75,
    }


def _write_broken_candidate(path: Path) -> str:
    broken_source = _candidate_source(_poor_surface()).replace(
        "    del feature_fields, seed\n",
        '    raise RuntimeError("intentional proposal crash")\n',
        1,
    )
    path.write_text(broken_source, encoding="utf-8")
    return broken_source


def _runner_base_args(
    *,
    manifest: Path,
    ledger: Path,
    champion: Path,
    latest_json: Path,
    latest_md: Path,
    policy_handoff: Path,
    chart_svg: Path,
    packet_dir: Path,
) -> list[str]:
    return [
        sys.executable,
        str(RUNNER_PATH),
        "--allow-noncanonical-candidate",
        "--manifest",
        str(manifest),
        "--ledger",
        str(ledger),
        "--champion-path",
        str(champion),
        "--latest-json",
        str(latest_json),
        "--latest-md",
        str(latest_md),
        "--policy-handoff-json",
        str(policy_handoff),
        "--chart-out",
        str(chart_svg),
        "--packet-dir",
        str(packet_dir),
    ]


def test_select_proposer_tier_can_force_expensive() -> None:
    now = datetime(2026, 3, 11, 23, 0, tzinfo=UTC)
    args = runner.parse_args(["--force-proposer-tier", "expensive"])

    selection = runner._select_proposer_tier([], now=now, args=args)

    assert selection["selected_tier"] == "expensive"
    assert selection["preferred_tier"] == "expensive"
    assert selection["proposer_model"] == runner.DEFAULT_EXPENSIVE_MODEL
    assert selection["escalation_reason"] == "forced_expensive"


def test_runner_mutation_cycle_keeps_then_discards_and_only_overwrites_canonical_on_keep(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmarks"
    freeze_benchmark_from_rows(_synthetic_rows(), benchmark_dir=benchmark_dir)

    incumbent_candidate = tmp_path / "market_model_candidate.py"
    incumbent_source = _candidate_source(_poor_surface())
    incumbent_candidate.write_text(incumbent_source, encoding="utf-8")
    incumbent_hash_before = sha256_file(incumbent_candidate)

    ledger = tmp_path / "results.jsonl"
    champion = tmp_path / "champion.json"
    latest_json = tmp_path / "latest.json"
    latest_md = tmp_path / "latest.md"
    policy_handoff = tmp_path / "policy_handoff.json"
    chart_svg = tmp_path / "progress.svg"
    packet_dir = tmp_path / "packets"
    manifest = benchmark_dir / "manifest.json"

    base_args = _runner_base_args(
        manifest=manifest,
        ledger=ledger,
        champion=champion,
        latest_json=latest_json,
        latest_md=latest_md,
        policy_handoff=policy_handoff,
        chart_svg=chart_svg,
        packet_dir=packet_dir,
    )

    first = subprocess.run(
        [*base_args, "--candidate-path", str(incumbent_candidate)],
        check=True,
        capture_output=True,
        text=True,
    )
    first_payload = json.loads(first.stdout)
    first_row = first_payload["latest_experiment"]
    first_proposal = first_payload["latest_proposal"]
    first_candidate_artifact = packet_dir / "experiment_0001_candidate.py"

    assert first_row["status"] == "keep"
    assert first_row["proposal_id"].startswith("btc5-market-proposal-")
    assert first_row["parent_champion_id"] is None
    assert first_row["candidate_path"] == str(first_candidate_artifact)
    assert first_row["mutable_surface_path"] == str(incumbent_candidate)
    assert first_row["estimated_llm_cost_usd"] == runner.DEFAULT_ROUTINE_ESTIMATED_LLM_COST_USD
    assert first_payload["budget"]["selected_tier"] == "routine"
    assert first_candidate_artifact.exists()
    assert incumbent_candidate.read_text(encoding="utf-8") == first_candidate_artifact.read_text(encoding="utf-8")
    assert sha256_file(incumbent_candidate) == first_row["candidate_hash"]
    assert sha256_file(incumbent_candidate) != incumbent_hash_before
    assert first_proposal["artifact_paths"]["proposal_candidate_py"] == str(first_candidate_artifact)

    first_packet = json.loads(Path(first_row["packet_json"]).read_text(encoding="utf-8"))
    assert first_packet["proposal_id"] == first_row["proposal_id"]
    assert first_packet["parent_champion_id"] is None
    assert first_packet["proposer_model"] == first_row["proposer_model"]
    assert first_packet["proposer_tier"] == first_row["proposer_tier"]
    assert first_packet["estimated_llm_cost_usd"] == first_row["estimated_llm_cost_usd"]
    assert first_packet["mutation_summary"] == first_row["mutation_summary"]
    assert first_packet["mutation_type"] == first_row["mutation_type"]
    assert first_packet["proposal"]["proposal_id"] == first_row["proposal_id"]
    assert first_packet["decision"]["status"] == "keep"
    assert first_packet["mutable_surface_path"] == str(incumbent_candidate)

    second = subprocess.run(
        [*base_args, "--candidate-path", str(incumbent_candidate)],
        check=True,
        capture_output=True,
        text=True,
    )
    second_payload = json.loads(second.stdout)
    second_row = second_payload["latest_experiment"]
    second_candidate_artifact = packet_dir / "experiment_0002_candidate.py"

    assert second_row["status"] == "discard"
    assert second_row["parent_champion_id"] == 1
    assert second_row["candidate_path"] == str(second_candidate_artifact)
    assert second_candidate_artifact.exists()
    assert incumbent_candidate.read_text(encoding="utf-8") == first_candidate_artifact.read_text(encoding="utf-8")
    assert sha256_file(incumbent_candidate) == first_row["candidate_hash"]
    assert second_row["candidate_hash"] != first_row["candidate_hash"]

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["status"] for row in rows] == ["keep", "discard"]
    assert rows[0]["champion_id"] == 1
    assert rows[1]["champion_id"] == 1
    assert rows[0]["mutable_surface_sha256_before"] == incumbent_hash_before
    assert rows[0]["mutable_surface_sha256_after"] == rows[0]["candidate_hash"]
    assert rows[1]["mutable_surface_sha256_after"] == rows[0]["candidate_hash"]

    champion_payload = json.loads(champion.read_text(encoding="utf-8"))
    assert champion_payload["experiment_id"] == 1
    assert champion_payload["candidate_path"] == str(first_candidate_artifact)
    assert champion_payload["mutable_surface_path"] == str(incumbent_candidate)
    assert chart_svg.exists()
    assert latest_json.exists()
    assert latest_md.exists()


def test_runner_crash_rows_preserve_proposal_lineage_and_do_not_overwrite_surface(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmarks"
    freeze_benchmark_from_rows(_synthetic_rows(), benchmark_dir=benchmark_dir)

    broken_candidate = tmp_path / "broken_candidate.py"
    broken_source = _write_broken_candidate(broken_candidate)

    ledger = tmp_path / "results.jsonl"
    champion = tmp_path / "champion.json"
    latest_json = tmp_path / "latest.json"
    latest_md = tmp_path / "latest.md"
    policy_handoff = tmp_path / "policy_handoff.json"
    chart_svg = tmp_path / "progress.svg"
    packet_dir = tmp_path / "packets"
    manifest = benchmark_dir / "manifest.json"

    result = subprocess.run(
        [
            *_runner_base_args(
                manifest=manifest,
                ledger=ledger,
                champion=champion,
                latest_json=latest_json,
                latest_md=latest_md,
                policy_handoff=policy_handoff,
                chart_svg=chart_svg,
                packet_dir=packet_dir,
            ),
            "--candidate-path",
            str(broken_candidate),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    crash_row = payload["latest_experiment"]
    assert crash_row["status"] == "crash"
    assert crash_row["loss"] is None
    assert crash_row["proposal_id"].startswith("btc5-market-proposal-")
    assert crash_row["candidate_path"].endswith("experiment_0001_candidate.py")
    assert broken_candidate.read_text(encoding="utf-8") == broken_source
    assert not champion.exists()

    crash_packet = json.loads(Path(crash_row["packet_json"]).read_text(encoding="utf-8"))
    assert crash_packet["proposal_id"] == crash_row["proposal_id"]
    assert crash_packet["proposer_model"] == crash_row["proposer_model"]
    assert crash_packet["estimated_llm_cost_usd"] == crash_row["estimated_llm_cost_usd"]
    assert crash_packet["mutation_type"] == crash_row["mutation_type"]
    assert crash_packet["proposal"]["proposal_id"] == crash_row["proposal_id"]
    assert crash_packet["proposal"]["mutation_type"] != ""
    assert crash_packet["error"] == {
        "type": "RuntimeError",
        "message": "intentional proposal crash",
    }
    assert crash_packet["mutable_surface_path"] == str(broken_candidate)

    crash_proposal = json.loads(Path(crash_row["artifact_paths"]["proposal_json"]).read_text(encoding="utf-8"))
    assert crash_proposal["status"] == "crash"
    assert crash_proposal["decision_reason"] == "RuntimeError"
    assert crash_proposal["artifact_paths"]["proposal_candidate_py"] == crash_row["candidate_path"]
    assert chart_svg.exists()


def test_select_proposer_tier_escalates_after_discard_streak() -> None:
    now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    rows = [
        {
            "generated_at": (now - timedelta(hours=11 - index)).isoformat(),
            "status": "discard",
            "estimated_llm_cost_usd": runner.DEFAULT_ROUTINE_ESTIMATED_LLM_COST_USD,
        }
        for index in range(10)
    ]
    args = argparse.Namespace(
        daily_proposer_budget_usd=runner.DEFAULT_DAILY_PROPOSER_BUDGET_USD,
        routine_proposer_model=runner.DEFAULT_ROUTINE_MODEL,
        expensive_proposer_model=runner.DEFAULT_EXPENSIVE_MODEL,
        budget_fallback_proposer_model=runner.DEFAULT_BUDGET_FALLBACK_MODEL,
        routine_estimated_llm_cost_usd=runner.DEFAULT_ROUTINE_ESTIMATED_LLM_COST_USD,
        expensive_estimated_llm_cost_usd=runner.DEFAULT_EXPENSIVE_ESTIMATED_LLM_COST_USD,
    )

    selection = runner._select_proposer_tier(rows, now=now, args=args)

    assert selection["selected_tier"] == "expensive"
    assert selection["preferred_tier"] == "expensive"
    assert selection["proposer_model"] == runner.DEFAULT_EXPENSIVE_MODEL
    assert selection["estimated_llm_cost_usd"] == runner.DEFAULT_EXPENSIVE_ESTIMATED_LLM_COST_USD
    assert selection["consecutive_discards"] == 10
    assert selection["escalation_reason"] == "discard_streak_10"
