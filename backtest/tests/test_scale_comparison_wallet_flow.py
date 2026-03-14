from . import _scale_comparison_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

def test_load_wallet_flow_evidence_returns_ready_when_archive_is_sufficient(monkeypatch):
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_edge_config",
        lambda: type("Cfg", (), {"system": type("S", (), {"db_path": "data/edge_discovery.db"})()})(),
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_or_build_wallet_flow_archive",
        lambda db_path, archive_path=None: (
            {
                "schema": "wallet_flow_resolved_signal_archive.v1",
                "counts": {
                    "resolved_qualifying_signals": 4,
                    "unique_markets": 3,
                    "replayable_signals": 4,
                },
                "requirements": {"min_resolved_signals": 3, "min_unique_markets": 2},
                "missing_requirements": [],
                "signals": [
                    {
                        "condition_id": "cond-1",
                        "timestamp_ts": 1700000000,
                        "timestamp": "2026-03-08T00:00:00+00:00",
                        "market_title": "BTC Up or Down 15m",
                        "direction": "buy_yes",
                        "entry_price": 0.52,
                        "win_probability": 0.71,
                        "actual_outcome": "YES_WON",
                        "edge": 0.19,
                        "volume_proxy": 320.0,
                        "liquidity_proxy": 410.0,
                    }
                ],
            },
            "loaded",
        ),
    )

    evidence = load_wallet_flow_evidence()

    assert evidence.status == "ready"
    assert len(evidence.opportunities) == 1
    assert evidence.evidence_summary["archive_source"] == "loaded"
    assert evidence.evidence_summary["resolved_replayable_signals"] == 4
    assert evidence.evidence_summary["unique_markets"] == 3
    assert evidence.opportunities[0].lane == "wallet_flow"


def test_load_wallet_flow_evidence_reports_missing_requirements(monkeypatch):
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_edge_config",
        lambda: type("Cfg", (), {"system": type("S", (), {"db_path": "data/edge_discovery.db"})()})(),
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_or_build_wallet_flow_archive",
        lambda db_path, archive_path=None: (
            {
                "schema": "wallet_flow_resolved_signal_archive.v1",
                "counts": {
                    "resolved_qualifying_signals": 1,
                    "unique_markets": 1,
                    "replayable_signals": 1,
                },
                "requirements": {"min_resolved_signals": 3, "min_unique_markets": 2},
                "missing_requirements": [
                    "resolved_signals 1 < required 3",
                    "unique_markets 1 < required 2",
                ],
                "signals": [],
            },
            "built",
        ),
    )

    evidence = load_wallet_flow_evidence()

    assert evidence.status == "insufficient_data"
    assert any("Resolved qualifying signals: 1 (required >= 3)." in reason for reason in evidence.reasons)
    assert any("Unique resolved markets: 1 (required >= 2)." in reason for reason in evidence.reasons)
    assert any("Missing requirement: resolved_signals 1 < required 3" in reason for reason in evidence.reasons)
    assert evidence.evidence_summary["missing_requirements"]


def test_load_or_build_wallet_flow_archive_rebuilds_cached_feature_bundle_failure(
    monkeypatch, tmp_path: Path
):
    archive_path = tmp_path / "wallet_flow_resolved_signals.json"
    archive_path.write_text(
        json.dumps(
            {
                "schema": "wallet_flow_resolved_signal_archive.v1",
                "signals": [],
                "missing_requirements": [
                    "feature_bundle_unavailable: OperationalError: no such table: markets"
                ],
            }
        )
    )
    rebuilt_payload = {
        "schema": "wallet_flow_resolved_signal_archive.v1",
        "signals": [{"condition_id": "cond-1"}],
        "missing_requirements": [],
    }
    monkeypatch.setattr(
        "backtest.run_scale_comparison._build_wallet_flow_replay_archive",
        lambda db_path: rebuilt_payload,
    )

    payload, source = load_or_build_wallet_flow_archive(
        db_path="data/edge_discovery.db",
        archive_path=archive_path,
    )

    assert source == "rebuilt"
    assert payload == rebuilt_payload


def test_load_or_build_wallet_flow_archive_keeps_healthy_cache(monkeypatch, tmp_path: Path):
    archive_path = tmp_path / "wallet_flow_resolved_signals.json"
    cached_payload = {
        "schema": "wallet_flow_resolved_signal_archive.v1",
        "signals": [{"condition_id": "cond-1"}],
        "missing_requirements": [],
    }
    archive_path.write_text(json.dumps(cached_payload))
    monkeypatch.setattr(
        "backtest.run_scale_comparison._build_wallet_flow_replay_archive",
        lambda db_path: (_ for _ in ()).throw(AssertionError("should not rebuild healthy archive")),
    )

    payload, source = load_or_build_wallet_flow_archive(
        db_path="data/edge_discovery.db",
        archive_path=archive_path,
    )

    assert source == "loaded"
    assert payload == cached_payload
