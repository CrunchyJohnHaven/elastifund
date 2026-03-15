from __future__ import annotations

import json
from pathlib import Path

from bot.cross_asset_history import (
    COINAPI_STARTUP_MONTHLY_USD,
    CrossAssetHistorySettings,
    build_instance_artifact,
    build_vendor_stack,
    run_cross_asset_history_dispatch,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeClient:
    def get(self, url: str, **kwargs):
        params = kwargs.get("params", {})
        if "binance" in url:
            start_time = int(params["startTime"])
            return FakeResponse(
                [
                    [start_time, "10.0", "11.0", "9.5", "10.5", "1.0", start_time + 59_999, "10.5", 3, "0.5", "5.25", "0"],
                ]
            )
        if "coingecko" in url:
            return FakeResponse({"prices": [[1_700_000_000_000, 100.0], [1_700_000_060_000, 101.0]]})
        if "coinapi" in url:
            return FakeResponse(
                [
                    {
                        "time_period_start": "2026-03-10T00:00:00.0000000Z",
                        "time_period_end": "2026-03-10T00:00:01.0000000Z",
                        "price_open": 10.0,
                        "price_high": 10.2,
                        "price_low": 9.9,
                        "price_close": 10.1,
                        "volume_traded": 1.0,
                        "trades_count": 2,
                    }
                ]
            )
        raise AssertionError(f"unexpected url {url}")


def _write_finance_latest(workspace_root: Path, *, finance_gate_pass: bool, free_cash_after_floor: float, action_cap: float) -> None:
    path = workspace_root / "reports" / "finance" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "finance_gate_pass": finance_gate_pass,
                "finance_gate": {"reason": "queue_ready" if finance_gate_pass else "blocked"},
                "finance_totals": {"free_cash_after_floor": free_cash_after_floor},
                "cycle_budget_ledger": {
                    "dollars": {
                        "single_action_cap_usd": action_cap,
                        "free_cash_after_floor_usd": free_cash_after_floor,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_vendor_stack_recommends_coinapi_when_one_second_gap_and_finance_green(tmp_path: Path) -> None:
    _write_finance_latest(tmp_path, finance_gate_pass=True, free_cash_after_floor=600.0, action_cap=250.0)
    history_report = {
        "generated_at": "2026-03-11T00:00:00Z",
        "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        "summary": {
            "one_minute_replay_ready_assets": 5,
            "one_second_replay_ready_assets": 0,
        },
    }

    vendor_stack = build_vendor_stack(history_report, workspace_root=tmp_path)

    assert vendor_stack["recommendation"]["decision"] == "buy_coinapi_startup"
    coinapi = next(row for row in vendor_stack["ranking"] if row["vendor"] == "coinapi_startup")
    assert coinapi["monthly_commitment_impact_usd"] == COINAPI_STARTUP_MONTHLY_USD
    assert coinapi["recommendation"] == "buy_now"


def test_vendor_stack_holds_when_finance_gate_blocked(tmp_path: Path) -> None:
    _write_finance_latest(tmp_path, finance_gate_pass=False, free_cash_after_floor=600.0, action_cap=250.0)
    history_report = {
        "generated_at": "2026-03-11T00:00:00Z",
        "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        "summary": {
            "one_minute_replay_ready_assets": 5,
            "one_second_replay_ready_assets": 0,
        },
    }

    vendor_stack = build_vendor_stack(history_report, workspace_root=tmp_path)

    assert vendor_stack["recommendation"]["decision"] == "hold_free_stack"
    coinapi = next(row for row in vendor_stack["ranking"] if row["vendor"] == "coinapi_startup")
    assert "finance_gate_or_budget_blocked" in coinapi["blocked_reasons"]


def test_dispatch_writes_reports_and_marks_one_second_ready_when_coinapi_enabled(tmp_path: Path) -> None:
    _write_finance_latest(tmp_path, finance_gate_pass=True, free_cash_after_floor=600.0, action_cap=250.0)
    settings = CrossAssetHistorySettings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "state" / "cross_asset_history",
        history_report_path=tmp_path / "reports" / "cross_asset_history" / "latest.json",
        vendor_stack_report_path=tmp_path / "reports" / "vendor_stack" / "latest.json",
        instance_report_path=tmp_path / "reports" / "parallel" / "instance3_multi_asset_data_dispatch.json",
        lookback_days=1,
        enable_coinapi_reference=True,
        coinapi_api_key="test-key",
    )

    history_report, vendor_stack_report, instance_artifact = run_cross_asset_history_dispatch(settings, client=FakeClient())

    assert history_report["summary"]["one_minute_replay_ready_assets"] == 5
    assert history_report["summary"]["one_second_replay_ready_assets"] == 5
    assert vendor_stack_report["recommendation"]["decision"] == "hold_free_stack"
    assert instance_artifact["finance_gate_pass"] is True
    assert settings.history_report_path.exists()
    assert settings.vendor_stack_report_path.exists()
    assert settings.instance_report_path.exists()


def test_instance_artifact_surfaces_block_reason_when_one_second_history_missing(tmp_path: Path) -> None:
    history_report = {
        "generated_at": "2026-03-11T00:00:00Z",
        "assets": ["BTC", "ETH"],
        "summary": {
            "one_minute_replay_ready_assets": 2,
            "one_second_replay_ready_assets": 0,
            "failures": [],
        },
    }
    vendor_stack_report = {
        "finance": {"finance_gate_pass": True},
        "recommendation": {"decision": "buy_coinapi_startup"},
    }

    artifact = build_instance_artifact(history_report, vendor_stack_report, workspace_root=tmp_path)

    assert "one_second_reference_history_missing" in artifact["block_reasons"]
    assert artifact["one_next_cycle_action"].startswith("Buy CoinAPI Startup")
