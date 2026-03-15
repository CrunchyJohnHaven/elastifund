from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "reports" / "tools" / "prune_timestamped_snapshots.py"
    spec = importlib.util.spec_from_file_location("prune_timestamped_snapshots", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_retention_days_uses_default_policy_when_no_override():
    mod = _load_module()
    policy = {
        "default_policy": {"retain_days": 14},
        "overrides": {"reports/parallel": {"retain_days": 7}},
    }
    assert mod.retention_days_for("reports/runtime/edge_scan_20260311T010101Z.json", policy, explicit_days=None) == 14


def test_retention_days_uses_longest_matching_override_prefix():
    mod = _load_module()
    policy = {
        "default_policy": {"retain_days": 14},
        "overrides": {
            "reports/parallel": {"retain_days": 7},
            "reports/parallel/handoffs": {"retain_days": 3},
        },
    }
    assert mod.retention_days_for("reports/parallel/handoffs/instance4.json", policy, explicit_days=None) == 3


def test_retention_days_honors_explicit_days_flag():
    mod = _load_module()
    policy = {
        "default_policy": {"retain_days": 14},
        "overrides": {"reports/parallel": {"retain_days": 7}},
    }
    assert mod.retention_days_for("reports/parallel/handoffs/instance4.json", policy, explicit_days=30) == 30
