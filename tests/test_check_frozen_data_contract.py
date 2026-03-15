from __future__ import annotations

import json

from scripts import check_frozen_data_contract as contract


def test_manifest_contains_priority_entries() -> None:
    manifest = json.loads(contract.MANIFEST_PATH.read_text(encoding="utf-8"))
    issues = contract.validate_priority_entries(manifest)
    assert issues == []


def test_tracking_contract_rejects_snapshot_descendants() -> None:
    manifest = {
        "version": 1,
        "entries": [
            {
                "path": "polymarket-bot/snapshots/20260305_2243",
                "classification": "historical_snapshot",
                "tracked": False,
            }
        ],
    }
    tracked = {
        "polymarket-bot/snapshots/README.md",
        "polymarket-bot/snapshots/.gitignore",
        "polymarket-bot/snapshots/20260305_2243/backtest/run_combined.py",
    }

    issues = contract.validate_tracking_contract(manifest, tracked)

    assert any("descendants" in issue for issue in issues)
    assert any("tracked snapshot artifact" in issue for issue in issues)
