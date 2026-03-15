from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import wallet_flow_detector as detector


@pytest.fixture(autouse=True)
def _reset_wallet_flow_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detector, "_persistent_monitor", None)
    monkeypatch.setattr(detector, "_monitor_initialized_at", 0.0)
    monkeypatch.setattr(detector, "_paper_signal_last_seen", {})


def test_flow_monitor_polls_condition_ids_and_respects_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smart_wallets = {
        "0xA": detector.WalletScore(address="0xA", activity_score=95.0, is_smart=True),
        "0xB": detector.WalletScore(address="0xB", activity_score=90.0, is_smart=True),
        "0xC": detector.WalletScore(address="0xC", activity_score=10.0, is_smart=True),
    }
    monitor = detector.FlowMonitor(
        smart_wallets,
        top_k=2,
        lookback_seconds=300,
        active_condition_ids=["cond-1"],
    )

    seen_params: list[dict] = []

    class FakeResp:
        status_code = 200

        def json(self) -> list[dict]:
            return [
                {
                    "proxyWallet": "0xA",
                    "conditionId": "cond-1",
                    "title": "Bitcoin Up or Down 5m",
                    "side": "BUY",
                    "outcome": "Down",
                    "outcomeIndex": 1,
                    "size": 8.0,
                    "timestamp": 1_800_000_001,
                },
                {
                    "proxyWallet": "0xC",
                    "conditionId": "cond-1",
                    "title": "Bitcoin Up or Down 5m",
                    "side": "BUY",
                    "outcome": "Down",
                    "outcomeIndex": 1,
                    "size": 7.0,
                    "timestamp": 1_800_000_002,
                },
            ]

    def fake_get(url: str, params: dict, timeout: int):  # noqa: ARG001
        seen_params.append(params)
        return FakeResp()

    monitor.last_seen_timestamp = 1_800_000_000
    monkeypatch.setattr(detector.requests, "get", fake_get)
    trades = monitor.poll_trades()

    assert seen_params[0]["conditionId"] == "cond-1"
    assert all(t["proxyWallet"] in {"0xA", "0xB"} for t in trades)
    assert len(trades) == 1


def test_scan_for_signals_returns_dispatch_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detector,
        "get_bootstrap_status",
        lambda: detector.BootstrapStatus(
            ready=True,
            reasons=[],
            wallet_count=2,
            scores_exists=True,
            db_exists=True,
            last_updated="2026-03-15T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        detector,
        "load_smart_wallets",
        lambda: (
            {
                "0xA": detector.WalletScore(address="0xA", activity_score=92.0, is_smart=True),
                "0xB": detector.WalletScore(address="0xB", activity_score=89.0, is_smart=True),
            },
            "2026-03-15T00:00:00+00:00",
        ),
    )

    class FakeMonitor:
        top_k = 10

        def poll_trades(self) -> list[dict]:
            return []

        def get_consensus_signals(self) -> list[detector.WalletFlowSignal]:
            return [
                detector.WalletFlowSignal(
                    market_id="cond-xyz",
                    market_title="Bitcoin Up or Down 5m",
                    slug="btc-up-or-down-5m",
                    direction="outcome_1",
                    outcome_name="Down",
                    confidence=0.72,
                    smart_wallets_count=4,
                    total_smart_size=44.0,
                    avg_smart_score=90.0,
                    signal_age_seconds=30.0,
                    timestamp="2026-03-15T00:00:10+00:00",
                    agreeing_wallets=["0xA", "0xB"],
                )
            ]

    monkeypatch.setattr(detector, "FlowMonitor", lambda *args, **kwargs: FakeMonitor())
    monkeypatch.setattr(detector, "WALLET_FLOW_PAPER_MODE", False)

    signals = detector.scan_for_signals()
    assert len(signals) == 1
    signal = signals[0]
    assert signal["market_id"] == "cond-xyz"
    assert signal["slug"] == "btc-up-or-down-5m"
    assert signal["side"] == "BUY"
    assert signal["outcome"] == "Down"
    assert signal["source"] == "wallet_flow"
    assert signal["wallet_count"] == 4
    assert signal["top_k"] == 10
    assert isinstance(signal["timestamp"], int)


def test_scan_for_signals_paper_mode_logs_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detector, "WALLET_FLOW_SIGNAL_LOG_FILE", tmp_path / "wallet_flow_signals.log")
    monkeypatch.setattr(detector, "WALLET_FLOW_PAPER_MODE", True)
    monkeypatch.setattr(
        detector,
        "get_bootstrap_status",
        lambda: detector.BootstrapStatus(
            ready=True,
            reasons=[],
            wallet_count=1,
            scores_exists=True,
            db_exists=True,
            last_updated="2026-03-15T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        detector,
        "load_smart_wallets",
        lambda: (
            {"0xA": detector.WalletScore(address="0xA", activity_score=95.0, is_smart=True)},
            "2026-03-15T00:00:00+00:00",
        ),
    )

    class FakeMonitor:
        top_k = 10

        def poll_trades(self) -> list[dict]:
            return []

        def get_consensus_signals(self) -> list[detector.WalletFlowSignal]:
            return [
                detector.WalletFlowSignal(
                    market_id="cond-1",
                    market_title="Bitcoin Up or Down 5m",
                    slug="btc-up-or-down-5m",
                    direction="outcome_1",
                    outcome_name="Down",
                    confidence=0.78,
                    smart_wallets_count=3,
                    total_smart_size=30.0,
                    avg_smart_score=88.0,
                    signal_age_seconds=12.0,
                    timestamp="2026-03-15T00:00:05+00:00",
                    agreeing_wallets=["0xA", "0xB", "0xC"],
                )
            ]

    monkeypatch.setattr(detector, "FlowMonitor", lambda *args, **kwargs: FakeMonitor())
    detector.scan_for_signals()

    lines = (tmp_path / "wallet_flow_signals.log").read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["market_id"] == "cond-1"
    assert payload["outcome"] == "Down"
    assert payload["wallet_count"] == 3
    assert payload["wallets"] == ["0xA", "0xB", "0xC"]


def test_get_signals_for_engine_paper_mode_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detector, "WALLET_FLOW_PAPER_MODE", True)
    monkeypatch.setattr(
        detector,
        "scan_for_signals",
        lambda: [
            {
                "market_id": "cond-1",
                "market_title": "Bitcoin Up or Down 5m",
                "direction": "outcome_1",
                "outcome_name": "Down",
                "confidence": 0.8,
                "smart_wallets_count": 3,
                "total_smart_size": 32.0,
                "avg_smart_score": 90.0,
                "signal_age_seconds": 10.0,
            }
        ],
    )

    assert detector.get_signals_for_engine() == []
