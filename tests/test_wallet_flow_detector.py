from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot import wallet_flow_detector as detector


@pytest.fixture(autouse=True)
def reset_monitor_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detector, "_persistent_monitor", None)
    monkeypatch.setattr(detector, "_monitor_initialized_at", 0.0)


def test_ingest_trades_parses_effective_outcome_and_fast_market_flag(tmp_path: Path) -> None:
    scorer = detector.WalletScorer(db_path=tmp_path / "wallet_scores.db")
    try:
        ingested = scorer.ingest_trades(
            [
                {
                    "proxyWallet": "0xaaa",
                    "conditionId": "cond-1",
                    "title": "BTC Up or Down 5m",
                    "side": "BUY",
                    "outcome": "Up",
                    "outcomeIndex": "0",
                    "size": "10.5",
                    "price": "0.61",
                    "timestamp": "1700000000",
                },
                {
                    "proxyWallet": "0xbbb",
                    "conditionId": "cond-1",
                    "title": "BTC Up or Down 5m",
                    "side": "SELL",
                    "outcome": "Up",
                    "outcomeIndex": "0",
                    "size": "7.0",
                    "price": "0.39",
                    "timestamp": "1700000010",
                },
            ]
        )

        rows = scorer.conn.execute(
            """
            SELECT wallet, effective_outcome, is_crypto_fast
            FROM wallet_trades
            ORDER BY wallet
            """
        ).fetchall()
    finally:
        scorer.conn.close()

    assert ingested == 2
    assert [(row["wallet"], row["effective_outcome"], row["is_crypto_fast"]) for row in rows] == [
        ("0xaaa", 0, 1),
        ("0xbbb", 1, 1),
    ]


def test_consensus_detector_emits_signal_for_unique_smart_wallets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = 1_700_000_000
    monkeypatch.setattr(detector.time, "time", lambda: fixed_now)
    smart_wallets = {
        "0x1": detector.WalletScore(address="0x1", activity_score=80.0, is_smart=True),
        "0x2": detector.WalletScore(address="0x2", activity_score=90.0, is_smart=True),
        "0x3": detector.WalletScore(address="0x3", activity_score=70.0, is_smart=True),
    }
    monitor = detector.FlowMonitor(smart_wallets)
    monitor._recent_trades = [
        _trade("0x1", fixed_now - 60, size=6.0),
        _trade("0x2", fixed_now - 45, size=6.0),
        _trade("0x3", fixed_now - 30, size=6.0),
        _trade("0x1", fixed_now - 15, size=2.0),
    ]

    signals = monitor.get_consensus_signals()

    assert len(signals) == 1
    signal = signals[0]
    assert signal.market_id == "cond-1"
    assert signal.direction == "outcome_0"
    assert signal.outcome_name == "Up"
    assert signal.smart_wallets_count == 3
    assert signal.total_smart_size == pytest.approx(20.0)
    assert signal.signal_age_seconds == 60
    assert signal.confidence > 0.5


def test_bootstrap_status_and_scan_explicitly_flag_missing_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores_path = tmp_path / "data" / "smart_wallets.json"
    db_path = tmp_path / "data" / "wallet_scores.db"
    monkeypatch.setattr(detector, "SCORES_FILE", scores_path)
    monkeypatch.setattr(detector, "DB_FILE", db_path)

    status = detector.get_bootstrap_status(
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    )

    assert status.ready is False
    assert status.wallet_count == 0
    assert status.scores_exists is False
    assert status.db_exists is False
    assert status.last_updated is None
    assert status.reasons == ["missing_scores_json", "missing_scores_db"]
    assert detector.scan_for_signals() == []


def test_bootstrap_status_flags_stale_bootstrap(tmp_path: Path) -> None:
    now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    scores_path = tmp_path / "data" / "smart_wallets.json"
    db_path = tmp_path / "data" / "wallet_scores.db"
    _create_db(db_path)
    _write_scores(
        scores_path,
        updated_at=(now - timedelta(hours=detector.BOOTSTRAP_MAX_AGE_HOURS + 1)).isoformat(),
        wallets={"0xabc": {"activity_score": 88.0}},
    )

    status = detector.get_bootstrap_status(scores_path=scores_path, db_path=db_path, now=now)

    assert status.ready is False
    assert status.reasons == ["stale_bootstrap"]
    assert status.wallet_count == 1
    assert status.scores_exists is True
    assert status.db_exists is True
    assert status.last_updated == (
        now - timedelta(hours=detector.BOOTSTRAP_MAX_AGE_HOURS + 1)
    ).isoformat()


def test_ensure_bootstrap_artifacts_leaves_ready_bootstrap_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores_path = tmp_path / "data" / "smart_wallets.json"
    db_path = tmp_path / "data" / "wallet_scores.db"
    _create_db(db_path)
    _write_scores(
        scores_path,
        updated_at=datetime.now(timezone.utc).isoformat(),
        wallets={"0xabc": {"activity_score": 88.0}},
    )

    def fail_if_called(self: detector.WalletScorer) -> list[detector.WalletScore]:
        raise AssertionError("ready bootstrap should not rebuild")

    monkeypatch.setattr(detector.WalletScorer, "build_initial_scores", fail_if_called)

    status = detector.ensure_bootstrap_artifacts(scores_path=scores_path, db_path=db_path)

    assert status.ready is True
    assert status.reasons == []
    assert status.wallet_count == 1


