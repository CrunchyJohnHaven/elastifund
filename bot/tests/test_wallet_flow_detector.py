#!/usr/bin/env python3
"""Focused tests for wallet flow detector v1 dispatch behavior."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot import wallet_flow_detector as detector  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: list[dict], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> list[dict]:
        return self._payload


def test_load_scored_wallets_honors_top_k_and_score_ranking(tmp_path: Path) -> None:
    scored_file = tmp_path / "smart_wallets_scored.json"
    scored_file.write_text(
        json.dumps(
            {
                "updated_at": "2026-03-15T00:00:00+00:00",
                "wallets": [
                    {"address": "0xbbb", "smart_score": 0.61},
                    {"address": "0xaaa", "smart_score": 0.88},
                    {"address": "0xccc", "smart_score": 0.55},
                ],
            }
        )
    )

    smart, updated_at = detector.load_scored_wallets(scored_file, top_k=2)

    assert list(smart.keys()) == ["0xaaa", "0xbbb"]
    assert smart["0xaaa"].activity_score == pytest.approx(88.0)
    assert smart["0xbbb"].is_smart is True
    assert updated_at == "2026-03-15T00:00:00+00:00"


def test_flow_monitor_uses_condition_id_targeted_polling() -> None:
    calls: list[dict] = []

    def fake_get(_url: str, *, params: dict, timeout: int):
        calls.append({"params": dict(params), "timeout": timeout})
        return _FakeResponse(
            [
                {
                    "proxyWallet": "0xsmart",
                    "conditionId": "cond-1",
                    "title": "Bitcoin Up or Down 5m",
                    "slug": "btc-updown-5m",
                    "side": "BUY",
                    "outcome": "Down",
                    "outcomeIndex": 1,
                    "size": "12.5",
                    "timestamp": "1700000100",
                }
            ]
        )

    monitor = detector.FlowMonitor(
        {"0xsmart": detector.WalletScore(address="0xsmart", activity_score=92.0, is_smart=True)},
        market_ids=["cond-1"],
        top_k=1,
        lookback_sec=600,
        http_get=fake_get,
    )
    monitor.last_seen_timestamp = 1700000000

    smart_trades = monitor.poll_trades()

    assert calls and calls[0]["params"]["conditionId"] == "cond-1"
    assert len(smart_trades) == 1
    assert smart_trades[0]["_effective_outcome"] == 1


def test_consensus_detector_emits_dispatch_compatible_signal_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ts = 1_700_000_100
    monkeypatch.setattr(detector.time, "time", lambda: now_ts)
    smart_wallets = {
        "0x1": detector.WalletScore(address="0x1", activity_score=95.0, is_smart=True),
        "0x2": detector.WalletScore(address="0x2", activity_score=92.0, is_smart=True),
        "0x3": detector.WalletScore(address="0x3", activity_score=90.0, is_smart=True),
        "0x4": detector.WalletScore(address="0x4", activity_score=88.0, is_smart=True),
    }
    consensus = detector.ConsensusDetector(
        smart_wallets,
        top_k=4,
        min_consensus=3,
        lookback_sec=600,
    )
    trades = [
        {
            "proxyWallet": "0x1",
            "conditionId": "cond-fast-1",
            "title": "Bitcoin Up or Down 5m",
            "slug": "btc-updown-5m-1",
            "side": "BUY",
            "outcome": "Down",
            "outcomeIndex": 1,
            "_effective_outcome": 1,
            "size": 8.0,
            "timestamp": now_ts - 30,
        },
        {
            "proxyWallet": "0x2",
            "conditionId": "cond-fast-1",
            "title": "Bitcoin Up or Down 5m",
            "slug": "btc-updown-5m-1",
            "side": "BUY",
            "outcome": "Down",
            "outcomeIndex": 1,
            "_effective_outcome": 1,
            "size": 7.0,
            "timestamp": now_ts - 20,
        },
        {
            "proxyWallet": "0x3",
            "conditionId": "cond-fast-1",
            "title": "Bitcoin Up or Down 5m",
            "slug": "btc-updown-5m-1",
            "side": "BUY",
            "outcome": "Down",
            "outcomeIndex": 1,
            "_effective_outcome": 1,
            "size": 6.0,
            "timestamp": now_ts - 10,
        },
    ]

    signals = consensus.detect(trades)

    assert len(signals) == 1
    normalized = detector._normalize_wallet_signal_output(asdict(signals[0]))
    assert normalized["market_id"] == "cond-fast-1"
    assert normalized["slug"] == "btc-updown-5m-1"
    assert normalized["side"] == "BUY"
    assert normalized["outcome"] == "Down"
    assert normalized["source"] == "wallet_flow"
    assert normalized["wallet_count"] == 3
    assert normalized["top_k"] == 4
    assert isinstance(normalized["timestamp"], int)
    assert 0.0 < normalized["confidence"] <= 1.0


def test_scan_for_signals_writes_paper_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "wallet_flow_signals.log"
    scored_path = tmp_path / "smart_wallets_scored.json"
    scored_path.write_text("{}")
    monkeypatch.setattr(detector, "WALLET_FLOW_ENABLED", True)
    monkeypatch.setattr(detector, "WALLET_FLOW_SIGNAL_LOG_FILE", log_path)
    monkeypatch.setattr(detector, "WALLET_FLOW_SCORED_FILE", scored_path)
    monkeypatch.setattr(detector, "_persistent_monitor", None)
    monkeypatch.setattr(detector, "_monitor_initialized_at", 0.0)
    monkeypatch.setattr(
        detector,
        "load_configured_smart_wallets",
        lambda top_k: (
            {"0xabc": detector.WalletScore(address="0xabc", activity_score=80.0, is_smart=True)},
            "2026-03-15T00:00:00+00:00",
            "smart_wallets_scored",
        ),
    )
    monkeypatch.setattr(
        detector,
        "get_bootstrap_status",
        lambda: detector.BootstrapStatus(
            ready=False,
            reasons=["missing_scores_json", "missing_scores_db"],
            wallet_count=0,
            scores_exists=False,
            db_exists=False,
            last_updated=None,
        ),
    )
    monkeypatch.setattr(
        detector,
        "_discover_active_fast_market_ids",
        lambda limit=150: ["cond-paper-1"],
    )

    class _FakeMonitor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def poll_trades(self) -> list[dict]:
            return []

        def get_consensus_signals(self) -> list[detector.WalletFlowSignal]:
            return [
                detector.WalletFlowSignal(
                    market_id="cond-paper-1",
                    market_title="Bitcoin Up or Down 5m",
                    slug="btc-updown-5m-paper",
                    side="BUY",
                    outcome="Down",
                    source="wallet_flow",
                    wallet_count=3,
                    top_k=10,
                    direction="outcome_1",
                    outcome_name="Down",
                    confidence=0.71,
                    smart_wallets_count=3,
                    total_smart_size=24.0,
                    avg_smart_score=82.0,
                    signal_age_seconds=12.0,
                    timestamp="2026-03-15T00:00:00+00:00",
                )
            ]

    monkeypatch.setattr(detector, "FlowMonitor", _FakeMonitor)

    signals = detector.scan_for_signals()

    assert len(signals) == 1
    assert signals[0]["source"] == "wallet_flow"
    assert signals[0]["wallet_count"] == 3
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["market_id"] == "cond-paper-1"

