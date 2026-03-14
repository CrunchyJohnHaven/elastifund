from __future__ import annotations

from pathlib import Path

from flywheel.contracts import CyclePacket
from flywheel.naming_guard import run_cycle_packet_naming_check


def test_cycle_packet_normalizes_numeric_snapshot_fields() -> None:
    packet = {
        "cycle_key": "cycle-1",
        "strategies": [
            {
                "strategy_key": "wallet-flow",
                "version_label": "v1",
                "lane": "fast_flow",
                "deployments": [
                    {
                        "environment": "paper",
                        "capital_cap_usd": "25",
                        "snapshot": {
                            "snapshot_date": "2026-03-07",
                            "starting_bankroll": "100",
                            "ending_bankroll": "101.5",
                            "realized_pnl": "1.5",
                            "unrealized_pnl": "0.0",
                            "open_positions": "1",
                            "closed_trades": "4",
                            "max_drawdown_pct": "0.05",
                            "kill_events": "0",
                        },
                    }
                ],
            }
        ],
    }

    normalized = CyclePacket.from_dict(packet).to_dict()
    snapshot = normalized["strategies"][0]["deployments"][0]["snapshot"]

    assert snapshot["starting_bankroll"] == 100.0
    assert snapshot["ending_bankroll"] == 101.5
    assert snapshot["open_positions"] == 1
    assert snapshot["closed_trades"] == 4


def test_cycle_packet_naming_guard_passes_for_repo() -> None:
    result = run_cycle_packet_naming_check(Path.cwd())

    assert result["ok"] is True
    assert result["violations"] == []
    assert result["checked_files"]
