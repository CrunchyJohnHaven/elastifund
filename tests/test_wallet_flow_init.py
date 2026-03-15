from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bot.jj_live as jj_live_module
from bot import wallet_flow_detector as detector
from bot.jj_live import JJLive


def _write_bootstrap(scores_path: Path, db_path: Path) -> None:
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()
    scores_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "count": 1,
                "wallets": {
                    "0xabc": {
                        "address": "0xabc",
                        "activity_score": 82.0,
                    }
                },
            }
        )
    )


def _make_live(tmp_path: Path) -> JJLive:
    live = JJLive.__new__(JJLive)
    live.enable_wallet_flow = True
    live.wallet_flow_module_available = True
    live.wallet_flow_scores_file = tmp_path / "data" / "smart_wallets.json"
    live.wallet_flow_db_file = tmp_path / "data" / "wallet_scores.db"
    return live


def test_ensure_bootstrap_artifacts_rebuilds_when_database_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scores_path = tmp_path / "data" / "smart_wallets.json"
    db_path = tmp_path / "data" / "wallet_scores.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()

    sample_scores = [
        detector.WalletScore(
            address="0xabc",
            total_trades=8,
            crypto_trades=6,
            unique_markets=4,
            total_volume=125.0,
            avg_size=15.0,
            win_rate=0.5,
            activity_score=82.0,
            is_smart=True,
            last_active="1700000000",
        )
    ]

    def fake_build(self: detector.WalletScorer) -> list[detector.WalletScore]:
        self.save_smart_wallets_json(sample_scores)
        return sample_scores

    monkeypatch.setattr(detector.WalletScorer, "build_initial_scores", fake_build)

    status = detector.ensure_bootstrap_artifacts(scores_path=scores_path, db_path=db_path)

    assert status.ready is True
    assert status.wallet_count == 1
    assert status.scores_exists is True
    assert status.db_exists is True
    payload = json.loads(scores_path.read_text())
    assert payload["count"] == 1
    assert "0xabc" in payload["wallets"]

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "wallet_trades" in tables
    assert "wallet_scores" in tables


def test_jj_live_skips_bootstrap_when_artifacts_are_already_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    live = _make_live(tmp_path)
    _write_bootstrap(live.wallet_flow_scores_file, live.wallet_flow_db_file)

    def fail_if_called(*, scores_path: Path, db_path: Path):
        raise AssertionError(f"unexpected rebuild for ready bootstrap: {scores_path}, {db_path}")

    monkeypatch.setattr(jj_live_module, "wallet_flow_ensure_bootstrap", fail_if_called)

    live._maybe_initialize_wallet_flow_bootstrap()

    assert live._wallet_flow_bootstrap_status() == (True, None)


def test_jj_live_bootstraps_wallet_flow_artifacts_when_scores_json_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    live = _make_live(tmp_path)
    live.wallet_flow_db_file.parent.mkdir(parents=True, exist_ok=True)
    live.wallet_flow_db_file.touch()

    captured: dict[str, tuple[Path, Path]] = {}

    def fake_ensure(*, scores_path: Path, db_path: Path):
        captured["paths"] = (scores_path, db_path)
        _write_bootstrap(scores_path, db_path)
        return detector.get_bootstrap_status(scores_path=scores_path, db_path=db_path)

    monkeypatch.setattr(jj_live_module, "wallet_flow_ensure_bootstrap", fake_ensure)

    live._maybe_initialize_wallet_flow_bootstrap()

    assert captured["paths"] == (live.wallet_flow_scores_file, live.wallet_flow_db_file)
    assert live._wallet_flow_bootstrap_status() == (True, None)


def test_jj_live_marks_stale_bootstrap_as_not_ready(tmp_path: Path) -> None:
    live = _make_live(tmp_path)
    live.wallet_flow_db_file.parent.mkdir(parents=True, exist_ok=True)
    live.wallet_flow_db_file.touch()
    live.wallet_flow_scores_file.parent.mkdir(parents=True, exist_ok=True)
    live.wallet_flow_scores_file.write_text(
        json.dumps(
            {
                "updated_at": (
                    datetime.now(timezone.utc)
                    - timedelta(hours=detector.BOOTSTRAP_MAX_AGE_HOURS + 1)
                ).isoformat(),
                "count": 1,
                "wallets": {"0xabc": {"address": "0xabc", "activity_score": 82.0}},
            }
        )
    )

    ready, reason = live._wallet_flow_bootstrap_status()

    assert ready is False
    assert reason == "stale_bootstrap"


def test_jj_live_bootstrap_rebuild_failure_is_non_fatal(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    live = _make_live(tmp_path)

    def fake_ensure(*, scores_path: Path, db_path: Path):
        raise RuntimeError("boom")

    monkeypatch.setattr(jj_live_module, "wallet_flow_ensure_bootstrap", fake_ensure)

    with caplog.at_level(logging.WARNING):
        live._maybe_initialize_wallet_flow_bootstrap()

    assert "Wallet flow bootstrap initialization failed (non-fatal): boom" in caplog.text
    assert live._wallet_flow_bootstrap_status()[0] is False
