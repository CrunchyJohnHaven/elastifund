"""Tests for the flywheel control plane."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data_layer import crud
from data_layer.schema import Base
from flywheel.automation import build_payload_from_config, run_from_config
from flywheel.bridge import build_payload_from_bot_db
from flywheel.federation import export_bulletin, import_bulletin
from flywheel.improvement_exchange import (
    export_improvement_bundle,
    import_improvement_bundle,
    load_knowledge_pack,
    publish_knowledge_pack,
    pull_knowledge_pack,
    load_improvement_bundle,
    verify_knowledge_pack,
    verify_improvement_bundle,
)
from flywheel.policy import evaluate_snapshot, is_lane_killed, KILLED_LANES
from flywheel.runner import build_scorecard_from_db, run_cycle


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
        engine.dispose()


def _snapshot_payload(**overrides):
    payload = {
        "snapshot_date": "2026-03-07",
        "starting_bankroll": 100.0,
        "ending_bankroll": 112.0,
        "realized_pnl": 12.0,
        "unrealized_pnl": 1.5,
        "open_positions": 2,
        "closed_trades": 24,
        "win_rate": 0.62,
        "fill_rate": 0.71,
        "avg_slippage_bps": 12.0,
        "rolling_brier": 0.22,
        "rolling_ece": 0.06,
        "max_drawdown_pct": 0.08,
        "kill_events": 0,
    }
    payload.update(overrides)
    return payload


class TestFlywheelPolicy:
    def test_paper_snapshot_promotes_when_thresholds_pass(self, session):
        version = crud.create_strategy_version(
            session,
            strategy_key="wallet-flow",
            version_label="v1",
            lane="fast_flow",
        )
        deployment = crud.create_deployment(
            session,
            strategy_version_id=version.id,
            environment="paper",
            capital_cap_usd=25.0,
        )
        snapshot = crud.create_daily_snapshot(
            session,
            strategy_version_id=version.id,
            deployment_id=deployment.id,
            environment="paper",
            **_snapshot_payload(),
        )

        outcome = evaluate_snapshot(snapshot)

        assert outcome.decision == "promote"
        assert outcome.to_stage == "shadow"
        assert outcome.reason_code == "promotion_policy_pass"

    def test_micro_live_snapshot_demotes_on_fill_rate_collapse(self, session):
        version = crud.create_strategy_version(
            session,
            strategy_key="constraint-arb",
            version_label="v2",
            lane="structural_arb",
        )
        deployment = crud.create_deployment(
            session,
            strategy_version_id=version.id,
            environment="micro_live",
            capital_cap_usd=25.0,
        )
        snapshot = crud.create_daily_snapshot(
            session,
            strategy_version_id=version.id,
            deployment_id=deployment.id,
            environment="micro_live",
            **_snapshot_payload(fill_rate=0.10, closed_trades=25),
        )

        outcome = evaluate_snapshot(snapshot)

        assert outcome.decision == "demote"
        assert outcome.to_stage == "shadow"
        assert outcome.reason_code == "fill_rate_below_gate"

    def test_any_kill_event_forces_kill(self, session):
        version = crud.create_strategy_version(
            session,
            strategy_key="llm-lane",
            version_label="v3",
            lane="slow_directional",
        )
        deployment = crud.create_deployment(
            session,
            strategy_version_id=version.id,
            environment="shadow",
            capital_cap_usd=10.0,
        )
        snapshot = crud.create_daily_snapshot(
            session,
            strategy_version_id=version.id,
            deployment_id=deployment.id,
            environment="shadow",
            **_snapshot_payload(kill_events=1),
        )

        outcome = evaluate_snapshot(snapshot)

        assert outcome.decision == "kill"
        assert outcome.reason_code == "kill_events_present"


    def test_killed_lane_blocks_promotion(self, session):
        version = crud.create_strategy_version(
            session,
            strategy_key="weather-bracket",
            version_label="v1",
            lane="kalshi_weather",
        )
        deployment = crud.create_deployment(
            session,
            strategy_version_id=version.id,
            environment="paper",
            capital_cap_usd=100.0,
        )
        snapshot = crud.create_daily_snapshot(
            session,
            strategy_version_id=version.id,
            deployment_id=deployment.id,
            environment="paper",
            **_snapshot_payload(
                metrics={"candidate_source": "kalshi_weather_bracket"},
            ),
        )

        outcome = evaluate_snapshot(snapshot)

        assert outcome.decision == "hold"
        assert outcome.reason_code == "lane_killed"
        assert "kalshi_weather_bracket" not in outcome.to_stage

    def test_is_lane_killed_utility(self):
        assert is_lane_killed("kalshi_weather_bracket") is True
        assert is_lane_killed("btc5_maker") is False


class TestFlywheelRunner:
    def test_run_cycle_persists_records_and_artifacts(self, session, tmp_path):
        payload = {
            "cycle_key": "20260307T210000Z",
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-20260307",
                    "lane": "fast_flow",
                    "artifact_uri": "artifacts/wallet-flow/wf-20260307.tar.gz",
                    "git_sha": "abc123",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                            "status": "active",
                            "snapshot": _snapshot_payload(),
                        }
                    ],
                },
                {
                    "strategy_key": "constraint-arb",
                    "version_label": "ca-20260307",
                    "lane": "structural_arb",
                    "artifact_uri": "artifacts/constraint-arb/ca-20260307.tar.gz",
                    "git_sha": "def456",
                    "deployments": [
                        {
                            "environment": "micro_live",
                            "capital_cap_usd": 25.0,
                            "status": "active",
                            "snapshot": _snapshot_payload(
                                fill_rate=0.20,
                                closed_trades=25,
                                realized_pnl=-4.0,
                                ending_bankroll=96.0,
                            ),
                        }
                    ],
                },
            ],
        }

        result = run_cycle(session, payload, artifact_root=tmp_path)

        assert result["evaluated"] == 2
        assert len(result["decisions"]) == 2
        assert len(result["tasks"]) == 2
        assert len(result["findings"]) == 2
        assert Path(result["artifacts"]["scorecard"]).exists()
        assert Path(result["artifacts"]["summary_md"]).exists()
        assert Path(result["artifacts"]["findings_json"]).exists()

        versions = crud.list_strategy_versions(session)
        deployments = crud.list_deployments(session)
        decisions = crud.list_promotion_decisions(session)
        findings = crud.list_flywheel_findings(session)
        tasks = crud.list_flywheel_tasks(session)
        cycles = crud.list_flywheel_cycles(session)

        assert len(versions) == 2
        assert len(decisions) == 2
        assert len(findings) == 2
        assert len(tasks) == 2
        assert len(cycles) == 1

        planned_shadow = [
            row for row in deployments if row.environment == "shadow" and row.status == "planned"
        ]
        assert planned_shadow, "Expected promoted or demoted follow-up deployment to be created"

    def test_build_scorecard_from_db_uses_latest_snapshots(self, session, tmp_path):
        payload = {
            "cycle_key": "20260307T220000Z",
            "strategies": [
                {
                    "strategy_key": "llm-lane",
                    "version_label": "llm-20260307",
                    "lane": "slow_directional",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 15.0,
                            "snapshot": _snapshot_payload(realized_pnl=5.0, closed_trades=18),
                        }
                    ],
                }
            ],
        }

        run_cycle(session, payload, artifact_root=tmp_path)
        scorecard = build_scorecard_from_db(session)

        assert scorecard["strategy_count"] >= 1
        assert "paper" in scorecard["environments"]
        assert scorecard["environments"]["paper"]["realized_pnl"] == pytest.approx(5.0)
        assert "finding_counts" in scorecard

        summary = json.loads(Path(tmp_path / "20260307T220000Z" / "scorecard.json").read_text())
        assert summary["strategy_count"] == 1


class TestFlywheelBridge:
    def test_build_payload_from_portfolio_bot_db(self, tmp_path):
        bot_db = _make_portfolio_bot_db(tmp_path / "bot.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="wallet-flow",
            version_label="wf-live",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            artifact_uri="artifacts/wf-live.tar.gz",
            git_sha="abc123",
            lookback_days=7,
        )

        strategy = payload["strategies"][0]
        deployment = strategy["deployments"][0]
        snapshot = deployment["snapshot"]

        assert strategy["strategy_key"] == "wallet-flow"
        assert deployment["environment"] == "paper"
        assert snapshot["snapshot_date"] == "2026-03-07"
        assert snapshot["starting_bankroll"] == pytest.approx(100.0)
        assert snapshot["ending_bankroll"] == pytest.approx(111.0)
        assert snapshot["closed_trades"] == 2
        assert snapshot["fill_rate"] == pytest.approx(2 / 3)
        assert snapshot["avg_slippage_bps"] == pytest.approx(10.0)
        assert snapshot["kill_events"] == 1

    def test_build_payload_from_runtime_bot_db(self, tmp_path):
        bot_db = _make_runtime_bot_db(tmp_path / "runtime.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="polymarket-bot",
            version_label="runtime-live",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            lookback_days=7,
        )

        strategy = payload["strategies"][0]
        snapshot = strategy["deployments"][0]["snapshot"]

        assert strategy["config"]["bridge_schema"] == "runtime"
        assert snapshot["snapshot_date"] == "2026-03-07"
        assert snapshot["starting_bankroll"] == pytest.approx(100.0)
        assert snapshot["ending_bankroll"] == pytest.approx(105.0)
        assert snapshot["realized_pnl"] == pytest.approx(6.0)
        assert snapshot["unrealized_pnl"] == pytest.approx(4.0)
        assert snapshot["open_positions"] == 2
        assert snapshot["closed_trades"] == 1
        assert snapshot["win_rate"] == pytest.approx(0.5)
        assert snapshot["fill_rate"] == pytest.approx(2 / 3)
        assert snapshot["avg_slippage_bps"] == pytest.approx(153.4090909090909)
        assert snapshot["kill_events"] == 1
        assert snapshot["metrics"]["bot_version"] == "0.1.2"
        assert snapshot["metrics"]["trade_decisions"] == 1
        assert snapshot["metrics"]["detector_opportunities"] == 1

    def test_build_payload_from_empty_runtime_bot_db(self, tmp_path):
        bot_db = _make_empty_runtime_bot_db(tmp_path / "empty-runtime.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="polymarket-bot",
            version_label="runtime-live",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            lookback_days=7,
        )

        snapshot = payload["strategies"][0]["deployments"][0]["snapshot"]

        assert snapshot["closed_trades"] == 0
        assert snapshot["fill_rate"] is None
        assert snapshot["avg_slippage_bps"] is None
        assert snapshot["kill_events"] == 0
        assert snapshot["metrics"]["bot_is_running"] is False

    def test_build_payload_from_jj_live_bot_db(self, tmp_path):
        bot_db = _make_jj_live_bot_db(tmp_path / "jj-live.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="jj-live",
            version_label="runtime-vps",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            lookback_days=7,
        )

        strategy = payload["strategies"][0]
        snapshot = strategy["deployments"][0]["snapshot"]

        assert strategy["config"]["bridge_schema"] == "jj_live"
        assert snapshot["snapshot_date"] == "2026-03-07"
        assert snapshot["starting_bankroll"] == pytest.approx(100.0)
        assert snapshot["ending_bankroll"] == pytest.approx(103.0)
        assert snapshot["realized_pnl"] == pytest.approx(3.0)
        assert snapshot["unrealized_pnl"] == pytest.approx(0.0)
        assert snapshot["open_positions"] == 1
        assert snapshot["closed_trades"] == 2
        assert snapshot["win_rate"] == pytest.approx(0.5)
        assert snapshot["fill_rate"] == pytest.approx(2 / 3)
        assert snapshot["avg_slippage_bps"] == pytest.approx(150.0)
        assert snapshot["rolling_brier"] == pytest.approx(0.125)
        assert snapshot["kill_events"] == 1
        assert snapshot["metrics"]["paper_mode"] is False
        assert snapshot["metrics"]["cycles_logged"] == 2
        assert snapshot["metrics"]["signals_found"] == 3
        assert snapshot["metrics"]["trades_placed"] == 3
        assert snapshot["metrics"]["unresolved_trades"] == 1

    def test_build_payload_from_sparse_jj_live_bot_db(self, tmp_path):
        bot_db = _make_sparse_jj_live_bot_db(tmp_path / "jj-live-sparse.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="jj-live",
            version_label="runtime-vps",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            lookback_days=7,
        )

        snapshot = payload["strategies"][0]["deployments"][0]["snapshot"]

        assert snapshot["starting_bankroll"] == pytest.approx(1000.0)
        assert snapshot["ending_bankroll"] == pytest.approx(1000.0)
        assert snapshot["closed_trades"] == 0
        assert snapshot["fill_rate"] is None
        assert snapshot["avg_slippage_bps"] is None
        assert snapshot["kill_events"] == 0
        assert snapshot["metrics"]["cycles_logged"] == 2
        assert snapshot["metrics"]["paper_mode"] is True
        assert snapshot["metrics"]["unresolved_trades"] == 0

    def test_build_payload_from_jj_live_bot_db_filters_current_mode(self, tmp_path):
        bot_db = _make_mixed_mode_jj_live_bot_db(tmp_path / "jj-live-mixed.db")

        payload = build_payload_from_bot_db(
            bot_db,
            strategy_key="jj-live",
            version_label="runtime-vps",
            lane="fast_flow",
            environment="paper",
            capital_cap_usd=25.0,
            lookback_days=7,
        )

        snapshot = payload["strategies"][0]["deployments"][0]["snapshot"]

        assert snapshot["starting_bankroll"] == pytest.approx(250.0)
        assert snapshot["ending_bankroll"] == pytest.approx(250.0)
        assert snapshot["max_drawdown_pct"] == pytest.approx(0.0)
        assert snapshot["metrics"]["paper_mode"] is False


class TestFlywheelAutomation:
    def test_build_payload_from_config(self, tmp_path):
        bot_db = _make_portfolio_bot_db(tmp_path / "bot.db")
        config = {
            "cycle_key": "runtime-test",
            "strategies": [
                {
                    "bot_db": str(bot_db),
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "environment": "paper",
                    "capital_cap_usd": 25.0,
                }
            ],
        }

        payload = build_payload_from_config(config)

        assert payload["cycle_key"] == "runtime-test"
        assert len(payload["strategies"]) == 1
        assert payload["strategies"][0]["strategy_key"] == "wallet-flow"

    def test_run_from_config_executes_full_cycle(self, tmp_path):
        bot_db = _make_portfolio_bot_db(tmp_path / "bot.db")
        control_db = tmp_path / "flywheel.db"
        config_path = tmp_path / "runtime.json"
        artifact_dir = tmp_path / "artifacts"
        config_path.write_text(
            json.dumps(
                {
                    "cycle_key": "runtime-test",
                    "control_db_url": f"sqlite:///{control_db}",
                    "artifact_dir": str(artifact_dir),
                    "strategies": [
                        {
                            "bot_db": str(bot_db),
                            "strategy_key": "wallet-flow",
                            "version_label": "wf-live",
                            "lane": "fast_flow",
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                        }
                    ],
                }
            )
        )

        result = run_from_config(config_path)

        assert result["cycle_key"] == "runtime-test"
        assert result["evaluated"] == 1
        assert Path(result["artifacts"]["summary_md"]).exists()

    def test_run_from_config_executes_full_cycle_for_jj_live_db(self, tmp_path):
        bot_db = _make_jj_live_bot_db(tmp_path / "jj-live.db")
        control_db = tmp_path / "flywheel.db"
        config_path = tmp_path / "runtime-jj-live.json"
        artifact_dir = tmp_path / "artifacts"
        config_path.write_text(
            json.dumps(
                {
                    "cycle_key": "jj-live-runtime-test",
                    "control_db_url": f"sqlite:///{control_db}",
                    "artifact_dir": str(artifact_dir),
                    "strategies": [
                        {
                            "bot_db": str(bot_db),
                            "strategy_key": "jj-live",
                            "version_label": "runtime-vps",
                            "lane": "fast_flow",
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                        }
                    ],
                }
            )
        )

        result = run_from_config(config_path)

        assert result["cycle_key"] == "jj-live-runtime-test"
        assert result["evaluated"] == 1
        assert Path(result["artifacts"]["summary_md"]).exists()


class TestFlywheelFederation:
    def test_export_and_import_bulletin(self, session, tmp_path):
        payload = {
            "cycle_key": "federation-seed",
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                            "snapshot": _snapshot_payload(),
                        }
                    ],
                }
            ],
        }
        run_cycle(session, payload, artifact_root=tmp_path)

        bulletin = export_bulletin(session, peer_name="alpha-fork", decision_types=("promote",), limit=10)

        assert bulletin["peer_name"] == "alpha-fork"
        assert bulletin["item_count"] >= 1
        assert bulletin["items"][0]["strategy_key"] == "wallet-flow"

        imported = import_bulletin(session, bulletin)

        assert imported["tasks_created"] >= 1
        tasks = crud.list_flywheel_tasks(session, status="open")
        assert any("Review peer paydirt from alpha-fork" in task.title for task in tasks)

    def test_import_bulletin_is_idempotent(self, session, tmp_path):
        payload = {
            "cycle_key": "federation-seed-2",
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                            "snapshot": _snapshot_payload(),
                        }
                    ],
                }
            ],
        }
        run_cycle(session, payload, artifact_root=tmp_path)

        bulletin = export_bulletin(session, peer_name="alpha-fork", decision_types=("promote",), limit=10)
        first = import_bulletin(session, bulletin)
        second = import_bulletin(session, bulletin)

        assert first["tasks_created"] >= 1
        assert first["already_imported"] is False
        assert second["tasks_created"] == 0
        assert second["already_imported"] is True

    def test_export_bulletin_can_include_knowledge_pack_summaries(self, session, tmp_path):
        pack = publish_knowledge_pack(
            session,
            peer_name="alpha-fork",
            engine_key="revenue_audit",
            engine_version="audit-v1",
            engine_metadata={
                "lane": "revenue_audit",
                "environment": "shadow",
                "summary": "Sanitized website-audit cohort results.",
            },
            detector_summaries=[
                {
                    "detector_key": "checkout_latency",
                    "summary": "Slow checkout pages reduce conversion for SMB storefronts.",
                    "sample_size": 12,
                    "conversion_rate": 0.18,
                    "customer_email": "hidden@example.com",
                }
            ],
            template_variants=[
                {
                    "template_key": "audit_lp",
                    "variant": "A",
                    "summary": "Control variant with direct CTA.",
                    "net_revenue_usd": 1200.0,
                }
            ],
            aggregated_outcomes={
                "observed_count": 12,
                "expected_net_cash_30d": 1800.0,
                "conversion_rate": 0.18,
                "refund_rate": 0.02,
                "gross_margin_pct": 0.7,
            },
            penalty_metrics={"refund_penalty": 0.02, "domain_health_penalty": 0.01},
            proof_references=[
                {
                    "ref_key": "proof-1",
                    "proof_type": "sha256",
                    "sha256": "a" * 64,
                }
            ],
            output_path=tmp_path / "knowledge_pack.json",
            signing_secret="shared-secret",
        )

        bulletin = export_bulletin(
            session,
            peer_name="alpha-fork",
            include_knowledge_packs=True,
        )

        assert bulletin["knowledge_pack_count"] == 1
        summary = bulletin["knowledge_packs"][0]
        assert summary["engine_key"] == "revenue_audit"
        assert summary["verification_status"] == "signed"
        assert pack["privacy"]["redaction_counts"]["customer_email"] == 1


class TestImprovementExchange:
    def test_export_and_import_improvement_bundle(self, session, tmp_path):
        payload = {
            "cycle_key": "improvement-seed",
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                            "snapshot": _snapshot_payload(),
                        }
                    ],
                }
            ],
        }
        run_cycle(session, payload, artifact_root=tmp_path / "artifacts")

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        source_file = repo_root / "strategy.py"
        source_file.write_text("EDGE_THRESHOLD = 0.07\n")
        output_path = tmp_path / "bundle.json"

        bundle = export_improvement_bundle(
            session,
            peer_name="alpha-fork",
            strategy_key="wallet-flow",
            version_label="wf-live",
            include_paths=[source_file],
            outcome="improved",
            summary="Raised the edge threshold and improved paper returns.",
            hypothesis="Filtering weaker setups improves realized edge.",
            repo_root=repo_root,
            output_path=output_path,
            signing_secret="shared-secret",
        )

        assert output_path.exists()
        assert bundle["claim"]["outcome"] == "improved"
        assert bundle["integrity"]["signature_hmac_sha256"]
        assert bundle["code"]["files"][0]["path"] == "strategy.py"

        imported_bundle = load_improvement_bundle(output_path)
        result = import_improvement_bundle(
            session,
            imported_bundle,
            review_root=tmp_path / "peer_reviews",
            signing_secret="shared-secret",
            require_signature=True,
        )

        assert result["tasks_created"] == 1
        assert result["verification_status"] == "verified"
        review_dir = Path(result["review_dir"])
        assert (review_dir / "bundle.json").exists()
        assert (review_dir / "review.md").exists()
        assert (review_dir / "pr_body.md").exists()
        assert (review_dir / "files" / "strategy.py").exists()

        tasks = crud.list_flywheel_tasks(session, status="open")
        assert any("Review peer improved bundle from alpha-fork" in task.title for task in tasks)

        imported_rows = crud.list_peer_improvement_bundles(session, direction="imported")
        exported_rows = crud.list_peer_improvement_bundles(session, direction="exported")
        assert len(imported_rows) == 1
        assert len(exported_rows) == 1

    def test_verify_improvement_bundle_rejects_tampering(self, session, tmp_path):
        payload = {
            "cycle_key": "improvement-seed-tamper",
            "strategies": [
                {
                    "strategy_key": "wallet-flow",
                    "version_label": "wf-live",
                    "lane": "fast_flow",
                    "deployments": [
                        {
                            "environment": "paper",
                            "capital_cap_usd": 25.0,
                            "snapshot": _snapshot_payload(),
                        }
                    ],
                }
            ],
        }
        run_cycle(session, payload, artifact_root=tmp_path / "artifacts")

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        source_file = repo_root / "strategy.py"
        source_file.write_text("EDGE_THRESHOLD = 0.07\n")

        bundle = export_improvement_bundle(
            session,
            peer_name="alpha-fork",
            strategy_key="wallet-flow",
            version_label="wf-live",
            include_paths=[source_file],
            outcome="failed",
            repo_root=repo_root,
            signing_secret="shared-secret",
        )
        bundle["code"]["files"][0]["content"] = "EDGE_THRESHOLD = 0.01\n"

        with pytest.raises(ValueError):
            verify_improvement_bundle(bundle, signing_secret="shared-secret", require_signature=True)

    def test_publish_and_pull_knowledge_pack(self, session, tmp_path):
        output_path = tmp_path / "knowledge_pack.json"
        pack = publish_knowledge_pack(
            session,
            peer_name="alpha-fork",
            engine_key="revenue_audit",
            engine_version="audit-v2",
            engine_metadata={
                "lane": "revenue_audit",
                "environment": "shadow",
                "summary": "Website audit packs for self-serve storefront fixes.",
                "sample_size": 18,
                "customer_name": "Should not survive",
            },
            detector_summaries=[
                {
                    "detector_key": "broken_checkout",
                    "summary": "Checkout abandonment spikes when mobile form validation fails. Contact ops@example.com.",
                    "sample_size": 18,
                    "conversion_rate": 0.22,
                    "refund_rate": 0.01,
                    "customer_email": "ops@example.com",
                }
            ],
            template_variants=[
                {
                    "template_key": "audit_lp",
                    "variant": "B",
                    "channel": "landing_page",
                    "summary": "Evidence-first landing page with proof hashes only.",
                    "net_revenue_usd": 2100.0,
                    "payment_details": "4111111111111111",
                }
            ],
            aggregated_outcomes={
                "observed_count": 18,
                "expected_net_cash_30d": 2400.0,
                "net_revenue_usd": 2100.0,
                "conversion_rate": 0.22,
                "refund_rate": 0.01,
                "churn_rate": 0.03,
                "gross_margin_pct": 0.68,
                "checkout_session_id": "cs_test_secret",
            },
            penalty_metrics={
                "refund_penalty": 0.02,
                "fulfillment_penalty": 0.03,
                "domain_health_penalty": 0.01,
            },
            proof_references=[
                {
                    "ref_key": "proof-1",
                    "proof_type": "sha256",
                    "sha256": "b" * 64,
                    "artifact_uri": "s3://packs/proof-1.json",
                }
            ],
            output_path=output_path,
            signing_secret="shared-secret",
        )

        assert output_path.exists()
        assert pack["bundle_type"] == "knowledge_pack"
        assert pack["privacy"]["raw_customer_data_included"] is False
        assert "customer_name" in pack["privacy"]["redaction_counts"]
        assert pack["detector_summaries"][0]["summary"].count("<redacted-email>") == 1
        assert "customer_email" not in pack["detector_summaries"][0]
        assert "payment_details" not in pack["template_variants"][0]
        assert "checkout_session_id" not in pack["aggregated_outcomes"]
        assert pack["leaderboard_entry"]["engine_key"] == "revenue_audit"
        assert pack["integrity"]["signature_hmac_sha256"]

        loaded_pack = load_knowledge_pack(output_path)
        pulled = pull_knowledge_pack(
            session,
            loaded_pack,
            review_root=tmp_path / "knowledge_reviews",
            signing_secret="shared-secret",
            require_signature=True,
        )

        assert pulled["tasks_created"] == 1
        assert pulled["verification_status"] == "verified"
        review_dir = Path(pulled["review_dir"])
        assert (review_dir / "knowledge_pack.json").exists()
        assert (review_dir / "review.md").exists()
        assert (review_dir / "leaderboard.json").exists()
        assert (review_dir / "leaderboard.md").exists()

        tasks = crud.list_flywheel_tasks(session, status="open")
        assert any("Review knowledge pack from alpha-fork" in task.title for task in tasks)

        imported_rows = crud.list_peer_improvement_bundles(session, direction="imported")
        exported_rows = crud.list_peer_improvement_bundles(session, direction="exported")
        assert len(imported_rows) == 1
        assert len(exported_rows) == 1

    def test_verify_knowledge_pack_rejects_private_fields(self, session, tmp_path):
        pack = publish_knowledge_pack(
            session,
            peer_name="alpha-fork",
            engine_key="revenue_audit",
            engine_version="audit-v3",
            engine_metadata={"lane": "revenue_audit"},
            detector_summaries=[],
            template_variants=[],
            aggregated_outcomes={"expected_net_cash_30d": 100.0},
            penalty_metrics={"refund_penalty": 0.01},
            proof_references=[],
            output_path=tmp_path / "knowledge_pack.json",
            signing_secret="shared-secret",
        )
        pack["detector_summaries"].append({"customer_email": "hidden@example.com"})

        with pytest.raises(ValueError):
            verify_knowledge_pack(pack, signing_secret="shared-secret", require_signature=True)


def _make_portfolio_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE portfolio_snapshots (
                id TEXT PRIMARY KEY,
                date TEXT UNIQUE,
                cash_usd REAL,
                positions_value_usd REAL,
                total_value_usd REAL,
                realized_pnl REAL,
                unrealized_pnl REAL,
                open_positions INTEGER,
                win_rate REAL,
                created_at TEXT
            );
            CREATE TABLE execution_stats (
                id TEXT PRIMARY KEY,
                slippage_vs_mid REAL,
                was_filled INTEGER,
                created_at TEXT
            );
            CREATE TABLE exit_events (
                id TEXT PRIMARY KEY,
                created_at TEXT
            );
            CREATE TABLE risk_events (
                id TEXT PRIMARY KEY,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO portfolio_snapshots
            (id, date, cash_usd, positions_value_usd, total_value_usd, realized_pnl, unrealized_pnl, open_positions, win_rate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("p1", "2026-03-06", 80.0, 20.0, 100.0, 5.0, 1.0, 1, 0.6, "2026-03-06T23:59:00"),
                ("p2", "2026-03-07", 90.0, 21.0, 111.0, 11.0, 1.5, 2, 0.62, "2026-03-07T23:59:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO execution_stats (id, slippage_vs_mid, was_filled, created_at) VALUES (?, ?, ?, ?)",
            [
                ("e1", 0.001, 1, "2026-03-07T10:00:00"),
                ("e2", 0.002, 1, "2026-03-07T11:00:00"),
                ("e3", 0.0, 0, "2026-03-07T12:00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO exit_events (id, created_at) VALUES (?, ?)",
            [
                ("x1", "2026-03-07T13:00:00"),
                ("x2", "2026-03-07T14:00:00"),
            ],
        )
        conn.execute(
            "INSERT INTO risk_events (id, created_at) VALUES (?, ?)",
            ("r1", "2026-03-07T15:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db


def _make_runtime_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE bot_state (
                id INTEGER PRIMARY KEY,
                is_running BOOLEAN NOT NULL,
                kill_switch BOOLEAN NOT NULL,
                last_heartbeat TEXT,
                last_error TEXT,
                version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE orders (
                id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                filled_size REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE fills (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                fee REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE positions (
                id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                avg_entry_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE risk_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE sizing_decisions (
                id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                p_estimated REAL NOT NULL,
                p_market REAL NOT NULL,
                fee_rate REAL NOT NULL,
                edge_raw REAL NOT NULL,
                edge_after_fee REAL NOT NULL,
                kelly_f REAL NOT NULL,
                kelly_mult REAL NOT NULL,
                bankroll REAL NOT NULL,
                raw_size_usd REAL NOT NULL,
                category_haircut BOOLEAN NOT NULL,
                final_size_usd REAL NOT NULL,
                decision TEXT NOT NULL,
                skip_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE detector_opportunities (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                detector TEXT NOT NULL,
                kind TEXT NOT NULL,
                group_label TEXT NOT NULL,
                market_ids TEXT NOT NULL,
                edge_pct REAL NOT NULL,
                detail TEXT NOT NULL,
                prices TEXT NOT NULL,
                meta_data TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO bot_state
            (id, is_running, kill_switch, last_heartbeat, last_error, version, created_at, updated_at)
            VALUES (1, 1, 0, '2026-03-07 13:15:00', NULL, '0.1.2', '2026-03-07 09:00:00', '2026-03-07 13:15:00')
            """
        )
        conn.executemany(
            """
            INSERT INTO orders
            (id, market_id, token_id, side, order_type, price, size, filled_size, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("o1", "m1", "t1", "BUY", "LIMIT", 0.40, 10.0, 10.0, "FILLED", "2026-03-07 09:30:00", "2026-03-07 09:31:00"),
                ("o2", "m2", "t2", "BUY", "LIMIT", 0.55, 8.0, 4.0, "PARTIALLY_FILLED", "2026-03-07 10:00:00", "2026-03-07 10:05:00"),
                ("o3", "m3", "t3", "BUY", "LIMIT", 0.20, 5.0, 0.0, "CANCELLED", "2026-03-07 11:00:00", "2026-03-07 11:30:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO fills
            (id, order_id, price, size, fee, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("f1", "o1", 0.405, 10.0, 0.0, "2026-03-07 09:31:00"),
                ("f2", "o2", 0.560, 4.0, 0.0, "2026-03-07 10:05:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO positions
            (id, market_id, token_id, side, size, avg_entry_price, unrealized_pnl, realized_pnl, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("p1", "m1", "t1", "LONG", 10.0, 0.40, 3.0, 8.0, "2026-03-07 12:00:00"),
                ("p2", "m2", "t2", "LONG", 4.0, 0.55, 1.0, -2.0, "2026-03-07 12:30:00"),
            ],
        )
        conn.execute(
            """
            INSERT INTO risk_events
            (id, event_type, message, data, created_at)
            VALUES ('r1', 'spread_warning', 'Spread widened', '{}', '2026-03-07 12:45:00')
            """
        )
        conn.executemany(
            """
            INSERT INTO sizing_decisions
            (id, market_id, side, p_estimated, p_market, fee_rate, edge_raw, edge_after_fee, kelly_f, kelly_mult, bankroll, raw_size_usd, category_haircut, final_size_usd, decision, skip_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("s1", "m1", "buy_yes", 0.62, 0.40, 0.02, 0.22, 0.20, 0.10, 0.25, 100.0, 15.0, 0, 10.0, "trade", "", "2026-03-07 09:25:00"),
                ("s2", "m2", "buy_yes", 0.58, 0.55, 0.02, 0.03, 0.01, 0.02, 0.25, 105.0, 5.0, 0, 2.5, "skip", "edge_too_small", "2026-03-07 09:55:00"),
            ],
        )
        conn.execute(
            """
            INSERT INTO detector_opportunities
            (id, run_id, detector, kind, group_label, market_ids, edge_pct, detail, prices, meta_data, detected_at)
            VALUES ('d1', 'run1', 'wallet_flow', 'single', 'Test group', '["m1"]', 6.5, 'Detected edge', '{"yes": 0.4}', '{}', '2026-03-07 09:20:00')
            """
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db


def _make_empty_runtime_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE bot_state (
                id INTEGER PRIMARY KEY,
                is_running BOOLEAN NOT NULL,
                kill_switch BOOLEAN NOT NULL,
                last_heartbeat TEXT,
                last_error TEXT,
                version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE orders (
                id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                filled_size REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE fills (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                fee REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE positions (
                id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                avg_entry_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE risk_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO bot_state
            (id, is_running, kill_switch, last_heartbeat, last_error, version, created_at, updated_at)
            VALUES (1, 0, 0, '2026-03-05 21:44:43', NULL, '0.0.1', '2026-03-05 21:44:43', '2026-03-05 21:44:43')
            """
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db


def _make_jj_live_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                question TEXT,
                direction TEXT,
                entry_price REAL,
                calibrated_prob REAL,
                outcome TEXT,
                resolution_price REAL,
                pnl REAL,
                resolved_at TEXT,
                paper INTEGER DEFAULT 0
            );
            CREATE TABLE cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cycle_number INTEGER,
                signals_found INTEGER,
                trades_placed INTEGER,
                bankroll REAL,
                daily_pnl REAL,
                open_positions INTEGER,
                paper INTEGER DEFAULT 0
            );
            CREATE TABLE daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades_placed INTEGER DEFAULT 0,
                trades_resolved INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                daily_pnl REAL DEFAULT 0.0,
                cumulative_pnl REAL DEFAULT 0.0,
                brier_score REAL,
                report_sent INTEGER DEFAULT 0
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                filled_size REAL DEFAULT 0.0,
                status TEXT DEFAULT 'open',
                paper INTEGER DEFAULT 0
            );
            CREATE TABLE fills (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                fill_price REAL NOT NULL,
                fill_size REAL NOT NULL
            );
            CREATE TABLE risk_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO trades
            (id, timestamp, market_id, question, direction, entry_price, calibrated_prob, outcome, resolution_price, pnl, resolved_at, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "t1",
                    "2026-03-06T09:30:00+00:00",
                    "m1",
                    "Will event one resolve yes?",
                    "buy_yes",
                    0.40,
                    0.60,
                    "won",
                    1.0,
                    5.0,
                    "2026-03-07T12:00:00+00:00",
                    0,
                ),
                (
                    "t2",
                    "2026-03-07T10:00:00+00:00",
                    "m2",
                    "Will event two resolve yes?",
                    "buy_yes",
                    0.50,
                    0.30,
                    "lost",
                    0.0,
                    -2.0,
                    "2026-03-07T15:00:00+00:00",
                    0,
                ),
                (
                    "t3",
                    "2026-03-07T16:00:00+00:00",
                    "m3",
                    "Will event three resolve yes?",
                    "buy_no",
                    0.25,
                    0.74,
                    None,
                    None,
                    None,
                    None,
                    0,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO cycles
            (timestamp, cycle_number, signals_found, trades_placed, bankroll, daily_pnl, open_positions, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-03-06T09:00:00+00:00", 1, 1, 1, 100.0, 0.0, 0, 0),
                ("2026-03-07T18:00:00+00:00", 2, 2, 2, 103.0, 3.0, 1, 0),
            ],
        )
        conn.execute(
            """
            INSERT INTO daily_reports
            (date, trades_placed, trades_resolved, wins, losses, daily_pnl, cumulative_pnl, brier_score, report_sent)
            VALUES ('2026-03-07', 2, 2, 1, 1, 3.0, 3.0, 0.125, 1)
            """
        )
        conn.executemany(
            """
            INSERT INTO orders
            (order_id, timestamp, price, size, filled_size, status, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("o1", "2026-03-07T09:00:00+00:00", 0.40, 10.0, 10.0, "filled", 0),
                ("o2", "2026-03-07T10:00:00+00:00", 0.50, 8.0, 4.0, "partially_filled", 0),
                ("o3", "2026-03-07T11:00:00+00:00", 0.20, 5.0, 0.0, "cancelled", 0),
            ],
        )
        conn.executemany(
            """
            INSERT INTO fills
            (id, order_id, timestamp, fill_price, fill_size)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("f1", "o1", "2026-03-07T09:01:00+00:00", 0.404, 10.0),
                ("f2", "o2", "2026-03-07T10:05:00+00:00", 0.510, 4.0),
            ],
        )
        conn.execute(
            """
            INSERT INTO risk_events
            (id, event_type, message, data, created_at)
            VALUES ('r1', 'stale_order', 'Cancelled stale order', '{}', '2026-03-07T18:05:00+00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db


def _make_sparse_jj_live_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                outcome TEXT,
                resolved_at TEXT,
                pnl REAL,
                paper INTEGER DEFAULT 1
            );
            CREATE TABLE cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cycle_number INTEGER,
                signals_found INTEGER,
                trades_placed INTEGER,
                bankroll REAL,
                daily_pnl REAL,
                open_positions INTEGER,
                paper INTEGER DEFAULT 1
            );
            CREATE TABLE daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades_placed INTEGER DEFAULT 0,
                trades_resolved INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                daily_pnl REAL DEFAULT 0.0,
                cumulative_pnl REAL DEFAULT 0.0,
                brier_score REAL,
                report_sent INTEGER DEFAULT 0
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO cycles
            (timestamp, cycle_number, signals_found, trades_placed, bankroll, daily_pnl, open_positions, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-03-07T19:00:00+00:00", 1, 0, 0, 1000.0, 0.0, 0, 1),
                ("2026-03-07T19:04:17+00:00", 2, 0, 0, 1000.0, 0.0, 0, 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db


def _make_mixed_mode_jj_live_bot_db(bot_db: Path) -> Path:
    conn = sqlite3.connect(bot_db)
    try:
        conn.executescript(
            """
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                outcome TEXT,
                resolved_at TEXT,
                pnl REAL,
                paper INTEGER DEFAULT 0
            );
            CREATE TABLE cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cycle_number INTEGER,
                signals_found INTEGER,
                trades_placed INTEGER,
                bankroll REAL,
                daily_pnl REAL,
                open_positions INTEGER,
                paper INTEGER DEFAULT 0
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO cycles
            (timestamp, cycle_number, signals_found, trades_placed, bankroll, daily_pnl, open_positions, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-03-07T19:00:00+00:00", 1, 0, 0, 1000.0, 0.0, 0, 1),
                ("2026-03-07T19:05:00+00:00", 2, 0, 0, 1000.0, 0.0, 0, 1),
                ("2026-03-07T22:00:00+00:00", 3, 0, 0, 250.0, 0.0, 0, 0),
                ("2026-03-07T22:05:00+00:00", 4, 0, 0, 250.0, 0.0, 0, 0),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return bot_db