def test_get_signals_for_engine_converts_wallet_flow_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detector,
        "scan_for_signals",
        lambda: [
            {
                "market_id": "cond-1",
                "market_title": "BTC Up or Down 5m",
                "direction": "outcome_1",
                "outcome_name": "Down",
                "confidence": 0.72,
                "smart_wallets_count": 4,
                "total_smart_size": 42.0,
                "avg_smart_score": 88.0,
                "signal_age_seconds": 12.0,
            }
        ],
    )

    signals = detector.get_signals_for_engine()

    assert len(signals) == 1
    signal = signals[0]
    assert signal["direction"] == "buy_no"
    assert signal["market_id"] == "cond-1"
    assert signal["question"] == "BTC Up or Down 5m"
    assert signal["edge"] == 0.37
    assert signal["confidence"] == 0.72
    assert signal["source"] == "wallet_flow"
    assert "4 smart wallets agree on Down" in signal["reasoning"]


def test_get_signals_for_engine_suppresses_balanced_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detector,
        "scan_for_signals",
        lambda: [
            {
                "market_id": "cond-1",
                "market_title": "BTC Up or Down 5m",
                "direction": "outcome_0",
                "outcome_name": "Up",
                "confidence": 0.74,
                "smart_wallets_count": 4,
                "total_smart_size": 44.0,
                "avg_smart_score": 88.0,
                "signal_age_seconds": 15.0,
            },
            {
                "market_id": "cond-1",
                "market_title": "BTC Up or Down 5m",
                "direction": "outcome_1",
                "outcome_name": "Down",
                "confidence": 0.72,
                "smart_wallets_count": 4,
                "total_smart_size": 41.0,
                "avg_smart_score": 84.0,
                "signal_age_seconds": 15.0,
            },
        ],
    )

    assert detector.get_signals_for_engine() == []


def test_get_signals_for_engine_keeps_dominant_direction_when_conflict_is_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detector,
        "scan_for_signals",
        lambda: [
            {
                "market_id": "cond-1",
                "market_title": "BTC Up or Down 5m",
                "direction": "outcome_0",
                "outcome_name": "Up",
                "confidence": 0.89,
                "smart_wallets_count": 6,
                "total_smart_size": 120.0,
                "avg_smart_score": 92.0,
                "signal_age_seconds": 10.0,
            },
            {
                "market_id": "cond-1",
                "market_title": "BTC Up or Down 5m",
                "direction": "outcome_1",
                "outcome_name": "Down",
                "confidence": 0.68,
                "smart_wallets_count": 3,
                "total_smart_size": 28.0,
                "avg_smart_score": 80.0,
                "signal_age_seconds": 10.0,
            },
        ],
    )

    signals = detector.get_signals_for_engine()

    assert len(signals) == 1
    assert signals[0]["market_id"] == "cond-1"
    assert signals[0]["direction"] == "buy_yes"
    assert "suppressed opposite-direction consensus" in signals[0]["reasoning"]


def test_status_json_cli_outputs_machine_readable_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scores_path = tmp_path / "data" / "smart_wallets.json"
    db_path = tmp_path / "data" / "wallet_scores.db"
    updated_at = datetime.now(timezone.utc).isoformat()
    _create_db(db_path)
    _write_scores(
        scores_path,
        updated_at=updated_at,
        wallets={"0xabc": {"activity_score": 88.0}},
    )
    monkeypatch.setattr(detector, "SCORES_FILE", scores_path)
    monkeypatch.setattr(detector, "DB_FILE", db_path)
    monkeypatch.setattr(sys, "argv", ["wallet_flow_detector.py", "--status-json"])

    detector.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is True
    assert payload["reasons"] == []
    assert payload["wallet_count"] == 1
    assert payload["scores_exists"] is True
    assert payload["db_exists"] is True
    assert payload["last_updated"] == updated_at


def test_scan_cli_returns_empty_json_when_bootstrap_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(detector, "SCORES_FILE", tmp_path / "data" / "smart_wallets.json")
    monkeypatch.setattr(detector, "DB_FILE", tmp_path / "data" / "wallet_scores.db")
    monkeypatch.setattr(sys, "argv", ["wallet_flow_detector.py", "--scan"])

    detector.main()

    assert json.loads(capsys.readouterr().out) == []


def _trade(wallet: str, timestamp: int, size: float) -> dict:
    return {
        "proxyWallet": wallet,
        "conditionId": "cond-1",
        "title": "BTC Up or Down 5m",
        "outcome": "Up",
        "outcomeIndex": 0,
        "side": "BUY",
        "size": size,
        "timestamp": timestamp,
        "_effective_outcome": 0,
    }


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.close()


def _write_scores(path: Path, updated_at: str, wallets: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": updated_at,
                "count": len(wallets),
                "wallets": wallets,
            },
            indent=2,
            sort_keys=True,
        )
    )
